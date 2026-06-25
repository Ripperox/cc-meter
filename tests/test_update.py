#!/usr/bin/env python3
"""Tests for update.py. No real network is ever performed (fetch is injected).
Run: python3 -m unittest discover -s tests"""
import importlib.util
import os
import shutil
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
_spec = importlib.util.spec_from_file_location("update", os.path.join(SCRIPTS, "update.py"))
update = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update)


class Versions(unittest.TestCase):
    def test_parse_strips_v(self):
        self.assertEqual(update.parse_version("v0.2.0"), (0, 2, 0))
        self.assertEqual(update.parse_version("1.10.3"), (1, 10, 3))

    def test_parse_bad(self):
        self.assertIsNone(update.parse_version("nightly"))
        self.assertIsNone(update.parse_version(""))
        self.assertIsNone(update.parse_version("1.x.0"))

    def test_is_newer(self):
        self.assertTrue(update.is_newer("v0.2.0", "0.1.0"))
        self.assertTrue(update.is_newer("0.1.10", "0.1.2"))
        self.assertFalse(update.is_newer("0.1.0", "0.1.0"))
        self.assertFalse(update.is_newer("0.1.0", "0.2.0"))

    def test_is_newer_bad_inputs_false(self):
        self.assertFalse(update.is_newer("garbage", "0.1.0"))
        self.assertFalse(update.is_newer("0.2.0", None))
        self.assertFalse(update.is_newer(None, "0.1.0"))


class CheckFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_cache = update.CACHE_PATH
        self._old_cfg = update.CONFIG_PATH
        update.CACHE_PATH = os.path.join(self.tmp, "update-check.json")
        update.CONFIG_PATH = os.path.join(self.tmp, "config.json")  # absent -> {}

    def tearDown(self):
        update.CACHE_PATH = self._old_cache
        update.CONFIG_PATH = self._old_cfg
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_should_check_first_run(self):
        self.assertTrue(update.should_check({}, now=1))
        self.assertTrue(update.should_check({"checked_at": 0}, now=1))

    def test_should_check_throttles_24h(self):
        self.assertFalse(update.should_check({"checked_at": 1000}, now=1000 + 60))
        self.assertTrue(update.should_check({"checked_at": 1000}, now=1000 + 90000))

    def test_opted_out_env(self):
        os.environ["CC_METER_NO_UPDATE_CHECK"] = "1"
        try:
            self.assertTrue(update.opted_out({}))
        finally:
            del os.environ["CC_METER_NO_UPDATE_CHECK"]

    def test_opted_out_config(self):
        self.assertTrue(update.opted_out({"update_check": False}))
        self.assertFalse(update.opted_out({"update_check": True}))
        self.assertFalse(update.opted_out({}))

    def test_do_check_opted_out_skips_fetch(self):
        os.environ["CC_METER_NO_UPDATE_CHECK"] = "1"
        calls = []
        try:
            update.do_check(now=1, fetch=lambda r: calls.append(r) or "v9.9.9")
        finally:
            del os.environ["CC_METER_NO_UPDATE_CHECK"]
        self.assertEqual(calls, [])

    def test_do_check_fresh_cache_skips_fetch(self):
        update.write_cache({"checked_at": 10_000_000_000, "current": "0.1.0",
                            "latest": "0.1.0", "update_available": False})
        calls = []
        update.do_check(now=10_000_000_001, fetch=lambda r: calls.append(r) or "v9.9.9")
        self.assertEqual(calls, [])

    def test_do_check_writes_normalized_latest_and_flag(self):
        update.do_check(now=1, fetch=lambda r: "v99.0.0")
        cache = update.read_cache()
        self.assertTrue(cache["update_available"])
        self.assertEqual(cache["latest"], "99.0.0")  # leading 'v' stripped
        self.assertEqual(cache["checked_at"], 1)

    def test_do_check_no_update_when_same(self):
        # Current version comes from this repo's plugin.json; a tiny tag is not newer.
        update.do_check(now=1, fetch=lambda r: "v0.0.1")
        self.assertFalse(update.read_cache()["update_available"])

    def test_do_check_fetch_failure_keeps_prior_cache(self):
        update.write_cache({"checked_at": 1, "current": "0.1.0", "latest": "0.5.0",
                            "update_available": True})
        update.do_check(now=10_000_000_000, fetch=lambda r: None)
        self.assertEqual(update.read_cache()["latest"], "0.5.0")  # unchanged

    def test_cache_write_atomic_no_tmp_left(self):
        update.write_cache({"checked_at": 1})
        self.assertFalse(os.path.exists(update.CACHE_PATH + ".tmp"))


class InstallDetect(unittest.TestCase):
    def test_detects_git_checkout(self):
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, ".git"))
            self.assertEqual(update.detect_install(d), "git")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_detects_plugin(self):
        d = tempfile.mkdtemp()
        try:
            self.assertEqual(update.detect_install(d), "plugin")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_repo_root_has_plugin_json(self):
        # repo_root() points at the actual checkout; plugin.json must exist there.
        self.assertTrue(os.path.exists(
            os.path.join(update.repo_root(), ".claude-plugin", "plugin.json")))


if __name__ == "__main__":
    unittest.main()
