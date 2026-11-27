# ── step `handle_event` (payments-webhook): one verified Stripe delivery ─────
# The gateway verified the Stripe-Signature, but this step still trusts NOTHING
# in the body except the event id: it re-fetches the event from Stripe with the
# test key. A forged or replayed body (or a direct execution of this playbook)
# can therefore only replay a real event of ours, which every transition below
# treats idempotently.
EVENT_ID_RE = re.compile(r"^evt_[A-Za-z0-9]{6,128}$")
HANDLED = ("payment_intent.amount_capturable_updated", "payment_intent.succeeded",
           "payment_intent.payment_failed", "payment_intent.canceled",
           "charge.refunded", "charge.dispute.created")


def _checkout_id_for(obj):
    obj = _as_dict(obj)
    if obj.get("object") == "payment_intent":
        return _text(_as_dict(obj.get("metadata")).get("checkout_id")), _text(obj.get("id"))
    pi_id = _text(obj.get("payment_intent"))
    if not pi_id:
        return "", ""
    pi = _stripe("GET", _pi_path(pi_id))
    return _text(_as_dict(pi.get("metadata")).get("checkout_id")), pi_id


def _plan(etype, obj, state):
    # -> (allowed_from or None to skip, fields, finalize?)
    if etype == "payment_intent.amount_capturable_updated":
        if state in ("created", "requires_payment", "payment_failed"):
            return ("created", "requires_payment", "payment_failed"), {"state": "authorized"}, True
        return None, {}, state == "authorized"
    if etype == "payment_intent.succeeded":
        if state in ("created", "requires_payment", "payment_failed", "authorized"):
            return CLAIMABLE_STATES, {"state": "needs_review", "error": {
                "code": "captured_without_booking", "message": "Payment was captured before the booking finished."}}, False
        return None, {}, False  # booking/confirmed: settle owns the outcome
    if etype == "payment_intent.payment_failed":
        err = _as_dict(obj.get("last_payment_error"))
        return ("requires_payment",), {"state": "payment_failed", "error": {
            "code": _text(err.get("decline_code") or err.get("code"), "card_declined"),
            "message": _text(err.get("message"), "The card was declined.")[:200]}}, False
    if etype == "payment_intent.canceled":
        return CLAIMABLE_STATES, {"state": "canceled"}, False
    if etype == "charge.refunded":
        if obj.get("refunded") is True:
            return ("confirmed", "refund_pending", "needs_review"), {"state": "refunded"}, False
        return ("confirmed", "refund_pending"), {"refunded_minor": _int(obj.get("amount_refunded"))}, False
    if etype == "charge.dispute.created":
        return None, {"ops_review": {"reason": "dispute", "dispute_id": _text(obj.get("id"))}}, False
    return None, {}, False


def _handle():
    eid = _text(event_id)
    if not EVENT_ID_RE.match(eid):
        return _err("webhook", "validation_error", "no Stripe event id in the delivery")
    event = _stripe("GET", "/v1/events/" + eid)  # raises livemode_refused on a live event
    etype = _text(event.get("type"))
    out = {"event_id": eid, "type": etype, "transition": "ignored", "route": "done"}
    if etype not in HANDLED:
        return dict(_ok("webhook"), **out)
    obj = _as_dict(_as_dict(event.get("data")).get("object"))
    cid, _pi = _checkout_id_for(obj)
    if not CHECKOUT_ID_RE.match(cid):
        return dict(_ok("webhook"), **out)  # not a muno checkout
    for _attempt in range(3):
        doc, ut = _get_checkout(cid)
        if doc is None:
            return dict(_ok("webhook"), **out)
        seen = [e for e in _as_list(doc.get("events_seen")) if isinstance(e, str)]
        out["checkout_id"] = cid
        if eid in seen:
            out["transition"] = "duplicate"
            return dict(_ok("webhook", doc), **out)
        allowed, fields, finalize = _plan(etype, obj, doc.get("state"))
        write = {"events_seen": (seen + [eid])[-EVENTS_SEEN_CAP:]}
        if allowed is not None and doc.get("state") in allowed:
            write.update(fields)
            out["transition"] = "%s->%s" % (doc.get("state"), fields.get("state", doc.get("state")))
        elif allowed is None and fields:
            write.update(fields)
            out["transition"] = "annotated"
        if _cas(cid, ut, write):
            doc.update(write)
            if finalize:
                out["route"] = "finalize"
                out["finalize_uid"] = _text(doc.get("uid"))
            return dict(_ok("webhook", doc), **out)
    return _err("webhook", "conflict", "checkout kept changing; finalize will reconcile it")


try:
    result = _handle()
except PaymentError as exc:
    # The gateway already acked the delivery (202 on forward), so Stripe does
    # NOT redeliver a failed run. The SPA's own finalize/get_status calls
    # re-read Stripe and converge the checkout regardless.
    result = _err("webhook", exc.code, exc.message)
except Exception as exc:
    result = _err("webhook", "internal", type(exc).__name__)
result.setdefault("route", "done")
