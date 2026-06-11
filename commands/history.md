---
description: Claude Code usage — cross-session summary, or "turns" for per-prompt cost (cc-meter)
allowed-tools: Bash(python3:*)
---

Use the Bash tool to run this command exactly (`$ARGUMENTS` is whatever the user typed after the command — e.g. `turns` for a per-prompt breakdown of the current session; empty for the cross-session summary):

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report.py" $ARGUMENTS

Then show the script's stdout to the user **verbatim** inside a code block. Do not summarize, analyze, reformat, or add any commentary — just display the report output as-is.
