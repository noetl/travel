#!/usr/bin/env python3
"""Pure helpers of scripts/validate_turn_firestore.py (no network)."""
import sys

sys.path.insert(0, "scripts")
from backfill_user_thread_map import edge_id as backfill_edge_id  # noqa: E402
from validate_turn_firestore import Firestore, edge_id, find_counts, locate_turn, ts_ms  # noqa: E402

failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


TURN1 = ["user_message", "agent_slot_update", "agent_tool_call", "agent_tool_response", "agent_widget_emit", "agent_chat"]
TURN2 = ["user_widget_cta_click", "agent_slot_update", "agent_tool_call", "agent_tool_response", "agent_widget_emit", "agent_chat"]

# A complete two-turn thread: turn 2 is found after turn 1, in full.
types = TURN1 + TURN2
times = [100] * 6 + [200] * 6
check(locate_turn(types, times, TURN1, 0, 50) == (0, TURN1), "turn 1 found at seq 1")
check(locate_turn(types, times, TURN2, 0, 150) == (6, TURN2), "turn 2 found at seq 7 without an offset")
check(locate_turn(types, times, TURN2, 6, 150) == (6, TURN2), "turn 2 found from the consumed offset")

# The lost-render case: only the pre-tool half of turn 2 was stored.
short = TURN1 + TURN2[:3]
i0, stored = locate_turn(short, [100] * 6 + [200] * 3, TURN2, 0, 150)
check((i0, stored) == (6, TURN2[:3]), "a partly stored turn reports what is there")

# Two turns that open with the same type: server_time picks the right one.
same = TURN1 + TURN1
check(locate_turn(same, [100] * 6 + [200] * 6, TURN1, 0, 150)[0] == 6, "server_time disambiguates repeated openers")

check(locate_turn(TURN1, [100] * 6, TURN2, 0, 50) == (None, []), "a turn with nothing stored")
check(locate_turn(TURN1, [100] * 6, [], 0, 50) == (None, []), "no expected events")

check(edge_id("auth0|u", "chat-x") == backfill_edge_id("auth0|u", "chat-x"), "edge id matches the backfill's")
check(ts_ms("2026-10-15T14:54:45.709579Z") == 1792076085709, "RFC3339 server_time to ms")
check(ts_ms(1792076085709) == 1792076085709 and ts_ms(None) == 0, "integer and missing server_time")
check(find_counts({"a": [{"set_count": 1, "event_count": 3, "set_succeeded": 1}]})["event_count"] == 3,
      "persist counts found anywhere in the child result")
check(Firestore.decode({"mapValue": {"fields": {"n": {"integerValue": "2"}, "l": {"arrayValue": {"values": [{"stringValue": "a"}]}}}}})
      == {"n": 2, "l": ["a"]}, "Firestore REST values decode")

if failures:
    sys.exit(f"{len(failures)} failure(s)")
