#!/usr/bin/env python3
"""Tests for statusline.py. Loaded by path (parity with test_log_session.py).
Run: python3 -m unittest discover -s tests"""
import importlib.util
import os
import json as _json
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
_spec = importlib.util.spec_from_file_location(
    "statusline", os.path.join(SCRIPTS, "statusline.py"))
statusline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(statusline)


class HumanizeRemaining(unittest.TestCase):
    def test_hours_and_minutes_zero_padded(self):
        self.assertEqual(statusline.humanize_remaining(2 * 3600 + 13 * 60), "2h13m")
        self.assertEqual(statusline.humanize_remaining(2 * 3600 + 5 * 60), "2h05m")

    def test_minutes_only(self):
        self.assertEqual(statusline.humanize_remaining(13 * 60), "13m")
        self.assertEqual(statusline.humanize_remaining(59 * 60 + 59), "59m")

    def test_under_one_minute(self):
        self.assertEqual(statusline.humanize_remaining(45), "<1m")
        self.assertEqual(statusline.humanize_remaining(1), "<1m")

    def test_zero_or_negative_returns_empty(self):
        self.assertEqual(statusline.humanize_remaining(0), "")
        self.assertEqual(statusline.humanize_remaining(-10), "")


class Segments(unittest.TestCase):
    def payload(self):
        return {
            "model": {"display_name": "Opus 4.8"},
            "context_window": {"total_input_tokens": 35763, "total_output_tokens": 477,
                               "used_percentage": 4},
            "cost": {"total_cost_usd": 0.3029775},
            "rate_limits": {
                "five_hour": {"used_percentage": 43, "resets_at": 9999999999},
                "seven_day": {"used_percentage": 64, "resets_at": 9999999999},
            },
        }

    def test_each_segment_renders(self):
        d = self.payload()
        self.assertIn("Opus 4.8", statusline.render_segment("model", d))
        self.assertIn("⬆", statusline.render_segment("tokens", d))
        self.assertEqual(statusline.render_segment("ctx", d), "ctx 4%")
        self.assertEqual(statusline.render_segment("cost", d), "$0.303")
        self.assertIn("5h", statusline.render_segment("5h", d))
        self.assertIn("7d", statusline.render_segment("7d", d))

    def test_time_segment_shows_hourglass(self):
        d = self.payload()
        self.assertIn("⏳", statusline.render_segment("time", d))

    def test_time_omitted_when_reset_missing_or_past(self):
        self.assertIsNone(statusline.render_segment(
            "time", {"rate_limits": {"five_hour": {"used_percentage": 1}}}))
        self.assertIsNone(statusline.render_segment(
            "time", {"rate_limits": {"five_hour": {"resets_at": 1}}}))  # long past

    def test_absent_data_hides_segment(self):
        self.assertIsNone(statusline.render_segment("cost", {}))
        self.assertIsNone(statusline.render_segment("ctx", {}))
        self.assertIsNone(statusline.render_segment("tokens", {}))

    def test_unknown_key_is_none(self):
        self.assertIsNone(statusline.render_segment("bogus", self.payload()))

    def test_build_line_uses_default_order_and_joins(self):
        line = statusline.build_line(self.payload(), {})
        self.assertIn("Opus 4.8", line)
        self.assertIn("⬆", line)
        self.assertNotIn("$", line)        # cost hidden by default
        self.assertNotIn("ctx", line)      # ctx hidden by default
        self.assertIn(" · ", line)

    def test_all_segments_constants(self):
        self.assertEqual(statusline.ALL_SEGMENTS,
                         ["model", "tokens", "ctx", "cost", "5h", "time", "7d"])
        self.assertEqual(statusline.DEFAULT_SEGMENTS,
                         ["model", "tokens", "5h", "time", "7d"])

    def test_malformed_payload_never_raises(self):
        for bad in [{}, {"model": None}, {"rate_limits": "x"}, {"cost": []},
                    {"context_window": 7}]:
            statusline.build_line(bad, {})  # must not raise


class ConfigDriven(unittest.TestCase):
    def test_config_overrides_order_and_visibility(self):
        cfg = {"statusline": {"segments": ["cost", "model"]}}
        self.assertEqual(statusline.selected_segments(cfg), ["cost", "model"])

    def test_unknown_keys_filtered(self):
        cfg = {"statusline": {"segments": ["model", "bogus", "7d"]}}
        self.assertEqual(statusline.selected_segments(cfg), ["model", "7d"])

    def test_empty_or_missing_falls_back_to_default(self):
        self.assertEqual(statusline.selected_segments({}), statusline.DEFAULT_SEGMENTS)
        self.assertEqual(statusline.selected_segments({"statusline": {"segments": []}}),
                         statusline.DEFAULT_SEGMENTS)
        self.assertEqual(statusline.selected_segments({"statusline": {"segments": ["nope"]}}),
                         statusline.DEFAULT_SEGMENTS)

    def test_load_config_reads_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            _json.dump({"statusline": {"segments": ["ctx"]}}, f)
            path = f.name
        old = statusline.CONFIG_PATH
        try:
            statusline.CONFIG_PATH = path
            self.assertEqual(statusline.load_config(),
                             {"statusline": {"segments": ["ctx"]}})
        finally:
            statusline.CONFIG_PATH = old
            os.unlink(path)

    def test_load_config_bad_json_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{not json")
            path = f.name
        old = statusline.CONFIG_PATH
        try:
            statusline.CONFIG_PATH = path
            self.assertEqual(statusline.load_config(), {})
        finally:
            statusline.CONFIG_PATH = old
            os.unlink(path)


class UpdateNudge(unittest.TestCase):
    def _with_cache(self, data):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            _json.dump(data, f)
            return f.name

    def test_nudge_when_available(self):
        path = self._with_cache({"update_available": True, "latest": "0.2.0"})
        old = statusline.UPDATE_CACHE
        try:
            statusline.UPDATE_CACHE = path
            nudge = statusline.update_nudge() or ""
            self.assertIn("0.2.0", nudge)
            self.assertIn("⟳", nudge)
        finally:
            statusline.UPDATE_CACHE = old
            os.unlink(path)

    def test_no_nudge_when_not_available(self):
        path = self._with_cache({"update_available": False, "latest": "0.2.0"})
        old = statusline.UPDATE_CACHE
        try:
            statusline.UPDATE_CACHE = path
            self.assertIsNone(statusline.update_nudge())
        finally:
            statusline.UPDATE_CACHE = old
            os.unlink(path)

    def test_missing_cache_no_crash(self):
        old = statusline.UPDATE_CACHE
        try:
            statusline.UPDATE_CACHE = "/nonexistent/cc-meter/update-check.json"
            self.assertIsNone(statusline.update_nudge())
        finally:
            statusline.UPDATE_CACHE = old

    def test_nudge_appended_to_line(self):
        path = self._with_cache({"update_available": True, "latest": "9.9.9"})
        old = statusline.UPDATE_CACHE
        try:
            statusline.UPDATE_CACHE = path
            line = statusline.build_line({"model": {"display_name": "X"}}, {})
            self.assertIn("9.9.9", line)
        finally:
            statusline.UPDATE_CACHE = old
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
