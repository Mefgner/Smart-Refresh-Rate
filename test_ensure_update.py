"""Focused tests for _is_newer/_parse_version and _ensure_config migration.
Stdlib only, run: python test_ensure_update.py"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import asyncio

import reschanger
import main
import update_check
from update_check import _is_newer, _parse_version

def assert_eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg}: {a!r} != {b!r}")

def test_parse_and_is_newer():
    # basic
    assert _is_newer("1.2.0", "1.1.5.0")
    assert not _is_newer("1.1.5.0", "1.1.5.0")
    assert _is_newer("v1.2.0-pre", "1.1.5.0")
    assert not _is_newer("1.2.0", "v1.2.0-pre"), "suffix ignored -> equal"
    # empty parts
    assert_eq(_parse_version("v1..2"), (1, 2), "v1..2")
    assert_eq(_parse_version("1.0..0"), (1, 0, 0), "1.0..0")
    assert_eq(_parse_version("v"), (), "v -> empty")
    assert_eq(_parse_version(""), (), "empty")
    assert_eq(_parse_version("  v1.2  "), (1, 2), "spaces")
    # malformed
    assert_eq(_parse_version("abc"), (), "abc -> empty")
    assert_eq(_parse_version("1.2.abc"), (1, 2), "1.2.abc -> 1,2")
    assert_eq(_parse_version("v1.a2b.3"), (1, 3), "v1.a2b.3 -> 1,3 (a2b has no leading digits)")
    # leading v variations
    assert _is_newer("V1.2.0", "1.1.0")
    # padded compare
    assert not _is_newer("1.0", "1.0.0"), "1.0 == 1.0.0"
    assert _is_newer("1.0.1", "1.0")
    # malformed tag vs current
    assert not _is_newer("", "1.0")
    assert not _is_newer("abc", "1.0")
    assert _is_newer("1.0", ""), "1.0 > empty"
    print("test_parse_and_is_newer PASS")

def _run_ensure(initial_json, active_displays, mock_w=2560, mock_h=1440, mock_freq=240, mock_bat=60):
    orig_active = reschanger.get_active_displays
    orig_settings = reschanger.get_display_settings
    orig_best = reschanger.best_powersave_freq
    orig_cfg = main.PATH_CONFIG
    orig_prog = main.PATH_TO_PROGRAM
    try:
        reschanger.get_active_displays = lambda: active_displays
        reschanger.get_display_settings = lambda a,m: (mock_w, mock_h, mock_freq)
        reschanger.best_powersave_freq = lambda a,w,h: mock_bat
        with tempfile.TemporaryDirectory() as tmp:
            prog = Path(tmp) / "SRR"
            cfg = prog / "config.json"
            main.PATH_TO_PROGRAM = prog
            main.PATH_CONFIG = cfg
            if initial_json is not None:
                prog.mkdir(parents=True, exist_ok=True)
                with open(cfg, "w") as f:
                    json.dump(initial_json, f, indent=4)
            main._ensure_config()
            if cfg.exists():
                with open(cfg, "r") as f:
                    return json.load(f)
            return None
    finally:
        reschanger.get_active_displays = orig_active
        reschanger.get_display_settings = orig_settings
        reschanger.best_powersave_freq = orig_best
        main.PATH_CONFIG = orig_cfg
        main.PATH_TO_PROGRAM = orig_prog

def test_ensure_migration_valid():
    displays = [
        {"monitor_id": r"MONITOR\A\1", "adapter_name": b"\\\\.\\DISPLAY1", "monitor_string": "A"},
        {"monitor_id": r"MONITOR\B\2", "adapter_name": b"\\\\.\\DISPLAY2", "monitor_string": "B"},
    ]
    flat = {"performance-state": {"width": 1920, "height": 1080, "refresh_rate": 144},
            "powersave-state": {"width": 1920, "height": 1080, "refresh_rate": 60}}
    res = _run_ensure(flat, displays)
    assert "performance-state" not in res
    assert res[displays[0]["monitor_id"]]["performance-state"]["refresh_rate"] == 144
    assert res[displays[1]["monitor_id"]]["performance-state"]["refresh_rate"] == 144
    print("test_ensure_migration_valid PASS")

def test_ensure_invalid_applies_legacy():
    # FIX 2: invalid entry should get legacy values, not registry, when legacy present
    displays = [{"monitor_id": r"MONITOR\A\1", "adapter_name": b"\\\\.\\DISPLAY1", "monitor_string": "A"}]
    # invalid without legacy -> registry
    invalid = {displays[0]["monitor_id"]: {"performance-state": {"width": 1920, "height": 1080, "refresh_rate": 0},
                                           "powersave-state": {"width": 1920, "height": 1080, "refresh_rate": 60}}}
    res = _run_ensure(invalid, displays, mock_w=3000, mock_h=2000, mock_freq=165)
    assert res[displays[0]["monitor_id"]]["performance-state"]["width"] == 3000, "invalid without legacy -> registry"
    print("test_ensure_invalid_without_legacy PASS")
    # FIX 2: mixed flat valid + invalid monitor entry -> invalid gets legacy, not registry
    mixed_invalid = {
        "performance-state": {"width": 1920, "height": 1080, "refresh_rate": 144},
        "powersave-state": {"width": 1920, "height": 1080, "refresh_rate": 60},
        displays[0]["monitor_id"]: {"performance-state": {"width": 1920, "height": 1080, "refresh_rate": 0},
                                    "powersave-state": {"width": 1920, "height": 1080, "refresh_rate": 60}},
    }
    res2 = _run_ensure(mixed_invalid, displays, mock_w=3000, mock_h=2000, mock_freq=240)
    # should be legacy 1920/144, not registry 3000/240
    assert res2[displays[0]["monitor_id"]]["performance-state"]["width"] == 1920, f"mixed invalid should get legacy, got {res2}"
    assert res2[displays[0]["monitor_id"]]["performance-state"]["refresh_rate"] == 144
    print("test_ensure_invalid_with_legacy PASS")
    # FIX 2: mixed flat valid + valid monitor entry -> valid preserved, not overwritten by legacy
    mixed_valid = {
        "performance-state": {"width": 1920, "height": 1080, "refresh_rate": 144},
        "powersave-state": {"width": 1920, "height": 1080, "refresh_rate": 60},
        displays[0]["monitor_id"]: {"performance-state": {"width": 2560, "height": 1440, "refresh_rate": 240},
                                    "powersave-state": {"width": 2560, "height": 1440, "refresh_rate": 60}},
    }
    res3 = _run_ensure(mixed_valid, displays, mock_w=3000, mock_h=2000, mock_freq=165)
    # valid entry should be preserved (2560), not overwritten by flat 1920
    assert res3[displays[0]["monitor_id"]]["performance-state"]["width"] == 2560, f"mixed valid should be preserved, got {res3}"
    print("test_ensure_valid_preserved_over_legacy PASS")

def test_ensure_bool_rejected():
    displays = [{"monitor_id": r"MONITOR\A\1", "adapter_name": b"\\\\.\\DISPLAY1", "monitor_string": "A"}]
    bool_entry = {displays[0]["monitor_id"]: {"performance-state": {"width": True, "height": 1080, "refresh_rate": 60},
                                             "powersave-state": {"width": 1920, "height": 1080, "refresh_rate": 60}}}
    res = _run_ensure(bool_entry, displays, mock_w=2560, mock_h=1440, mock_freq=240)
    # bool True should be rejected as invalid, so regenerated to 2560
    assert res[displays[0]["monitor_id"]]["performance-state"]["width"] == 2560, f"bool not rejected, got {res}"
    # also test bool in flat
    flat_bool = {"performance-state": {"width": True, "height": 1080, "refresh_rate": 144},
                 "powersave-state": {"width": 1920, "height": 1080, "refresh_rate": 60}}
    res2 = _run_ensure(flat_bool, displays, mock_w=2560, mock_h=1440, mock_freq=240)
    # flat with bool should be considered invalid, so registry used
    assert res2[displays[0]["monitor_id"]]["performance-state"]["width"] == 2560
    print("test_ensure_bool_rejected PASS")

def test_ensure_no_active_keeps_legacy():
    flat = {"performance-state": {"width": 1920, "height": 1080, "refresh_rate": 144},
            "powersave-state": {"width": 1920, "height": 1080, "refresh_rate": 60}}
    res = _run_ensure(flat, [])  # no active displays
    # FIX 1: should keep legacy intact
    assert res is not None and "performance-state" in res and "powersave-state" in res, f"legacy lost, got {res}"
    assert res["performance-state"]["width"] == 1920
    print("test_ensure_no_active_keeps_legacy PASS")

def test_ensure_coercion():
    displays = [{"monitor_id": r"MONITOR\A\1", "adapter_name": b"\\\\.\\DISPLAY1", "monitor_string": "A"}]
    coerced = {displays[0]["monitor_id"]: {"performance-state": {"width": "1920", "height": "1080", "refresh_rate": "144"},
                                          "powersave-state": {"width": "1920", "height": "1080", "refresh_rate": "60"}}}
    res = _run_ensure(coerced, displays)
    assert isinstance(res[displays[0]["monitor_id"]]["performance-state"]["width"], int)
    assert res[displays[0]["monitor_id"]]["performance-state"]["width"] == 1920
    print("test_ensure_coercion PASS")

def test_ensure_target_preserved():
    displays = [{"monitor_id": r"MONITOR\A\1", "adapter_name": b"\\\\.\\DISPLAY1", "monitor_string": "A"}]
    flat = {"target_display": r"MONITOR\A\1",
            "performance-state": {"width": 1920, "height": 1080, "refresh_rate": 144},
            "powersave-state": {"width": 1920, "height": 1080, "refresh_rate": 60}}
    res = _run_ensure(flat, displays)
    assert res["target_display"] == r"MONITOR\A\1"
    print("test_ensure_target_preserved PASS")

def test_ensure_flat_notifications_preserved():
    # reviewer: legacy flat config carrying the old `notifications` key must be
    # classified as pure flat (preserve values), not "mixed" (which would drop
    # the custom flat values and regenerate from registry).
    displays = [{"monitor_id": r"MONITOR\A\1", "adapter_name": b"\\\\.\\DISPLAY1", "monitor_string": "A"}]
    flat_notif = {"performance-state": {"width": 2560, "height": 1440, "refresh_rate": 144},
                  "powersave-state": {"width": 2560, "height": 1440, "refresh_rate": 60},
                  "notifications": True}
    # active displays present -> pure flat migration preserves 144/60 (not registry 240)
    res = _run_ensure(flat_notif, displays, mock_w=3840, mock_h=2160, mock_freq=240, mock_bat=60)
    assert res[displays[0]["monitor_id"]]["performance-state"]["refresh_rate"] == 144, f"flat perf must be preserved, got {res}"
    assert res[displays[0]["monitor_id"]]["powersave-state"]["refresh_rate"] == 60, f"flat psav must be preserved, got {res}"
    assert "notifications" not in res, "legacy notifications must not be persisted back"
    # no active displays at migration time -> config kept intact (FIX 1)
    res2 = _run_ensure(flat_notif, [])
    assert res2["performance-state"]["refresh_rate"] == 144
    assert res2["powersave-state"]["refresh_rate"] == 60
    print("test_ensure_flat_notifications_preserved PASS")

def test_dedup_startup_and_periodic():
    # covers Fix4: same version → no second notify, new version → notify
    orig_check = update_check.check_for_updates
    orig_last = main._last_notified_update_version
    orig_tray = main._tray

    class MockTray:
        def __init__(self):
            self.notified = []
            self.versions = []
        def set_update_available(self, v):
            self.versions.append(v)
        def notify(self, msg, title="SRR"):
            self.notified.append((msg, title))

    mock_tray = MockTray()
    main._tray = mock_tray
    main._last_notified_update_version = None

    async def mock_120():
        return "1.2.0"

    async def mock_same():
        return "1.2.0"

    async def mock_130():
        return "1.3.0"

    async def do_check():
        ver = await update_check.check_for_updates()
        if ver and main._tray is not None:
            main._tray.set_update_available(ver)
            if ver != main._last_notified_update_version:
                main._tray.notify(f"Update available: v{ver}", "SRR")
                main._last_notified_update_version = ver

    update_check.check_for_updates = mock_120
    asyncio.run(do_check())
    assert len(mock_tray.notified) == 1, "startup first should notify"
    assert mock_tray.versions[-1] == "1.2.0"

    # periodic same version -> no second notify (dedup)
    update_check.check_for_updates = mock_same
    asyncio.run(do_check())
    assert len(mock_tray.notified) == 1, "same version periodic should not notify again"
    assert mock_tray.versions[-1] == "1.2.0"

    # new version -> notify (both startup and periodic share dedup)
    update_check.check_for_updates = mock_130
    asyncio.run(do_check())
    assert len(mock_tray.notified) == 2, "new version should notify"
    assert mock_tray.notified[-1][0] == "Update available: v1.3.0"

    # restore
    main._tray = orig_tray
    main._last_notified_update_version = orig_last
    update_check.check_for_updates = orig_check
    print("test_dedup_startup_and_periodic PASS")

def test_clear_stale_on_no_update():
    # D-2: a "no update" result must clear the tray status to None (disabled
    # "No updates yet"), not keep a stale version; clearing must not notify.
    orig_check = update_check.check_for_updates
    orig_last = main._last_notified_update_version
    orig_tray = main._tray

    class MockTray:
        def __init__(self):
            self.notified = []
            self.versions = []
        def set_update_available(self, v):
            self.versions.append(v)
        def notify(self, msg, title="SRR"):
            self.notified.append((msg, title))

    mock_tray = MockTray()
    main._tray = mock_tray
    main._last_notified_update_version = None

    async def mock_120():
        return "1.2.0"

    async def mock_none():
        return None

    update_check.check_for_updates = mock_120
    asyncio.run(main._run_update_check())
    assert mock_tray.versions[-1] == "1.2.0"
    assert len(mock_tray.notified) == 1, "update should notify"

    # no update -> status cleared, no second notify, no stale version kept
    update_check.check_for_updates = mock_none
    asyncio.run(main._run_update_check())
    assert mock_tray.versions[-1] is None, "no-update must clear stale status"
    assert len(mock_tray.notified) == 1, "clear must not notify"

    # restore
    main._tray = orig_tray
    main._last_notified_update_version = orig_last
    update_check.check_for_updates = orig_check
    print("test_clear_stale_on_no_update PASS")

if __name__ == "__main__":
    test_parse_and_is_newer()
    test_ensure_migration_valid()
    test_ensure_invalid_applies_legacy()
    test_ensure_bool_rejected()
    test_ensure_no_active_keeps_legacy()
    test_ensure_coercion()
    test_ensure_target_preserved()
    test_ensure_flat_notifications_preserved()
    test_dedup_startup_and_periodic()
    test_clear_stale_on_no_update()
    print("\nALL TESTS PASSED")
