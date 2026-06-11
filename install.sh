#!/usr/bin/env bash
# cc-meter installer — wires the status line, SessionEnd logger, and /cc-meter
# command into ~/.claude, pointing at THIS checkout (no hardcoded paths).
# Idempotent: re-running updates the paths and never double-registers the hook.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "cc-meter: python3 is required but was not found on PATH." >&2
  exit 1
fi

"$PY" - "$REPO" <<'PYEOF'
import json, os, sys, shutil

repo = sys.argv[1]
claude = os.path.join(os.path.expanduser("~"), ".claude")
os.makedirs(os.path.join(claude, "commands"), exist_ok=True)

settings = os.path.join(claude, "settings.json")
data = {}
if os.path.exists(settings):
    shutil.copy(settings, settings + ".bak-ccmeter")
    try:
        with open(settings) as f:
            data = json.load(f)
    except Exception:
        print("cc-meter: warning — existing settings.json was not valid JSON; "
              "a backup was saved and it will be rewritten.", file=sys.stderr)
        data = {}

statusline = 'python3 "%s/scripts/statusline.py"' % repo
logsession = 'python3 "%s/scripts/log-session.py"' % repo

data["statusLine"] = {"type": "command", "command": statusline, "padding": 0}

hooks = data.setdefault("hooks", {})
se = hooks.get("SessionEnd", []) or []
# Drop any prior cc-meter entry (including an old hardcoded path), then re-add.
se = [g for g in se
      if not any("log-session.py" in (h.get("command", "") or "")
                 for h in g.get("hooks", []))]
se.append({"hooks": [{"type": "command", "command": logsession}]})
hooks["SessionEnd"] = se

with open(settings, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

cmd_md = os.path.join(claude, "commands", "cc-meter.md")
with open(cmd_md, "w") as f:
    f.write(
        '---\n'
        'description: Claude Code usage — cross-session summary, or "turns" for per-prompt cost (cc-meter)\n'
        'allowed-tools: Bash(python3:*)\n'
        '---\n\n'
        'Use the Bash tool to run this command exactly (`$ARGUMENTS` is whatever the user '
        'typed after `/cc-meter` — e.g. `turns` for a per-prompt breakdown of the current '
        'session; empty for the cross-session summary):\n\n'
        '    python3 "%s/scripts/report.py" $ARGUMENTS\n\n'
        'Then show the script\'s stdout to the user **verbatim** inside a code block. '
        'Do not summarize, analyze, reformat, or add any commentary — just display the '
        'report output as-is.\n' % repo
    )

print("cc-meter installed:")
print("  status line   -> %s/scripts/statusline.py" % repo)
print("  SessionEnd    -> %s/scripts/log-session.py" % repo)
print("  /cc-meter cmd -> %s/scripts/report.py" % repo)
print("  settings      -> %s (backup: %s.bak-ccmeter)" % (settings, settings))
PYEOF

echo
echo "Done. Restart Claude Code (or /exit and reopen) to load the status line, hook, and command."
