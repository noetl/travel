#!/usr/bin/env python3
"""Unit-test the extract_turn routing logic of itinerary-planner.yaml (v56 fix).

Extracts the real embedded `code:` block from the `extract_turn` step and runs
it against mock slot states for the 5 scenarios the fix must satisfy, with no
external calls (auth-free, deterministic).
"""
import sys, yaml, copy

PLAYBOOK = "playbooks/itinerary-planner.yaml"

doc = yaml.safe_load(open(PLAYBOOK))
steps = doc["workflow"]
extract = next(s for s in steps if s.get("step") == "extract_turn")
code = extract["tool"]["code"]

def run(event_type, text, loaded_slot_state):
    g = {
        "thread_path": "chat_threads/test",
        "event_type": event_type,
        "event_payload": {"text": text} if text is not None else {},
        "input_event": {},
        "user_uid": "guest",
        "loaded_slot_state": {"data": copy.deepcopy(loaded_slot_state)},
        "ai_provider": "openai",
        "llm_extraction_model": "gpt-4o",
        "openai_api_key": "",
        "anthropic_api_key": "",
        "flight_provider": "duffel",
        "duffel_env": "test",
    }
    exec(compile(code, PLAYBOOK + ":extract_turn", "exec"), g)
    return g["result"]

def summ(r):
    return {
        "first_tool": r["first_tool"],
        "render_intent": r["render_intent"],
        "query": (r["first_tool_arguments"] or {}).get("query"),
        "places_seen": r["slot_state"].get("places_seen"),
        "region": r["slot_state"].get("region", {}).get("label"),
    }

PARIS_STATE = {
    "region": {"label": "Paris", "city_code": "PAR", "country_code": "FR", "kind": "city"},
    "region_label": "Paris", "region_city_code": "PAR",
    "places_seen": ["ChIJD7fiBh9u5kcRYJSMaMOCCwQ"], "total_results_seen": 1,
}

failures = []
def check(name, got, want_tool, want_intent_kind, extra=None):
    ok = got["first_tool"] == want_tool and got["render_intent"].get("kind") == want_intent_kind
    if extra:
        ok = ok and extra(got)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {got}")
    if not ok:
        failures.append(name)

# (1) fresh thread, lowercase destination -> show_places
check("1 fresh lowercase 'Trip to paris'",
      summ(run("user_message", "Trip to paris", {})),
      "mcp/google-places.search_text", "show_places",
      lambda g: g["query"] == "Paris" and g["places_seen"] == [])

# (1b) fresh thread, capitalized -> identical
check("1b fresh capitalized 'Trip to Paris'",
      summ(run("user_message", "Trip to Paris", {})),
      "mcp/google-places.search_text", "show_places",
      lambda g: g["query"] == "Paris")

# (2) repeat same destination on populated thread -> NOW re-shows places (the bug)
check("2 repeat 'Trip to paris' on populated thread",
      summ(run("user_message", "Trip to paris", PARIS_STATE)),
      "mcp/google-places.search_text", "show_places",
      lambda g: g["query"] == "Paris" and g["places_seen"] == [])

# (3) destination CHANGE on populated Paris thread -> London places, state reset
check("3 destination change 'Trip to London' on Paris thread",
      summ(run("user_message", "Trip to London", PARIS_STATE)),
      "mcp/google-places.search_text", "show_places",
      lambda g: g["query"] == "London" and g["region"] == "London" and g["places_seen"] == [])

# (4) in-flow dates follow-up (no region restated) -> stays collect_missing (date picker), NO places re-search
check("4 in-flow dates follow-up 'next month'",
      summ(run("user_message", "next month", PARIS_STATE)),
      "", "collect_missing",
      lambda g: g["places_seen"] == ["ChIJD7fiBh9u5kcRYJSMaMOCCwQ"])

# (5) widget place-pick (user_widget_submit writes region) -> must NOT re-search places
PICK_STATE = copy.deepcopy(PARIS_STATE)
r5 = run("user_widget_submit", "Paris", PICK_STATE)
# emulate the planner's submit handling by injecting a submitted place via payload
g5 = summ(r5)
check("5 widget place-pick does not re-search places (user_widget_submit)",
      g5, "", g5["render_intent"].get("kind"),
      lambda g: g["first_tool"] != "mcp/google-places.search_text")

print()
if failures:
    print("FAILURES:", failures); sys.exit(1)
print("ALL ROUTING SCENARIOS PASS")
