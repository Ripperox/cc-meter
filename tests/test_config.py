#!/usr/bin/env python3
"""Tests for config.py (the /cc-meter customize editor).
Run: python3 -m unittest discover -s tests"""
import importlib.util
import os
import json
import shutil
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


config = _load("config", "config.py")


class ConfigCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "config.json")
        self._old = config.CONFIG_PATH
        config.CONFIG_PATH = self.path

    def tearDown(self):
        config.CONFIG_PATH = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_set_writes_valid_json(self):
        self.assertEqual(config.cmd_set("model,5h,time"), 0)
        with open(self.path) as f:
            data = json.load(f)
        self.assertEqual(data["statusline"]["segments"], ["model", "5h", "time"])

    def test_set_rejects_unknown_key(self):
        self.assertNotEqual(config.cmd_set("model,bogus"), 0)
        self.assertFalse(os.path.exists(self.path))

    def test_set_rejects_empty(self):
        self.assertNotEqual(config.cmd_set(""), 0)
        self.assertFalse(os.path.exists(self.path))

    def test_set_preserves_unrelated_keys(self):
        config.save({"update_check": False, "statusline": {"segments": ["model"]}})
        config.cmd_set("7d")
        data = config.load()
        self.assertEqual(data["update_check"], False)
        self.assertEqual(data["statusline"]["segments"], ["7d"])

    def test_preset_expands(self):
        self.assertEqual(config.cmd_preset("minimal"), 0)
        self.assertEqual(config.load()["statusline"]["segments"],
                         config.PRESETS["minimal"])

    def test_preset_unknown_rejected(self):
        self.assertNotEqual(config.cmd_preset("nope"), 0)

    def test_presets_use_valid_keys(self):
        for name, keys in config.PRESETS.items():
            for k in keys:
                self.assertIn(k, config.statusline.ALL_SEGMENTS, (name, k))

    def test_show_shape(self):
        payload = config.show_payload()
        self.assertIn("available", payload)
        self.assertTrue(all({"key", "label", "sample"} <= set(a)
                            for a in payload["available"]))
        self.assertEqual([a["key"] for a in payload["available"]],
                         config.statusline.ALL_SEGMENTS)
        self.assertIn("current", payload)
        self.assertIn("update_check", payload)
        self.assertTrue(payload["update_check"])  # default true

    def test_save_is_atomic_replace(self):
        config.save({"statusline": {"segments": ["model"]}})
        # No leftover tmp file.
        self.assertFalse(os.path.exists(self.path + ".tmp"))


if __name__ == "__main__":
    unittest.main()
