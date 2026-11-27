#!/usr/bin/env python3
"""Stripe checkout (muno/playbooks/payments + payments-webhook), run against the
real generated step code with every outside call faked. No network, no key.

urllib.request.urlopen is patched with one router that plays:
  metadata server   -> a token
  Secret Manager    -> stripe-api-test / duffel-api-test / hotelbeds-hotels-test
  Firestore REST    -> in-memory documents with updateTime preconditions
  Stripe            -> PaymentIntents, refunds and events, with Idempotency-Key
                       replay (same key + same params -> same response)
  Duffel / HotelBeds-> offer and checkRate re-price

The provider booking itself is a `kind: playbook` child in the workflow; the test
hands `settle` the same MCP envelope shape those children return.
"""
import base64
import copy
import io
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml

PAY = "playbooks/payments.yaml"
HOOK = "playbooks/payments-webhook.yaml"
PROJECT = "test-project"
FS_ROOT = "https://firestore.googleapis.com/v1/projects/%s/databases/(default)/documents/" % PROJECT
ALICE, BOB = "auth0|alice", "auth0|bob"
failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def steps_of(path):
    return {s["step"]: s for s in yaml.safe_load(open(path))["workflow"]}


PAY_STEPS = steps_of(PAY)
HOOK_STEPS = steps_of(HOOK)
RUN = PAY_STEPS["run"]["tool"]["code"]
SETTLE = PAY_STEPS["settle"]["tool"]["code"]
HANDLE = HOOK_STEPS["handle_event"]["tool"]["code"]


def enc(v):
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: enc(x) for k, x in v.items()}}}
    if isinstance(v, list):
        return {"arrayValue": {"values": [enc(x) for x in v]}}
    return {"stringValue": str(v)}


def dec(v):
    if "nullValue" in v:
        return None
    if "booleanValue" in v:
        return v["booleanValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return v["doubleValue"]
    if "stringValue" in v:
        return v["stringValue"]
    if "mapValue" in v:
        return {k: dec(x) for k, x in v["mapValue"].get("fields", {}).items()}
    if "arrayValue" in v:
        return [dec(x) for x in v["arrayValue"].get("values", [])]
    raise AssertionError(v)


class _resp(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode())
        self.status = status
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(url, code, payload):
    return urllib.error.HTTPError(url, code, "err", {}, io.BytesIO(json.dumps(payload).encode()))


class World:
    def __init__(self, stripe_key="sk_test_abc", duffel_token="duffel_test_xyz"):
        self.secrets = {
            "stripe-api-test": json.dumps({"data": {"token": stripe_key}}),
            "duffel-api-test": json.dumps({"data": {"token": duffel_token}}),
            "hotelbeds-hotels-test": json.dumps({"apikey": "k", "secret": "s"}),
        }
        self.docs = {}          # path -> (fields, n)
        self.n = 0
        self.conflict_next = 0  # fail the next N CAS writes with a precondition error
        self.on_conflict = None # ...after applying this (a concurrent writer)
        self.pis = {}
        self.events = {}
        self.idem = {}
        self.stripe_calls = []  # (method, path, params, idem)
        self.offer = {"id": "off_1", "total_amount": "123.45", "total_currency": "USD",
                      "expires_at": "2099-01-01T00:00:00Z", "passengers": [{"id": "pas_1"}],
                      "live_mode": False}
        self.rate = {"net": "240.00", "currency": "EUR"}
        self.provider_calls = []
        self.capture_fails = False
        self.stripe_livemode = False
        self.callbacks = []

    # ── router ──
    def urlopen(self, req, timeout=None):
        url = req.full_url
        method = req.get_method()
        if "metadata.google.internal" in url:
            return _resp({"access_token": "t"})
        if url.startswith("https://secretmanager.googleapis.com/"):
            name = re.search(r"/secrets/([^/]+)/versions", url).group(1)
            if name not in self.secrets:
                raise _http_error(url, 404, {})
            return _resp({"payload": {"data": base64.b64encode(self.secrets[name].encode()).decode()}})
        if url.startswith(FS_ROOT):
            return self.firestore(req, url, method)
        if url.startswith("https://api.stripe.com/"):
            return self.stripe(req, url, method)
        if url.startswith("https://api.duffel.com/air/offers/"):
            self.provider_calls.append(("duffel_offer", url))
            assert req.headers.get("Authorization") == "Bearer duffel_test_xyz"
            return _resp({"data": self.offer})
        if url.startswith("https://api.test.hotelbeds.com/hotel-api/1.0/checkrates"):
            self.provider_calls.append(("hb_checkrate", json.loads(req.data)))
            return _resp({"hotel": {"name": "Hotel Test", "currency": self.rate["currency"],
                                    "checkIn": "2026-07-10", "checkOut": "2026-07-12",
                                    "rooms": [{"rates": [{"rateKey": "RK-FRESH", "net": self.rate["net"]}]}]}})
        if url.endswith("/api/internal/callback/async"):
            self.callbacks.append(json.loads(req.data))
            return _resp({})
        raise AssertionError("unexpected %s %s" % (method, url))

    def firestore(self, req, url, method):
        rest = url[len(FS_ROOT):]
        path, _, query = rest.partition("?")
        path = urllib.parse.unquote(path)
        q = urllib.parse.parse_qs(query)
        if method == "GET":
            if path not in self.docs:
                raise _http_error(url, 404, {})
            fields, n = self.docs[path]
            return _resp({"fields": {k: enc(v) for k, v in fields.items()}, "updateTime": "ut%d" % n})
        assert method == "PATCH", method
        if q.get("currentDocument.exists") == ["false"] and path in self.docs:
            raise _http_error(url, 409, {})
        if "currentDocument.updateTime" in q:
            if self.conflict_next:
                self.conflict_next -= 1
                if self.on_conflict:
                    self.on_conflict(self)
                raise _http_error(url, 400, {})
            if path not in self.docs or "ut%d" % self.docs[path][1] != q["currentDocument.updateTime"][0]:
                raise _http_error(url, 400, {})
        body = {k: dec(v) for k, v in json.loads(req.data)["fields"].items()}
        mask = q.get("updateMask.fieldPaths")
        if mask:
            fields = dict(self.docs.get(path, ({}, 0))[0])
            for k in mask:
                fields[k] = body.get(k)
        else:
            fields = body
        self.n += 1
        self.docs[path] = (fields, self.n)
        return _resp({"updateTime": "ut%d" % self.n})

    def stripe(self, req, url, method):
        auth = req.headers.get("Authorization")
        assert auth == "Bearer " + _extract(self.secrets["stripe-api-test"]), "stripe called with the wrong key"
        parsed = urllib.parse.urlsplit(url)
        path = parsed.path
        params = dict(urllib.parse.parse_qsl(req.data.decode() if req.data else parsed.query))
        idem = req.headers.get("Idempotency-key")
        self.stripe_calls.append((method, path, params, idem))
        if method == "POST":
            assert idem, "POST without Idempotency-Key: " + path
            if idem in self.idem:
                old_params, old_resp = self.idem[idem]
                if old_params != params:
                    raise _http_error(url, 400, {"error": {"type": "idempotency_error", "message": "reused key"}})
                return _resp(old_resp)
        resp = self._stripe_route(method, path, params, url)
        if self.stripe_livemode:
            resp = dict(resp, livemode=True)
        if method == "POST":
            self.idem[idem] = (params, resp)
        return _resp(resp)

    def _stripe_route(self, method, path, params, url):
        m = re.match(r"^/v1/payment_intents(?:/([^/]+))?(?:/(capture|cancel))?$", path)
        if m and method == "POST" and not m.group(1):
            pid = "pi_%d" % (len(self.pis) + 1)
            pi = {"id": pid, "object": "payment_intent", "amount": int(params["amount"]),
                  "currency": params["currency"], "capture_method": params["capture_method"],
                  "status": "requires_payment_method", "amount_capturable": 0, "livemode": False,
                  "client_secret": pid + "_secret_x",
                  "metadata": {k[9:-1]: v for k, v in params.items() if k.startswith("metadata[")}}
            self.pis[pid] = pi
            return copy.deepcopy(pi)
        if m and m.group(1):
            pi = self.pis[m.group(1)]
            if m.group(2) == "capture":
                if self.capture_fails:
                    raise _http_error(url, 402, {"error": {"type": "invalid_request_error", "message": "nope"}})
                pi.update(status="succeeded", amount_received=int(params["amount_to_capture"]), amount_capturable=0)
            elif m.group(2) == "cancel":
                pi.update(status="canceled", amount_capturable=0)
            return copy.deepcopy(pi)
        if path == "/v1/refunds":
            return {"id": "re_1", "object": "refund", "status": "succeeded", "livemode": False}
        m = re.match(r"^/v1/events/(evt_[A-Za-z0-9]+)$", path)
        if m:
            if m.group(1) not in self.events:
                raise _http_error(url, 404, {"error": {"type": "invalid_request_error", "message": "No such event"}})
            return copy.deepcopy(self.events[m.group(1)])
        raise AssertionError("unexpected stripe %s %s" % (method, path))

    # ── helpers ──
    def doc(self, cid):
        return self.docs.get("checkouts/" + cid, (None, 0))[0]

    def hold(self, pid):
        pi = self.pis[pid]
        pi.update(status="requires_capture", amount_capturable=pi["amount"])

    def calls(self, method, suffix):
        return [c for c in self.stripe_calls if c[0] == method and c[1].endswith(suffix)]


def _extract(raw):
    obj = json.loads(raw)
    return obj["data"]["token"]


def exec_step(world, code, bindings):
    real = urllib.request.urlopen
    urllib.request.urlopen = world.urlopen
    try:
        g = dict(bindings)
        g.setdefault("firestore_project", PROJECT)
        g.setdefault("firestore_database", "(default)")
        g.setdefault("request_id", "")
        g.setdefault("gateway_url", "")
        exec(compile(code, "<step>", "exec"), g)
        return g["result"]
    finally:
        urllib.request.urlopen = real


RUN_DEFAULTS = {"uid": ALICE, "action": "get_status", "checkout_id": "", "kind": "", "offer_id": "",
                "rate_key": "", "passengers": [], "holder": {}, "rooms": 1, "adults": 1, "children": 0,
                "client_request_id": "", "source": "widget", "thread_id": "", "title": ""}
PAX = [{"given_name": "Ada", "family_name": "Lovelace", "born_on": "1990-01-01", "gender": "f",
        "title": "ms", "email": "ada@example.com", "phone_number": "+442080160000"}]


def run(world, **kw):
    b = dict(RUN_DEFAULTS)
    b.update(kw)
    return exec_step(world, RUN, b)


def create_flight(world, crid="req-flight-0001", uid=ALICE, **kw):
    return run(world, uid=uid, action="create_checkout", kind="flight", offer_id="off_1",
               passengers=PAX, client_request_id=crid, title="SFO to CDG", **kw)


def create_hotel(world, crid="req-hotel-0001"):
    return run(world, action="create_checkout", kind="hotel", rate_key="RK-1",
               holder={"name": "Ada", "surname": "Lovelace"}, adults=2, client_request_id=crid)


def ok_flight_envelope(ref="ABC123"):
    data = {"ok": True, "order_id": "ord_1", "booking_reference": ref,
            "order": {"id": "ord_1", "booking_reference": ref, "total_amount": "123.45", "total_currency": "USD"}}
    return {"provider": {"status": "ok", "isError": False, "data": data}}


def fail_envelope():
    return {"provider": {"status": "ok", "isError": True, "data": {"ok": False, "code": "offer_expired"}}}


def settle(world, claim, flight=None, hotel=None):
    return exec_step(world, SETTLE, {"claim": claim, "flight_result": flight or {}, "hotel_result": hotel or {}})


def finalize_and_settle(world, cid, flight=None, hotel=None, uid=ALICE):
    claim = run(world, uid=uid, action="finalize", checkout_id=cid)
    if claim.get("route", "done") == "done":
        return claim, None
    return claim, settle(world, claim, flight, hotel)


# ── wiring: what the playbooks bind and route ───────────────────────────────
run_inputs = set(PAY_STEPS["run"]["tool"]["input"])
for forbidden in ("amount", "total", "pricing", "stripe_secret_name", "duffel_api_base",
                  "hotelbeds_api_base", "stripe_api_base", "markup_bps"):
    check(forbidden not in run_inputs, "run does not bind a client-steerable %r" % forbidden)
arcs = PAY_STEPS["run"]["next"]["arcs"]
check([a.get("step") for a in arcs] == ["book_flight", "book_hotel", "done"], "run routes book_flight | book_hotel | done")
check(PAY_STEPS["book_flight"]["tool"][0]["provider"]["path"] == "automation/agents/mcp/duffel"
      and PAY_STEPS["book_hotel"]["tool"][0]["provider"]["path"] == "automation/agents/mcp/hotelbeds",
      "bookings go through the registered Duffel / HotelBeds providers")
check(HOOK_STEPS["finalize_checkout"]["tool"][0]["finalize"]["path"] == "muno/playbooks/payments",
      "the webhook finalizes through muno/playbooks/payments")
all_text = "".join(open(p).read() for p in (PAY, HOOK, "playbooks/subscriptions/stripe-test.yaml"))
check(not re.search(r"(sk|rk|pk)_(test|live)_[A-Za-z0-9]{6,}|whsec_[A-Za-z0-9]{6,}", all_text),
      "no Stripe key or webhook secret value in the playbooks or the Subscription")

# ── create (flight): server re-price, manual capture, idempotency ───────────
w = World()
w.offer["total_amount"] = "123.45"
r = create_flight(w, amount="1.00")  # a client amount is not even an input; passing one changes nothing
cid = (r.get("checkout") or {}).get("checkout_id", "")
check(r["status"] == "ok" and re.match(r"^co_[0-9a-f]{24}$", cid), "create_checkout ok, checkout id co_<24 hex>")
check(r["checkout"]["state"] == "requires_payment" and r.get("client_secret") == "pi_1_secret_x",
      "create returns requires_payment + the PaymentIntent client_secret")
check(r["checkout"]["amount_minor"] == 12345 and r["checkout"]["currency"] == "USD"
      and r["checkout"]["display_amount"] == "USD 123.45", "amount comes from the Duffel re-price (12345 USD minor)")
_, path, params, idem = w.calls("POST", "/v1/payment_intents")[0]
check(params["amount"] == "12345" and params["currency"] == "usd" and params["capture_method"] == "manual"
      and params["automatic_payment_methods[enabled]"] == "true", "PaymentIntent: amount, currency, manual capture, APMs")
check(idem == "checkout:%s:create" % cid, "PaymentIntent create carries Idempotency-Key checkout:{id}:create")
check(params["metadata[checkout_id]"] == cid and ALICE not in json.dumps(params)
      and len(params["metadata[uid_hash]"]) == 32, "metadata has checkout_id + uid_hash, never the raw uid")
stored = w.doc(cid)
check(stored["uid"] == ALICE and stored["traveller"]["passengers"][0]["given_name"] == "Ada"
      and stored["quote"]["line_items"] == [{"code": "provider_total", "label": "Booking", "amount_minor": 12345}],
      "checkout document holds uid, travellers and an itemised quote")

w.offer["total_amount"] = "999.99"  # the provider price moves between retries
r2 = create_flight(w)
check(r2["checkout"]["checkout_id"] == cid and r2.get("client_secret") == "pi_1_secret_x",
      "retry with the same client_request_id: same checkout, same client_secret")
check(len(w.calls("POST", "/v1/payment_intents")) == 1 and len([c for c in w.provider_calls if c[0] == "duffel_offer"]) == 1,
      "retry neither re-prices nor creates a second PaymentIntent")
r3 = create_flight(w, crid="req-flight-0002")
check(r3["checkout"]["checkout_id"] != cid and r3["checkout"]["amount_minor"] == 99999,
      "a new client_request_id is a new checkout at the new price")

# crash between the document write and the PaymentIntent: the retry finishes the job
w = World()
w.secrets["stripe-api-test"] = json.dumps({"data": {"token": "sk_test_abc"}})
real_stripe = w.stripe
w.stripe = lambda req, url, method: (_ for _ in ()).throw(_http_error(url, 500, {"error": {"message": "down"}}))
r = create_flight(w)
check(r["status"] == "error" and r["error"].startswith("stripe_"), "Stripe down at create: error, checkout left 'created'")
cid = next(iter(w.docs))[len("checkouts/"):]
check(w.doc(cid)["state"] == "created", "document exists in state created")
w.stripe = real_stripe
r = create_flight(w)
check(r["status"] == "ok" and r["checkout"]["state"] == "requires_payment"
      and w.calls("POST", "/v1/payment_intents")[0][3] == "checkout:%s:create" % cid,
      "retry creates the PaymentIntent from the stored quote with the same key")

# ── validation and identity ────────────────────────────────────────────────
w = World()
check(create_flight(w, uid="guest")["error"] == "unauthenticated", "guest uid refused")
check(create_flight(w, uid="")["error"] == "unauthenticated", "empty uid refused")
check(run(w, action="create_checkout", kind="flight", offer_id="off_1", passengers=[{"given_name": "A"}],
          client_request_id="req-flight-0001")["error"] == "validation_error", "incomplete passenger refused")
check(create_flight(w, crid="x")["error"] == "validation_error", "short client_request_id refused")
check(run(w, action="nope")["error"] == "validation_error", "unknown action refused")
r = create_flight(w)
cid = r["checkout"]["checkout_id"]
check(run(w, uid=BOB, action="get_status", checkout_id=cid)["error"] == "not_found",
      "another uid cannot read the checkout (reads as not found)")
check(run(w, uid=BOB, action="finalize", checkout_id=cid)["error"] == "not_found",
      "another uid cannot finalize the checkout")
check(run(w, action="get_status", checkout_id="../users/x")["error"] == "validation_error",
      "malformed checkout_id refused before any read")
s = run(w, action="get_status", checkout_id=cid)
check(s["status"] == "ok" and s["checkout"]["state"] == "requires_payment" and "client_secret" not in s,
      "get_status returns the view, never the client_secret")
check("traveller" not in json.dumps(s) and "Lovelace" not in json.dumps(s), "the view carries no traveller details")

w.offer["expires_at"] = "2000-01-01T00:00:00Z"
check(create_flight(w, crid="req-flight-0009")["error"] == "offer_expired", "an expired Duffel offer is refused")

# ── test-mode guards ───────────────────────────────────────────────────────
for bad in ("sk_live_abc", "rk_live_abc", "pk_test_abc", "whatever"):
    w = World(stripe_key=bad)
    r = create_flight(w)
    check(r["error"] == "live_key_refused" and not w.stripe_calls,
          "Stripe key %r refused before any Stripe request" % bad[:8])
w = World(duffel_token="duffel_live_abc")
r = create_flight(w)
check(r["error"] == "live_key_refused" and not w.provider_calls, "a live Duffel token is refused before re-pricing")
w = World()
w.stripe_livemode = True
check(create_flight(w)["error"] == "livemode_refused", "a livemode Stripe response is refused")

# ── pricing helpers ────────────────────────────────────────────────────────
core_g = {}
exec(compile(RUN.split("# ── step `run`")[0], "<core>", "exec"), core_g)
q = core_g["_price_quote"](10000, "usd", {"markup_bps": 250, "service_fee_minor": 99})
check(q["markup_minor"] == 250 and q["fee_minor"] == 99 and q["total_minor"] == 10349
      and [i["code"] for i in q["line_items"]] == ["provider_total", "markup", "service_fee"],
      "_price_quote itemises markup and service fee (structure ready for later)")
q = core_g["_price_quote"](10000, "USD", {"markup_bps": -500, "service_fee_minor": -1})
check(q["total_minor"] == 10000, "negative markup/fee are clamped to zero")
check(core_g["PRICING"] == {"markup_bps": 0, "service_fee_minor": 0}, "live pricing is the provider total as-is")
check(core_g["_to_minor"]("12345", "JPY") == 12345 and core_g["_fmt"](12345, "JPY") == "JPY 12345",
      "zero-decimal currency (JPY) has no minor unit")
check(core_g["_to_minor"]("10.005", "EUR") == 1001, "minor units round half-up")

# ── finalize: authorize -> book -> capture ─────────────────────────────────
w = World()
cid = create_flight(w)["checkout"]["checkout_id"]
claim = run(w, action="finalize", checkout_id=cid)
check(claim["route"] == "done" and claim["checkout"]["state"] == "requires_payment",
      "finalize before the card is authorised: no booking")
w.hold("pi_1")
claim = run(w, action="finalize", checkout_id=cid)
check(claim["route"] == "book_flight" and claim["final"] is False and w.doc(cid)["state"] == "booking",
      "requires_capture: checkout claimed (booking) and routed to book_flight")
check(claim["book_args"] == {"offer_id": "off_1", "passengers": w.doc(cid)["traveller"]["passengers"],
                             "duffel_env": "test"}, "book_flight gets the real passengers, duffel_env test")
again = run(w, action="finalize", checkout_id=cid)
check(again["route"] == "done" and again["checkout"]["state"] == "booking",
      "a second finalize while booking does not book again")
out = settle(w, claim, flight=ok_flight_envelope())
check(out["status"] == "ok" and out["checkout"]["state"] == "confirmed" and out["checkout"]["provider_ref"] == "ABC123",
      "provider ok: captured, confirmed with the booking reference")
cap = w.calls("POST", "/capture")
check(len(cap) == 1 and cap[0][2] == {"amount_to_capture": "12345"} and cap[0][3] == "checkout:%s:capture" % cid,
      "capture: the quoted total, Idempotency-Key checkout:{id}:capture")
check(w.pis["pi_1"]["status"] == "succeeded", "PaymentIntent succeeded")
out2 = settle(w, claim, flight=ok_flight_envelope())
check(out2["checkout"]["state"] == "confirmed" and len(w.calls("POST", "/capture")) == 1,
      "settling twice captures once")
claim3, _ = finalize_and_settle(w, cid)
check(claim3["route"] == "done" and claim3["checkout"]["state"] == "confirmed", "finalize after confirmed is a no-op")

# ── finalize: provider failure releases the hold ───────────────────────────
w = World()
cid = create_flight(w)["checkout"]["checkout_id"]
w.hold("pi_1")
_, out = finalize_and_settle(w, cid, flight=fail_envelope())
check(out["checkout"]["state"] == "booking_failed_released" and out["checkout"]["error"]["code"] == "offer_expired",
      "provider failure: booking_failed_released with the provider's code")
check(w.pis["pi_1"]["status"] == "canceled" and not w.calls("POST", "/capture")
      and w.calls("POST", "/cancel")[0][3] == "checkout:%s:cancel" % cid, "hold cancelled (no capture), keyed")
w2 = World()
cid2 = create_flight(w2)["checkout"]["checkout_id"]
w2.hold("pi_1")
_, out = finalize_and_settle(w2, cid2, flight={})
check(out["checkout"]["state"] == "booking_failed_released" and out["checkout"]["error"]["code"] == "provider_no_result",
      "no provider result at all (child timed out): hold released")

# capture fails after the provider booked -> needs_review, not confirmed
w = World()
cid = create_flight(w)["checkout"]["checkout_id"]
w.hold("pi_1")
w.capture_fails = True
_, out = finalize_and_settle(w, cid, flight=ok_flight_envelope())
check(out["checkout"]["state"] == "needs_review" and out["checkout"]["error"]["code"] == "capture_failed"
      and out["checkout"]["provider_ref"] == "ABC123", "capture failure after booking: needs_review with the reference")

# concurrent claim: the CAS loser does not book
w = World()
cid = create_flight(w)["checkout"]["checkout_id"]
w.hold("pi_1")

def _rival_claims(world):
    # Another finalize claims the checkout between our read and our write.
    fields, _n = world.docs["checkouts/" + cid]
    world.n += 1
    world.docs["checkouts/" + cid] = (dict(fields, state="booking", claimed_at_ms=fields.get("claimed_at_ms") or 1 << 60), world.n)


w.conflict_next = 1
w.on_conflict = _rival_claims
loser = run(w, action="finalize", checkout_id=cid)
check(loser["route"] == "done" and loser["checkout"]["state"] == "booking",
      "racing finalizes: the one whose claim write loses the CAS does not book")

# PaymentIntent states that must not book
for status, extra, want in (("requires_payment_method", {"last_payment_error": {"code": "card_declined",
                                                                                "decline_code": "insufficient_funds",
                                                                                "message": "Your card has insufficient funds."}},
                             "payment_failed"),
                            ("requires_action", {}, "requires_payment"),
                            ("processing", {}, "requires_payment"),
                            ("canceled", {}, "canceled"),
                            ("succeeded", {}, "needs_review")):
    w = World()
    cid = create_flight(w)["checkout"]["checkout_id"]
    w.pis["pi_1"].update(status=status, **extra)
    r = run(w, action="finalize", checkout_id=cid)
    check(r["route"] == "done" and w.doc(cid)["state"] == want, "PI %s -> no booking, state %s" % (status, want))
check(w.doc(cid)["error"]["code"] == "captured_without_booking", "a capture without a booking is flagged")

w = World()
cid = create_flight(w)["checkout"]["checkout_id"]
w.pis["pi_1"].update(status="requires_capture", amount_capturable=100)
r = run(w, action="finalize", checkout_id=cid)
check(r["route"] == "done" and w.doc(cid)["state"] == "needs_review"
      and w.doc(cid)["error"]["code"] == "amount_mismatch", "authorised amount below the quote: needs_review, no booking")

# stuck booking
w = World()
cid = create_flight(w)["checkout"]["checkout_id"]
w.hold("pi_1")
run(w, action="finalize", checkout_id=cid)
fields, n = w.docs["checkouts/" + cid]
w.docs["checkouts/" + cid] = (dict(fields, claimed_at_ms=1), n)
r = run(w, action="finalize", checkout_id=cid)
check(r["checkout"]["state"] == "needs_review" and r["checkout"]["error"]["code"] == "booking_stuck",
      "a booking stuck over 10 minutes goes to needs_review")

# ── hotel ──────────────────────────────────────────────────────────────────
w = World()
r = create_hotel(w)
cid = r["checkout"]["checkout_id"]
check(r["checkout"]["amount_minor"] == 24000 and r["checkout"]["currency"] == "EUR"
      and w.provider_calls[0] == ("hb_checkrate", {"rooms": [{"rateKey": "RK-1"}]}),
      "hotel: priced from HotelBeds checkRate net (24000 EUR minor)")
check(w.calls("POST", "/v1/payment_intents")[0][2]["currency"] == "eur", "hotel charged in the offer currency")
w.hold("pi_1")
claim = run(w, action="finalize", checkout_id=cid)
check(claim["route"] == "book_hotel" and claim["book_args"] == {
    "rate_key": "RK-FRESH", "holder_name": "Ada", "holder_surname": "Lovelace", "rooms": 1, "adults": 2,
    "children": 0, "client_reference": cid}, "book_hotel gets the holder, the fresh rateKey and clientReference=checkout_id")
hb_ok = {"provider": {"isError": False, "data": {"ok": True, "booking_reference": "HB-1", "status": "CONFIRMED",
                                                  "hotel_name": "Hotel Test", "totalNet": "250.00", "currency": "EUR"}}}
out = settle(w, claim, hotel=hb_ok)
check(out["checkout"]["state"] == "confirmed" and out["checkout"]["provider_ref"] == "HB-1"
      and w.calls("POST", "/capture")[0][2] == {"amount_to_capture": "24000"},
      "hotel confirmed; the traveller is charged the quoted total")
check(w.doc(cid)["ops_review"] == {"reason": "provider_price_drift", "drift_minor": 1000},
      "a provider re-price above the hold is recorded for ops")

# ── cancel_booking (sketch, disabled) ──────────────────────────────────────
check(run(w, action="cancel_booking", checkout_id=cid)["error"] == "not_enabled"
      and not w.calls("POST", "/v1/refunds"), "cancel_booking is off and sends no refund")

# ── async callback ─────────────────────────────────────────────────────────
w = World()
r = create_flight(w, request_id="rq1", gateway_url="https://gw.example")
check(w.callbacks and w.callbacks[0]["request_id"] == "rq1" and w.callbacks[0]["status"] == "COMPLETED",
      "the gateway async callback carries the result")

# ── webhook ────────────────────────────────────────────────────────────────
def hook(world, event_id):
    return exec_step(world, HANDLE, {"event_id": event_id})


def event(world, eid, etype, obj, livemode=False):
    world.events[eid] = {"id": eid, "object": "event", "type": etype, "livemode": livemode,
                         "data": {"object": obj}}


w = World()
cid = create_flight(w)["checkout"]["checkout_id"]
w.hold("pi_1")
check(hook(w, "not-an-event")["error"] == "validation_error", "a delivery without an evt_ id is refused")
check(hook(w, "evt_unknown1")["error"].startswith("stripe_") and w.doc(cid)["state"] == "requires_payment",
      "an id Stripe does not know (forged body) changes nothing")
event(w, "evt_cap001", "payment_intent.amount_capturable_updated", w.pis["pi_1"])
r = hook(w, "evt_cap001")
check(r["transition"] == "requires_payment->authorized" and r["route"] == "finalize" and r["finalize_uid"] == ALICE,
      "amount_capturable_updated: authorized, then finalize as the checkout's own uid")
check(w.doc(cid)["events_seen"] == ["evt_cap001"], "event id recorded")
r = hook(w, "evt_cap001")
check(r["transition"] == "duplicate" and r["route"] == "done", "redelivery of the same event is a duplicate no-op")
claim = run(w, action="finalize", checkout_id=cid)
check(claim["route"] == "book_flight", "finalize books from authorized")

# forged body: the gateway forwards a body claiming capture, Stripe says the event is a failure
w = World()
cid = create_flight(w)["checkout"]["checkout_id"]
w.pis["pi_1"].update(last_payment_error={"code": "card_declined", "message": "Your card was declined."})
event(w, "evt_fail01", "payment_intent.payment_failed", w.pis["pi_1"])
r = hook(w, "evt_fail01")  # whatever the body said, only the id is used
check(r["transition"] == "requires_payment->payment_failed" and w.doc(cid)["error"]["code"] == "card_declined",
      "the transition follows the event as re-fetched from Stripe, not the delivered body")

w = World()
cid = create_flight(w)["checkout"]["checkout_id"]
event(w, "evt_live01", "payment_intent.amount_capturable_updated", w.pis["pi_1"], livemode=True)
r = hook(w, "evt_live01")
check(r["error"] == "livemode_refused" and w.doc(cid)["state"] == "requires_payment", "a livemode event is refused")

w = World()
cid = create_flight(w)["checkout"]["checkout_id"]
event(w, "evt_can001", "payment_intent.canceled", dict(w.pis["pi_1"], status="canceled"))
check(hook(w, "evt_can001")["transition"] == "requires_payment->canceled", "payment_intent.canceled -> canceled")

w = World()
cid = create_flight(w)["checkout"]["checkout_id"]
w.hold("pi_1")
claim, _ = finalize_and_settle(w, cid, flight=ok_flight_envelope())
event(w, "evt_suc001", "payment_intent.succeeded", w.pis["pi_1"])
r = hook(w, "evt_suc001")
check(r["transition"] == "ignored" and w.doc(cid)["state"] == "confirmed", "succeeded after settle: state unchanged")
event(w, "evt_ref001", "charge.refunded", {"id": "ch_1", "object": "charge", "payment_intent": "pi_1",
                                           "refunded": True, "amount_refunded": 12345})
check(hook(w, "evt_ref001")["transition"] == "confirmed->refunded", "charge.refunded (full) -> refunded, via the PI's metadata")
event(w, "evt_dsp001", "charge.dispute.created", {"id": "dp_1", "object": "dispute", "payment_intent": "pi_1"})
r = hook(w, "evt_dsp001")
check(r["transition"] == "annotated" and w.doc(cid)["ops_review"]["reason"] == "dispute", "dispute -> ops_review")
event(w, "evt_oth001", "customer.created", {"id": "cus_1", "object": "customer"})
check(hook(w, "evt_oth001")["transition"] == "ignored", "unhandled event types are ignored with ok")
event(w, "evt_frn001", "payment_intent.succeeded", {"id": "pi_x", "object": "payment_intent", "metadata": {}})
check(hook(w, "evt_frn001")["transition"] == "ignored", "a PaymentIntent that is not a muno checkout is ignored")

w = World()
cid = create_flight(w)["checkout"]["checkout_id"]
w.hold("pi_1")
event(w, "evt_cap002", "payment_intent.amount_capturable_updated", w.pis["pi_1"])
w.conflict_next = 1
r = hook(w, "evt_cap002")
check(r["transition"] == "requires_payment->authorized", "a CAS conflict is retried after a re-read")

if failures:
    print("\n%d failure(s)" % len(failures))
    sys.exit(1)
print("\nALL PAYMENTS CHECKOUT SCENARIOS PASS")
