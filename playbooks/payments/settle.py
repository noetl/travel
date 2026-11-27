# ── step `settle`: capture on a confirmed provider booking, cancel otherwise ──
FAILED_PROVIDER_STATUSES = ("FAILED", "ERROR", "CANCELLED", "CANCELED")


def _find_envelope(value, depth=0):
    # The provider child's MCP envelope ({isError, data}) sits somewhere inside
    # the labelled step result; walk to it rather than hard-code the nesting.
    if depth > 8:
        return None
    if isinstance(value, str):
        value = _as_dict(value) or _as_list(value)
    if isinstance(value, dict):
        if "isError" in value and isinstance(value.get("data"), dict):
            return value
        for key in ("provider", "result", "data", "output", "payload"):
            if key in value:
                found = _find_envelope(value[key], depth + 1)
                if found:
                    return found
        for key, nested in value.items():
            if key not in ("provider", "result", "data", "output", "payload"):
                found = _find_envelope(nested, depth + 1)
                if found:
                    return found
    if isinstance(value, list):
        for nested in value:
            found = _find_envelope(nested, depth + 1)
            if found:
                return found
    return None


def _provider_outcome(kind, raw):
    env = _find_envelope(raw)
    if env is None:
        return False, "", {}, {"code": "provider_no_result",
                               "message": "The provider did not answer, so nothing was booked."}
    data = _as_dict(env.get("data"))
    if env.get("isError") or data.get("ok") is False:
        return False, "", {}, {"code": _text(data.get("code"), "provider_failed"),
                               "message": "The provider could not confirm the booking, so nothing was booked."}
    if kind == "flight":
        order = _as_dict(data.get("order"))
        ref = _text(data.get("booking_reference") or order.get("booking_reference"))
        order_id = _text(data.get("order_id") or order.get("id"))
        if not (ref or order_id):
            return False, "", {}, {"code": "provider_no_reference",
                                   "message": "The airline returned no booking reference, so nothing was booked."}
        return True, ref or order_id, {"order_id": order_id, "booking_reference": ref,
                                       "total_amount": _text(order.get("total_amount")),
                                       "total_currency": _text(order.get("total_currency"))}, None
    ref = _text(data.get("booking_reference"))
    if not ref or _text(data.get("status")).upper() in FAILED_PROVIDER_STATUSES:
        return False, "", {}, {"code": "provider_no_reference",
                               "message": "The hotel returned no confirmation, so nothing was booked."}
    return True, ref, {"booking_reference": ref, "status": _text(data.get("status")),
                       "hotel_name": _text(data.get("hotel_name")), "check_in": _text(data.get("checkIn")),
                       "check_out": _text(data.get("checkOut")), "total_amount": _text(data.get("totalNet")),
                       "total_currency": _text(data.get("currency"))}, None


def _price_drift(quote, details):
    try:
        booked = _to_minor(details.get("total_amount"), details.get("total_currency") or quote.get("currency"))
    except PaymentError:
        return 0
    if _text(details.get("total_currency")).upper() not in ("", _text(quote.get("currency")).upper()):
        return 0
    return max(0, booked - _int(quote.get("base_minor")))


def _settle():
    cid = _text(_as_dict(claim).get("checkout", {}).get("checkout_id"))
    if not CHECKOUT_ID_RE.match(cid):
        return _err("finalize", "internal", "settle reached without a claimed checkout")
    doc, _ = _get_checkout(cid)
    if doc is None:
        return _err("finalize", "not_found", "checkout not found")
    if doc.get("state") != "booking":
        return _ok("finalize", doc)  # already settled by a concurrent run
    kind = doc.get("kind")
    ok, ref, details, error = _provider_outcome(kind, flight_result if kind == "flight" else hotel_result)
    pi_id = doc.get("payment_intent_id")
    quote = _as_dict(doc.get("quote"))
    if ok:
        captured = None
        for _attempt in range(2):  # same Idempotency-Key, so a retry cannot double-capture
            try:
                captured = _stripe("POST", _pi_path(pi_id, "/capture"),
                                   {"amount_to_capture": int(quote["total_minor"])},
                                   idem="checkout:%s:capture" % cid)
                break
            except PaymentError as exc:
                last = exc
        fields = {"provider_ref": ref, "provider_booking": details}
        drift = _price_drift(quote, details)
        if drift:
            # The provider re-priced above the hold. The traveller is charged the
            # quoted total; Adiona absorbs the difference, recorded for ops.
            fields["ops_review"] = {"reason": "provider_price_drift", "drift_minor": drift}
        if captured is not None and _text(captured.get("status")) == "succeeded":
            fields.update({"state": "confirmed", "error": None})
        else:
            fields.update({"state": "needs_review", "error": {
                "code": "capture_failed",
                "message": "Your booking is made but the payment did not complete; our team will contact you."}})
        doc, _ = _transition(cid, ("booking",), fields)
        return _ok("finalize", doc)
    try:
        _stripe("POST", _pi_path(pi_id, "/cancel"), {"cancellation_reason": "abandoned"},
                idem="checkout:%s:cancel" % cid)
        fields = {"state": "booking_failed_released", "error": error}
    except PaymentError as exc:
        fields = {"state": "needs_review", "error": {
            "code": "release_failed", "message": "The booking failed and the card hold could not be released yet."}}
    doc, _ = _transition(cid, ("booking",), fields)
    return _ok("finalize", doc)


try:
    result = _settle()
except PaymentError as exc:
    result = _err("finalize", exc.code, exc.message)
except Exception as exc:
    result = _err("finalize", "internal", type(exc).__name__)
_callback(result)
