#!/usr/bin/env python3
"""Tests for the cc-meter SessionEnd logger (log-session.py).

The module name has a hyphen, so it is loaded by path. Run with:
    python3 -m unittest discover -s tests
"""
import importlib.util
import os
import unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
_spec = importlib.util.spec_from_file_location(
    "log_session", os.path.join(SCRIPTS, "log-session.py")
)
log_session = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(log_session)


def assistant(model="claude-opus-4-8", inp=0, out=0, cr=0, cw=0, tools=None, ts=None):
    content = [{"type": "tool_use", "name": t} for t in (tools or [])]
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_read_input_tokens": cr,
                "cache_creation_input_tokens": cw,
            },
            "content": content,
        },
    }


class BuildSessionRecord(unittest.TestCase):
    def test_sums_usage_counts_tools_and_picks_model(self):
        objs = [
            {"type": "user", "message": {"content": "hi"}},
            assistant(inp=10, out=100, cr=1000, cw=200, tools=["Bash", "Edit"], ts="2026-06-11T10:00:00Z"),
            assistant(inp=5, out=20, cr=500, tools=["Bash"], ts="2026-06-11T10:05:00Z"),
        ]
        rec = log_session.build_session_record(objs, "sess-1", "myproj")
        self.assertEqual(rec["api_calls"], 2)
        self.assertEqual(rec["input_tokens"], 15)
        self.assertEqual(rec["output_tokens"], 120)
        self.assertEqual(rec["cache_read_tokens"], 1500)
        self.assertEqual(rec["cache_write_tokens"], 200)
        self.assertEqual(rec["tools"], {"Bash": 2, "Edit": 1})
        self.assertEqual(rec["session_id"], "sess-1")
        self.assertEqual(rec["project"], "myproj")
        self.assertEqual(rec["last_ts"], "2026-06-11T10:05:00Z")
        self.assertEqual(rec["first_ts"], "2026-06-11T10:00:00Z")

    def test_returns_none_when_no_assistant_calls(self):
        objs = [{"type": "user", "message": {"content": "hi"}}]
        self.assertIsNone(log_session.build_session_record(objs, "sess-2", "p"))

    def test_cost_uses_model_pricing(self):
        # opus: (5, 25, 0.5, 6.25) per 1M
        objs = [assistant(model="claude-opus-4-8", inp=10, out=100, cr=1000, cw=200)]
        rec = log_session.build_session_record(objs, "s", "p")
        # (10*5 + 100*25 + 1000*0.5 + 200*6.25)/1e6 = 4300/1e6
        self.assertAlmostEqual(rec["est_cost_usd"], 0.0043, places=6)

    def test_unknown_model_falls_back_to_sonnet(self):
        objs = [assistant(model="some-future-model", inp=1_000_000, out=0)]
        rec = log_session.build_session_record(objs, "s", "p")
        # sonnet input price 3.0 per 1M -> exactly 3.0
        self.assertAlmostEqual(rec["est_cost_usd"], 3.0, places=4)


class Dedupe(unittest.TestCase):
    def test_drops_prior_entry_for_same_session(self):
        existing = [
            {"session_id": "a", "est_cost_usd": 1.0},
            {"session_id": "b", "est_cost_usd": 2.0},
        ]
        rec = {"session_id": "a", "est_cost_usd": 9.9}
        out = log_session.dedupe(existing, rec)
        sids = [r["session_id"] for r in out]
        self.assertEqual(sids, ["b", "a"])  # old 'a' dropped, new 'a' appended last
        self.assertEqual(out[-1]["est_cost_usd"], 9.9)

    def test_keeps_all_when_new_session(self):
        existing = [{"session_id": "a"}, {"session_id": "b"}]
        rec = {"session_id": "c"}
        out = log_session.dedupe(existing, rec)
        self.assertEqual([r["session_id"] for r in out], ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
