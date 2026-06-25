#!/usr/bin/env python3
"""cc-meter status line: reads Claude Code's status-line JSON on stdin and prints a
compact one-liner of named segments (model · tokens · ctx · cost · 5h · time · 7d),
plus an optional update nudge. Order/visibility come from ~/.claude/cc-meter/config.json.
Must never crash, block, or hit the network — everything is guarded."""
import sys
import os
import json
import time

DIM, GREEN, YELLOW, RED, CYAN = "2", "32", "33", "31", "36"

CONFIG_PATH = os.path.expanduser("~/.claude/cc-meter/config.json")
UPDATE_CACHE = os.path.expanduser("~/.claude/cc-meter/update-check.json")

ALL_SEGMENTS = ["model", "tokens", "ctx", "cost", "5h", "time", "7d"]
DEFAULT_SEGMENTS = ["model", "tokens", "5h", "time", "7d"]
SEGMENT_LABELS = {
    "model": "Model name",
    "tokens": "Input/output tokens",
    "ctx": "Context window %",
    "cost": "Session cost ($)",
    "5h": "5-hour usage bar",
    "time": "Time left in 5h window",
    "7d": "7-day usage bar",
}
SAMPLE_PAYLOAD = {
    "model": {"display_name": "Opus 4.8"},
    "context_window": {"total_input_tokens": 14200, "total_output_tokens": 1300,
                       "used_percentage": 8},
    "cost": {"total_cost_usd": 0.024},
    "rate_limits": {"five_hour": {"used_percentage": 41, "resets_at": 0},
                    "seven_day": {"used_percentage": 12, "resets_at": 0}},
}


def c(s, code):
    return f"\033[{code}m{s}\033[0m"


def fmt(n):
    n = float(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(int(n))


def bar(pct):
    pct = max(0.0, min(100.0, float(pct or 0)))
    filled = int(round(pct / 20.0))  # 5 segments, 20% each
    glyph = "▓" * filled + "░" * (5 - filled)
    code = GREEN if pct < 50 else (YELLOW if pct < 80 else RED)
    return c(glyph, code)


def humanize_remaining(seconds):
    """Compact 'time left' string. <=0 -> '' (caller omits the segment)."""
    s = int(seconds or 0)
    if s <= 0:
        return ""
    h, m = s // 3600, (s % 3600) // 60
    if h > 0:
        return f"{h}h{m:02d}m"
    if m > 0:
        return f"{m}m"
    return "<1m"


def _ratebar(d, key, label):
    rl = (d.get("rate_limits") or {}).get(key) or {}
    p = rl.get("used_percentage")
    if p is None:
        return None
    warn = " ⚠" if float(p) >= 80 else ""
    return f"{label} {bar(p)} {int(float(p))}%{warn}"


def _seg_model(d):
    m = d.get("model") or {}
    return c(m.get("display_name") or m.get("id") or "?", CYAN)


def _seg_tokens(d):
    cw = d.get("context_window") or {}
    if cw.get("total_input_tokens") is None and cw.get("total_output_tokens") is None:
        return None
    return f"⬆{fmt(cw.get('total_input_tokens'))} ⬇{fmt(cw.get('total_output_tokens'))}"


def _seg_ctx(d):
    cw = d.get("context_window") or {}
    if cw.get("used_percentage") is None:
        return None
    return f"ctx {int(cw['used_percentage'])}%"


def _seg_cost(d):
    cost = (d.get("cost") or {}).get("total_cost_usd")
    return None if cost is None else f"${float(cost):.3f}"


def _seg_time(d):
    rl = (d.get("rate_limits") or {}).get("five_hour") or {}
    resets = rl.get("resets_at")
    if not resets:
        return None
    label = humanize_remaining(float(resets) - time.time())
    return c(f"⏳{label}", DIM) if label else None


SEGMENT_RENDERERS = {
    "model": _seg_model,
    "tokens": _seg_tokens,
    "ctx": _seg_ctx,
    "cost": _seg_cost,
    "5h": lambda d: _ratebar(d, "five_hour", "5h"),
    "7d": lambda d: _ratebar(d, "seven_day", "7d"),
    "time": _seg_time,
}


def render_segment(key, d):
    fn = SEGMENT_RENDERERS.get(key)
    if fn is None:
        return None
    try:
        return fn(d if isinstance(d, dict) else {})
    except Exception:
        return None


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def selected_segments(cfg):
    seg = ((cfg or {}).get("statusline") or {}).get("segments")
    if isinstance(seg, list):
        keys = [k for k in seg if k in SEGMENT_RENDERERS]
        if keys:
            return keys
    return DEFAULT_SEGMENTS


def update_nudge():
    try:
        with open(UPDATE_CACHE) as f:
            data = json.load(f)
        if data.get("update_available") and data.get("latest"):
            return c(f"⟳ v{data['latest']}", YELLOW)
    except Exception:
        pass
    return None


def build_line(d, cfg):
    parts = []
    for key in selected_segments(cfg):
        s = render_segment(key, d)
        if s:
            parts.append(s)
    line = c(" · ", DIM).join(parts)
    nudge = update_nudge()
    if nudge:
        line = line + c(" · ", DIM) + nudge if line else nudge
    return line


def main():
    d = json.loads(sys.stdin.read() or "{}")
    sys.stdout.write(build_line(d if isinstance(d, dict) else {}, load_config()))


try:
    main()
except Exception:
    sys.stdout.write("cc-meter")
