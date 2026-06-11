# cc-meter

Cross-session **usage observability for Claude Code**. Two pieces:

1. **Live status line** — model · in/out tokens · context % · estimated $ · **5h / 7d rate-limit bars** (color-shifting green→yellow→red, with a ⚠ near your cap):

   ```
   Sonnet · ⬆14.2k ⬇1.3k · ctx 8% · $0.024 · 5h ▓▓░░░ 41% · 7d ▓░░░░ 12%
   ```

2. **`/cc-meter` usage report** — token & cost **trends across sessions**: totals, a daily-spend sparkline, per-project breakdown, and top tools.

3. **`/cc-meter turns`** — a **per-prompt breakdown of the current session**: every user turn with its input/output/cache tokens, API calls, and estimated cost, plus a session total. This is the "how much did each prompt and answer cost" view.

## Why this exists (vs. the built-in `/usage`)

Claude Code already ships `/usage` (aliases `/cost`, `/stats`) for **per-session** cost, plan limits, and an activity breakdown. cc-meter does the thing `/usage` doesn't: **persistence and trends over time.** A `SessionEnd` hook appends each session's usage to `~/.claude/cc-meter/sessions.jsonl`, and the report aggregates across days/projects so you can see your usage *history*, not just the current session.

Everything is **local** — it reads Claude Code's own status-line JSON and session transcripts. No proxy, no API key, no network. Works on a Pro/Max subscription.

## How it works

| Piece | Mechanism | Data source |
|---|---|---|
| Status line | `statusLine` command in `settings.json` → `scripts/statusline.py` | the JSON Claude Code pipes to the status line each turn |
| Session logger | `SessionEnd` hook → `scripts/log-session.py` | the session transcript (`message.usage` per assistant turn) |
| `/cc-meter` report | slash command → `scripts/report.py` | `~/.claude/cc-meter/sessions.jsonl` |

## Install

### Quick (what's wired up locally)

The status line and `SessionEnd` hook are registered in `~/.claude/settings.json`, and `/cc-meter` is a user command in `~/.claude/commands/`. Restart Claude Code and it's live.

```jsonc
// ~/.claude/settings.json
"statusLine": { "type": "command", "command": "python3 /path/to/cc-meter/scripts/statusline.py", "padding": 0 },
"hooks": { "SessionEnd": [ { "hooks": [ { "type": "command", "command": "python3 /path/to/cc-meter/scripts/log-session.py" } ] } ] }
```

### As a Claude Code plugin (for sharing)

This repo is also packaged as a plugin (`.claude-plugin/`, `hooks/`, `commands/`). To install the plugin form instead of the manual wiring:

```bash
claude plugin marketplace add /path/to/cc-meter
claude plugin install cc-meter@cc-meter
```

> The plugin provides the `SessionEnd` hook and `/cc-meter:history` command. The **main status line** is a user setting (`settings.json`), so point it at `scripts/statusline.py` regardless. If you enable the plugin, remove the manual `SessionEnd` hook from `settings.json` so it doesn't log twice.

## Notes

- **Cost is a token-price estimate.** On a Pro/Max plan you pay your subscription, not per token — the `$` figure shows the equivalent token value, useful for relative comparison.
- The rate-limit bars only appear for subscription accounts, after the first API response of a session.
- Requires `python3` (standard on macOS / most Linux). No dependencies.
