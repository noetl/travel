#!/usr/bin/env python3
"""Offline guard for the profile-merge QA case's LIVE tier (qa/regression/lib/profile_live.py).

The live tier used to call `POST {gateway}/api/profile` with `users/{id}/profile`. Neither exists,
so it could only ever report `blocked`, and nothing noticed. This runs the real flow end to end
against a fake gateway that models what actually happens behind it:

  /graphql executePlaybook -> profile playbook -> Firestore `users/{uid}`, merge = top-level keys
  /noetl/executions/{id}   -> execution document with build_response's result nested inside

and proves the case can PASS against a correct backend and FAILS against the two regressions it
exists for: a merge that replaces the document, and a login read that wipes it.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "qa", "regression", "lib"))
import profile_live  # noqa: E402
import qa_report  # noqa: E402

failures = []
checks = 0


def check(label, cond):
    global checks
    checks += 1
    print("  %-72s %s" % (label, "OK" if cond else "FAIL"))
    if not cond:
        failures.append(label)


class FakeGateway:
    """mode: 'correct' | 'replace' (save overwrites the doc) | 'read_wipes' (pre-#133 + empty merge)."""

    def __init__(self, mode="correct", pending_polls=2):
        self.mode = mode
        self.store = {}
        self.executions = {}
        self.pending_polls = pending_polls
        self.calls = []

    def _run_playbook(self, uid, profile, read_only):
        path = f"users/{uid}"
        if self.mode == "read_wipes" and read_only:
            self.store[path] = {}  # set_doc(merge=true, data={}) without updateMask
        elif not read_only:
            if self.mode == "replace":
                self.store[path] = dict(profile)
            else:
                self.store.setdefault(path, {}).update(profile)
        found = path in self.store
        return {"ok": True, "uid": uid, "saved": not read_only, "read_only": read_only,
                "found": found, "found_after_write": (False if read_only else found),
                "profile": dict(self.store.get(path, {})), "suggestions": [],
                "suggestions_error": "profile has no home_lat/home_lng; suggestions skipped"}

    def __call__(self, method, path, body=None):
        self.calls.append((method, path))
        if method == "POST" and path == "/graphql":
            v = body["variables"]["vars"]
            assert body["variables"]["name"] == "muno/playbooks/profile"
            eid = str(len(self.executions) + 1000)
            result = self._run_playbook(v["uid"], v["profile"], v["read_only"])
            # Nest it the way the runtime does: deep inside events, and once as a JSON string.
            self.executions[eid] = {"polls": 0, "doc": {
                "execution_id": eid, "status": "COMPLETED",
                "events": [{"event_type": "step.exit", "result": {"data": json.dumps({"result": result})}}]}}
            return {"data": {"executePlaybook": {"id": eid, "executionId": eid, "status": "started"}}}
        if method == "GET" and path.startswith("/noetl/executions/"):
            ex = self.executions[path.rsplit("/", 1)[1]]
            ex["polls"] += 1
            if ex["polls"] <= self.pending_polls:
                return {"status": "RUNNING"}
            return ex["doc"]
        raise AssertionError(f"unexpected call {method} {path}")


def run(gw, uid="qa-regression-user-0001"):
    case = qa_report.Case("profile_merge_live", "t")
    profile_live.run_merge_case(case, gw, "muno/playbooks/profile", uid,
                                "home_airport", "LIS", "seat_preference", "aisle",
                                timeout_s=5, poll_s=0, sleep=lambda s: None)
    return case


print("live tier against a correct backend")
gw = FakeGateway("correct")
case = run(gw)
check("verdict is PASS", case.verdict() == "pass")
check("it called the real endpoints only (/graphql + /noetl/executions)",
      {p.split("/noetl/executions/")[0] or "/noetl/executions/" for _, p in gw.calls}
      <= {"/graphql", "/noetl/executions/"})
check("it never touches the non-existent /api/profile", all("/api/profile" not in p for _, p in gw.calls))
check("it polled past non-terminal statuses", sum(1 for m, _ in gw.calls if m == "GET") > 3)
check("the document it wrote is users/{uid}, not users/{uid}/profile",
      list(gw.store) == ["users/qa-regression-user-0001"])
check("three executions: write A, write B, read", len(gw.executions) == 3)

print("live tier against the regressions it exists for")
case = run(FakeGateway("replace"))
check("a save that REPLACES the document fails the case", case.verdict() == "fail")
check("...on section A surviving", "section_a_survived_the_section_b_write" in case.result()["failed_assertions"])
case = run(FakeGateway("read_wipes"))
check("a login read that WIPES the document fails the case", case.verdict() == "fail")
check("...on an empty read-back", "read_back_returned_a_document" in case.result()["failed_assertions"])

print("safety")
gw = FakeGateway("correct")
case = run(gw, uid="auth0|real-person")
check("a non-synthetic uid is refused before any call", case.verdict() == "blocked" and gw.calls == [])

print("payload extraction")
check("finds build_response inside a JSON string inside events",
      (profile_live.find_payload({"events": [{"x": json.dumps({"ok": True, "profile": {"a": 1}})}]})
       or {}).get("profile") == {"a": 1})
check("an execution with no payload yields None", profile_live.find_payload({"status": "COMPLETED"}) is None)

print("detector shared with the case's controls")
check("merged_ok accepts both sections", profile_live.merged_ok({"a": 1, "b": 2}, "a", 1, "b", 2))
check("merged_ok rejects a wipe / empty / None",
      not any(profile_live.merged_ok(p, "a", 1, "b", 2) for p in ({"b": 2}, {}, None)))
case_yaml = open(os.path.join(HERE, "..", "qa", "regression", "cases", "profile-merge.yaml")).read()
check("the case's detector step imports the same merged_ok", "from profile_live import merged_ok" in case_yaml)
check("the case no longer references /api/profile or users/{id}/profile",
      "/api/profile" not in case_yaml and "/profile\"" not in case_yaml)

import yaml  # noqa: E402
steps = {st["step"]: st for st in yaml.safe_load(case_yaml)["workflow"]}
arcs = [a.get("step") for a in steps["verify_merge_detector"]["next"]["arcs"]]
check("the detector still routes to BOTH the live tier and the blocked report",
      arcs == ["run_live_profile_merge", "report_live_blocked"])
check("the live step exists and runs the shared module",
      "profile_live.run_merge_case" in steps["run_live_profile_merge"]["tool"]["cmds"][0])

print("\n%d checks, %d failed" % (checks, len(failures)))
sys.exit(1 if failures else 0)
