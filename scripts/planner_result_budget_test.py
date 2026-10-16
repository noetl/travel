#!/usr/bin/env python3
"""A large flight search must fit under the 100 KB step-result offload line.

The worker moves any step result over 100 KB (NOETL_EVENT_RESULT_CONTEXT_MAX_BYTES) to
the result store, and the next step's template then sees nothing. For the itinerary
planner that silently lost data three ways, all found on prod:

  * render_widget_chat carried a 50-offer flight list ~6 times (~250 KB), so
    persist_all_atomically got no post_docs/post_events: the turn's tool response,
    widget, reply, api_calls document, slot state and user_thread_map update were never
    saved, while the save step reported success;
  * call_duffel_offers returned the offers twice (data + control_data, ~125 KB), so
    normalize got nothing and the traveller was told there were no flights;
  * saving the offers in slot state would have put them into extract_turn's result
    (4 copies) on the NEXT turn, breaking it the same way.

The fix keeps the offers out of every step result: render saves them once, inline, in
the search's api_calls document; slot state and the tool event hold a reference; the
picked-offer views read them back. This runs render_widget_chat's and final_result's own
code on a synthetic 50-offer search, with Firestore stubbed.
"""
import io
import json
import re
import sys
import urllib.request

import yaml

PLAYBOOK = "playbooks/itinerary-planner.yaml"
BUDGET = 100 * 1024
THREAD = "chat_threads/chat-budget-test"

failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


steps = {s["step"]: s for s in yaml.safe_load(open(PLAYBOOK))["workflow"]}
src = open(PLAYBOOK).read()


def card(i):
    seg = lambda a, b, h: {"arrival": {"at": "2026-11-10T%02d:30:00Z" % h, "iata": b}, "carrier": "ZZ",
                           "departure": {"at": "2026-11-10T%02d:00:00Z" % (h - 5), "iata": a},
                           "duration": "PT5H30M", "flight_number": "ZZ%04d" % (100 + i), "stops": 0}
    return {"baggage": {"carry_on": 1, "checked": i % 2, "known": True}, "carriers": ["ZZ"],
            "conditions": {"changeable": bool(i % 2), "refundable": False}, "ctas": ["pick", "detail"],
            "duration": "PT5H30M", "fare_brand": None,
            "itineraries": [{"duration": "PT5H30M", "segments": [seg("SFO", "JFK", 13)]},
                            {"duration": "PT5H30M", "segments": [seg("JFK", "SFO", 20)]}],
            "offer_id": "off_%04d" % i, "price": {"currency": "USD", "total": "%d.00" % (300 + i)},
            "stops": 0, "validating_airline": "ZZ"}


OFFERS = [card(i) for i in range(50)]
SLOT = {"flight_origin": {"iata": "SFO"}, "flight_destination": {"iata": "JFK"},
        "check_in_date": "2026-11-10", "check_out_date": "2026-11-17",
        "party": {"rooms": 1, "adults": 2, "children": []},
        "flight_search_results": [o["offer_id"] for o in OFFERS],
        "flight_offers_ref": {"path": THREAD + "/api_calls/call_budget", "call_id": "call_budget", "count": 50}}
SUMMARY = {"tool": "mcp/duffel.search_offers", "call_id": "call_budget", "ok": True, "isError": False,
           "offers": OFFERS, "over_budget_excluded": 0,
           "groups": {k: {"currency": "USD", "duration_minutes": 330, "offer_id": OFFERS[0]["offer_id"],
                          "price": "300.00", "stops": 0} for k in ("best_value", "cheapest", "fastest")},
           "raw_response": {"status": "ok"}, "response_summary": "50 offers"}
EXTRACT = {"first_tool": "mcp/duffel.search_offers", "first_tool_arguments": {"origin": "SFO"},
           "render_intent": {"kind": "show_flights"}, "captured_slots": SLOT, "call_id": "call_budget"}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


writes, reads = [], []
saved = {}


def fake_urlopen(req, timeout=None):
    url = req.full_url
    if "metadata.google.internal" in url:
        return _Resp(b'{"access_token":"t"}')
    if req.get_method() == "PATCH":
        writes.append(url)
        saved[url] = json.loads(req.data.decode())
        return _Resp(b"{}")
    reads.append(url)
    return _Resp(json.dumps(saved.get(url, {})).encode())


urllib.request.urlopen = fake_urlopen
size = lambda o: len(json.dumps(o, default=str))


def render(tool_summary, slot, intent):
    g = dict(thread_path=THREAD, event_type="user_message", event_payload={},
             extraction_context=dict(EXTRACT, render_intent=intent), render_intent=intent, extraction_json="{}",
             slot_state_pre_tool=slot, slot_state_post_tool=slot, tool_summary=tool_summary, user_uid="u",
             relation_docs=[{"path": "user_thread_map/e", "doc": {"uid": "u"}, "merge": True}],
             firestore_project="p", firestore_database="(default)")
    exec(steps["render_widget_chat"]["tool"]["code"], g)
    return g["result"]


# ── The search turn ──────────────────────────────────────────────────────
r = render(SUMMARY, SLOT, {"kind": "show_flights"})
check(size(OFFERS) > 30000, "the synthetic search is realistic (%d bytes of offers)" % size(OFFERS))
check(size(r) < BUDGET, "render_widget_chat result is under the 100 KB offload line: %d bytes" % size(r))
check(size(r) < BUDGET // 2 + 10000, "with headroom: one copy of the widget, not several (%d bytes)" % size(r))
check(r.get("result_bytes") and abs(r["result_bytes"] - size(r)) < 200, "result_bytes reports the result's size")
check(r["offers_saved"] is True and any(u.endswith("/api_calls/call_budget") for u in writes),
      "the offers are saved once, inline, in the search's api_calls document")
stored = saved[[u for u in writes if u.endswith("/api_calls/call_budget")][0]]["fields"]
check(len(stored["offers"]["arrayValue"]["values"]) == 50 and "response" in stored and "arguments" in stored,
      "the saved document holds all 50 offers plus the call's arguments and response")
blob = json.dumps({k: r[k] for k in ("post_docs", "post_events", "final_slot_state")})
check(blob.count('"offer_id": "%s"' % OFFERS[37]["offer_id"]) == 1 and '"flight_offers"' not in blob,
      "an offer card appears once in the save batch (the widget the user sees), not in slot state or the tool event")
types = [e["event"]["type"] for e in r["post_events"]]
check(types == ["agent_tool_response", "agent_widget_emit", "agent_chat"], "all post-tool events are in the save batch: %s" % types)
tr = r["post_events"][0]["event"]["payload"]
check("offers" not in tr and tr.get("offers_count") == 50 and tr.get("offers_ref", "").endswith("/api_calls/call_budget"),
      "the tool event carries a reference and a count, not the offers")
check([d["path"].rsplit("/", 2)[-2:] for d in r["post_docs"]][:1] == [["slot_state", "current"]]
      and any(d["path"].startswith("user_thread_map/") for d in r["post_docs"]),
      "slot_state/current and the user_thread_map edge are in the save batch")
check(r["first_widget"] is None and r["first_widget_in_post_events"], "the large widget is carried once, in post_events")

g = dict(thread_path=THREAD, slot_state=r["final_slot_state"], extraction=EXTRACT, widget=r["first_widget"],
         post_events=r["post_events"], bot_message=r["bot_message"], request_id="", gateway_url="")
exec(steps["final_result"]["tool"]["code"], g)
fr = g["result"]
check((fr["render"] or {}).get("widget_type") == "flight_list" and len(fr["render"]["payload"].get("items") or []) == 50,
      "final_result still returns the full flight_list (read from post_events)")
check(fr["emitted_widget_types"] == ["flight_list"], "emitted_widget_types is unchanged")

# ── The next turn: the traveller picks offer 37 ──────────────────────────
reads.clear()
picked = dict(SLOT, picked_flight_offer_id="off_0037")
r2 = render({}, picked, {"kind": "flight_detail"})
w = r2["first_widget"] or {}
check(len(reads) == 1 and "off_0037" in json.dumps(w) and "selected-offer" not in json.dumps(w),
      "a picked offer is read back from the saved document (one read), not a placeholder")
check(size(r2) < BUDGET, "the pick turn is small: %d bytes" % size(r2))

# ── Small results stay byte-for-byte as before ───────────────────────────
small = render(dict(SUMMARY, offers=OFFERS[:3]), SLOT, {"kind": "show_flights"})
check(small["first_widget"] is not None and small["widgets"] and not small["first_widget_in_post_events"],
      "a small widget keeps first_widget and widgets as before")

# ── Static guards on the other two steps ─────────────────────────────────
norm = steps["normalize_tool_response"]["tool"]["code"]
check('next_state["flight_offers"] = ' not in norm and 'next_state["flight_offers_ref"]' in norm,
      "normalize_tool_response keeps a pointer in slot state, not the offers")
duffel = steps["call_duffel_offers"]["tool"]["code"]
ok_fn = duffel[duffel.index("def _ok("):duffel.index("def _request(")]
check('"control_data": payload' not in ok_fn and '"data": payload' in ok_fn,
      "call_duffel_offers returns the offers once (control_data is status only)")
check(re.search(r'"flight_offers_ref"', steps["extract_turn"]["tool"]["code"]) is not None,
      "a search-affecting change also clears the saved-offers pointer")

if failures:
    sys.exit("%d failure(s)" % len(failures))
