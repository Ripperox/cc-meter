#!/usr/bin/env python3
"""cc-meter SessionEnd hook: reads the hook JSON on stdin, parses the session's
transcript, sums token usage + tool calls, estimates token-price value, and appends a
one-line summary to ~/.claude/cc-meter/sessions.jsonl (deduped by session_id).

This is what `/usage` can't do: a persistent per-session ledger for cross-session trends.
Fails silently — a hook must never disrupt session shutdown."""
import sys
import os
import json

# Rough token prices per 1M tokens: (input, output, cache_read, cache_write_5m).
PRICES = {
    "opus": (5.0, 25.0, 0.5, 6.25),
    "sonnet": (3.0, 15.0, 0.3, 3.75),
    "haiku": (1.0, 5.0, 0.1, 1.25),
}

LOG_DIR = os.path.expanduser("~/.claude/cc-meter")
LOG = os.path.join(LOG_DIR, "sessions.jsonl")


def price_for(model):
    m = (model or "").lower()
    for key, p in PRICES.items():
        if key in m:
            return p
    return PRICES["sonnet"]


def main():
    raw = sys.stdin.read()
    hook = json.loads(raw) if raw.strip() else {}
    tx = hook.get("transcript_path")
    sid = hook.get("session_id") or "unknown"
    cwd = hook.get("cwd") or ""
    if not tx or not os.path.exists(tx):
        return

    agg = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "api_calls": 0}
    tools = {}
    model = None
    first_ts = last_ts = None
    branch = None
    project = os.path.basename(cwd.rstrip("/")) or "—"

    with open(tx) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("timestamp"):
                first_ts = first_ts or o["timestamp"]
                last_ts = o["timestamp"]
            if o.get("gitBranch"):
                branch = o["gitBranch"]
            if o.get("type") != "assistant":
                continue
            msg = o.get("message") or {}
            u = msg.get("usage")
            if isinstance(u, dict):
                agg["input"] += u.get("input_tokens", 0) or 0
                agg["output"] += u.get("output_tokens", 0) or 0
                agg["cache_read"] += u.get("cache_read_input_tokens", 0) or 0
                agg["cache_write"] += u.get("cache_creation_input_tokens", 0) or 0
                agg["api_calls"] += 1
                model = msg.get("model") or model
            for blk in (msg.get("content") or []):
                if isinstance(blk, dict) and blk.get("type") == "tool_use":
                    name = blk.get("name", "?")
                    tools[name] = tools.get(name, 0) + 1

    if agg["api_calls"] == 0:
        return  # nothing worth logging

    pin, pout, pcr, pcw = price_for(model)
    cost = (
        agg["input"] * pin
        + agg["output"] * pout
        + agg["cache_read"] * pcr
        + agg["cache_write"] * pcw
    ) / 1_000_000.0

    rec = {
        "ts": last_ts or first_ts,
        "session_id": sid,
        "project": project,
        "branch": branch,
        "model": model,
        "api_calls": agg["api_calls"],
        "input_tokens": agg["input"],
        "output_tokens": agg["output"],
        "cache_read_tokens": agg["cache_read"],
        "cache_write_tokens": agg["cache_write"],
        "est_cost_usd": round(cost, 4),
        "tools": tools,
        "first_ts": first_ts,
        "last_ts": last_ts,
    }

    os.makedirs(LOG_DIR, exist_ok=True)
    rows = []
    if os.path.exists(LOG):
        with open(LOG) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("session_id") != sid:  # dedupe: drop prior entry for this session
                        rows.append(r)
                except Exception:
                    pass
    rows.append(rec)
    tmp = LOG + ".tmp"
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    os.replace(tmp, LOG)


try:
    main()
except Exception:
    pass
