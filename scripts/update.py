#!/usr/bin/env python3
"""cc-meter updater.

  update.py --check   throttled, opt-out background version check (run by an async
                      SessionStart hook); writes a cache the status line reads.
  update.py           auto-detecting update: git checkout -> pull + reinstall;
                      plugin install -> print `claude plugin update`.

Network is a single call, timed out, and silent on any failure. The status line
never invokes this — only the hook (check) and the slash command (update) do."""
import os
import sys
import json
import time
import subprocess
import urllib.request

REPO = "Ripperox/cc-meter"
CACHE_PATH = os.path.expanduser("~/.claude/cc-meter/update-check.json")
CONFIG_PATH = os.path.expanduser("~/.claude/cc-meter/config.json")
CHECK_INTERVAL = 24 * 3600
TIMEOUT = 3


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_version(s):
    if not s:
        return None
    s = s.strip().lstrip("vV")
    if not s:
        return None
    try:
        return tuple(int(p) for p in s.split("."))
    except (ValueError, TypeError):
        return None


def is_newer(latest, current):
    lv, cv = parse_version(latest), parse_version(current)
    if lv is None or cv is None:
        return False
    return lv > cv


def local_version(root):
    try:
        with open(os.path.join(root, ".claude-plugin", "plugin.json")) as f:
            return json.load(f).get("version")
    except Exception:
        return None


def _config():
    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def opted_out(cfg):
    if os.environ.get("CC_METER_NO_UPDATE_CHECK"):
        return True
    return cfg.get("update_check", True) is False


def should_check(cache, now):
    last = cache.get("checked_at")
    if not last:
        return True
    try:
        return (now - float(last)) >= CHECK_INTERVAL
    except Exception:
        return True


def read_cache():
    try:
        with open(CACHE_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_cache(d):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, CACHE_PATH)


def fetch_latest_tag(repo):
    """Highest semver tag from the GitHub tags API. None on any failure."""
    url = "https://api.github.com/repos/%s/tags?per_page=100" % repo
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cc-meter"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            tags = json.load(r)
        best = None
        for t in tags:
            name = t.get("name", "")
            v = parse_version(name)
            if v and (best is None or v > best[0]):
                best = (v, name)
        return best[1] if best else None
    except Exception:
        return None


def do_check(now=None, fetch=fetch_latest_tag):
    now = time.time() if now is None else now
    if opted_out(_config()):
        return 0
    if not should_check(read_cache(), now):
        return 0
    latest_raw = fetch(REPO)
    if not latest_raw:
        return 0  # silent: keep any prior cache untouched
    current = local_version(repo_root()) or "0.0.0"
    write_cache({
        "checked_at": now,
        "current": current,
        "latest": latest_raw.lstrip("vV"),
        "update_available": is_newer(latest_raw, current),
    })
    return 0


def detect_install(root):
    return "git" if os.path.isdir(os.path.join(root, ".git")) else "plugin"


def do_update():
    root = repo_root()
    if detect_install(root) == "plugin":
        sys.stdout.write(
            "cc-meter was installed as a Claude Code plugin.\n"
            "Update it with:\n\n    claude plugin update cc-meter\n\n"
            "(We don't modify Claude-managed plugin files directly.)\n")
        return 0
    try:
        subprocess.run(["git", "-C", root, "pull", "--ff-only"], check=True)
        subprocess.run([os.path.join(root, "install.sh")], check=True)
    except Exception as e:
        sys.stderr.write(
            "cc-meter: update failed: %s\n"
            "Resolve it (e.g. commit/stash local changes, check your network) "
            "and retry.\n" % e)
        return 1
    try:  # clear the nudge right away
        cache = read_cache()
        cache["update_available"] = False
        cache["current"] = local_version(root) or cache.get("current")
        write_cache(cache)
    except Exception:
        pass
    sys.stdout.write("\ncc-meter updated. Restart Claude Code (or /exit and reopen).\n")
    return 0


def main(argv):
    if argv and argv[0] == "--check":
        return do_check()
    return do_update()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
