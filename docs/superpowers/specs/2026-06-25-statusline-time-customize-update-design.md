# cc-meter: session time-left, customizable status line, and in-CLI updates

**Date:** 2026-06-25
**Status:** Approved design — pending spec review
**Author:** brainstorm with Rishit-D

## Summary

Three linked features for cc-meter, plus the wiring that makes them adopt cleanly:

1. **Time-left indicator** — show how much of the current 5-hour rate-limit window
   remains (e.g. `⏳2h13m`), not just how much is used.
2. **Customizable status line** — every piece of the line becomes an independent,
   named segment the user can show/hide/reorder, edited interactively via
   `/cc-meter customize` (a tick-box list) backed by a config file.
3. **In-CLI update notifications** — a passive "update available" nudge in the
   status line plus a one-command `/cc-meter update`, so the two existing users
   (and future ones) get new changes effortlessly.

Hard requirement across all of it: **production-grade**. The status line must never
crash or block; all file writes are atomic; the network check is throttled, timed
out, and fails silently; the installer stays idempotent; no new third-party
dependencies (Python stdlib only); every new pure function is unit-tested.

## Current state (as built)

- `scripts/statusline.py` — reads Claude Code's status-line JSON on stdin, prints
  one line: model · `⬆/⬇` tokens · `ctx %` · `$cost` · `5h`/`7d` usage bars. Whole
  body guarded by `try/except → "cc-meter"`. Contains a leftover **TEMP capture**
  block (writes `/tmp/cc-meter-statusline-capture.json` every render) to be removed.
- `scripts/log-session.py` — SessionEnd hook; unchanged by this work.
- `scripts/report.py` — `/cc-meter` report (summary / `turns` modes); unchanged
  except the command markdown that invokes it gains new modes.
- `install.sh` — idempotent installer. Wires `statusLine`, a `SessionEnd` hook, and
  writes `~/.claude/commands/cc-meter.md`, all pointing at the checkout's own
  absolute path. Backs up `settings.json` to `.bak-ccmeter`.
- `hooks/hooks.json` — plugin form; registers `SessionEnd` (with `"async": true`).
- `tests/` — `unittest`, modules loaded by path. `test_log_session.py`,
  `test_report.py`. No status-line test yet.
- Repo published at `github.com/Ripperox/cc-meter`; version in
  `.claude-plugin/plugin.json` (`0.1.0` → bump to `0.2.0` for this release).

The status-line payload already carries everything needed for time-left:

```json
"rate_limits": {
  "five_hour": { "used_percentage": 43, "resets_at": 1782387000 },
  "seven_day": { "used_percentage": 64, "resets_at": 1782568800 }
}
```

## Feature A — Time-left indicator

`resets_at` is a Unix timestamp; remaining = `resets_at − now`. Only the 5-hour
window gets a countdown (it is "the session" most people mean).

**Pure formatter** `humanize_remaining(seconds) -> str`:

| remaining        | renders   |
|------------------|-----------|
| ≥ 1 hour         | `2h13m` (minutes zero-padded: `2h05m`) |
| 1–59 min         | `13m`     |
| > 0 and < 1 min  | `<1m`     |
| ≤ 0              | *(caller omits the segment)* |

Seconds are intentionally **not** shown: the status line only re-renders per turn,
so a ticking `45s` would be stale and misleading; `<1m` is honest.

Rendered as its own segment, dim, with an hourglass glyph: `⏳2h13m`. It is a
standalone segment (not glued to the 5h bar), so it can show even if the 5h bar is
hidden. Omitted entirely when `resets_at` is missing, unparseable, or already past.

## Feature B — Customizable status line

### Segment model

Every piece of the line is a named segment, all joined by the existing dim ` · `.
This de-crowds the line (today `5h`/`7d` are space-jammed) and makes show/hide
trivial — visibility is just presence in a list.

| key      | renders                  |
|----------|--------------------------|
| `model`  | `Opus 4.8 (1M context)`  |
| `tokens` | `⬆35.8k ⬇477`            |
| `ctx`    | `ctx 4%`                 |
| `cost`   | `$0.303`                 |
| `5h`     | `5h ▓▓░░░ 43%`           |
| `time`   | `⏳2h13m` (Feature A)     |
| `7d`     | `7d ▓░░░░ 64%`           |

A segment self-hides when its data is absent (e.g. no `cost` in the payload).

The **update nudge is NOT a segment** — it is an alert rendered specially (see
Feature D), always appended when an update is available, controlled solely by the
`update_check` flag. Keeping it out of the segment list keeps "arrange your columns"
and "alert me to updates" as separate, clean concerns.

### Config file — `~/.claude/cc-meter/config.json`

```json
{
  "statusline": { "segments": ["model", "tokens", "5h", "time", "7d"] },
  "update_check": true
}
```

- `statusline.segments` — ordered list; **both** what shows and the order.
- Missing file, missing key, or unreadable/invalid JSON → built-in **default**:
  `["model", "tokens", "5h", "time", "7d"]` (drops `cost` and `ctx` by default;
  users add them back).
- Unknown keys in the list are ignored (forward-compatible).
- `update_check` — bool, default `true`. `false` disables the network check and the
  nudge. Env `CC_METER_NO_UPDATE_CHECK=1` overrides to `false` regardless of file.

`statusline.py` reads this config with a small **guarded** helper that never raises
and **never imports another module** — the hot path stays import-free and
crash-proof. On any read/parse error it returns the default.

### `/cc-meter customize` — interactive tick-box editor

A new mode of the `/cc-meter` command. Flow:

1. Run `python3 scripts/config.py --show` → prints JSON: every available segment
   (key, human label, a live sample string) and which are currently enabled.
2. Claude presents an **`AskUserQuestion` multi-select** (pre-ticked = currently
   shown). It also offers the three **presets** as quick picks:
   - `default` = `model, tokens, 5h, time, 7d` (the out-of-box default)
   - `full` = `model, tokens, ctx, cost, 5h, time, 7d` (everything)
   - `minimal` = `model, 5h, time`
3. Run `python3 scripts/config.py --set k1,k2,…` (or `--preset default`) to persist.
4. Echo a preview of the resulting line and remind to restart/redraw.

Tick = **visibility**, rendered in the canonical order in the table above. Custom
**reordering** is a power-user action — hand-edit `config.json` (documented in
README). This keeps the tick UI dead-simple.

### New module — `scripts/config.py`

Single source of truth for config read/write, used by the slash command (never on
the status-line hot path).

- Imports `statusline.py` **by path** (the importlib trick the tests already use) to
  reuse the canonical segment keys, labels, and default list — no duplication.
- `--show` → emit `{available:[{key,label,sample}], current:[…], update_check:bool}`.
- `--set a,b,c` → validate keys against the registry (reject unknown → nonzero exit
  + message), write config.
- `--preset default|full|minimal` → expand and write.
- All writes **atomic**: write `config.json.tmp`, `os.replace`. Preserve unrelated
  keys already in the file (read-merge-write).

## Feature D — In-CLI update notifications

### Detection (background, throttled, opt-out)

- New `scripts/update.py` with two entry points:
  - `update.py --check` — the throttled background checker.
  - `update.py` (no args) — performs the update (below).
- `--check` logic:
  1. Respect opt-out: if `update_check` is false (config or
     `CC_METER_NO_UPDATE_CHECK`), exit immediately, no network.
  2. Read cache `~/.claude/cc-meter/update-check.json`. If `checked_at` is < 24h
     old, exit (no network).
  3. Otherwise fetch the latest version from the GitHub **tags** API
     (`https://api.github.com/repos/Ripperox/cc-meter/tags`) using stdlib `urllib`
     with a **User-Agent** header and a **short timeout (≤ 3s)**. Pick the highest
     semver tag (`vX.Y.Z`).
  4. Read local version from `<repo>/.claude-plugin/plugin.json` (self-locating via
     `__file__`).
  5. Write cache atomically:
     `{checked_at, current, latest, update_available: <semver latest > current>}`.
  6. **Any** failure (network, timeout, parse, rate-limit) → silently leave the old
     cache untouched and exit 0. The user is never bothered by a failed check.
- Triggered by a new **`SessionStart` hook** with `"async": true` — fires once per
  session start, never blocks startup, and the 24h throttle caps real network calls
  at ≤ 1/day regardless of how many sessions open.

### The nudge (status line)

`statusline.py` reads `update-check.json` (guarded). If `update_available` is true,
append a final alert part: `⟳ v{latest}` in yellow (matching the existing warn
palette). Reads a precomputed boolean — **no version-compare logic on the hot
path**. Disappears automatically once the user updates (next `--check` flips the
flag, or `/cc-meter update` clears the cache).

### `/cc-meter update` — one-command update (auto-detect)

`update.py` (no args), invoked by the `update` mode of the command:

- **Self-locate** repo root from `__file__`.
- If `<root>/.git` exists → **git checkout**: run `git -C <root> pull --ff-only`
  then `<root>/install.sh` (idempotent). Print a concise success/needs-restart note.
- Else (running under `~/.claude/plugins/…`) → **plugin**: print the exact command
  to run — `claude plugin update cc-meter` — and explain we don't mutate
  Claude-managed plugin files ourselves.
- On success, clear/refresh `update-check.json` so the nudge clears immediately.
- Never leave a half-applied state: `--ff-only` avoids merge surprises; if `git
  pull` fails (dirty tree, no network), report it and make no further changes.

### Command surface

The single `/cc-meter` command branches on `$ARGUMENTS`:

| `$ARGUMENTS`     | behavior                                            |
|------------------|-----------------------------------------------------|
| *(empty)*        | cross-session summary (existing)                    |
| `turns`          | per-prompt breakdown (existing)                     |
| `customize`      | interactive tick-box editor (Feature B)             |
| `update`         | run `update.py` and show its output (Feature D)     |

`allowed-tools` for the command becomes `Bash(python3:*)` and `AskUserQuestion`.
(The update path shells out to `git`/`install.sh` *inside* `update.py`, so the only
Bash command Claude issues is `python3 …`.)

## Installer & onboarding

### `install.sh` changes (still idempotent)

- Register the new **`SessionStart`** hook (`update.py --check`, async), deduped the
  same way the `SessionEnd` entry is.
- Write the richer `~/.claude/commands/cc-meter.md` (the four modes above).
- Everything keeps pointing at the checkout's own absolute path. Re-running stays
  safe and updates paths/content in place.

### `hooks/hooks.json` (plugin form)

Add the `SessionStart` async entry alongside `SessionEnd`, using
`${CLAUDE_PLUGIN_ROOT}`.

### Bootstrap caveat (the one manual step)

The two current users' installs predate the updater, so the *first* hop is manual —
done once:

- git checkout: `cd <cc-meter> && git pull && ./install.sh`
- plugin: `claude plugin update cc-meter`

After that, the in-CLI nudge + `/cc-meter update` make every future update
effortless. README will spell this out.

### Release process (maintainer)

Each release: bump `version` in `.claude-plugin/plugin.json` **and** push a matching
git tag `vX.Y.Z`. The checker compares installed `plugin.json` version against the
highest GitHub tag.

## Files touched

| File | Change |
|------|--------|
| `scripts/statusline.py` | segment registry + ordering, `humanize_remaining`, `time` segment, config read, update nudge, remove TEMP capture |
| `scripts/config.py` | **new** — config schema/validate/atomic write, `--show/--set/--preset` |
| `scripts/update.py` | **new** — `--check` (background) and update action (auto-detect) |
| `hooks/hooks.json` | add async `SessionStart` → `update.py --check` |
| `install.sh` | register `SessionStart`, write 4-mode `cc-meter.md` |
| `commands/history.md` | document the new modes (plugin command form) |
| `.claude-plugin/plugin.json` | version `0.1.0` → `0.2.0` |
| `README.md` | document customize, update, config.json, nudge, bootstrap; amend the "no network" line to "no network except an optional daily update check (opt-out)" |
| `tests/test_statusline.py` | **new** |
| `tests/test_config.py` | **new** |
| `tests/test_update.py` | **new** |

## Testing strategy

TDD: write the failing test, then the code. Pure logic is extracted so it is
testable without I/O or network.

- **`test_statusline.py`**
  - `humanize_remaining`: `≥1h → "2h13m"`, zero-pad `2h05m`, `13m`, `<1m`, and the
    ≤0 omit contract.
  - segment registry: each key renders the expected string; absent data self-hides.
  - config-driven order & visibility; unknown key ignored; missing/invalid config →
    built-in default.
  - `time` omitted when `resets_at` is past / missing / unparseable.
  - update nudge shown iff cache `update_available` true; bad/missing cache → no
    nudge, no crash.
  - fuzz: random/garbage payloads never raise (always prints something).
- **`test_config.py`**
  - `--set` writes valid JSON, atomically, preserving unrelated keys.
  - invalid keys rejected (nonzero exit, nothing written).
  - presets expand to the documented lists.
  - `--show` output shape.
- **`test_update.py`**
  - semver compare incl. non-semver inputs (no false "update available").
  - 24h throttle: fresh cache → no network attempt.
  - opt-out (config flag and env) → no network attempt.
  - cache write shape; simulated fetch failure leaves prior cache intact, exits 0.
  - install-type detection (git vs plugin) via a temp dir with/without `.git`.

Run: `python3 -m unittest discover -s tests` — must be green.

## Production-grade acceptance criteria

- Status line: never raises (top-level guard intact), never blocks, never performs
  network or spawns subprocesses on the hot path. Renders correctly for empty `{}`,
  partial, and malformed payloads.
- All file writes (config, caches, settings) are atomic (`tmp` + `os.replace`).
- Network: single throttled call, ≤3s timeout, UA header, total silence on failure,
  fully opt-out.
- Installer idempotent; re-run is safe; `settings.json` backed up before edit.
- Stdlib only — no new dependencies. Works on macOS and Linux, `python3`.
- All tests green; `humanize_remaining` and version-compare have boundary tests.
- README accurately reflects the new network behavior and the new commands.

## Out of scope (YAGNI)

- Per-segment color customization, custom glyphs, or custom separators.
- Reordering inside the tick UI (hand-edit the file).
- Auto-applying updates without the user running `/cc-meter update`.
- Windows-specific install path.
- Changes to `log-session.py` or the report's existing modes.
