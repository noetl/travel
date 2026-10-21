#!/usr/bin/env python3
"""playbooks/hotel-cards.yaml: runs map_cards' own embedded code offline (no HotelBeds).

adiona/frontend#63: a provider failure must come back as the provider's message, not
the boolean `true` it used to be (`isError or error`), so the UI can say what went wrong.
"""
import sys

import yaml

PLAYBOOK = "playbooks/hotel-cards.yaml"
failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


steps = {s["step"]: s for s in yaml.safe_load(open(PLAYBOOK))["workflow"]}


def map_cards(search_result, **kw):
    g = dict(search_result=search_result, check_in="2026-11-03", check_out="2026-11-07",
             adults=2, children=0, max_rooms=10, price_bands=4)
    g.update(kw)
    exec(steps["map_cards"]["tool"]["code"], g)
    return g["result"]


# The provider's error envelope (automation/agents/mcp/hotelbeds `_error`).
CHILD_REFUSAL = "children=1 needs one age per child; pass children_ages, e.g. [8, 11]"
error_envelope = {
    "status": "ok",
    "isError": True,
    "summary": "Those guests cannot be searched: " + CHILD_REFUSAL + ".",
    "text": "Those guests cannot be searched: " + CHILD_REFUSAL + ".",
    "_meta": {"backend": "hotelbeds", "tool": "search_hotels", "error": CHILD_REFUSAL, "code": "validation_error"},
    "data": {"ok": False, "status": "error", "error": CHILD_REFUSAL, "status_code": 0,
             "code": "validation_error", "hotels": []},
}
r = map_cards(error_envelope)
check(isinstance(r["provider_error"], str) and r["provider_error"] is not True,
      "a provider failure is reported as text, not `true`: %r" % (r["provider_error"],))
check(r["provider_error"] == error_envelope["summary"], "provider_error is the provider's user-safe summary")
check(r["provider_error_code"] == "validation_error", "the provider's error code rides along")
check(r["provider_error_detail"] == CHILD_REFUSAL, "the full diagnostic is kept separately")
check(r["count"] == 0 and r["hotels"] == [], "no cards from a failed search")

# A raw HotelBeds body stays out of the displayed message (noetl/ai-meta#175).
raw = 'HotelBeds availability failed HTTP 400: {"auditData": {...}, "error": {"code": "INVALID_DATA"}}'
r = map_cards({"isError": True, "summary": "Hotels are temporarily unavailable.",
               "_meta": {"error": raw, "code": "request"},
               "data": {"error": raw, "code": "request", "hotels": []}})
check(r["provider_error"] == "Hotels are temporarily unavailable." and "auditData" not in r["provider_error"],
      "the displayed message never carries the raw provider body")
check("auditData" in (r["provider_error_detail"] or ""), "the raw body is still available for diagnosis")

# An older provider with no summary still yields its error text.
r = map_cards({"isError": True, "data": {"error": "HTTP 500", "hotels": []}})
check(r["provider_error"] == "HTTP 500", "without a summary, the provider's error text is used")

# A successful search reports no error.
ok_envelope = {"status": "ok", "isError": False, "data": {"ok": True, "hotels": [
    {"code": 1, "name": "Hotel One", "categoryName": "4 STARS", "minRate": "400.00", "currency": "USD",
     "destinationName": "Rome", "rates": []}]}}
r = map_cards(ok_envelope)
check(r["provider_error"] is None and r["provider_error_code"] is None and r["provider_error_detail"] is None,
      "a successful search has no provider error")
check(r["count"] == 1 and r["hotels"][0]["name"] == "Hotel One", "a successful search still maps its cards")

if failures:
    sys.exit("%d failure(s)" % len(failures))
