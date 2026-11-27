# ── muno payments core (generated into every payments python step) ──────────
# SOURCE OF TRUTH: playbooks/payments/core.py. scripts/build_payments_playbooks.py
# renders it into playbooks/payments.yaml and playbooks/payments-webhook.yaml;
# scripts/payments_build_sync_test.py fails when the two drift. Edit here, then
# run the generator; never edit the generated `code:` blocks by hand.
#
# TEST MODE ONLY. Every guard below fails closed:
#   * the Stripe key must be sk_test_/rk_test_ (else `live_key_refused`, and no
#     request is sent), and every Stripe response/event must be livemode:false;
#   * Duffel tokens must be duffel_test_; HotelBeds must be the sandbox host.
# Hosts, secret names and pricing are CONSTANTS, not workload: a caller can pass
# any workload variable through the gateway, and none of these may be steerable
# (a workload `duffel_api_base` would ship the bearer to an arbitrary host, and
# a workload markup could price a booking below cost).
#
# The Stripe client transcribes automation/agents/mcp/stripe (noetl/ops) inline
# for latency, the way the planner inlines HotelBeds: a `kind: playbook` hop
# costs ~9s of orchestration (noetl/ai-meta#286).
import base64
import calendar
import gzip
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

SCHEMA = "muno.payments.v1"
METADATA_TOKEN_URL = ("http://metadata.google.internal/computeMetadata/v1/"
                      "instance/service-accounts/default/token")
SECRETS_PROJECT = "shastaratech-noetl-prod"
STRIPE_API = "https://api.stripe.com"
STRIPE_VERSION = "2024-06-20"
STRIPE_SECRET = "stripe-api-test"
DUFFEL_API = "https://api.duffel.com"
DUFFEL_VERSION = "v2"
DUFFEL_SECRET = "duffel-api-test"
HOTELBEDS_API = "https://api.test.hotelbeds.com"
HOTELBEDS_SECRET = "hotelbeds-hotels-test"
SANDBOX_HOST_MARKERS = ("api.test.hotelbeds.com", "sandbox")
CHECKRATES_PATH = "/hotel-api/1.0/checkrates"
# Option A (owner, 2026-11-26): charge the provider total as-is. A markup or
# service fee is a change to these two numbers; _price_quote already itemises.
PRICING = {"markup_bps": 0, "service_fee_minor": 0}
# The traveller-cancel path refunds through Stripe but does not yet cancel the
# provider booking, so it stays off until that half exists.
CANCEL_BOOKING_ENABLED = False
STUCK_BOOKING_MS = 10 * 60 * 1000
EVENTS_SEEN_CAP = 50
ZERO_DECIMAL = {"BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG",
                "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"}
CHECKOUT_ID_RE = re.compile(r"^co_[0-9a-f]{24}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
FINAL_STATES = ("confirmed", "booking_failed_released", "refund_pending",
                "refunded", "canceled", "needs_review")
CLAIMABLE_STATES = ("created", "requires_payment", "payment_failed", "authorized")


class PaymentError(Exception):
    def __init__(self, code, message, status=0):
        Exception.__init__(self, message)
        self.code = code
        self.message = message
        self.status = status


def _as_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _as_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _text(value, default=""):
    value = default if value is None else value
    return str(value).strip()


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _now_ms():
    return int(time.time() * 1000)


def _uid_ok(uid):
    uid = _text(uid)
    return bool(uid) and uid.lower() != "guest"


def _uid_hash(uid):
    return hashlib.sha256(_text(uid).encode("utf-8")).hexdigest()[:32]


# ── GCP: metadata token + Secret Manager ────────────────────────────────────
_cache = {}


def _metadata_token():
    if "metadata" not in _cache:
        req = urllib.request.Request(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
        except Exception as exc:
            raise PaymentError("credential_unavailable",
                               "metadata token unavailable (Workload Identity): %s" % type(exc).__name__)
        token = _as_dict(payload).get("access_token")
        if not token:
            raise PaymentError("credential_unavailable", "metadata token endpoint returned no access_token")
        _cache["metadata"] = token
    return _cache["metadata"]


def _gsm(secret_name):
    # The value is never logged, returned or put in an error message.
    key = "gsm:" + secret_name
    if key not in _cache:
        name = "projects/%s/secrets/%s/versions/latest:access" % (SECRETS_PROJECT, secret_name)
        req = urllib.request.Request("https://secretmanager.googleapis.com/v1/" + name,
                                     headers={"Authorization": "Bearer " + _metadata_token()}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            raise PaymentError("credential_unavailable",
                               "secret manager HTTP %s for '%s': the worker GSA lacks "
                               "secretmanager.secretAccessor, or the secret is not loaded yet"
                               % (exc.code, secret_name))
        except Exception as exc:
            raise PaymentError("credential_unavailable",
                               "secret manager unreachable for '%s': %s" % (secret_name, type(exc).__name__))
        encoded = _text(_as_dict(_as_dict(payload).get("payload")).get("data"))
        if not encoded:
            raise PaymentError("credential_unavailable", "secret '%s' has no payload data" % secret_name)
        _cache[key] = base64.b64decode(encoded).decode("utf-8").strip()
    return _cache[key]


def _extract_token(raw):
    # Bare string, {"token": ...} or {"data": {"token": ...}} (the Duffel shape).
    s = _text(raw)
    if s.startswith("{"):
        try:
            obj = json.loads(s)
        except Exception:
            return s
        if isinstance(obj, dict):
            data = obj.get("data")
            if isinstance(data, dict) and data.get("token"):
                return _text(data.get("token"))
            for k in ("token", "secret_key", "api_key", "key"):
                if obj.get(k):
                    return _text(obj.get(k))
    return s


# ── Firestore REST (inline, like threads.yaml) ──────────────────────────────
def _fs_root():
    return ("https://firestore.googleapis.com/v1/projects/%s/databases/%s/documents/"
            % (_text(globals().get("firestore_project"), SECRETS_PROJECT) or SECRETS_PROJECT,
               urllib.parse.quote(_text(globals().get("firestore_database"), "(default)") or "(default)",
                                  safe="()")))


def _fs_encode(value):
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {str(k): _fs_encode(v) for k, v in value.items()}}}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [_fs_encode(v) for v in value]}}
    return {"stringValue": str(value)}


def _fs_decode(value):
    value = _as_dict(value)
    if "nullValue" in value:
        return None
    if "booleanValue" in value:
        return bool(value["booleanValue"])
    if "integerValue" in value:
        return _int(value["integerValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "stringValue" in value:
        return value["stringValue"]
    if "mapValue" in value:
        return {k: _fs_decode(v) for k, v in _as_dict(_as_dict(value["mapValue"]).get("fields")).items()}
    if "arrayValue" in value:
        return [_fs_decode(v) for v in _as_list(_as_dict(value["arrayValue"]).get("values"))]
    return None


def _fs_call(method, path, query=None, body=None):
    url = _fs_root() + urllib.parse.quote(path, safe="/")
    if query:
        url += "?" + urllib.parse.urlencode(query, doseq=True)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Authorization": "Bearer " + _metadata_token()}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def _doc_path(cid):
    return "checkouts/" + cid


def _get_checkout(cid):
    status, body = _fs_call("GET", _doc_path(cid))
    if status == 404:
        return None, None
    if status != 200:
        raise PaymentError("store_unavailable", "Firestore read failed (%s)" % status)
    fields = {k: _fs_decode(v) for k, v in _as_dict(body.get("fields")).items()}
    return fields, body.get("updateTime")


def _create_checkout_doc(cid, fields):
    status, body = _fs_call("PATCH", _doc_path(cid), query={"currentDocument.exists": "false"},
                            body={"fields": {k: _fs_encode(v) for k, v in fields.items()}})
    if status in (400, 409, 412):
        return None  # already exists
    if status != 200:
        raise PaymentError("store_unavailable", "Firestore create failed (%s)" % status)
    return body.get("updateTime")


def _cas(cid, update_time, fields):
    # Compare-and-set: the write lands only if nobody wrote the checkout since we
    # read it at `update_time`. Returns the new updateTime, or None on conflict.
    fields = dict(fields)
    fields["updated_at_ms"] = _now_ms()
    query = [("updateMask.fieldPaths", k) for k in fields]
    if update_time:
        query.append(("currentDocument.updateTime", update_time))
    status, body = _fs_call("PATCH", _doc_path(cid), query=query,
                            body={"fields": {k: _fs_encode(v) for k, v in fields.items()}})
    if status in (400, 409, 412):
        return None
    if status != 200:
        raise PaymentError("store_unavailable", "Firestore write failed (%s)" % status)
    return body.get("updateTime") or "written"


def _transition(cid, allowed_from, fields, attempts=3):
    # Re-read and CAS until the write lands or the state is no longer one we
    # may move from. Returns (doc_after, moved).
    for _ in range(attempts):
        doc, ut = _get_checkout(cid)
        if doc is None:
            raise PaymentError("not_found", "checkout not found")
        if allowed_from is not None and doc.get("state") not in allowed_from:
            return doc, False
        if _cas(cid, ut, fields):
            doc.update(fields)
            return doc, True
    doc, _ = _get_checkout(cid)
    return doc, False


# ── Money ───────────────────────────────────────────────────────────────────
def _exponent(currency):
    return 0 if _text(currency).upper() in ZERO_DECIMAL else 2


def _to_minor(amount, currency):
    try:
        value = Decimal(_text(amount))
    except (InvalidOperation, ValueError):
        raise PaymentError("pricing_failed", "provider returned a non-numeric amount")
    exp = _exponent(currency)
    minor = int((value * (Decimal(10) ** exp)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if minor <= 0:
        raise PaymentError("pricing_failed", "provider returned a non-positive amount")
    return minor


def _fmt(minor, currency):
    exp = _exponent(currency)
    cur = _text(currency).upper()
    if exp == 0:
        return "%s %d" % (cur, minor)
    return "%s %s" % (cur, str((Decimal(minor) / (Decimal(10) ** exp)).quantize(Decimal("0.01"))))


def _price_quote(base_minor, currency, pricing):
    pricing = _as_dict(pricing)
    bps = max(0, _int(pricing.get("markup_bps"), 0))
    fee = max(0, _int(pricing.get("service_fee_minor"), 0))
    markup = (int(base_minor) * bps + 5000) // 10000
    total = int(base_minor) + markup + fee
    items = [{"code": "provider_total", "label": "Booking", "amount_minor": int(base_minor)}]
    if markup:
        items.append({"code": "markup", "label": "Adiona markup", "amount_minor": markup})
    if fee:
        items.append({"code": "service_fee", "label": "Service fee", "amount_minor": fee})
    return {"base_minor": int(base_minor), "markup_minor": markup, "fee_minor": fee,
            "total_minor": total, "currency": _text(currency).upper(), "line_items": items}


# ── Stripe (TEST MODE ONLY) ─────────────────────────────────────────────────
def _stripe_key():
    if "stripe" not in _cache:
        key = _extract_token(_gsm(STRIPE_SECRET))
        if not (key.startswith("sk_test_") or key.startswith("rk_test_")):
            raise PaymentError("live_key_refused",
                               "the Stripe key in '%s' is not a test-mode key; refusing to call Stripe"
                               % STRIPE_SECRET)
        _cache["stripe"] = key
    return _cache["stripe"]


def _form(params, prefix=""):
    pairs = []
    if isinstance(params, dict):
        for k, v in params.items():
            pairs.extend(_form(v, "%s[%s]" % (prefix, k) if prefix else str(k)))
    elif isinstance(params, (list, tuple)):
        for i, v in enumerate(params):
            pairs.extend(_form(v, "%s[%d]" % (prefix, i)))
    elif params is None:
        pass
    elif isinstance(params, bool):
        pairs.append((prefix, "true" if params else "false"))
    else:
        pairs.append((prefix, str(params)))
    return pairs


def _stripe(method, path, params=None, idem=None):
    method = method.upper()
    if method == "POST" and not idem:
        raise PaymentError("internal", "every Stripe POST needs an Idempotency-Key")
    headers = {"Authorization": "Bearer " + _stripe_key(), "Stripe-Version": STRIPE_VERSION}
    url = STRIPE_API + path
    data = None
    if method == "GET" and params:
        url += "?" + urllib.parse.urlencode(_form(params))
    elif params is not None or method == "POST":
        data = urllib.parse.urlencode(_form(params or {})).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if idem:
        headers["Idempotency-Key"] = idem
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            err = _as_dict(json.loads(exc.read().decode("utf-8") or "{}").get("error"))
        except Exception:
            err = {}
        code = _text(err.get("decline_code") or err.get("code") or err.get("type"), "stripe_error")
        raise PaymentError("stripe_" + code, _text(err.get("message"), "Stripe request failed")[:300], exc.code)
    except Exception as exc:
        raise PaymentError("stripe_unreachable", "Stripe unreachable: %s" % type(exc).__name__)
    if _as_dict(body).get("livemode") is True:
        raise PaymentError("livemode_refused", "Stripe returned a live-mode object; refusing to continue")
    return _as_dict(body)


def _pi_path(pi_id, suffix=""):
    return "/v1/payment_intents/" + urllib.parse.quote(_text(pi_id), safe="") + suffix


# ── Providers: re-price (TEST/SANDBOX only) ─────────────────────────────────
def _duffel_offer(offer_id):
    token = _extract_token(_gsm(DUFFEL_SECRET))
    if not token.startswith("duffel_test_"):
        raise PaymentError("live_key_refused", "the Duffel token is not a test token; refusing to re-price")
    url = "%s/air/offers/%s?return_available_services=false" % (
        DUFFEL_API, urllib.parse.quote(_text(offer_id), safe=""))
    req = urllib.request.Request(url, method="GET", headers={
        "Authorization": "Bearer " + token, "Duffel-Version": DUFFEL_VERSION,
        "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raise PaymentError("offer_unavailable", "Duffel offer lookup failed (%s)" % exc.code, exc.code)
    except Exception as exc:
        raise PaymentError("offer_unavailable", "Duffel unreachable: %s" % type(exc).__name__)
    offer = _as_dict(_as_dict(body).get("data"))
    if offer.get("live_mode") is True:
        raise PaymentError("livemode_refused", "Duffel returned a live-mode offer")
    return offer


def _is_sandbox(base):
    low = _text(base).lower()
    return any(marker in low for marker in SANDBOX_HOST_MARKERS)


def _hotelbeds_checkrate(rate_key):
    if not _is_sandbox(HOTELBEDS_API):
        raise PaymentError("not_sandbox", "HotelBeds host is not the sandbox")
    raw = _gsm(HOTELBEDS_SECRET)
    try:
        cred = json.loads(raw)
    except Exception:
        raise PaymentError("credential_unavailable", "HotelBeds secret is not JSON")
    apikey = _text(cred.get("apikey") or cred.get("api_key") or cred.get("key"))
    secret = _text(cred.get("secret") or cred.get("shared_secret"))
    if not apikey or not secret:
        raise PaymentError("credential_unavailable", "HotelBeds secret is missing apikey/secret")
    sig = hashlib.sha256(("%s%s%d" % (apikey, secret, int(time.time()))).encode("utf-8")).hexdigest()
    req = urllib.request.Request(
        HOTELBEDS_API + CHECKRATES_PATH, method="POST",
        data=json.dumps({"rooms": [{"rateKey": rate_key}]}).encode("utf-8"),
        headers={"Api-key": apikey, "X-Signature": sig, "Accept": "application/json",
                 "Accept-Encoding": "gzip", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw_body = resp.read()
            if "gzip" in _text(resp.headers.get("Content-Encoding") if getattr(resp, "headers", None) else "").lower():
                raw_body = gzip.decompress(raw_body)
            body = json.loads(raw_body.decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raise PaymentError("rate_unavailable", "HotelBeds checkRate failed (%s)" % exc.code, exc.code)
    except Exception as exc:
        raise PaymentError("rate_unavailable", "HotelBeds unreachable: %s" % type(exc).__name__)
    hotel = _as_dict(_as_dict(body).get("hotel"))
    for room in _as_list(hotel.get("rooms")):
        for rate in _as_list(_as_dict(room).get("rates")):
            rate = _as_dict(rate)
            if _text(rate.get("rateKey")):
                return {"rate_key": _text(rate.get("rateKey")), "net": rate.get("net"),
                        "currency": _text(hotel.get("currency")), "hotel_name": _text(hotel.get("name")),
                        "check_in": _text(hotel.get("checkIn")), "check_out": _text(hotel.get("checkOut"))}
    raise PaymentError("rate_unavailable", "HotelBeds checkRate returned no bookable rate")


# ── Views ───────────────────────────────────────────────────────────────────
def _view(doc):
    doc = _as_dict(doc)
    quote = _as_dict(doc.get("quote"))
    view = {
        "checkout_id": doc.get("checkout_id"),
        "state": doc.get("state"),
        "kind": doc.get("kind"),
        "title": doc.get("title") or "",
        "amount_minor": quote.get("total_minor"),
        "currency": quote.get("currency"),
        "display_amount": _fmt(quote.get("total_minor") or 0, quote.get("currency") or "USD") if quote else "",
        "line_items": _as_list(quote.get("line_items")),
    }
    if doc.get("provider_ref"):
        view["provider_ref"] = doc.get("provider_ref")
    if _as_dict(doc.get("provider_booking")):
        view["provider_booking"] = _as_dict(doc.get("provider_booking"))
    if _as_dict(doc.get("error")):
        view["error"] = _as_dict(doc.get("error"))
    return view


def _ok(action, doc=None, **extra):
    out = {"status": "ok", "schema": SCHEMA, "action": action, "final": True}
    if doc is not None:
        out["checkout"] = _view(doc)
    out.update(extra)
    return out


def _err(action, code, message):
    return {"status": "error", "schema": SCHEMA, "action": action, "final": True,
            "error": code, "message": _text(message)[:300]}


def _callback(result):
    rid = _text(globals().get("request_id"))
    gw = _text(globals().get("gateway_url"))
    if not (rid and gw):
        return
    try:
        body = json.dumps({"request_id": rid,
                           "status": "COMPLETED" if result.get("status") == "ok" else "FAILED",
                           "data": result}).encode("utf-8")
        req = urllib.request.Request(gw.rstrip("/") + "/api/internal/callback/async", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as response:
            result["gateway_callback"] = {"delivered": 200 <= response.status < 300}
    except Exception as exc:
        result["gateway_callback"] = {"delivered": False, "error": type(exc).__name__}
# ── end of muno payments core ───────────────────────────────────────────────
