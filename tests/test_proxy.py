"""Tests for the choice of Bluetooth proxy.

The module imports nothing from Home Assistant, so it is loaded directly.

Run: python tests/test_proxy.py (or python -m pytest tests/).
"""

import importlib.util
import os
import sys

_PATH = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "danfoss_eco", "proxy.py"
)
_spec = importlib.util.spec_from_file_location("danfoss_eco_proxy_under_test", _PATH)
proxy = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = proxy
_spec.loader.exec_module(proxy)

P1 = "B8:27:EB:73:3A:1F"
P2 = "B8:27:EB:3D:94:5D"
NUC = "00:C2:C6:C9:0A:AD"
HEARD = {P1: 5.0, P2: 5.0, NUC: 5.0}


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


def _tracker(locked=None, roll=0.99, records=None, clock=None):
    """Tracker with fixed dice; records = {source: (attempts, successes)}."""
    tracker = proxy.ProxyTracker(locked, rng=lambda: roll, now=clock or Clock())
    for source, (attempts, successes) in (records or {}).items():
        tracker.stats[source] = proxy.ProxyStats(attempts, successes)
    return tracker


def test_scanner_with_the_best_record_is_chosen():
    tracker = _tracker(records={P1: (20, 9), P2: (20, 2), NUC: (20, 4)})
    assert tracker.choose(HEARD) == (P1, proxy.CHOICE_LEARNED)


def test_home_assistant_chooses_until_a_scanner_has_enough_attempts():
    tracker = _tracker(records={P1: (proxy.MIN_ATTEMPTS - 1, 4)})
    assert tracker.choose(HEARD) == (None, proxy.CHOICE_HA)
    tracker.record(P1, True)
    assert tracker.choose(HEARD) == (P1, proxy.CHOICE_LEARNED)


def test_few_lucky_attempts_do_not_beat_a_long_good_record():
    # 5 of 5 smooths to 6/7 = 0.86, 90 of 100 to 91/102 = 0.89.
    tracker = _tracker(records={P1: (5, 5), P2: (100, 90)})
    assert tracker.choose(HEARD)[0] == P2
    # Without smoothing 1.00 would beat 0.90.
    assert tracker.stats[P1].rate < tracker.stats[P2].rate


def test_one_in_ten_connects_is_left_to_home_assistant():
    records = {P1: (20, 9), P2: (20, 2)}
    assert _tracker(roll=0.05, records=records).choose(HEARD) == (
        None,
        proxy.CHOICE_HA,
    )
    assert _tracker(roll=0.10, records=records).choose(HEARD)[0] == P1
    rolls = iter(i / 1000 for i in range(1000))
    tracker = proxy.ProxyTracker(rng=lambda: next(rolls))
    tracker.stats[P1] = proxy.ProxyStats(20, 9)
    left_to_ha = sum(tracker.choose(HEARD)[0] is None for _ in range(1000))
    assert left_to_ha == 100


def test_scanner_that_has_not_heard_the_thermostat_recently_is_skipped():
    tracker = _tracker(records={P1: (20, 9), P2: (20, 4)})
    heard = {P1: proxy.RECENT_ADVERT_S + 1, P2: 5.0}
    assert tracker.choose(heard) == (P2, proxy.CHOICE_LEARNED)
    # Exactly at the limit still counts as recent.
    assert tracker.choose({P1: proxy.RECENT_ADVERT_S, P2: 5.0})[0] == P1
    # Not heard by anyone it knows: Home Assistant decides.
    assert tracker.choose({NUC: 5.0}) == (None, proxy.CHOICE_HA)
    assert tracker.choose({}) == (None, proxy.CHOICE_HA)


def test_lock_wins_over_the_learned_choice_and_is_never_explored_away():
    tracker = _tracker(locked=P2, roll=0.0, records={P1: (50, 40), P2: (50, 1)})
    assert tracker.choose(HEARD) == (P2, proxy.CHOICE_LOCKED)


def test_lock_works_without_any_record():
    assert _tracker(locked=NUC).choose(HEARD) == (NUC, proxy.CHOICE_LOCKED)


def test_locked_scanner_that_has_not_heard_falls_back_to_home_assistant():
    tracker = _tracker(locked=P2, records={P1: (50, 40)})
    assert tracker.choose({P1: 5.0, P2: 601.0}) == (None, proxy.CHOICE_HA)
    assert tracker.choose({P1: 5.0}) == (None, proxy.CHOICE_HA)


def test_automatic_is_not_a_lock():
    assert _tracker(locked=proxy.AUTO).locked is None
    assert _tracker(locked="").locked is None
    assert _tracker(locked=None).locked is None


def test_failures_in_a_row_rest_the_scanner_then_give_it_one_more_try():
    clock = Clock()
    tracker = _tracker(records={P1: (20, 12), P2: (20, 6)}, clock=clock)
    for _ in range(proxy.MAX_CONSECUTIVE_FAILURES - 1):
        tracker.record(P1, False)
    assert tracker.choose(HEARD)[0] == P1
    tracker.record(P1, False)
    assert tracker.is_benched(P1)
    assert tracker.choose(HEARD) == (P2, proxy.CHOICE_LEARNED)

    clock.t += proxy.BENCH_S + 1
    assert not tracker.is_benched(P1)
    assert tracker.choose(HEARD)[0] == P1
    # One more failure rests it again at once.
    tracker.record(P1, False)
    assert tracker.choose(HEARD)[0] == P2
    # A success clears the streak.
    clock.t += proxy.BENCH_S + 1
    tracker.record(P1, True)
    tracker.record(P1, False)
    assert not tracker.is_benched(P1)


def test_locked_scanner_that_keeps_failing_falls_back_to_home_assistant():
    clock = Clock()
    tracker = _tracker(locked=P1, clock=clock)
    for _ in range(proxy.MAX_CONSECUTIVE_FAILURES):
        assert tracker.choose(HEARD) == (P1, proxy.CHOICE_LOCKED)
        tracker.record(P1, False, proxy.CHOICE_LOCKED)
    assert tracker.choose(HEARD) == (None, proxy.CHOICE_HA)
    clock.t += proxy.BENCH_S + 1
    assert tracker.choose(HEARD) == (P1, proxy.CHOICE_LOCKED)


def test_record_counts_and_remembers_the_latest_connect():
    tracker = _tracker()
    tracker.record(P1, True, proxy.CHOICE_LEARNED)
    tracker.record(P2, False, proxy.CHOICE_HA)
    assert (tracker.stats[P1].attempts, tracker.stats[P1].successes) == (1, 1)
    assert (tracker.stats[P2].attempts, tracker.stats[P2].successes) == (1, 0)
    assert (tracker.last_source, tracker.last_choice) == (P2, proxy.CHOICE_HA)


def test_old_counts_fade_so_a_moved_proxy_is_relearned():
    tracker = _tracker(records={P1: (proxy.DECAY_AT, 80)})
    tracker.record(P1, True)
    stats = tracker.stats[P1]
    assert (stats.attempts, stats.successes) == ((proxy.DECAY_AT + 1) // 2, 40)


def test_records_survive_a_save_and_load():
    clock = Clock()
    tracker = _tracker(records={P1: (20, 9)}, clock=clock)
    for _ in range(3):
        tracker.record(P2, False)
    restored = proxy.ProxyTracker(now=clock)
    restored.load(tracker.as_dict())
    assert restored.as_dict() == tracker.as_dict()
    assert restored.is_benched(P2)


def test_unreadable_saved_records_are_skipped():
    tracker = _tracker()
    tracker.load(None)
    tracker.load("nonsense")
    tracker.load(
        {
            P1: {"attempts": 4, "successes": 9},
            P2: {"attempts": "x"},
            NUC: "nonsense",
        }
    )
    # Successes can never exceed attempts.
    assert tracker.as_dict() == {
        P1: {
            "attempts": 4,
            "successes": 4,
            "consecutive_failures": 0,
            "last_failure": 0.0,
        }
    }


def test_summary_shows_the_plain_rate_per_scanner():
    tracker = _tracker(records={P1: (20, 9), P2: (0, 0)})
    assert tracker.summary() == {
        P2: {"attempts": 0, "successes": 0, "success_rate": None, "benched": False},
        P1: {"attempts": 20, "successes": 9, "success_rate": 0.45, "benched": False},
    }


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("all good")
