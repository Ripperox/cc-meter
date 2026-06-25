# cc-meter

Cross-session **usage observability for Claude Code**. Two pieces:

1. **Live status line** — pick from named segments: model · in/out tokens · context % · estimated $ · **5h / 7d rate-limit bars** (color-shifting green→yellow→red, with a ⚠ near your cap) · **time left in the 5h session** (`⏳2h13m`):

   ```
   Sonnet · ⬆14.2k ⬇1.3k · 5h ▓▓░░░ 41% · ⏳2h13m · 7d ▓░░░░ 12%
   ```

   The `⏳` segment counts down to when your 5-hour rate-limit window resets, so you see not just *how much* you've used but *how long until it frees up*. Every piece is a toggleable segment — see [Customize](#customize-the-status-line).

2. **`/cc-meter` usage report** — token & cost **trends across sessions**: totals, a daily-spend sparkline, per-project breakdown, and top tools.

3. **`/cc-meter turns`** — a **per-prompt breakdown of the current session**: every user turn with its input/output/cache tokens, API calls, and estimated cost, plus a session total. This is the "how much did each prompt and answer cost" view.

4. **`/cc-meter customize`** — interactively tick which status-line segments to show, and **`/cc-meter update`** — one command to pull the latest cc-meter (with a `⟳ vX.Y.Z` nudge in the status line when an update is available).

## Why this exists (vs. the built-in `/usage`)

Claude Code already ships `/usage` (aliases `/cost`, `/stats`) for **per-session** cost, plan limits, and an activity breakdown. cc-meter does the thing `/usage` doesn't: **persistence and trends over time.** A `SessionEnd` hook appends each session's usage to `~/.claude/cc-meter/sessions.jsonl`, and the report aggregates across days/projects so you can see your usage *history*, not just the current session.

Everything is **local** — it reads Claude Code's own status-line JSON and session transcripts. No proxy, no API key. The **one** exception is an optional, opt-out daily check to the GitHub API for a newer cc-meter version (powers the `⟳` update nudge); disable it with `CC_METER_NO_UPDATE_CHECK=1` or `"update_check": false` in your config. Works on a Pro/Max subscription.

## How it works

| Piece | Mechanism | Data source |
|---|---|---|
| Status line | `statusLine` command in `settings.json` → `scripts/statusline.py` | the JSON Claude Code pipes to the status line each turn |
| Session logger | `SessionEnd` hook → `scripts/log-session.py` | the session transcript (`message.usage` per assistant turn) |
| `/cc-meter` report | slash command → `scripts/report.py` | `~/.claude/cc-meter/sessions.jsonl` |
| Segment config | `scripts/config.py` (via `/cc-meter customize`) | `~/.claude/cc-meter/config.json` |
| Update check | async `SessionStart` hook → `scripts/update.py --check` | GitHub tags API (≤ once/day, opt-out), cached to `update-check.json` |

## Install

### Quick — run the installer

Clone the repo and run `install.sh`. It wires the status line, the `SessionEnd` logger + async `SessionStart` update-check hooks, and the `/cc-meter` command into `~/.claude` **using this checkout's own path** (no hardcoded paths), merges into your existing `settings.json` (with a `.bak-ccmeter` backup), and is idempotent — safe to re-run.

```bash
git clone https://github.com/Ripperox/cc-meter.git
cd cc-meter
./install.sh
```

Then restart Claude Code (or `/exit` and reopen).

### As a Claude Code plugin (for sharing)

This repo is also packaged as a plugin (`.claude-plugin/`, `hooks/`, `commands/`). To install the plugin form instead of the manual wiring:

```bash
claude plugin marketplace add /path/to/cc-meter
claude plugin install cc-meter@cc-meter
```

> The plugin provides the `SessionEnd` logger + `SessionStart` update-check hooks and the `/cc-meter` command (modes: report, `turns`, `customize`, `update`). The **main status line** is a user setting (`settings.json`), so point it at `scripts/statusline.py` regardless. If you enable the plugin, remove the manual hooks from `settings.json` so they don't fire twice (the installer's wiring and the plugin's hooks would both run).

## Customize the status line

Every part of the status line is a named **segment**. Show, hide, and reorder them however you like — the default keeps it uncrowded.

| key | shows | in default? |
|---|---|---|
| `model` | model name | ✓ |
| `tokens` | `⬆`/`⬇` input/output tokens | ✓ |
| `ctx` | context-window % used | |
| `cost` | session token-value `$` | |
| `5h` | 5-hour usage bar | ✓ |
| `time` | `⏳` time left in the 5h window | ✓ |
| `7d` | 7-day usage bar | ✓ |

**Default:** `model · tokens · 5h · time · 7d`.

The easiest way to change it is interactive:

```
/cc-meter customize
```

This pops up a tick-list (pre-checked with what's on now), plus one-tap presets — **default**, **full** (everything), and **minimal** (`model · 5h · time`). Your choice is saved to `~/.claude/cc-meter/config.json`:

```json
{ "statusline": { "segments": ["model", "tokens", "5h", "time", "7d"] } }
```

The list controls **both visibility and order** — to reorder, hand-edit it into the order you want (canonical keys: `model, tokens, ctx, cost, 5h, time, 7d`). The status line redraws on the next turn.

## Keeping cc-meter up to date

cc-meter checks GitHub for a newer version at most **once a day** (an async `SessionStart` hook — it never blocks startup and never runs on the status-line render). When a newer version exists, the status line shows a nudge:

```
… · ⟳ v0.2.0
```

Pull it in with one command:

```
/cc-meter update
```

It auto-detects how you installed: a **git checkout** runs `git pull` + the idempotent `install.sh`; a **plugin** install prints the `claude plugin update cc-meter` to run. Then restart Claude Code.

**First time only:** installs from before this feature don't have the checker yet, so do the first update by hand — `git pull && ./install.sh` in your checkout, or `claude plugin update cc-meter`. After that the nudge + `/cc-meter update` keep you current.

**Opting out:** set `CC_METER_NO_UPDATE_CHECK=1` (env) or `"update_check": false` in `config.json` — no network, no nudge.

## Tests

Pure-function tests (classifier, per-turn aggregation, status-line segments, config editor, update logic), no dependencies:

```bash
python3 -m unittest discover -s tests
```

## Notes

- **Cost is a token-price estimate.** On a Pro/Max plan you pay your subscription, not per token — the `$` figure shows the equivalent token value, useful for relative comparison.
- The rate-limit bars and the `⏳` time-left segment only appear for subscription accounts, after the first API response of a session (they need the `rate_limits` payload, including the 5h window's reset time).
- Requires `python3` (standard on macOS / most Linux). No dependencies.
