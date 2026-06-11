#!/usr/bin/env python3
"""cc-meter report.

  report.py            cross-session summary (totals, daily sparkline, per-project, tools)
  report.py turns      per-prompt breakdown of the CURRENT session (each user turn's tokens + $)

Reads ~/.claude/cc-meter/sessions.jsonl (written by the SessionEnd hook) for the summary,
and the live session transcript for the per-turn view. Local only — no proxy, no API key."""
import os
import sys
import json
import collections

LOG = os.path.expanduser("~/.claude/cc-meter/sessions.jsonl")
PROJECTS = os.path.expanduser("~/.claude/projects")
BLOCKS = "▁▂▃▄▅▆▇█"

# Rough token prices per 1M tokens: (input, output, cache_read, cache_write_5m).
PRICES = {
    "opus": (5.0, 25.0, 0.5, 6.25),
    "sonnet": (3.0, 15.0, 0.3, 3.75),
    "haiku": (1.0, 5.0, 0.1, 1.25),
}


def price_for(model):
    m = (model or "").lower()
    for key, p in PRICES.items():
        if key in m:
            return p
    return PRICES["sonnet"]


def cost_of(model, inp, out, cr, cw):
    pin, pout, pcr, pcw = price_for(model)
    return (inp * pin + out * pout + cr * pcr + cw * pcw) / 1_000_000.0


def fmt(n):
    n = float(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(int(n))


def day(ts):
    return (ts or "")[:10] or "?"


def hhmm(ts):
    # "2026-06-11T13:26:01.000Z" -> "13:26"
    try:
        return ts[11:16]
    except Exception:
        return "--:--"


# ---------------------------------------------------------------- summary mode

def summary_report():
    if not os.path.exists(LOG):
        print("cc-meter: no sessions logged yet.")
        print("Finish a Claude Code session (the SessionEnd hook records it), then run /cc-meter again.")
        return
    rows = []
    with open(LOG) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    if not rows:
        print("cc-meter: no sessions logged yet.")
        return

    tot = collections.Counter()
    by_day = collections.defaultdict(collections.Counter)
    by_proj = collections.defaultdict(collections.Counter)
    tools = collections.Counter()
    for r in rows:
        tot["sessions"] += 1
        for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "api_calls"):
            tot[k] += r.get(k, 0) or 0
        tot["cost"] += r.get("est_cost_usd", 0) or 0
        d = day(r.get("ts") or r.get("last_ts"))
        toks = (r.get("input_tokens", 0) or 0) + (r.get("output_tokens", 0) or 0)
        by_day[d]["cost"] += r.get("est_cost_usd", 0) or 0
        by_day[d]["tok"] += toks
        p = r.get("project") or "—"
        by_proj[p]["cost"] += r.get("est_cost_usd", 0) or 0
        by_proj[p]["tok"] += toks
        by_proj[p]["sessions"] += 1
        for t, n in (r.get("tools") or {}).items():
            tools[t] += n

    print("cc-meter — usage across sessions")
    print("─" * 46)
    print(f"Sessions:    {tot['sessions']}    ·    API calls: {tot['api_calls']}")
    print(
        f"Tokens:      in {fmt(tot['input_tokens'])} · out {fmt(tot['output_tokens'])} · "
        f"cache-read {fmt(tot['cache_read_tokens'])} · cache-write {fmt(tot['cache_write_tokens'])}"
    )
    denom = tot["cache_read_tokens"] + tot["input_tokens"]
    hit = (tot["cache_read_tokens"] / denom * 100) if denom else 0
    print(f"Cache hit:   {hit:.0f}%")
    print(f"Est. value:  ${tot['cost']:.2f}    (token-price estimate — you pay your plan, not per token)")
    print()

    days = sorted(by_day.keys())[-14:]
    costs = [by_day[d]["cost"] for d in days]
    if len(costs) >= 2 and max(costs) > 0:
        mx = max(costs)
        spark = "".join(BLOCKS[min(7, int(c / mx * 7))] for c in costs)
        print(f"Daily spend (last {len(days)}d):  {spark}   ${min(costs):.2f}–${max(costs):.2f}/day")
        print()

    top = sorted(by_proj.items(), key=lambda kv: kv[1]["cost"], reverse=True)[:6]
    if top:
        print("Top projects:")
        for p, cnt in top:
            print(f"  {p[:24]:<24} ${cnt['cost']:>7.2f}  ·  {fmt(cnt['tok']):>6} tok  ·  {cnt['sessions']} sess")
        print()

    if tools:
        print("Top tools:   " + " · ".join(f"{t} {n}" for t, n in tools.most_common(6)))
    print()
    print("Tip: run  /cc-meter turns  for a per-prompt breakdown of the current session.")


# ------------------------------------------------------------------ turns mode

def find_current_transcript():
    """The active session is the most-recently-modified transcript under ~/.claude/projects."""
    newest, newest_m = None, -1.0
    for root, _, files in os.walk(PROJECTS):
        for fn in files:
            if fn.endswith(".jsonl"):
                p = os.path.join(root, fn)
                try:
                    m = os.path.getmtime(p)
                except OSError:
                    continue
                if m > newest_m:
                    newest, newest_m = p, m
    return newest


def is_user_prompt(o):
    """A real user turn (typed prompt), not a tool_result continuation."""
    if o.get("type") != "user":
        return False
    c = (o.get("message") or {}).get("content")
    if isinstance(c, str):
        return c.strip() != ""
    if isinstance(c, list):
        return any(isinstance(b, dict) and b.get("type") == "text" for b in c)
    return False


def prompt_text(o):
    c = (o.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text":
                return b.get("text", "")
    return ""


def turns_report():
    tx = find_current_transcript()
    if not tx:
        print("cc-meter: no active session transcript found.")
        return

    turns = []
    cur = None
    with open(tx) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if is_user_prompt(o):
                cur = {
                    "prompt": " ".join(prompt_text(o).split())[:34],
                    "ts": o.get("timestamp"),
                    "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
                    "calls": 0, "model": None,
                }
                turns.append(cur)
            elif o.get("type") == "assistant" and cur is not None:
                u = (o.get("message") or {}).get("usage")
                if isinstance(u, dict):
                    cur["input"] += u.get("input_tokens", 0) or 0
                    cur["output"] += u.get("output_tokens", 0) or 0
                    cur["cache_read"] += u.get("cache_read_input_tokens", 0) or 0
                    cur["cache_write"] += u.get("cache_creation_input_tokens", 0) or 0
                    cur["calls"] += 1
                    cur["model"] = (o.get("message") or {}).get("model") or cur["model"]

    turns = [t for t in turns if t["calls"] > 0]
    if not turns:
        print("cc-meter: no completed prompts in the current session yet.")
        return

    print("cc-meter — current session, per prompt")
    print("─" * 72)
    print(f"{'#':>2}  {'time':>5}  {'in':>6} {'out':>6} {'cache-rd':>8} {'calls':>5}  {'$':>7}  prompt")
    tc = collections.Counter()
    for i, t in enumerate(turns, 1):
        c = cost_of(t["model"], t["input"], t["output"], t["cache_read"], t["cache_write"])
        tc["input"] += t["input"]; tc["output"] += t["output"]
        tc["cache_read"] += t["cache_read"]; tc["cost"] += c; tc["calls"] += t["calls"]
        print(
            f"{i:>2}  {hhmm(t['ts']):>5}  {fmt(t['input']):>6} {fmt(t['output']):>6} "
            f"{fmt(t['cache_read']):>8} {t['calls']:>5}  ${c:>6.3f}  {t['prompt']}"
        )
    print("─" * 72)
    print(
        f"{'Σ':>2}  {len(turns):>2}p   {fmt(tc['input']):>6} {fmt(tc['output']):>6} "
        f"{fmt(tc['cache_read']):>8} {tc['calls']:>5}  ${tc['cost']:>6.2f}"
    )
    print()
    print("$ is a token-price estimate (you pay your plan). Big cache-rd = re-reading the growing context.")


def main():
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "summary"
    if mode in ("turns", "turn", "prompts", "session"):
        turns_report()
    else:
        summary_report()


try:
    main()
except Exception as e:
    print("cc-meter: error:", e)
