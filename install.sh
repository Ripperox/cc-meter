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
checkupd = 'python3 "%s/scripts/update.py" --check' % repo

data["statusLine"] = {"type": "command", "command": statusline, "padding": 0}

hooks = data.setdefault("hooks", {})

se = hooks.get("SessionEnd", []) or []
# Drop any prior cc-meter entry (including an old hardcoded path), then re-add.
se = [g for g in se
      if not any("log-session.py" in (h.get("command", "") or "")
                 for h in g.get("hooks", []))]
se.append({"hooks": [{"type": "command", "command": logsession}]})
hooks["SessionEnd"] = se

ss = hooks.get("SessionStart", []) or []
ss = [g for g in ss
      if not any("update.py" in (h.get("command", "") or "")
                 for h in g.get("hooks", []))]
ss.append({"hooks": [{"type": "command", "command": checkupd, "async": True}]})
hooks["SessionStart"] = ss

with open(settings, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

cmd_md = os.path.join(claude, "commands", "cc-meter.md")
with open(cmd_md, "w") as f:
    f.write(
        '---\n'
        'description: cc-meter — usage report (or "turns" for per-turn breakdown)\n'
        'allowed-tools: Bash(python3:*)\n'
        '---\n\n'
        'Run and show stdout **verbatim** in a code block (no summary, no commentary):\n\n'
        '    python3 "%(repo)s/scripts/report.py" $ARGUMENTS\n'
        % {"repo": repo}
    )

cust_md = os.path.join(claude, "commands", "cc-meter-customize.md")
with open(cust_md, "w") as f:
    f.write(
        '---\n'
        'description: cc-meter — customize which status-line segments are shown\n'
        'allowed-tools: Bash(python3:*)\n'
        '---\n\n'
        'Run this command exactly as-is and wait for it to finish:\n\n'
        '    python3 "%(repo)s/scripts/config.py" --interactive\n\n'
        'Before running, say one sentence: "The picker is running in the Terminal panel'
        ' below — click there, toggle with 1-7, preset with d/f/m, s to save."\n'
        'After it exits say: "Done — status line updates on the next turn."\n'
        'Do not ask questions, show menus, or modify config yourself.\n'
        % {"repo": repo}
    )

upd_md = os.path.join(claude, "commands", "cc-meter-update.md")
with open(upd_md, "w") as f:
    f.write(
        '---\n'
        'description: cc-meter — check for updates and apply if available\n'
        'allowed-tools: Bash(python3:*)\n'
        '---\n\n'
        'Run and show stdout **verbatim** in a code block:\n\n'
        '    python3 "%(repo)s/scripts/update.py"\n'
        % {"repo": repo}
    )

print("cc-meter installed:")
print("  status line      -> %s/scripts/statusline.py" % repo)
print("  SessionStart     -> %s/scripts/update.py --check" % repo)
print("  SessionEnd       -> %s/scripts/log-session.py" % repo)
print("  /cc-meter        -> usage report")
print("  /cc-meter-customize -> interactive segment picker")
print("  /cc-meter-update -> update checker")
print("  settings         -> %s (backup: %s.bak-ccmeter)" % (settings, settings))
PYEOF

echo
echo "Done. Restart Claude Code (or /exit and reopen) to load the status line, hook, and command."
