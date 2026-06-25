#!/usr/bin/env python3
"""cc-meter config editor — backs `/cc-meter customize`. Reads/writes
~/.claude/cc-meter/config.json atomically. The single source of truth for segment
keys/labels/samples is statusline.py (imported by path), so the two never drift."""
import os
import re
import sys
import json
import importlib.util

CONFIG_PATH = os.path.expanduser("~/.claude/cc-meter/config.json")

_ANSI = re.compile(r"\033\[[0-9;]*m")
# Representative samples for segments whose live render is time-dependent.
_SAMPLE_OVERRIDES = {"time": "⏳2h13m"}

_spec = importlib.util.spec_from_file_location(
    "statusline",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "statusline.py"))
statusline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(statusline)

PRESETS = {
    "default": list(statusline.DEFAULT_SEGMENTS),
    "full": list(statusline.ALL_SEGMENTS),
    "minimal": ["model", "5h", "time"],
}


def load():
    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.replace(tmp, CONFIG_PATH)


def _set_segments(keys):
    cfg = load()
    cfg.setdefault("statusline", {})["segments"] = keys
    save(cfg)


def cmd_set(csv):
    keys = [k.strip() for k in (csv or "").split(",") if k.strip()]
    unknown = [k for k in keys if k not in statusline.ALL_SEGMENTS]
    if unknown or not keys:
        sys.stderr.write("cc-meter: unknown or empty segment(s): %s\n"
                         % (", ".join(unknown) or "(none given)"))
        sys.stderr.write("valid: %s\n" % ", ".join(statusline.ALL_SEGMENTS))
        return 2
    _set_segments(keys)
    return 0


def cmd_preset(name):
    if name not in PRESETS:
        sys.stderr.write("cc-meter: unknown preset '%s' (valid: %s)\n"
                         % (name, ", ".join(PRESETS)))
        return 2
    _set_segments(list(PRESETS[name]))
    return 0


def _sample(key):
    raw = statusline.render_segment(key, statusline.SAMPLE_PAYLOAD)
    text = _ANSI.sub("", raw) if raw else ""
    return text or _SAMPLE_OVERRIDES.get(key, "")


def show_payload():
    cfg = load()
    available = [{"key": k,
                  "label": statusline.SEGMENT_LABELS.get(k, k),
                  "sample": _sample(k)}
                 for k in statusline.ALL_SEGMENTS]
    return {
        "available": available,
        "current": statusline.selected_segments(cfg),
        "update_check": bool(cfg.get("update_check", True)),
    }


def cmd_show():
    sys.stdout.write(json.dumps(show_payload(), indent=2) + "\n")
    return 0


def cmd_interactive():
    """Full-screen terminal segment picker. Requires a real TTY."""
    if not sys.stdin.isatty():
        sys.stderr.write("cc-meter: --interactive requires a real terminal.\n")
        return 1

    cfg = load()
    current = set(statusline.selected_segments(cfg))

    def render():
        sys.stdout.write("\033[2J\033[H")
        print("cc-meter — customize status line")
        print("─" * 38)
        for i, key in enumerate(statusline.ALL_SEGMENTS, 1):
            check = "✓" if key in current else " "
            sample = _sample(key)
            print(f"  {i}  [{check}] {key:<8}  {sample}")
        print()
        print("  Presets:  d default · f full · m minimal")
        print("  Toggle 1-7 · s save · q quit")
        print()

    while True:
        render()
        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 0

        if choice == "q":
            print("No changes saved.")
            break
        elif choice == "s":
            ordered = [k for k in statusline.ALL_SEGMENTS if k in current]
            if not ordered:
                input("Select at least one segment. Press Enter to continue.")
                continue
            _set_segments(ordered)
            sys.stdout.write("\033[2J\033[H")
            print(f"Saved: {' · '.join(ordered)}")
            print("Status line updates on your next Claude turn.")
            break
        elif choice == "d":
            current = set(statusline.DEFAULT_SEGMENTS)
        elif choice == "f":
            current = set(statusline.ALL_SEGMENTS)
        elif choice == "m":
            current = set(PRESETS["minimal"])
        elif choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(statusline.ALL_SEGMENTS):
                key = statusline.ALL_SEGMENTS[n - 1]
                if key in current:
                    current.discard(key)
                else:
                    current.add(key)

    return 0


def main(argv):
    if not argv:
        return cmd_show()
    a = argv[0]
    if a == "--show":
        return cmd_show()
    if a == "--interactive":
        return cmd_interactive()
    if a == "--set" and len(argv) > 1:
        return cmd_set(argv[1])
    if a == "--preset" and len(argv) > 1:
        return cmd_preset(argv[1])
    sys.stderr.write("usage: config.py [--show | --interactive | --set k1,k2 | --preset NAME]\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
