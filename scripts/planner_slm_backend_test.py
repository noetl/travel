#!/usr/bin/env python3
"""Unit-test the selectable model backend in itinerary-planner extract_turn.

Extracts the REAL embedded `code:` block from the playbook (same technique as
planner_restate_routing_test.py) and exercises `_llm_extract` against a mocked
transport -- no network, no credentials, deterministic.

The load-bearing assertion is DefaultUnchanged: with `slm_backend` unset the
dispatcher must still build a Gemini `:generateContent` request, so turning the
flag off is a true revert.

Run:  python3 scripts/planner_slm_backend_test.py
"""
import copy
import io
import json
import sys
import unittest
import urllib.request

import yaml

PLAYBOOK = "playbooks/itinerary-planner.yaml"

_doc = yaml.safe_load(open(PLAYBOOK))
_code = next(s for s in _doc["workflow"] if s.get("step") == "extract_turn")["tool"]["code"]
assert "_llm_extract_openai" in _code, "extraction failed: refactor not present in playbook"


class _Resp(io.BytesIO):
    """Minimal context-manager stand-in for urlopen's return."""
    def __enter__(self): return self
    def __exit__(self, *a): return False


def load(**overrides):
    """exec the real block with the LLM path disabled, return its globals."""
    g = {
        "thread_path": "chat_threads/test",
        "event_type": "user_message",
        "event_payload": {"text": "trip to Lisbon"},
        "input_event": {},
        "user_uid": "guest",
        "loaded_slot_state": {"data": {}},
        "ai_provider": "vertex-ai",
        "llm_extraction_model": "gemini-3.8-flash",
        "openai_api_key": "",
        "anthropic_api_key": "",
        "flight_provider": "duffel",
        "duffel_env": "test",
        # keep the in-exec LLM call from firing; we call _llm_extract directly
        "llm_extraction_enabled": "false",
        "default_origin": "SFO",
        "vertex_project": "shastaratech-noetl-prod",
        "vertex_region": "global",
        "slm_backend": "gemini",
        "slm_endpoint": "",
        "slm_model": "",
        "slm_api_key": "",
    }
    g.update(overrides)
    exec(compile(_code, PLAYBOOK + ":extract_turn", "exec"), g)
    return g


class Capture:
    """Swap urllib.request.urlopen for a recorder returning a canned body."""
    def __init__(self, body):
        self.body = body
        self.req = None
    def __enter__(self):
        self._orig = urllib.request.urlopen
        def fake(req, timeout=None):
            url = getattr(req, "full_url", str(req))
            if "metadata.google.internal" in url:
                # _vertex_token() mints a WI token; hand back a stub so the
                # Gemini path can proceed without a metadata server.
                return _Resp(json.dumps({"access_token": "stub-token"}).encode())
            self.req = req
            return _Resp(json.dumps(self.body).encode())
        urllib.request.urlopen = fake
        return self
    def __exit__(self, *a):
        urllib.request.urlopen = self._orig
        return False


GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": '{"slot_updates":{},"tool_requests":[],"render_intent":{"kind":"collect_missing"}}'}]}}]}
OPENAI_OK = {"choices": [{"message": {"content": '{"slot_updates":{},"tool_requests":[],"render_intent":{"kind":"collect_missing"}}'}}]}
EXPECT = {"slot_updates": {}, "tool_requests": [], "render_intent": {"kind": "collect_missing"}}


class DefaultUnchanged(unittest.TestCase):
    """Flag off => the existing Gemini path, unchanged."""

    def _run(self, **ov):
        g = load(**ov)
        with Capture(GEMINI_OK) as cap:
            out = g["_llm_extract"]("gemini-3.8-flash", "trip to Lisbon", {},
                                    "user_message", "proj-x", "global")
        return out, cap.req

    def test_unset_backend_uses_generatecontent(self):
        out, req = self._run(slm_backend="")
        self.assertEqual(out, EXPECT)
        self.assertIn(":generateContent", req.full_url)
        self.assertIn("proj-x", req.full_url)

    def test_explicit_gemini_uses_generatecontent(self):
        out, req = self._run(slm_backend="gemini")
        self.assertEqual(out, EXPECT)
        self.assertIn(":generateContent", req.full_url)

    def test_gemini_body_still_uses_responsemimetype(self):
        _, req = self._run(slm_backend="gemini")
        body = json.loads(req.data.decode())
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("systemInstruction", body)

    def test_global_region_uses_global_host(self):
        _, req = self._run(slm_backend="gemini")
        self.assertTrue(req.full_url.startswith("https://aiplatform.googleapis.com/"))


class OpenAIBackend(unittest.TestCase):
    EP = "http://vllm.noetl.svc.cluster.local:8000/v1/chat/completions"

    def _run(self, endpoint=None, **ov):
        g = load(slm_backend="vllm", slm_endpoint=endpoint or self.EP, **ov)
        with Capture(OPENAI_OK) as cap:
            out = g["_llm_extract"]("gemini-3.8-flash", "trip to Lisbon", {},
                                    "user_message", "proj-x", "global")
        return out, cap.req

    def test_returns_same_contract(self):
        out, _ = self._run()
        self.assertEqual(out, EXPECT)

    def test_posts_openai_shape(self):
        _, req = self._run()
        self.assertEqual(req.full_url, self.EP)
        body = json.loads(req.data.decode())
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertEqual(body["temperature"], 0)
        self.assertNotIn("generationConfig", body)

    def test_slm_model_overrides_the_gemini_model_id(self):
        _, req = self._run(slm_model="google/gemma4@gemma-4-26b-a4b-it")
        self.assertEqual(json.loads(req.data.decode())["model"],
                         "google/gemma4@gemma-4-26b-a4b-it")

    def test_plain_incluster_endpoint_sends_no_auth(self):
        _, req = self._run()
        self.assertIsNone(req.headers.get("Authorization"))

    def test_vertex_dedicated_endpoint_gets_workload_identity_token(self):
        """A Gemma endpoint on Vertex is OpenAI-shaped but still needs the
        pod's WI token -- this is the path the Gemma 4 migration uses."""
        _, req = self._run(endpoint="https://ep-123.us-central1-99.prediction.vertexai.goog/v1/projects/p/locations/us-central1/endpoints/ep-123/chat/completions")
        self.assertEqual(req.headers.get("Authorization"), "Bearer stub-token")

    def test_explicit_api_key_is_used(self):
        _, req = self._run(slm_api_key="sk-test")
        self.assertEqual(req.headers.get("Authorization"), "Bearer sk-test")

    def test_empty_content_raises_so_caller_falls_back(self):
        g = load(slm_backend="vllm", slm_endpoint=self.EP)
        with Capture({"choices": [{"message": {"content": "   "}}]}):
            with self.assertRaises(ValueError):
                g["_llm_extract"]("m", "t", {}, "user_message", "p", "global")

    def test_no_choices_raises(self):
        g = load(slm_backend="vllm", slm_endpoint=self.EP)
        with Capture({"choices": []}):
            with self.assertRaises(ValueError):
                g["_llm_extract"]("m", "t", {}, "user_message", "p", "global")


class MisconfigurationIsLoud(unittest.TestCase):
    def test_vllm_without_endpoint_raises(self):
        g = load(slm_backend="vllm", slm_endpoint="")
        with self.assertRaises(ValueError):
            g["_llm_extract"]("m", "t", {}, "user_message", "p", "global")

    def test_unknown_backend_raises_rather_than_silently_using_gemini(self):
        g = load(slm_backend="vertex-ai")   # plausible typo
        with self.assertRaises(ValueError):
            g["_llm_extract"]("m", "t", {}, "user_message", "p", "global")


if __name__ == "__main__":
    unittest.main(verbosity=2)
