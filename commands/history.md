---
description: cc-meter — usage report, or "turns"/"customize"/"update"
allowed-tools: Bash(python3:*), AskUserQuestion
---

Dispatch on `$ARGUMENTS`:

- **empty** or **`turns`** — run and show the stdout **verbatim** in a code block
  (no summary, no commentary):

      python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report.py" $ARGUMENTS

- **`customize`** — let the user pick which status-line segments show:
  1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" --show` and parse its JSON
     (`available` = `{key,label,sample}` per segment, `current` = enabled keys).
  2. Use **AskUserQuestion** (`multiSelect: true`) listing each segment as
     `label — sample`, pre-selecting the `current` keys. Offer the presets
     **default** / **full** / **minimal** too.
  3. Persist the choice:
     - a preset → `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" --preset NAME`
     - explicit ticks → `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" --set k1,k2,...`
       (keys in canonical order: `model,tokens,ctx,cost,5h,time,7d`).
  4. Show a one-line preview of the result and note the status line refreshes next turn.

- **`update`** — run and show its output (it auto-detects git checkout vs plugin):

      python3 "${CLAUDE_PLUGIN_ROOT}/scripts/update.py"
