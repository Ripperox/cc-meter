#!/usr/bin/env python3
"""cc-meter report: reads ~/.claude/cc-meter/sessions.jsonl (written by the SessionEnd
hook) and prints cross-session usage trends — totals, a daily-spend sparkline, per-project
breakdown, and top tools. This is the part `/usage` doesn't do: history over time."""
import os
import json
import collections

LOG = os.path.expanduser("~/.claude/cc-meter/sessions.jsonl")
BLOCKS = "▁▂▃▄▅▆▇█"


def fmt(n):
    n = float(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(int(n))


def day(ts):
    return (ts or "")[:10] or "?"


def main():
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


try:
    main()
except Exception as e:
    print("cc-meter: error reading log:", e)
