#!/usr/bin/env python3
"""Tests for cc-meter report classification + turn aggregation.

Pure-function tests — no files, no stdout. Run with:
    python3 -m unittest discover -s tests   (from the repo root)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import report  # noqa: E402


def user(text, **extra):
    """A type=user record with string content."""
    o = {"type": "user", "message": {"role": "user", "content": text}}
    o.update(extra)
    return o


def user_blocks(blocks, **extra):
    o = {"type": "user", "message": {"role": "user", "content": blocks}}
    o.update(extra)
    return o


def assistant(model="claude-opus-4-8", inp=0, out=0, cr=0, cw=0):
    return {
        "type": "assistant",
        "message": {
            "model": model,
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_read_input_tokens": cr,
                "cache_creation_input_tokens": cw,
            },
        },
    }


# --------------------------------------------------------- classifier signals

class PromptSourceClassifier(unittest.TestCase):
    """When the transcript carries promptSource, trust it exactly."""

    def test_typed_is_a_prompt(self):
        self.assertTrue(report.is_user_prompt(user("hello", promptSource="typed"), True))

    def test_system_notification_is_not_a_prompt(self):
        note = user("<task-notification> ...", promptSource="system")
        self.assertFalse(report.is_user_prompt(note, True))

    def test_skill_base_dir_is_not_a_prompt(self):
        # isMeta injection, no promptSource key at all
        meta = user_blocks([{"type": "text", "text": "Base directory for this skill: /x"}], isMeta=True)
        self.assertFalse(report.is_user_prompt(meta, True))

    def test_slash_command_body_is_not_a_prompt(self):
        body = user_blocks([{"type": "text", "text": "Use the Bash tool to run this command"}], isMeta=True)
        self.assertFalse(report.is_user_prompt(body, True))

    def test_tool_result_is_not_a_prompt(self):
        tr = user_blocks([{"type": "tool_result", "content": "ok"}], toolUseResult={"x": 1})
        self.assertFalse(report.is_user_prompt(tr, True))

    def test_assistant_is_never_a_prompt(self):
        self.assertFalse(report.is_user_prompt(assistant(), True))


class LegacyHeuristicClassifier(unittest.TestCase):
    """Older transcripts have no promptSource — fall back to negative filters."""

    def test_plain_typed_text_is_a_prompt(self):
        self.assertTrue(report.is_user_prompt(user("fix the bug"), False))

    def test_local_command_stdout_is_not_a_prompt(self):
        self.assertFalse(report.is_user_prompt(user("<local-command-stdout>done</local-command-stdout>"), False))

    def test_command_name_is_not_a_prompt(self):
        self.assertFalse(report.is_user_prompt(user("<command-name>/model</command-name> ..."), False))

    def test_interrupt_marker_is_not_a_prompt(self):
        blk = user_blocks([{"type": "text", "text": "[Request interrupted by user]"}])
        self.assertFalse(report.is_user_prompt(blk, False))

    def test_skill_base_dir_is_not_a_prompt(self):
        meta = user_blocks([{"type": "text", "text": "Base directory for this skill: /x"}], isMeta=True)
        self.assertFalse(report.is_user_prompt(meta, False))


class DetectPromptSource(unittest.TestCase):
    def test_detects_when_present(self):
        objs = [user("hi", promptSource="typed"), assistant(out=5)]
        self.assertTrue(report.transcript_uses_prompt_source(objs))

    def test_false_when_absent(self):
        objs = [user("hi"), assistant(out=5)]
        self.assertFalse(report.transcript_uses_prompt_source(objs))


# ----------------------------------------------------------- turn aggregation

class BuildTurns(unittest.TestCase):
    def test_groups_assistant_usage_under_the_typed_prompt(self):
        objs = [
            user("first prompt", promptSource="typed"),
            assistant(inp=10, out=100, cr=50),
            assistant(inp=5, out=20, cr=10),
            user("second prompt", promptSource="typed"),
            assistant(inp=1, out=7, cr=2),
        ]
        turns = report.build_turns(objs)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]["prompt"], "first prompt")
        self.assertEqual(turns[0]["input"], 15)
        self.assertEqual(turns[0]["output"], 120)
        self.assertEqual(turns[0]["cache_read"], 60)
        self.assertEqual(turns[0]["calls"], 2)
        self.assertEqual(turns[1]["calls"], 1)

    def test_injected_rows_do_not_create_turns(self):
        objs = [
            user("real prompt", promptSource="typed"),
            user_blocks([{"type": "text", "text": "Base directory for this skill: /x"}], isMeta=True),
            assistant(inp=10, out=100),
            user("<task-notification> done", promptSource="system"),
            assistant(inp=2, out=3),
        ]
        turns = report.build_turns(objs)
        self.assertEqual(len(turns), 1)
        # both assistant turns accrue to the one real prompt
        self.assertEqual(turns[0]["calls"], 2)
        self.assertEqual(turns[0]["output"], 103)

    def test_drops_prompts_with_no_assistant_calls(self):
        objs = [
            user("answered", promptSource="typed"),
            assistant(out=5),
            user("never answered", promptSource="typed"),
        ]
        turns = report.build_turns(objs)
        self.assertEqual([t["prompt"] for t in turns], ["answered"])

    def test_legacy_transcript_without_prompt_source(self):
        objs = [
            user("legacy prompt"),
            assistant(inp=3, out=9),
            user("<local-command-stdout>x</local-command-stdout>"),
            assistant(inp=1, out=1),
        ]
        turns = report.build_turns(objs)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["calls"], 2)


if __name__ == "__main__":
    unittest.main()
