"""Tests for the sums of a placement test.

The module imports nothing from Home Assistant, so it is loaded directly.

Run: python tests/test_placement.py (or python -m pytest tests/).
"""

import importlib.util
import os
import sys

_PATH = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "danfoss_eco", "placement.py"
)
_spec = importlib.util.spec_from_file_location("danfoss_eco_placement_under_test", _PATH)
placement = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = placement
_spec.loader.exec_module(placement)

T0 = 1_800_000_000.0
A = "00:04:2F:00:00:01"
B = "00:04:2F:00:00:02"
P1 = "B8:27:EB:73:3A:1F"
P2 = "B8:27:EB:3D:94:5D"
NAMES = {P1: "bt-proxy-1", P2: "bt-proxy-2"}


def _test(minutes=30, last_read=T0 - 60):
    test = placement.PlacementTest("Rack", "moved off the rack", T0, minutes * 60)
    test.add_thermostat(A, "Kontor 1", last_read)
    test.add_thermostat(B, "Lager", last_read)
    return test


def test_connects_are_counted_per_thermostat_and_scanner():
    test = _test()
    for success in (True, True, False):
        test.connect(A, P1, success)
    test.connect(A, P2, False)
    test.connect(B, P1, True)
    result = test.result(T0 + 1800, NAMES)
    assert result["thermostats"]["Kontor 1"]["scanners"]["bt-proxy-1"]["attempts"] == 3
    assert result["thermostats"]["Kontor 1"]["scanners"]["bt-proxy-1"]["successes"] == 2
    assert result["scanners"]["bt-proxy-1"] == {
        "address": P1,
        "attempts": 4,
        "successes": 3,
        "rate_pct": 75,
    }
    assert result["scanners"]["bt-proxy-2"]["rate_pct"] == 0
    assert test.progress() == {P1: [3, 4], P2: [0, 1]}


def test_signal_is_averaged_over_the_samples_that_heard_the_thermostat():
    test = _test()
    test.signal(A, {P1: -60, P2: None})
    test.signal(A, {P1: -70, P2: -90})
    test.signal(A, {P1: None, P2: None})
    test.signal(A, {P1: -62, P2: None})
    scanners = test.result(T0 + 1800, NAMES)["thermostats"]["Kontor 1"]["scanners"]
    assert scanners["bt-proxy-1"]["signal"] == -64
    assert scanners["bt-proxy-1"]["heard_pct"] == 75
    assert scanners["bt-proxy-2"]["signal"] == -90
    assert scanners["bt-proxy-2"]["heard_pct"] == 25


def test_scanner_that_never_heard_the_thermostat_has_no_signal():
    test = _test()
    test.signal(A, {P2: None})
    pair = test.result(T0 + 1800, NAMES)["thermostats"]["Kontor 1"]["scanners"][
        "bt-proxy-2"
    ]
    assert pair["signal"] is None and pair["heard_pct"] == 0


def test_age_of_the_latest_reading_with_a_read_every_two_minutes():
    # Read exactly at the start and every 2 minutes: the age saws between 0
    # and 2 minutes, so it averages 1 minute and is never stale.
    test = _test(minutes=30, last_read=T0)
    for step in range(1, 16):
        test.read(A, T0 + step * 120)
    valve = test.result(T0 + 1800, NAMES)["thermostats"]["Kontor 1"]
    assert valve["reads"] == 15
    assert valve["reads_per_hour"] == 30.0
    assert valve["mean_age_min"] == 1.0
    assert valve["stale_pct"] == 0
    assert valve["longest_gap_min"] == 2.0


def test_a_long_gap_counts_as_stale_from_five_minutes_on():
    # One read at 10 minutes in a 30 minute test, last read at the start:
    # stale from 5 to 10 and from 15 to 30, 20 of 30 minutes.
    test = _test(minutes=30, last_read=T0)
    test.read(A, T0 + 600)
    valve = test.result(T0 + 1800, NAMES)["thermostats"]["Kontor 1"]
    assert valve["stale_pct"] == 67
    assert valve["longest_gap_min"] == 20.0
    # Mean age: (10^2/2 + 20^2/2) / 30 = 8.33 minutes.
    assert valve["mean_age_min"] == 8.3


def test_the_reading_from_before_the_test_sets_the_age_at_the_start():
    # Last read 4 minutes before the start and none during: stale after 1
    # minute of a 10 minute test.
    test = _test(minutes=10, last_read=T0 - 240)
    valve = test.result(T0 + 600, NAMES)["thermostats"]["Kontor 1"]
    assert valve["stale_pct"] == 90
    assert valve["longest_gap_min"] == 14.0
    # Unknown last read: the age is counted from the start.
    unknown = _test(minutes=10, last_read=None)
    assert unknown.result(T0 + 600, NAMES)["thermostats"]["Kontor 1"][
        "longest_gap_min"
    ] == 10.0


def test_reads_before_the_start_and_unknown_thermostats_are_ignored():
    test = _test()
    test.read(A, T0 - 5)
    test.read("00:04:2F:00:00:99", T0 + 5)
    test.connect("00:04:2F:00:00:99", P1, True)
    test.signal("00:04:2F:00:00:99", {P1: -60})
    result = test.result(T0 + 1800, NAMES)
    assert result["thermostats"]["Kontor 1"]["reads"] == 0
    assert list(result["thermostats"]) == ["Kontor 1", "Lager"]


def test_result_carries_name_note_times_and_summary():
    test = placement.PlacementTest(
        "Rack", "moved", T0, 1800, {"poll_minutes": [1], "version": "x"}
    )
    test.add_thermostat(A, "Kontor 1", T0)
    test.add_thermostat(B, "Lager", T0)
    for step in range(1, 16):
        test.read(A, T0 + step * 120)
    test.read(B, T0 + 600)
    result = test.result(T0 + 5000, NAMES)
    assert result["id"] == test.test_id
    assert (result["name"], result["note"]) == ("Rack", "moved")
    assert result["minutes"] == 30 and result["interrupted"] is False
    assert result["ended"] > result["started"]
    assert result["poll_minutes"] == [1] and result["version"] == "x"
    assert result["summary"] == {
        "thermostats": 2,
        "reads_per_hour": 16.0,
        "mean_age_min": 4.7,
        "stale_pct": 33,
    }


def test_a_test_stopped_early_ends_at_the_stop():
    test = _test(minutes=30, last_read=T0)
    test.read(A, T0 + 120)
    result = test.result(T0 + 300, NAMES, interrupted=True)
    assert result["minutes"] == 5 and result["interrupted"] is True
    assert result["thermostats"]["Kontor 1"]["longest_gap_min"] == 3.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
