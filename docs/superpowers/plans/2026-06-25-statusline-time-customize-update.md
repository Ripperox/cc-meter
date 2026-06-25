# Status-line Time-left, Customization & In-CLI Updates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 5h-session time-left indicator, a fully customizable status line (segment model + config + `/cc-meter customize`), and in-CLI update notifications (`/cc-meter update` + a status-line nudge) to cc-meter.

**Architecture:** `statusline.py` becomes a registry of named segments assembled per a config-driven order; it reads two small JSON files (`config.json`, `update-check.json`) with fully guarded helpers and never imports anything, never blocks, never hits the network. A new `config.py` is the editor CLI behind `/cc-meter customize`. A new `update.py` does the throttled background version check (`--check`, run by an async `SessionStart` hook) and the auto-detecting update action. Installer + plugin hooks register the new hook and richer command.

**Tech Stack:** Python 3 stdlib only (`json`, `os`, `sys`, `time`, `urllib`, `subprocess`, `importlib`), `unittest`. No third-party deps.

## Global Constraints

- **Stdlib only** — no new dependencies. Python 3, macOS + Linux.
- **Status line never crashes** — top-level `try/except` prints `"cc-meter"`; every helper it calls is independently guarded and returns a safe default.
- **Status line never blocks / never networks / never spawns subprocesses** on render. All network is in `update.py --check`, run async by the hook.
- **All file writes atomic** — write `<path>.tmp`, then `os.replace`.
- **Network call**: single, ≤3s timeout, `User-Agent` header, total silence on any failure, fully opt-out (`update_check:false` in config OR `CC_METER_NO_UPDATE_CHECK=1`).
- **Installer idempotent** — re-run safe; backs up `settings.json` to `.bak-ccmeter`; dedupes hook entries.
- **Canonical segment order:** `["model", "tokens", "ctx", "cost", "5h", "time", "7d"]`.
- **Built-in default segments:** `["model", "tokens", "5h", "time", "7d"]`.
- **Presets:** `default = model,tokens,5h,time,7d` · `full = model,tokens,ctx,cost,5h,time,7d` · `minimal = model,5h,time`.
- **Config path:** `~/.claude/cc-meter/config.json`. **Update cache:** `~/.claude/cc-meter/update-check.json`.
- **Repo / version source:** `github.com/Ripperox/cc-meter`; local version from `<root>/.claude-plugin/plugin.json`; latest from GitHub **tags** API; strip a leading `v` before comparing. Bump `plugin.json` to `0.2.0`.
- **Run tests:** `python3 -m unittest discover -s tests` — must stay green.

## File Structure & Public Interfaces

`scripts/statusline.py` (modify) — owns the segment registry and is the single source of truth imported by `config.py` and the tests. Module-level API:

```
ALL_SEGMENTS    : list[str]              # canonical order (7 keys)
DEFAULT_SEGMENTS: list[str]              # the 5 default keys
SEGMENT_LABELS  : dict[str,str]          # key -> human label (for --show)
SAMPLE_PAYLOAD  : dict                   # canned status-line JSON for samples
humanize_remaining(seconds: float) -> str
render_segment(key: str, d: dict) -> str | None   # None => segment hidden
load_config() -> dict                    # guarded; {} on any error
selected_segments(cfg: dict) -> list[str]          # config order, validated, else DEFAULT
update_nudge() -> str | None             # reads update-check.json; guarded
build_line(d: dict, cfg: dict) -> str    # assemble visible segments + nudge
```

`scripts/config.py` (new) — editor CLI. Imports `statusline` by path. API:
```
CONFIG_PATH : str
PRESETS     : dict[str, list[str]]
load() -> dict ; save(cfg: dict) -> None          # atomic, preserves unknown keys
cmd_show() -> int        # prints JSON {available:[{key,label,sample}], current:[...], update_check:bool}
cmd_set(csv: str) -> int # validate keys, write statusline.segments
cmd_preset(name: str) -> int
main(argv) -> int        # dispatch --show/--set/--preset
```

`scripts/update.py` (new) — version check + update action. API:
```
REPO = "Ripperox/cc-meter" ; CACHE_PATH : str
parse_version(s: str) -> tuple | None             # strip 'v', ("1","2","3")->(1,2,3); None if unparseable
is_newer(latest: str, current: str) -> bool       # False on any unparseable
repo_root() -> str                                # parent of scripts/ via __file__
local_version(root: str) -> str | None            # from plugin.json
opted_out(cfg: dict) -> bool                      # config flag or env
should_check(cache: dict, now: float) -> bool     # 24h throttle
fetch_latest_tag(repo: str) -> str | None         # network; guarded; None on any failure
read_cache() -> dict ; write_cache(d: dict) -> None   # atomic
do_check(now=None, fetch=fetch_latest_tag) -> int # orchestrate --check (injectable for tests)
detect_install(root: str) -> str                  # "git" | "plugin"
do_update() -> int                                # auto-detect; pull+install or instruct
main(argv) -> int                                 # --check => do_check else do_update
```

`hooks/hooks.json` (modify), `install.sh` (modify), `commands/history.md` (modify), `.claude-plugin/plugin.json` (modify), `README.md` (modify).

Tests: `tests/test_statusline.py`, `tests/test_config.py`, `tests/test_update.py` (new).

---

### Task 1: `humanize_remaining` pure formatter

**Files:**
- Modify: `scripts/statusline.py` (add function near top, after `bar`)
- Test: `tests/test_statusline.py` (new)

**Interfaces:**
- Produces: `humanize_remaining(seconds: float) -> str`

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
"""Tests for statusline.py. Loaded by path (sibling has no hyphen, but keep parity
with test_log_session.py). Run: python3 -m unittest discover -s tests"""
import importlib.util, os, unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
_spec = importlib.util.spec_from_file_location(
    "statusline", os.path.join(SCRIPTS, "statusline.py"))
statusline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(statusline)


class HumanizeRemaining(unittest.TestCase):
    def test_hours_and_minutes_zero_padded(self):
        self.assertEqual(statusline.humanize_remaining(2 * 3600 + 13 * 60), "2h13m")
        self.assertEqual(statusline.humanize_remaining(2 * 3600 + 5 * 60), "2h05m")

    def test_minutes_only(self):
        self.assertEqual(statusline.humanize_remaining(13 * 60), "13m")
        self.assertEqual(statusline.humanize_remaining(59 * 60 + 59), "59m")

    def test_under_one_minute(self):
        self.assertEqual(statusline.humanize_remaining(45), "<1m")
        self.assertEqual(statusline.humanize_remaining(1), "<1m")

    def test_zero_or_negative_returns_empty(self):
        self.assertEqual(statusline.humanize_remaining(0), "")
        self.assertEqual(statusline.humanize_remaining(-10), "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_statusline -v`
Expected: FAIL — `AttributeError: module 'statusline' has no attribute 'humanize_remaining'`

- [ ] **Step 3: Write minimal implementation** (add to `scripts/statusline.py` after `bar`)

```python
def humanize_remaining(seconds):
    """Compact 'time left' string. <=0 -> '' (caller omits the segment)."""
    s = int(seconds or 0)
    if s <= 0:
        return ""
    h, m = s // 3600, (s % 3600) // 60
    if h > 0:
        return f"{h}h{m:02d}m"
    if m > 0:
        return f"{m}m"
    return "<1m"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_statusline -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/statusline.py tests/test_statusline.py
git commit -m "feat(statusline): add humanize_remaining time-left formatter"
```

---

### Task 2: Segment registry + config-free rendering (remove TEMP block)

Rewrites `statusline.py` rendering into a registry. Uses `DEFAULT_SEGMENTS` directly (config wiring is Task 3). Removes the leftover TEMP-capture block.

**Files:**
- Modify: `scripts/statusline.py`
- Test: `tests/test_statusline.py`

**Interfaces:**
- Consumes: `humanize_remaining` (Task 1)
- Produces: `ALL_SEGMENTS`, `DEFAULT_SEGMENTS`, `SEGMENT_LABELS`, `SAMPLE_PAYLOAD`, `render_segment(key, d) -> str|None`, `build_line(d, cfg) -> str` (cfg unused until Task 3; pass `{}`)

- [ ] **Step 1: Write the failing tests** (append class to `tests/test_statusline.py`)

```python
class Segments(unittest.TestCase):
    def payload(self):
        return {
            "model": {"display_name": "Opus 4.8"},
            "context_window": {"total_input_tokens": 35763, "total_output_tokens": 477,
                               "used_percentage": 4},
            "cost": {"total_cost_usd": 0.3029775},
            "rate_limits": {
                "five_hour": {"used_percentage": 43, "resets_at": 9999999999},
                "seven_day": {"used_percentage": 64, "resets_at": 9999999999},
            },
        }

    def test_each_segment_renders(self):
        d = self.payload()
        self.assertEqual(statusline.render_segment("model", d), "Opus 4.8")
        self.assertIn("⬆", statusline.render_segment("tokens", d))
        self.assertEqual(statusline.render_segment("ctx", d), "ctx 4%")
        self.assertEqual(statusline.render_segment("cost", d), "$0.303")
        self.assertIn("5h", statusline.render_segment("5h", d))
        self.assertIn("7d", statusline.render_segment("7d", d))

    def test_absent_data_hides_segment(self):
        self.assertIsNone(statusline.render_segment("cost", {}))
        self.assertIsNone(statusline.render_segment("ctx", {}))

    def test_unknown_key_is_none(self):
        self.assertIsNone(statusline.render_segment("bogus", self.payload()))

    def test_build_line_uses_default_order_and_joins(self):
        line = statusline.build_line(self.payload(), {})
        # default = model,tokens,5h,time,7d  (no ctx, no cost)
        self.assertIn("Opus 4.8", line)
        self.assertIn("⬆", line)
        self.assertNotIn("$", line)        # cost hidden by default
        self.assertNotIn("ctx", line)      # ctx hidden by default
        self.assertIn(" · ", line)

    def test_all_segments_constant(self):
        self.assertEqual(statusline.ALL_SEGMENTS,
                         ["model", "tokens", "ctx", "cost", "5h", "time", "7d"])
        self.assertEqual(statusline.DEFAULT_SEGMENTS,
                         ["model", "tokens", "5h", "time", "7d"])
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_statusline -v`
Expected: FAIL — `render_segment` / `build_line` / `ALL_SEGMENTS` missing.

- [ ] **Step 3: Rewrite `scripts/statusline.py`** to the registry form. Full file:

```python
#!/usr/bin/env python3
"""cc-meter status line: reads Claude Code's status-line JSON on stdin and prints a
compact one-liner of named segments (model · tokens · ctx · cost · 5h · time · 7d),
plus an optional update nudge. Order/visibility come from ~/.claude/cc-meter/config.json.
Must never crash, block, or hit the network — everything is guarded."""
import sys
import os
import json
import time

DIM, GREEN, YELLOW, RED, CYAN = "2", "32", "33", "31", "36"

CONFIG_PATH = os.path.expanduser("~/.claude/cc-meter/config.json")
UPDATE_CACHE = os.path.expanduser("~/.claude/cc-meter/update-check.json")

ALL_SEGMENTS = ["model", "tokens", "ctx", "cost", "5h", "time", "7d"]
DEFAULT_SEGMENTS = ["model", "tokens", "5h", "time", "7d"]
SEGMENT_LABELS = {
    "model": "Model name", "tokens": "Input/output tokens", "ctx": "Context window %",
    "cost": "Session cost ($)", "5h": "5-hour usage bar", "time": "Time left in 5h window",
    "7d": "7-day usage bar",
}
SAMPLE_PAYLOAD = {
    "model": {"display_name": "Opus 4.8"},
    "context_window": {"total_input_tokens": 14200, "total_output_tokens": 1300,
                       "used_percentage": 8},
    "cost": {"total_cost_usd": 0.024},
    "rate_limits": {"five_hour": {"used_percentage": 41, "resets_at": 0},
                    "seven_day": {"used_percentage": 12, "resets_at": 0}},
}


def c(s, code):
    return f"\033[{code}m{s}\033[0m"


def fmt(n):
    n = float(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(int(n))


def bar(pct):
    pct = max(0.0, min(100.0, float(pct or 0)))
    filled = int(round(pct / 20.0))
    glyph = "▓" * filled + "░" * (5 - filled)
    code = GREEN if pct < 50 else (YELLOW if pct < 80 else RED)
    return c(glyph, code)


def humanize_remaining(seconds):
    """Compact 'time left' string. <=0 -> '' (caller omits the segment)."""
    s = int(seconds or 0)
    if s <= 0:
        return ""
    h, m = s // 3600, (s % 3600) // 60
    if h > 0:
        return f"{h}h{m:02d}m"
    if m > 0:
        return f"{m}m"
    return "<1m"


def _ratebar(d, key, label):
    rl = (d.get("rate_limits") or {}).get(key) or {}
    p = rl.get("used_percentage")
    if p is None:
        return None
    warn = " ⚠" if float(p) >= 80 else ""
    return f"{label} {bar(p)} {int(float(p))}%{warn}"


def _seg_model(d):
    m = d.get("model") or {}
    return c(m.get("display_name") or m.get("id") or "?", CYAN)


def _seg_tokens(d):
    cw = d.get("context_window") or {}
    if cw.get("total_input_tokens") is None and cw.get("total_output_tokens") is None:
        return None
    return f"⬆{fmt(cw.get('total_input_tokens'))} ⬇{fmt(cw.get('total_output_tokens'))}"


def _seg_ctx(d):
    cw = d.get("context_window") or {}
    if cw.get("used_percentage") is None:
        return None
    return f"ctx {int(cw['used_percentage'])}%"


def _seg_cost(d):
    cost = (d.get("cost") or {}).get("total_cost_usd")
    return None if cost is None else f"${float(cost):.3f}"


def _seg_time(d):
    rl = (d.get("rate_limits") or {}).get("five_hour") or {}
    resets = rl.get("resets_at")
    if not resets:
        return None
    label = humanize_remaining(float(resets) - time.time())
    return c(f"⏳{label}", DIM) if label else None


SEGMENT_RENDERERS = {
    "model": _seg_model, "tokens": _seg_tokens, "ctx": _seg_ctx, "cost": _seg_cost,
    "5h": lambda d: _ratebar(d, "five_hour", "5h"),
    "7d": lambda d: _ratebar(d, "seven_day", "7d"),
    "time": _seg_time,
}


def render_segment(key, d):
    fn = SEGMENT_RENDERERS.get(key)
    if fn is None:
        return None
    try:
        return fn(d)
    except Exception:
        return None


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def selected_segments(cfg):
    seg = ((cfg or {}).get("statusline") or {}).get("segments")
    if isinstance(seg, list):
        keys = [k for k in seg if k in SEGMENT_RENDERERS]
        if keys:
            return keys
    return DEFAULT_SEGMENTS


def update_nudge():
    return None  # implemented in Task 6


def build_line(d, cfg):
    parts = []
    for key in selected_segments(cfg):
        s = render_segment(key, d)
        if s:
            parts.append(s)
    line = c(" · ", DIM).join(parts)
    nudge = update_nudge()
    if nudge:
        line = line + c(" · ", DIM) + nudge if line else nudge
    return line


def main():
    d = json.loads(sys.stdin.read() or "{}")
    sys.stdout.write(build_line(d, load_config()))


try:
    main()
except Exception:
    sys.stdout.write("cc-meter")
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest tests.test_statusline -v`
Expected: PASS (Task 1 + Task 2 classes).

- [ ] **Step 5: Smoke-test render manually**

Run: `printf '{"model":{"display_name":"Opus 4.8"},"rate_limits":{"five_hour":{"used_percentage":43,"resets_at":9999999999}}}' | python3 scripts/statusline.py; echo`
Expected: a line containing `Opus 4.8`, `5h`, and `⏳` with hours.

- [ ] **Step 6: Commit**

```bash
git add scripts/statusline.py tests/test_statusline.py
git commit -m "feat(statusline): segment registry, time segment, drop TEMP capture"
```

---

### Task 3: Config-driven order & visibility

`selected_segments` already reads `cfg`; this task proves the file path end-to-end by pointing `CONFIG_PATH` at a temp file in tests, and adds the fallback/validation tests.

**Files:**
- Modify: `scripts/statusline.py` (no logic change expected; only if a test reveals a gap)
- Test: `tests/test_statusline.py`

**Interfaces:**
- Consumes: `selected_segments`, `load_config`, `CONFIG_PATH`
- Produces: (none new)

- [ ] **Step 1: Write failing tests** (append)

```python
import json as _json, tempfile

class ConfigDriven(unittest.TestCase):
    def test_config_overrides_order_and_visibility(self):
        cfg = {"statusline": {"segments": ["cost", "model"]}}
        self.assertEqual(statusline.selected_segments(cfg), ["cost", "model"])

    def test_unknown_keys_filtered(self):
        cfg = {"statusline": {"segments": ["model", "bogus", "7d"]}}
        self.assertEqual(statusline.selected_segments(cfg), ["model", "7d"])

    def test_empty_or_missing_falls_back_to_default(self):
        self.assertEqual(statusline.selected_segments({}), statusline.DEFAULT_SEGMENTS)
        self.assertEqual(statusline.selected_segments({"statusline": {"segments": []}}),
                         statusline.DEFAULT_SEGMENTS)
        self.assertEqual(statusline.selected_segments({"statusline": {"segments": ["nope"]}}),
                         statusline.DEFAULT_SEGMENTS)

    def test_load_config_reads_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            _json.dump({"statusline": {"segments": ["ctx"]}}, f)
            path = f.name
        old = statusline.CONFIG_PATH
        try:
            statusline.CONFIG_PATH = path
            self.assertEqual(statusline.load_config(),
                             {"statusline": {"segments": ["ctx"]}})
        finally:
            statusline.CONFIG_PATH = old
            os.unlink(path)

    def test_load_config_bad_json_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{not json")
            path = f.name
        old = statusline.CONFIG_PATH
        try:
            statusline.CONFIG_PATH = path
            self.assertEqual(statusline.load_config(), {})
        finally:
            statusline.CONFIG_PATH = old
            os.unlink(path)
```

- [ ] **Step 2: Run**

Run: `python3 -m unittest tests.test_statusline -v`
Expected: PASS (logic already present from Task 2). If any fails, fix `selected_segments`/`load_config` minimally to satisfy it.

- [ ] **Step 3: Commit**

```bash
git add tests/test_statusline.py scripts/statusline.py
git commit -m "test(statusline): config-driven order, visibility, fallback"
```

---

### Task 4: `config.py` editor CLI

**Files:**
- Create: `scripts/config.py`
- Test: `tests/test_config.py` (new)

**Interfaces:**
- Consumes: `statusline.ALL_SEGMENTS`, `SEGMENT_LABELS`, `SAMPLE_PAYLOAD`, `render_segment`, `DEFAULT_SEGMENTS`
- Produces: `CONFIG_PATH`, `PRESETS`, `load()`, `save(cfg)`, `cmd_show()`, `cmd_set(csv)`, `cmd_preset(name)`, `main(argv)`

- [ ] **Step 1: Write failing tests** (`tests/test_config.py`)

```python
#!/usr/bin/env python3
"""Tests for config.py. Run: python3 -m unittest discover -s tests"""
import importlib.util, os, json, tempfile, unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
config = _load("config", "config.py")


class ConfigCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "config.json")
        self._old = config.CONFIG_PATH
        config.CONFIG_PATH = self.path

    def tearDown(self):
        config.CONFIG_PATH = self._old

    def test_set_writes_valid_json(self):
        self.assertEqual(config.cmd_set("model,5h,time"), 0)
        with open(self.path) as f:
            data = json.load(f)
        self.assertEqual(data["statusline"]["segments"], ["model", "5h", "time"])

    def test_set_rejects_unknown_key(self):
        self.assertNotEqual(config.cmd_set("model,bogus"), 0)
        self.assertFalse(os.path.exists(self.path))

    def test_set_preserves_unrelated_keys(self):
        config.save({"update_check": False, "statusline": {"segments": ["model"]}})
        config.cmd_set("7d")
        data = config.load()
        self.assertEqual(data["update_check"], False)
        self.assertEqual(data["statusline"]["segments"], ["7d"])

    def test_preset_expands(self):
        self.assertEqual(config.cmd_preset("minimal"), 0)
        self.assertEqual(config.load()["statusline"]["segments"],
                         config.PRESETS["minimal"])

    def test_preset_unknown_rejected(self):
        self.assertNotEqual(config.cmd_preset("nope"), 0)

    def test_show_shape(self):
        # cmd_show prints JSON; capture via main on stdout is overkill — call helper
        payload = config.show_payload()
        self.assertIn("available", payload)
        self.assertTrue(all({"key", "label", "sample"} <= set(a) for a in payload["available"]))
        self.assertIn("current", payload)
        self.assertIn("update_check", payload)
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_config -v`
Expected: FAIL — cannot import `config` (file missing).

- [ ] **Step 3: Create `scripts/config.py`**

```python
#!/usr/bin/env python3
"""cc-meter config editor — backs /cc-meter customize. Reads/writes
~/.claude/cc-meter/config.json atomically. Single source of truth for segment
keys/labels/samples is statusline.py (imported by path)."""
import os
import sys
import json
import importlib.util

CONFIG_PATH = os.path.expanduser("~/.claude/cc-meter/config.json")

_spec = importlib.util.spec_from_file_location(
    "statusline", os.path.join(os.path.dirname(os.path.abspath(__file__)), "statusline.py"))
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


def show_payload():
    cfg = load()
    available = [{"key": k, "label": statusline.SEGMENT_LABELS.get(k, k),
                  "sample": statusline.render_segment(k, statusline.SAMPLE_PAYLOAD) or ""}
                 for k in statusline.ALL_SEGMENTS]
    return {
        "available": available,
        "current": statusline.selected_segments(cfg),
        "update_check": bool(cfg.get("update_check", True)),
    }


def cmd_show():
    sys.stdout.write(json.dumps(show_payload(), indent=2) + "\n")
    return 0


def main(argv):
    if not argv:
        return cmd_show()
    a = argv[0]
    if a == "--show":
        return cmd_show()
    if a == "--set" and len(argv) > 1:
        return cmd_set(argv[1])
    if a == "--preset" and len(argv) > 1:
        return cmd_preset(argv[1])
    sys.stderr.write("usage: config.py [--show | --set k1,k2 | --preset NAME]\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Note: strip ANSI when emitting samples is unnecessary — samples include color codes but `--show` output is consumed by Claude, which is fine. (If a plain sample is preferred later, add a strip; out of scope now.)

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest tests.test_config -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/config.py tests/test_config.py
git commit -m "feat(config): config.py editor CLI for status-line segments"
```

---

### Task 5: `update.py` check logic (no network in tests)

**Files:**
- Create: `scripts/update.py`
- Test: `tests/test_update.py` (new)

**Interfaces:**
- Produces: `parse_version`, `is_newer`, `repo_root`, `local_version`, `opted_out`, `should_check`, `read_cache`, `write_cache`, `do_check(now, fetch)`, `CACHE_PATH`, `REPO`

- [ ] **Step 1: Write failing tests** (`tests/test_update.py`)

```python
#!/usr/bin/env python3
"""Tests for update.py. No real network. Run: python3 -m unittest discover -s tests"""
import importlib.util, os, json, tempfile, unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
_spec = importlib.util.spec_from_file_location("update", os.path.join(SCRIPTS, "update.py"))
update = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update)


class Versions(unittest.TestCase):
    def test_parse_strips_v(self):
        self.assertEqual(update.parse_version("v0.2.0"), (0, 2, 0))
        self.assertEqual(update.parse_version("1.10.3"), (1, 10, 3))

    def test_parse_bad(self):
        self.assertIsNone(update.parse_version("nightly"))
        self.assertIsNone(update.parse_version(""))

    def test_is_newer(self):
        self.assertTrue(update.is_newer("v0.2.0", "0.1.0"))
        self.assertFalse(update.is_newer("0.1.0", "0.1.0"))
        self.assertFalse(update.is_newer("0.1.0", "0.2.0"))

    def test_is_newer_bad_inputs_false(self):
        self.assertFalse(update.is_newer("garbage", "0.1.0"))
        self.assertFalse(update.is_newer("0.2.0", None))


class CheckFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = update.CACHE_PATH
        update.CACHE_PATH = os.path.join(self.tmp, "update-check.json")

    def tearDown(self):
        update.CACHE_PATH = self._old

    def test_should_check_throttles_24h(self):
        self.assertTrue(update.should_check({}, now=1000))
        self.assertFalse(update.should_check({"checked_at": 1000}, now=1000 + 60))
        self.assertTrue(update.should_check({"checked_at": 1000}, now=1000 + 90000))

    def test_opted_out_env(self):
        os.environ["CC_METER_NO_UPDATE_CHECK"] = "1"
        try:
            self.assertTrue(update.opted_out({}))
        finally:
            del os.environ["CC_METER_NO_UPDATE_CHECK"]

    def test_opted_out_config(self):
        self.assertTrue(update.opted_out({"update_check": False}))
        self.assertFalse(update.opted_out({"update_check": True}))

    def test_do_check_fresh_cache_skips_fetch(self):
        update.write_cache({"checked_at": 10_000_000_000, "current": "0.1.0",
                            "latest": "0.1.0", "update_available": False})
        calls = []
        update.do_check(now=10_000_000_001, fetch=lambda repo: calls.append(repo) or "v9.9.9")
        self.assertEqual(calls, [])  # throttled: no fetch

    def test_do_check_writes_update_available(self):
        update.do_check(now=1, fetch=lambda repo: "v99.0.0",
                        )  # current read from plugin.json (0.x) -> newer
        cache = update.read_cache()
        self.assertTrue(cache["update_available"])
        self.assertEqual(cache["latest"], "99.0.0")

    def test_do_check_fetch_failure_keeps_prior_cache(self):
        update.write_cache({"checked_at": 1, "current": "0.1.0", "latest": "0.5.0",
                            "update_available": True})
        update.do_check(now=10_000_000_000, fetch=lambda repo: None)
        cache = update.read_cache()
        self.assertEqual(cache["latest"], "0.5.0")  # unchanged on failure
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_update -v`
Expected: FAIL — cannot import `update`.

- [ ] **Step 3: Create `scripts/update.py`** (check half; update action added in Task 7)

```python
#!/usr/bin/env python3
"""cc-meter updater. `--check` performs a throttled, opt-out background version
check (run by an async SessionStart hook) and writes a cache the status line reads.
With no args it performs an auto-detecting update. Network is single-call, timed
out, and silent on any failure; never invoked by the status line."""
import os
import sys
import json
import time
import urllib.request

REPO = "Ripperox/cc-meter"
CACHE_PATH = os.path.expanduser("~/.claude/cc-meter/update-check.json")
CHECK_INTERVAL = 24 * 3600
TIMEOUT = 3


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_version(s):
    if not s:
        return None
    s = s.strip().lstrip("vV")
    parts = s.split(".")
    try:
        return tuple(int(p) for p in parts)
    except (ValueError, TypeError):
        return None


def is_newer(latest, current):
    lv, cv = parse_version(latest or ""), parse_version(current or "")
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
        with open(os.path.expanduser("~/.claude/cc-meter/config.json")) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def opted_out(cfg):
    if os.environ.get("CC_METER_NO_UPDATE_CHECK"):
        return True
    return cfg.get("update_check", True) is False


def should_check(cache, now):
    last = cache.get("checked_at") or 0
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
            v = parse_version(t.get("name", ""))
            if v and (best is None or v > best[0]):
                best = (v, t["name"])
        return best[1] if best else None
    except Exception:
        return None


def do_check(now=None, fetch=fetch_latest_tag):
    now = time.time() if now is None else now
    cfg = _config()
    if opted_out(cfg):
        return 0
    cache = read_cache()
    if not should_check(cache, now):
        return 0
    latest = fetch(REPO)
    if not latest:
        return 0  # silent: keep prior cache
    current = local_version(repo_root()) or "0.0.0"
    write_cache({"checked_at": now, "current": current, "latest": latest,
                 "update_available": is_newer(latest, current)})
    return 0
```

Add `main` + `__main__` dispatch as a stub that calls `do_check` for `--check` (update action filled in Task 7):

```python
def main(argv):
    if argv and argv[0] == "--check":
        return do_check()
    sys.stderr.write("cc-meter: update action not yet implemented\n")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest tests.test_update -v`
Expected: PASS (all Versions + CheckFlow tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/update.py tests/test_update.py
git commit -m "feat(update): throttled opt-out version check with cache"
```

---

### Task 6: Status-line update nudge

**Files:**
- Modify: `scripts/statusline.py` (replace the `update_nudge` stub)
- Test: `tests/test_statusline.py`

**Interfaces:**
- Consumes: `UPDATE_CACHE`
- Produces: `update_nudge() -> str|None`

- [ ] **Step 1: Write failing tests** (append to `tests/test_statusline.py`)

```python
class UpdateNudge(unittest.TestCase):
    def _with_cache(self, data):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            _json.dump(data, f)
            return f.name

    def test_nudge_when_available(self):
        path = self._with_cache({"update_available": True, "latest": "0.2.0"})
        old = statusline.UPDATE_CACHE
        try:
            statusline.UPDATE_CACHE = path
            self.assertIn("0.2.0", statusline.update_nudge() or "")
            self.assertIn("⟳", statusline.update_nudge() or "")
        finally:
            statusline.UPDATE_CACHE = old
            os.unlink(path)

    def test_no_nudge_when_not_available(self):
        path = self._with_cache({"update_available": False, "latest": "0.2.0"})
        old = statusline.UPDATE_CACHE
        try:
            statusline.UPDATE_CACHE = path
            self.assertIsNone(statusline.update_nudge())
        finally:
            statusline.UPDATE_CACHE = old
            os.unlink(path)

    def test_missing_cache_no_crash(self):
        old = statusline.UPDATE_CACHE
        try:
            statusline.UPDATE_CACHE = "/nonexistent/cc-meter/update-check.json"
            self.assertIsNone(statusline.update_nudge())
        finally:
            statusline.UPDATE_CACHE = old
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_statusline -v`
Expected: FAIL — `update_nudge` returns None unconditionally (stub), so `test_nudge_when_available` fails.

- [ ] **Step 3: Replace the `update_nudge` stub** in `scripts/statusline.py`

```python
def update_nudge():
    try:
        with open(UPDATE_CACHE) as f:
            data = json.load(f)
        if data.get("update_available") and data.get("latest"):
            return c(f"⟳ v{data['latest']}", YELLOW)
    except Exception:
        pass
    return None
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest tests.test_statusline -v`
Expected: PASS (all statusline classes).

- [ ] **Step 5: Commit**

```bash
git add scripts/statusline.py tests/test_statusline.py
git commit -m "feat(statusline): show update-available nudge from cache"
```

---

### Task 7: `update.py` auto-detecting update action

**Files:**
- Modify: `scripts/update.py` (add `detect_install`, `do_update`, wire `main`)
- Test: `tests/test_update.py`

**Interfaces:**
- Produces: `detect_install(root) -> "git"|"plugin"`, `do_update() -> int`

- [ ] **Step 1: Write failing tests** (append)

```python
class InstallDetect(unittest.TestCase):
    def test_detects_git_checkout(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, ".git"))
        self.assertEqual(update.detect_install(d), "git")

    def test_detects_plugin(self):
        d = tempfile.mkdtemp()  # no .git
        self.assertEqual(update.detect_install(d), "plugin")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_update -v`
Expected: FAIL — `detect_install` missing.

- [ ] **Step 3: Add to `scripts/update.py`** and replace `main`

```python
import subprocess


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
        sys.stderr.write("cc-meter: update failed: %s\n"
                         "Fix the issue (e.g. commit/stash local changes) and retry.\n" % e)
        return 1
    # Clear the nudge immediately.
    try:
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
```

(Remove the earlier stub `main`/`__main__` from Task 5 when adding this — there must be exactly one `main` and one `__main__` block.)

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest tests.test_update -v`
Expected: PASS (Versions + CheckFlow + InstallDetect).

- [ ] **Step 5: Commit**

```bash
git add scripts/update.py tests/test_update.py
git commit -m "feat(update): auto-detecting /cc-meter update action"
```

---

### Task 8: Wiring — hook, installer, command, version bump

**Files:**
- Modify: `hooks/hooks.json`, `install.sh`, `commands/history.md`, `.claude-plugin/plugin.json`
- Test: manual (installer dry-run against temp HOME) + full suite stays green

**Interfaces:** none (integration).

- [ ] **Step 1: `hooks/hooks.json`** — add async `SessionStart` alongside `SessionEnd`. Full file:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/update.py\" --check",
            "async": true
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/log-session.py\"",
            "async": true
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: `.claude-plugin/plugin.json`** — bump version.

Change `"version": "0.1.0"` → `"version": "0.2.0"`.

- [ ] **Step 3: `install.sh`** — register `SessionStart` (deduped like `SessionEnd`) and write the 4-mode command. In the embedded Python, after the `SessionEnd` block, add:

```python
    checkupd = 'python3 "%s/scripts/update.py" --check' % repo
    ss = hooks.get("SessionStart", []) or []
    ss = [g for g in ss
          if not any("update.py" in (h.get("command", "") or "")
                     for h in g.get("hooks", []))]
    ss.append({"hooks": [{"type": "command", "command": checkupd, "async": True}]})
    hooks["SessionStart"] = ss
```

And replace the `cmd_md` writer body so `~/.claude/commands/cc-meter.md` documents all four modes:

```python
    cmd_md = os.path.join(claude, "commands", "cc-meter.md")
    with open(cmd_md, "w") as f:
        f.write(
            '---\n'
            'description: cc-meter — usage report, or "turns"/"customize"/"update"\n'
            'allowed-tools: Bash(python3:*), AskUserQuestion\n'
            '---\n\n'
            'Dispatch on `$ARGUMENTS`:\n\n'
            '- **empty** or **`turns`** — run and show **verbatim** in a code block:\n\n'
            '        python3 "%(repo)s/scripts/report.py" $ARGUMENTS\n\n'
            '- **`customize`** — run `python3 "%(repo)s/scripts/config.py" --show`, parse its\n'
            '  JSON, then use AskUserQuestion (multiSelect) to let the user tick segments\n'
            '  (pre-tick the `current` ones; offer presets default/full/minimal). Persist with\n'
            '  `python3 "%(repo)s/scripts/config.py" --set k1,k2,...` (or `--preset NAME`), then\n'
            '  show a one-line preview and remind them the status line refreshes next turn.\n\n'
            '- **`update`** — run and show output:\n\n'
            '        python3 "%(repo)s/scripts/update.py"\n'
            % {"repo": repo}
        )
```

- [ ] **Step 4: `commands/history.md`** (plugin form) — mirror the four modes. Full file:

```markdown
---
description: cc-meter — usage report, or "turns"/"customize"/"update"
allowed-tools: Bash(python3:*), AskUserQuestion
---

Dispatch on `$ARGUMENTS`:

- **empty** or **`turns`** — run and show the stdout **verbatim** in a code block:

      python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report.py" $ARGUMENTS

- **`customize`** — run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" --show`, parse
  its JSON, then use AskUserQuestion (multiSelect) to let the user tick which segments
  show (pre-tick the `current` ones; also offer presets default/full/minimal). Persist
  with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" --set k1,k2,...` (or
  `--preset NAME`). Then show a one-line preview and note the status line refreshes next turn.

- **`update`** — run and show its output:

      python3 "${CLAUDE_PLUGIN_ROOT}/scripts/update.py"
```

- [ ] **Step 5: Installer dry-run against a temp HOME**

Run:
```bash
TMPH=$(mktemp -d); HOME="$TMPH" bash install.sh >/dev/null 2>&1; \
python3 - "$TMPH" <<'PY'
import json,sys,os
s=json.load(open(os.path.join(sys.argv[1],".claude","settings.json")))
hooks=s["hooks"]
assert any("update.py" in h["command"] for g in hooks["SessionStart"] for h in g["hooks"]), "SessionStart missing"
assert any("log-session.py" in h["command"] for g in hooks["SessionEnd"] for h in g["hooks"]), "SessionEnd missing"
assert s["statusLine"]["command"].endswith('statusline.py"'), s["statusLine"]
md=open(os.path.join(sys.argv[1],".claude","commands","cc-meter.md")).read()
assert "customize" in md and "update" in md, "command modes missing"
print("installer OK")
PY
rm -rf "$TMPH"
```
Expected: `installer OK`.

- [ ] **Step 6: Idempotency check** — run installer twice into the same temp HOME; assert exactly one `SessionStart` and one `SessionEnd` cc-meter entry.

Run:
```bash
TMPH=$(mktemp -d); HOME="$TMPH" bash install.sh >/dev/null 2>&1; HOME="$TMPH" bash install.sh >/dev/null 2>&1; \
python3 - "$TMPH" <<'PY'
import json,sys,os
s=json.load(open(os.path.join(sys.argv[1],".claude","settings.json")))
ss=[h for g in s["hooks"]["SessionStart"] for h in g["hooks"] if "update.py" in h["command"]]
se=[h for g in s["hooks"]["SessionEnd"] for h in g["hooks"] if "log-session.py" in h["command"]]
assert len(ss)==1, ("dup SessionStart", len(ss))
assert len(se)==1, ("dup SessionEnd", len(se))
print("idempotent OK")
PY
rm -rf "$TMPH"
```
Expected: `idempotent OK`.

- [ ] **Step 7: Full suite green**

Run: `python3 -m unittest discover -s tests`
Expected: OK.

- [ ] **Step 8: Commit**

```bash
git add hooks/hooks.json install.sh commands/history.md .claude-plugin/plugin.json
git commit -m "feat: wire SessionStart update-check hook, 4-mode command, v0.2.0"
```

---

### Task 9: README + docs

**Files:**
- Modify: `README.md`

**Interfaces:** none.

- [ ] **Step 1: Update README** — make these concrete edits:
  1. Status-line example line: change to the new default
     `Sonnet · ⬆14.2k ⬇1.3k · 5h ▓▓░░░ 41% · ⏳2h13m · 7d ▓░░░░ 12%`.
  2. Add a **Customize** subsection documenting `/cc-meter customize`, the segment
     keys (`model, tokens, ctx, cost, 5h, time, 7d`), the default
     (`model, tokens, 5h, time, 7d`), presets, the `config.json` location/shape, and
     that hand-editing the list controls order.
  3. Add an **Updating** subsection: the status-line `⟳ vX.Y.Z` nudge, `/cc-meter update`
     (auto-detects git checkout vs plugin), and the one-time bootstrap
     (`git pull && ./install.sh`, or `claude plugin update cc-meter`).
  4. Amend the "no network" claim: "Everything is **local** — *except an optional,
     opt-out daily check to GitHub for a newer version* (disable with
     `CC_METER_NO_UPDATE_CHECK=1` or `"update_check": false`). No proxy, no API key."
  5. Add `SessionStart` to the "How it works" table (update check).

- [ ] **Step 2: Verify links/sanity** — re-read README; ensure commands shown match
  actual (`/cc-meter`, `/cc-meter turns`, `/cc-meter customize`, `/cc-meter update`).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document customize, time-left, and update flow"
```

---

## Self-Review

**Spec coverage:**
- Time-left (Feature A) → Task 1 (`humanize_remaining`) + Task 2 (`time` segment). ✓
- Segment model + config + default (Feature B) → Tasks 2–3. ✓
- `/cc-meter customize` + `config.py` + presets → Task 4 + command wiring Task 8. ✓
- Update detection/cache/opt-out/throttle (Feature D) → Task 5. ✓
- Status-line nudge → Task 6. ✓
- `/cc-meter update` auto-detect → Task 7. ✓
- SessionStart hook, installer, command modes, version bump → Task 8. ✓
- README incl. amended "no network" + bootstrap → Task 9. ✓
- Remove TEMP capture → Task 2. ✓
- Atomic writes → config.py `save`, update.py `write_cache`. ✓
- Never-crash/never-block/never-network status line → guarded helpers, no imports, no net in statusline. ✓

**Placeholder scan:** No TBD/TODO; every code step has full code. The `update_nudge` stub in Task 2 is explicitly replaced in Task 6 (intentional, noted). The Task 5 stub `main` is explicitly replaced in Task 7 (noted).

**Type consistency:** `selected_segments(cfg)`, `render_segment(key,d)`, `load_config()`, `SAMPLE_PAYLOAD`, `SEGMENT_LABELS`, `ALL_SEGMENTS`, `DEFAULT_SEGMENTS` used identically across statusline tests and `config.py`. `do_check(now,fetch)` / `read_cache` / `write_cache` / `CACHE_PATH` consistent across update.py and its tests. `detect_install` returns `"git"|"plugin"` consistently.

**Note for executor:** Tasks share files (`statusline.py`, `update.py`, `tests/*`) and MUST run in order. The two intentional stubs (Task 2 `update_nudge`, Task 5 `main`) are replaced later — don't treat them as final.
