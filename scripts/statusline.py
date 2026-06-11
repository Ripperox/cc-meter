#!/usr/bin/env python3
"""cc-meter status line: reads Claude Code's status-line JSON on stdin and prints a
compact one-liner (model · tokens · context% · $ · 5h/7d rate-limit bars). Must never
crash — a status-line error renders as ugly noise — so everything is guarded."""
import sys
import json

DIM, GREEN, YELLOW, RED, CYAN = "2", "32", "33", "31", "36"


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


def main():
    d = json.loads(sys.stdin.read() or "{}")
    parts = []

    model = (d.get("model") or {})
    parts.append(c(model.get("display_name") or model.get("id") or "?", CYAN))

    cw = d.get("context_window") or {}
    if cw.get("total_input_tokens") is not None or cw.get("total_output_tokens") is not None:
        parts.append(f"⬆{fmt(cw.get('total_input_tokens'))} ⬇{fmt(cw.get('total_output_tokens'))}")
    if cw.get("used_percentage") is not None:
        parts.append(f"ctx {int(cw['used_percentage'])}%")

    cost = (d.get("cost") or {}).get("total_cost_usd")
    if cost is not None:
        parts.append(f"${float(cost):.3f}")

    rl = d.get("rate_limits") or {}
    segs = []
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        p = (rl.get(key) or {}).get("used_percentage")
        if p is not None:
            warn = " ⚠" if float(p) >= 80 else ""
            segs.append(f"{label} {bar(p)} {int(float(p))}%{warn}")
    if segs:
        parts.append(" ".join(segs))

    sys.stdout.write(c(" · ", DIM).join(parts))


try:
    main()
except Exception:
    sys.stdout.write("cc-meter")
