# ── step `run`: create_checkout / finalize (claim) / get_status / cancel_booking
ACTIONS = ("create_checkout", "finalize", "get_status", "cancel_booking")
PASSENGER_FIELDS = ("given_name", "family_name", "born_on", "email", "phone_number")


def _owned(cid, uid):
    if not CHECKOUT_ID_RE.match(_text(cid)):
        raise PaymentError("validation_error", "checkout_id is malformed")
    doc, ut = _get_checkout(cid)
    # Not found and not yours look the same, so a probe learns nothing.
    if doc is None or _text(doc.get("uid")) != _text(uid):
        raise PaymentError("not_found", "checkout not found")
    return doc, ut


def _clean_passengers(raw):
    passengers = _as_list(raw)
    if not passengers:
        raise PaymentError("validation_error", "passengers must be a non-empty array")
    out = []
    for idx, p in enumerate(passengers):
        p = _as_dict(p)
        missing = [k for k in PASSENGER_FIELDS if not _text(p.get(k))]
        if missing:
            raise PaymentError("validation_error",
                               "passenger %d is missing %s" % (idx + 1, ", ".join(missing)))
        item = {k: _text(p.get(k))[:120] for k in PASSENGER_FIELDS}
        item["title"] = _text(p.get("title") or "mr").lower()[:8]
        if _text(p.get("gender")):
            item["gender"] = _text(p.get("gender")).lower()[:1]
        out.append(item)
    return out


def _reprice(kind, args):
    # The server is the only source of the amount: any client amount is ignored.
    if kind == "flight":
        offer = _duffel_offer(args["offer_id"])
        expires = _text(offer.get("expires_at"))
        try:
            _exp_s = calendar.timegm(time.strptime(expires[:19], "%Y-%m-%dT%H:%M:%S")) if expires else 0
        except ValueError:
            _exp_s = 0
        if _exp_s and _exp_s <= time.time():
            raise PaymentError("offer_expired", "this fare has expired; search again")
        currency = _text(offer.get("total_currency")).upper()
        base_minor = _to_minor(offer.get("total_amount"), currency)
        if len(_as_list(offer.get("passengers"))) not in (0, len(args["passengers"])):
            raise PaymentError("validation_error", "the fare is priced for %d passenger(s)"
                               % len(_as_list(offer.get("passengers"))))
        return base_minor, currency, {"name": "duffel", "offer_id": args["offer_id"],
                                      "expires_at": expires}
    rate = _hotelbeds_checkrate(args["rate_key"])
    currency = rate["currency"].upper()
    return _to_minor(rate["net"], currency), currency, {
        "name": "hotelbeds", "rate_key": rate["rate_key"], "hotel_name": rate["hotel_name"],
        "check_in": rate["check_in"], "check_out": rate["check_out"]}


def _create_pi(cid, doc):
    quote = _as_dict(doc.get("quote"))
    return _stripe("POST", "/v1/payment_intents", {
        "amount": int(quote["total_minor"]),
        "currency": _text(quote["currency"]).lower(),
        "capture_method": "manual",
        "automatic_payment_methods": {"enabled": True},
        "description": ("Adiona %s: %s" % (doc.get("kind"), doc.get("title") or cid))[:200],
        "metadata": {"checkout_id": cid, "uid_hash": _uid_hash(doc.get("uid")),
                     "kind": doc.get("kind"), "source": doc.get("source")},
    }, idem="checkout:%s:create" % cid)


def _do_create(uid):
    kind = _text(globals().get("kind")).lower()
    if kind not in ("flight", "hotel"):
        raise PaymentError("validation_error", "kind must be flight or hotel")
    crid = _text(globals().get("client_request_id"))
    if not REQUEST_ID_RE.match(crid):
        raise PaymentError("validation_error", "client_request_id must be 8-128 of [A-Za-z0-9_-]")
    args = {}
    if kind == "flight":
        args["offer_id"] = _text(globals().get("offer_id"))
        if not args["offer_id"]:
            raise PaymentError("validation_error", "offer_id is required")
        args["passengers"] = _clean_passengers(globals().get("passengers"))
        traveller = {"passengers": args["passengers"]}
    else:
        args["rate_key"] = _text(globals().get("rate_key"))
        if not args["rate_key"]:
            raise PaymentError("validation_error", "rate_key is required")
        holder = _as_dict(globals().get("holder"))
        if not _text(holder.get("name")) or not _text(holder.get("surname")):
            raise PaymentError("validation_error", "holder name and surname are required")
        traveller = {"holder": {"name": _text(holder["name"])[:60], "surname": _text(holder["surname"])[:60]},
                     "rooms": max(1, _int(globals().get("rooms"), 1)),
                     "adults": max(1, _int(globals().get("adults"), 1)),
                     "children": max(0, _int(globals().get("children"), 0))}

    cid = "co_" + hashlib.sha256((uid + "\n" + crid).encode("utf-8")).hexdigest()[:24]
    doc, ut = _get_checkout(cid)
    if doc is None:
        base_minor, currency, provider = _reprice(kind, args)
        now = _now_ms()
        title = _text(globals().get("title"))[:120] or (provider.get("hotel_name") or "")
        doc = {"checkout_id": cid, "uid": uid, "kind": kind,
               "source": _text(globals().get("source"), "widget")[:16] or "widget",
               "thread_id": _text(globals().get("thread_id"))[:128], "title": title,
               "state": "created", "provider": provider, "traveller": traveller,
               "quote": _price_quote(base_minor, currency, PRICING),
               "payment_intent_id": "", "provider_ref": "", "events_seen": [],
               "created_at_ms": now, "updated_at_ms": now, "claimed_at_ms": 0}
        if _create_checkout_doc(cid, doc) is None:
            doc, ut = _get_checkout(cid)  # a concurrent retry created it first
    if _text(doc.get("uid")) != uid:
        raise PaymentError("not_found", "checkout not found")

    if doc.get("payment_intent_id"):
        if doc.get("state") not in ("requires_payment", "payment_failed"):
            return _ok("create_checkout", doc)
        pi = _stripe("GET", _pi_path(doc["payment_intent_id"]))
    else:
        # The stored quote, not a fresh re-price: a retried create must send the
        # same parameters, or Stripe rejects the reused Idempotency-Key.
        pi = _create_pi(cid, doc)
        doc, _moved = _transition(cid, ("created",), {"state": "requires_payment",
                                                      "payment_intent_id": pi.get("id")})
    return _ok("create_checkout", doc, client_secret=pi.get("client_secret"))


def _do_finalize(uid):
    cid = _text(globals().get("checkout_id"))
    doc, ut = _owned(cid, uid)
    state = doc.get("state")
    if state in FINAL_STATES:
        return _ok("finalize", doc), None
    if state == "booking":
        if _now_ms() - _int(doc.get("claimed_at_ms")) > STUCK_BOOKING_MS:
            doc, _ = _transition(cid, ("booking",), {"state": "needs_review", "error": {
                "code": "booking_stuck", "message": "The booking did not finish; our team will check it."}})
        return _ok("finalize", doc), None
    if not doc.get("payment_intent_id"):
        return _ok("finalize", doc), None

    pi = _stripe("GET", _pi_path(doc["payment_intent_id"]))
    quote = _as_dict(doc.get("quote"))
    status = _text(pi.get("status"))
    if status == "requires_capture":
        if (_int(pi.get("amount_capturable")) < _int(quote.get("total_minor"))
                or _text(pi.get("currency")).upper() != _text(quote.get("currency")).upper()
                or _text(_as_dict(pi.get("metadata")).get("checkout_id")) != cid):
            doc, _ = _transition(cid, CLAIMABLE_STATES, {"state": "needs_review", "error": {
                "code": "amount_mismatch", "message": "The authorised amount does not match the quote."}})
            return _ok("finalize", doc), None
        doc, moved = _transition(cid, CLAIMABLE_STATES, {"state": "booking", "claimed_at_ms": _now_ms()})
        if not moved:
            return _ok("finalize", doc), None  # another finalize won the claim
        return _ok("finalize", doc), doc
    if status == "requires_payment_method" and _as_dict(pi.get("last_payment_error")):
        doc, _ = _transition(cid, ("requires_payment",), {"state": "payment_failed", "error": {
            "code": _text(_as_dict(pi.get("last_payment_error")).get("decline_code")
                          or _as_dict(pi.get("last_payment_error")).get("code"), "card_declined"),
            "message": _text(_as_dict(pi.get("last_payment_error")).get("message"),
                             "The card was declined.")[:200]}})
    elif status == "canceled":
        doc, _ = _transition(cid, CLAIMABLE_STATES, {"state": "canceled"})
    elif status == "succeeded":
        doc, _ = _transition(cid, CLAIMABLE_STATES, {"state": "needs_review", "error": {
            "code": "captured_without_booking", "message": "Payment was captured before the booking finished."}})
    return _ok("finalize", doc, payment_status=status), None


def _book_args(doc):
    traveller = _as_dict(doc.get("traveller"))
    provider = _as_dict(doc.get("provider"))
    if doc.get("kind") == "flight":
        return {"offer_id": provider.get("offer_id"), "passengers": _as_list(traveller.get("passengers")),
                "duffel_env": "test"}
    holder = _as_dict(traveller.get("holder"))
    return {"rate_key": provider.get("rate_key"), "holder_name": holder.get("name"),
            "holder_surname": holder.get("surname"), "rooms": traveller.get("rooms") or 1,
            "adults": traveller.get("adults") or 1, "children": traveller.get("children") or 0,
            "client_reference": doc.get("checkout_id")}


def _do_status(uid):
    doc, _ = _owned(_text(globals().get("checkout_id")), uid)
    return _ok("get_status", doc)


def _do_cancel(uid):
    # SKETCH (owner-approved scope): refund the captured charge in test mode.
    # Provider-side cancellation (Duffel order_cancellations / HotelBeds DELETE
    # booking, and refunding their quote rather than the full total) is not
    # built yet, so the action is off until it is (CANCEL_BOOKING_ENABLED).
    cid = _text(globals().get("checkout_id"))
    doc, _ = _owned(cid, uid)
    if not CANCEL_BOOKING_ENABLED:
        return _err("cancel_booking", "not_enabled", "Cancelling a confirmed booking is not available yet.")
    if doc.get("state") != "confirmed":
        return _ok("cancel_booking", doc)
    doc, moved = _transition(cid, ("confirmed",), {"state": "refund_pending",
                                                   "ops_review": {"reason": "provider_cancellation_manual"}})
    if not moved:
        return _ok("cancel_booking", doc)
    refund = _stripe("POST", "/v1/refunds", {"payment_intent": doc.get("payment_intent_id"),
                                             "metadata": {"checkout_id": cid}},
                     idem="checkout:%s:refund:1" % cid)
    if _text(refund.get("status")) == "succeeded":
        doc, _ = _transition(cid, ("refund_pending",), {"state": "refunded"})
    return _ok("cancel_booking", doc)


route = "done"
book_args = {}
_act = _text(action).lower()
_uid = _text(uid)
try:
    if _act not in ACTIONS:
        result = _err(_act or "unknown", "validation_error", "action must be one of " + ", ".join(ACTIONS))
    elif not _uid_ok(_uid):
        result = _err(_act, "unauthenticated", "sign in to pay")
    elif _act == "create_checkout":
        result = _do_create(_uid)
    elif _act == "finalize":
        result, _claimed = _do_finalize(_uid)
        if _claimed is not None:
            route = "book_" + _claimed.get("kind")
            book_args = _book_args(_claimed)
            result["final"] = False  # settle writes the outcome
    elif _act == "get_status":
        result = _do_status(_uid)
    else:
        result = _do_cancel(_uid)
except PaymentError as exc:
    result = _err(_act, exc.code, exc.message)
except Exception as exc:
    result = _err(_act, "internal", type(exc).__name__)

result["route"] = route
result["book_args"] = book_args
if route == "done":
    _callback(result)
