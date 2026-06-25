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
        'description: cc-meter — usage report, or "turns"/"customize"/"update"\n'
        'allowed-tools: Bash(python3:*), AskUserQuestion\n'
        '---\n\n'
        'Dispatch on `$ARGUMENTS`:\n\n'
        '- **empty** or **`turns`** — run and show the stdout **verbatim** in a code '
        'block (no summary, no commentary):\n\n'
        '        python3 "%(repo)s/scripts/report.py" $ARGUMENTS\n\n'
        '- **`customize`** — let the user pick which status-line segments show:\n'
        '  1. Run `python3 "%(repo)s/scripts/config.py" --show` and parse its JSON\n'
        '     (`available` = `{key,label,sample}` per segment, `current` = enabled keys).\n'
        '  2. Use **AskUserQuestion** (`multiSelect: true`) listing each segment as\n'
        '     `label — sample`, pre-selecting the `current` keys. Offer the presets\n'
        '     **default** / **full** / **minimal** too.\n'
        '  3. Persist: a preset -> `python3 "%(repo)s/scripts/config.py" --preset NAME`;\n'
        '     explicit ticks -> `python3 "%(repo)s/scripts/config.py" --set k1,k2,...`\n'
        '     (canonical order: `model,tokens,ctx,cost,5h,time,7d`).\n'
        '  4. Show a one-line preview and note the status line refreshes next turn.\n\n'
        '- **`update`** — run and show its output (auto-detects git checkout vs plugin):\n\n'
        '        python3 "%(repo)s/scripts/update.py"\n'
        % {"repo": repo}
    )

print("cc-meter installed:")
print("  status line   -> %s/scripts/statusline.py" % repo)
print("  SessionStart  -> %s/scripts/update.py --check" % repo)
print("  SessionEnd    -> %s/scripts/log-session.py" % repo)
print("  /cc-meter cmd -> report.py / config.py / update.py (modes)")
print("  settings      -> %s (backup: %s.bak-ccmeter)" % (settings, settings))
PYEOF

echo
echo "Done. Restart Claude Code (or /exit and reopen) to load the status line, hook, and command."
