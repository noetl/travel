#!/usr/bin/env python3
"""Test-report primitives for the NoETL regression suite.

One test case writes one result document. The suite runner merges those documents into a report.
Everything here exists to make a case that did not really pass unable to look like one.

Three rules are enforced rather than documented:

**A result must carry at least one assertion.** A case that asserted nothing is not a passing case,
it is a case that did not test anything, and it is recorded as `error`.

**`pass` requires every assertion to have passed.** The verdict is computed from the assertions, not
supplied by the caller. A case cannot declare itself green.

**An empty fetch is never a pass.** `assert_non_empty` exists because the most common false green in
an integration suite is a request that returned nothing and an assertion that only checked for the
absence of an exception.

Verdicts: `pass` · `fail` (assertion failed) · `blocked` (preconditions absent -- credentials, a
disabled provider; the case did not run and must not be counted as a pass) · `error` (the harness
itself broke).
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PASS = "pass"
FAIL = "fail"
BLOCKED = "blocked"
ERROR = "error"
VERDICTS = (PASS, FAIL, BLOCKED, ERROR)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Case:
    """Collects assertions for one test case and writes its result document."""

    def __init__(self, case_id: str, title: str, suite: str = "travel-regression") -> None:
        if not str(case_id).strip():
            raise ValueError("a test case needs a case_id")
        self.case_id = case_id
        self.title = title
        self.suite = suite
        self.started_at = utc_now()
        self._start = time.monotonic()
        self.assertions: list[dict[str, Any]] = []
        self.evidence: dict[str, Any] = {}
        self.blocked_reason = ""

    # -- assertions -------------------------------------------------------------------------

    def _record(self, name: str, ok: bool, detail: str, expected: Any = None,
                actual: Any = None) -> bool:
        self.assertions.append({
            "assertion": name,
            "ok": bool(ok),
            "detail": detail,
            "expected": expected,
            "actual": actual,
        })
        return bool(ok)

    def assert_true(self, name: str, condition: bool, detail: str = "") -> bool:
        return self._record(name, bool(condition), detail, True, bool(condition))

    def assert_equal(self, name: str, actual: Any, expected: Any, detail: str = "") -> bool:
        return self._record(name, actual == expected, detail, expected, actual)

    def assert_in(self, name: str, needle: Any, haystack: Any, detail: str = "") -> bool:
        try:
            ok = needle in haystack
        except TypeError:
            ok = False
        return self._record(name, ok, detail, f"contains {needle!r}", _summarise(haystack))

    def assert_non_empty(self, name: str, value: Any, detail: str = "") -> bool:
        """The assertion that stops an empty response from reading as a pass.

        A fetch that returned nothing, a document with no fields, an empty pose list -- each of
        these satisfies "no exception was raised" while proving nothing at all.
        """

        ok = value is not None and value != "" and value != [] and value != {}
        return self._record(name, ok, detail or "value must be non-empty", "non-empty",
                            _summarise(value))

    def assert_max_duration(self, name: str, seconds: float, budget_seconds: float,
                            detail: str = "") -> bool:
        """Catches the stall class of failure, where a run completes but far too slowly."""

        return self._record(
            name, seconds <= budget_seconds,
            detail or f"must complete within {budget_seconds}s",
            f"<= {budget_seconds}s", f"{seconds:.3f}s",
        )

    # -- outcome ----------------------------------------------------------------------------

    def block(self, reason: str) -> None:
        """Declare the case unable to run. Blocked is never counted as a pass."""

        self.blocked_reason = reason

    def add_evidence(self, **items: Any) -> None:
        self.evidence.update(items)

    def verdict(self) -> str:
        if self.blocked_reason:
            return BLOCKED
        if not self.assertions:
            return ERROR  # a case that asserted nothing tested nothing
        return PASS if all(a["ok"] for a in self.assertions) else FAIL

    def result(self) -> dict[str, Any]:
        verdict = self.verdict()
        failed = [a["assertion"] for a in self.assertions if not a["ok"]]
        return {
            "schema_version": 1,
            "suite": self.suite,
            "case_id": self.case_id,
            "title": self.title,
            "status": verdict,
            "started_at": self.started_at,
            "ended_at": utc_now(),
            "duration_ms": round((time.monotonic() - self._start) * 1000, 3),
            "assertion_count": len(self.assertions),
            "failed_assertions": failed,
            "blocked_reason": self.blocked_reason,
            "assertions": self.assertions,
            "evidence": self.evidence,
        }

    def write(self, path: str | Path) -> dict[str, Any]:
        result = self.result()
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result

    def finish(self, path: str | Path) -> int:
        """Write the result and return the process exit code the runtime should see.

        A failing or errored case exits non-zero so the step fails loudly. `blocked` also exits
        non-zero: a case whose preconditions were absent did not pass, and a suite that treated it
        as green would be reporting coverage it does not have.
        """

        result = self.write(path)
        print(json.dumps({
            "case_id": result["case_id"],
            "status": result["status"],
            "duration_ms": result["duration_ms"],
            "assertion_count": result["assertion_count"],
            "failed_assertions": result["failed_assertions"],
            "blocked_reason": result["blocked_reason"],
        }, sort_keys=True))
        return 0 if result["status"] == PASS else 1


def _summarise(value: Any, limit: int = 200) -> str:
    try:
        text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def require_debug() -> None:
    """Refuse to run under -O / PYTHONOPTIMIZE.

    Assertions in a test harness that the interpreter has stripped are the purest form of false
    green: every check disappears and the suite reports success.
    """

    if not __debug__:
        raise SystemExit(
            "assertions are disabled (-O / PYTHONOPTIMIZE). Refusing to run a test case whose "
            "checks would not execute. Invoke as: env -u PYTHONOPTIMIZE python3 ..."
        )


def env_or_block(case: Case, name: str, default: str = "") -> str:
    """Read a required environment value, or mark the case blocked rather than guessing."""

    value = os.environ.get(name, default).strip()
    if not value:
        case.block(f"required environment value is absent: {name}")
    return value


if __name__ == "__main__":  # pragma: no cover - smoke check
    require_debug()
    demo = Case("self_check", "qa_report self check")
    demo.assert_true("library_loads", True, "the harness imported and ran")
    demo.assert_non_empty("verdicts_declared", list(VERDICTS))
    sys.exit(demo.finish(sys.argv[1] if len(sys.argv) > 1 else "/dev/stdout"))
