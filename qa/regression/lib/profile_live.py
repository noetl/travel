"""Live half of the profile-merge regression: drive the REAL profile path.

    gateway POST /graphql  executePlaybook(name: "muno/playbooks/profile", variables: {uid, profile, read_only})
    gateway GET  /noetl/executions/{id}   until terminal
    -> build_response's result: {ok, uid, saved, read_only, found, found_after_write, profile, ...}

This is exactly what adiona/frontend does (`executeProfilePlaybook` + `waitForExecutionResult`).
The previous live tier called `POST {gateway}/api/profile` with `users/{id}/profile`; neither the
endpoint nor the path exists (the profile is the document `users/{uid}`), so it could only ever
report `blocked`.

The transport is injected so `scripts/qa_profile_merge_live_test.py` can run the whole flow
against a fake gateway in CI.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable

TERMINAL_STATUSES = {"completed", "succeeded", "failed", "error", "cancelled", "canceled"}
SUCCESS_STATUSES = {"completed", "succeeded"}
SYNTHETIC_PREFIXES = ("qa-", "test-")

EXECUTE_MUTATION = """
mutation ExecutePlaybook($name: String!, $vars: JSON) {
  executePlaybook(name: $name, variables: $vars) { id executionId name status }
}
"""


class GatewayError(RuntimeError):
    pass


def merged_ok(profile: Any, a_key: str, a_value: Any, b_key: str, b_value: Any) -> bool:
    """The detector: both sections present with their own values in the read-back profile."""
    profile = profile if isinstance(profile, dict) else {}
    return profile.get(a_key) == a_value and profile.get(b_key) == b_value


def find_payload(value: Any, depth: int = 0) -> dict | None:
    """Locate build_response's result inside an execution document, wherever the runtime nests
    it. Mirrors the SPA's extractProfilePlaybookPayload: an object carrying a `profile` object."""
    if depth > 30 or value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in "{[" and text[-1:] in "}]":
            try:
                return find_payload(json.loads(text), depth + 1)
            except ValueError:
                return None
        return None
    if isinstance(value, list):
        for item in reversed(value):  # last event wins, as in the SPA
            found = find_payload(item, depth + 1)
            if found:
                return found
        return None
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("profile"), dict) and "ok" in value:
        return value
    priority = ["result", "output", "data", "payload", "response", "event_payload", "details"]
    for key in [k for k in priority if k in value] + [k for k in value if k not in priority]:
        found = find_payload(value[key], depth + 1)
        if found:
            return found
    return None


def execution_status(execution: dict) -> str:
    for holder in (execution, execution.get("data"), execution.get("result")):
        if isinstance(holder, dict) and holder.get("status"):
            return str(holder["status"]).strip().lower()
    return ""


Transport = Callable[[str, str, "dict | None"], dict]


def http_transport(base_url: str, token: str, timeout: float = 30.0) -> Transport:
    base = base_url.rstrip("/")

    def call(method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{base}{path}", data=data, method=method, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            raise GatewayError(f"HTTP {exc.code} {method} {path}: "
                               f"{exc.read().decode('utf-8', 'replace')[:300]}") from None

    return call


def run_profile(call: Transport, playbook: str, uid: str, profile: dict, read_only: bool,
                timeout_s: float = 180.0, poll_s: float = 1.5,
                sleep: Callable[[float], None] = time.sleep) -> dict:
    """One profile playbook execution, end to end. Returns
    {execution_id, status, payload} where payload is build_response's result (or None)."""
    body = call("POST", "/graphql", {"query": EXECUTE_MUTATION, "variables": {
        "name": playbook, "vars": {"uid": uid, "profile": profile, "read_only": read_only}}})
    if body.get("errors"):
        raise GatewayError(f"executePlaybook: {body['errors'][0].get('message', body['errors'][0])}")
    started = (body.get("data") or {}).get("executePlaybook") or {}
    execution_id = str(started.get("executionId") or started.get("id") or "").strip()
    if not execution_id:
        raise GatewayError(f"executePlaybook returned no execution id: {json.dumps(body)[:300]}")

    deadline = time.monotonic() + timeout_s
    execution: dict = {}
    while True:
        try:
            execution = call("GET", f"/noetl/executions/{execution_id}", None)
        except GatewayError as exc:
            # The execution can be briefly absent from the gateway projection after dispatch.
            if "HTTP 404" not in str(exc):
                raise
        status = execution_status(execution)
        if status in TERMINAL_STATUSES:
            break
        if time.monotonic() >= deadline:
            raise GatewayError(f"execution {execution_id} not terminal after {timeout_s:.0f}s "
                               f"(last status {status or 'unknown'!r})")
        sleep(poll_s)
    return {"execution_id": execution_id, "status": status, "payload": find_payload(execution)}


def run_merge_case(case, call: Transport, playbook: str, uid: str,
                   a_key: str, a_value: Any, b_key: str, b_value: Any, **run_kw) -> None:
    """Write section A, write section B, read back read-only; require both sections.
    Records assertions on `case` (qa_report.Case)."""
    if not uid.startswith(SYNTHETIC_PREFIXES):
        # A real user id must never reach a live write. Checked here as well as in the playbook's
        # prepare step, because this function is what actually writes.
        case.block(f"refusing to write a non-synthetic uid {uid!r}: must start with qa- or test-")
        return

    # ⚠ PREFLIGHT, read-only. The gateway binds `uid` to the SESSION's identity (it does not
    # trust the request), so with a token for a real account every write below would land on
    # that account's profile, not on the synthetic uid asked for. Read first and compare: if
    # the uid the playbook actually ran as differs, stop before writing anything. The fix is a
    # dedicated QA Auth0 account whose subject IS the test_user_id.
    preflight = run_profile(call, playbook, uid, {}, True, **run_kw)
    ran_as = (preflight["payload"] or {}).get("uid")
    if ran_as != uid:
        case.block(f"the gateway ran the profile playbook as {ran_as!r}, not the requested {uid!r} "
                   "(identity is bound to the session); refusing to write. Use a QA account whose "
                   "Auth0 subject is test_user_id.")
        case.add_evidence(preflight_execution_id=preflight["execution_id"])
        return

    runs = {}
    for label, profile, read_only in (("write_a", {a_key: a_value}, False),
                                      ("write_b", {b_key: b_value}, False),
                                      ("read", {}, True)):
        run = run_profile(call, playbook, uid, profile, read_only, **run_kw)
        runs[label] = run
        payload = run["payload"] or {}
        case.assert_in(f"{label}_execution_succeeded", run["status"], sorted(SUCCESS_STATUSES),
                       f"execution {run['execution_id']}")
        case.assert_equal(f"{label}_payload_ok", payload.get("ok"), True,
                          "build_response must report ok (validate_input accepted the input)")
        if read_only:
            case.assert_equal("read_reports_read_only", payload.get("read_only"), True,
                              "the login-time read must take the read-only branch")
            case.assert_equal("read_did_not_save", payload.get("saved"), False,
                              "a read must not write (adiona/frontend#59)")
        else:
            case.assert_equal(f"{label}_saved", payload.get("saved"), True, "the write must be attempted")
            case.assert_equal(f"{label}_found_after_write", payload.get("found_after_write"), True,
                              "read-after-write must find the document the write just made")

    profile = (runs["read"]["payload"] or {}).get("profile") or {}
    # An empty read-back is the false green this case exists to prevent.
    case.assert_non_empty("read_back_returned_a_document", profile,
                          "a read-back that returned nothing cannot evidence a merge")
    case.assert_equal("section_b_was_saved", profile.get(b_key), b_value,
                      "the write under test must itself have landed")
    case.assert_equal("section_a_survived_the_section_b_write", profile.get(a_key), a_value,
                      "THE REGRESSION: writing section B must merge, not replace the document")
    case.add_evidence(
        playbook=playbook, document_path=f"users/{uid}",
        execution_ids={k: v["execution_id"] for k, v in runs.items()},
        read_back_keys=sorted(profile),
    )
