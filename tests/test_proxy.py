"""Tests for the choice of Bluetooth proxy.

The module imports nothing from Home Assistant, so it is loaded directly.

Run: python tests/test_proxy.py (or python -m pytest tests/).
"""

import importlib.util
import os
import random
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
P3 = "B8:27:EB:FC:B8:AB"
HEARD = {P1: 5.0, P2: 5.0, P3: 5.0}
HOUR = 3600.0


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


def _mean(a: float, b: float) -> float:
    """Dice that always land on the expected value: no exploring."""
    return a / (a + b)


def _tracker(locked=None, sample=_mean, records=None, clock=None):
    """Tracker with fixed dice; records = {source: (successes, failures)}."""
    clock = clock or Clock()
    tracker = proxy.ProxyTracker(locked, sample=sample, now=clock)
    for source, (successes, failures) in (records or {}).items():
        tracker.stats[source] = proxy.ProxyStats(
            successes=successes, failures=failures, updated=clock()
        )
    return tracker


# ------------------------------------------------------------- signal ----
def test_stronger_signal_means_a_better_expected_rate():
    rates = [proxy.prior_rate(rssi) for rssi in (-95, -88, -80, -72, -65, -50)]
    assert rates == sorted(rates)
    assert proxy.prior_rate(-95) < 0.05
    assert 0.7 < proxy.prior_rate(-65) < 0.8
    # No reading at all: a cautious middle, not zero.
    assert 0.2 < proxy.prior_rate(None) < 0.4


def test_new_scanner_is_judged_by_its_signal_at_once():
    # Nothing counted yet. The scanner that hears the valve best is used,
    # instead of spending twenty connects on each scanner to find out.
    tracker = _tracker()
    signals = {P1: -88, P2: -66, P3: -80}
    assert tracker.choose(HEARD, signals) == (P2, proxy.CHOICE_SIGNAL)
    assert tracker.assigned(HEARD, signals) == (P2, proxy.CHOICE_SIGNAL)


def test_counted_connects_overrule_the_signal():
    # The scanner on the rack hears the valve best but connects badly.
    tracker = _tracker(records={P2: (8, 12), P3: (11, 9)})
    signals = {P2: -69, P3: -74}
    heard = {P2: 5.0, P3: 5.0}
    assert tracker.choose(heard, signals) == (P3, proxy.CHOICE_LEARNED)


def test_choice_is_called_learned_only_with_enough_counted_connects():
    tracker = _tracker(records={P1: (proxy.MIN_ATTEMPTS - 1, 0)})
    signals = {P1: -60}
    heard = {P1: 5.0}
    assert tracker.choose(heard, signals) == (P1, proxy.CHOICE_SIGNAL)
    tracker.record(P1, True)
    assert tracker.choose(heard, signals) == (P1, proxy.CHOICE_LEARNED)


def test_without_signal_readings_the_records_decide():
    tracker = _tracker(records={P1: (9, 11), P2: (2, 18), P3: (4, 16)})
    assert tracker.choose(HEARD) == (P1, proxy.CHOICE_LEARNED)


# ---------------------------------------------------------- forgetting ----
def test_old_connects_count_for_less():
    clock = Clock()
    tracker = _tracker(records={P1: (0, 40)}, clock=clock)
    signals = {P1: -60}
    before = tracker.expected(P1, -60)
    assert before < 0.1
    # The proxy was moved; two days later the bad record has all but gone and
    # the signal speaks again.
    clock.t += 48 * HOUR
    assert tracker.expected(P1, -60) > 0.5
    assert tracker.assigned({P1: 5.0}, signals) == (P1, proxy.CHOICE_SIGNAL)


def test_a_record_halves_in_one_half_life():
    clock = Clock()
    tracker = _tracker(records={P1: (30, 10)}, clock=clock)
    clock.t += proxy.HALF_LIFE_S
    record = tracker.summary()[P1]
    assert record["attempts"] == 20
    assert record["successes"] == 15
    assert record["success_rate"] == 0.75


def test_new_connects_are_added_to_what_is_left_of_the_old():
    clock = Clock()
    tracker = _tracker(records={P1: (8, 8)}, clock=clock)
    clock.t += proxy.HALF_LIFE_S
    tracker.record(P1, True)
    stats = tracker.stats[P1]
    assert (stats.successes, stats.failures) == (5.0, 4.0)
    assert stats.updated == clock.t


def test_a_record_that_has_faded_away_is_dropped():
    clock = Clock()
    tracker = _tracker(records={P1: (3, 3), P2: (20, 5)}, clock=clock)
    tracker.record(P2, True)
    clock.t += 10 * proxy.HALF_LIFE_S
    tracker.record(P2, True)
    assert P1 not in tracker.summary()
    assert P1 not in tracker.as_dict()


# ----------------------------------------------------------- exploring ----
def test_uncertain_scanners_are_tried_in_proportion_to_their_chances():
    # P1 has a long good record, P2 is new with a fair signal, P3 is hopeless.
    rng = random.Random(7)
    tracker = _tracker(sample=rng.betavariate, records={P1: (60, 20)})
    signals = {P1: -68, P2: -74, P3: -94}
    picks = [tracker.choose(HEARD, signals)[0] for _ in range(2000)]
    assert picks.count(P1) > 1500
    assert 20 < picks.count(P2) < 500
    assert picks.count(P3) < 10


def test_a_pick_other_than_the_standing_one_is_called_explore():
    # Dice that favour P2 although P1 has the better expected rate.
    def sample(a, b):
        return 0.9 if round(a + b) == proxy.PRIOR_WEIGHT else 0.5

    tracker = _tracker(sample=sample, records={P1: (15, 5)})
    signals = {P1: -68, P2: -74}
    heard = {P1: 5.0, P2: 5.0}
    assert tracker.choose(heard, signals) == (P2, proxy.CHOICE_EXPLORE)
    assert tracker.assigned(heard, signals) == (P1, proxy.CHOICE_LEARNED)


def test_scanner_that_went_quiet_is_not_used():
    tracker = _tracker(records={P1: (18, 2), P2: (8, 12)})
    heard = {P1: proxy.RECENT_ADVERT_S + 1, P2: 5.0}
    assert tracker.choose(heard) == (P2, proxy.CHOICE_LEARNED)


def test_home_assistant_chooses_when_no_scanner_hears_the_valve():
    tracker = _tracker(records={P1: (18, 2)})
    assert tracker.choose({}) == (None, proxy.CHOICE_HA)
    assert tracker.choose({P1: 600.0}) == (None, proxy.CHOICE_HA)


# ---------------------------------------------------------------- queue ----
def test_a_busy_scanner_gives_way_to_one_that_is_nearly_as_good():
    tracker = _tracker(records={P1: (16, 4), P2: (14, 6)})
    heard = {P1: 5.0, P2: 5.0}
    assert tracker.choose(heard, load={P1: 0, P2: 0})[0] == P1
    # Two connects already wait for P1: 0.72 / 2 loses to 0.63.
    assert tracker.choose(heard, load={P1: 2, P2: 0})[0] == P2


def test_a_busy_scanner_still_beats_a_poor_one():
    tracker = _tracker(records={P1: (18, 2), P2: (4, 16)})
    heard = {P1: 5.0, P2: 5.0}
    assert tracker.choose(heard, load={P1: 2, P2: 0})[0] == P1


def test_the_standing_assignment_ignores_the_queue():
    tracker = _tracker(records={P1: (16, 4), P2: (14, 6)})
    heard = {P1: 5.0, P2: 5.0}
    assert tracker.assigned(heard) == (P1, proxy.CHOICE_LEARNED)


# ----------------------------------------------------------------- lock ----
def test_locked_scanner_is_always_used():
    tracker = _tracker(locked=P2, records={P1: (18, 2), P2: (1, 19)})
    assert tracker.choose(HEARD, {P1: -50, P2: -95}) == (P2, proxy.CHOICE_LOCKED)
    assert tracker.choose({}) == (P2, proxy.CHOICE_LOCKED)
    assert tracker.assigned(HEARD) == (P2, proxy.CHOICE_LOCKED)


def test_auto_is_no_lock():
    tracker = _tracker(locked=proxy.AUTO, records={P1: (18, 2)})
    assert tracker.locked is None
    tracker.set_locked(P2)
    assert tracker.locked == P2
    tracker.set_locked(None)
    assert tracker.locked is None


# ---------------------------------------------------------------- bench ----
def test_scanner_rests_after_many_failures_in_a_row():
    clock = Clock()
    tracker = _tracker(records={P1: (80, 20), P2: (4, 16)}, clock=clock)
    for _ in range(proxy.MIN_CONSECUTIVE_FAILURES - 1):
        tracker.record(P1, False)
    assert not tracker.is_benched(P1)
    tracker.record(P1, False)
    assert tracker.is_benched(P1)
    # The best scanner rests: Home Assistant chooses, not the runner-up,
    # which would only be worn out in turn.
    assert tracker.choose(HEARD) == (None, proxy.CHOICE_HA)
    clock.t += proxy.BENCH_S
    assert not tracker.is_benched(P1)
    assert tracker.choose(HEARD)[0] == P1


def test_a_weak_scanner_gets_more_failures_before_it_rests():
    # At one success in four, eight failures in a row happen every tenth
    # time by chance alone.
    tracker = _tracker(records={P1: (25, 75)})
    for _ in range(proxy.MIN_CONSECUTIVE_FAILURES):
        tracker.record(P1, False)
    assert not tracker.is_benched(P1)
    for _ in range(proxy.MAX_CONSECUTIVE_FAILURES - proxy.MIN_CONSECUTIVE_FAILURES):
        tracker.record(P1, False)
    assert tracker.is_benched(P1)


def test_a_success_ends_the_run_of_failures():
    tracker = _tracker(records={P1: (80, 20)})
    for _ in range(proxy.MIN_CONSECUTIVE_FAILURES - 1):
        tracker.record(P1, False)
    tracker.record(P1, True)
    tracker.record(P1, False)
    assert not tracker.is_benched(P1)


def test_a_resting_scanner_that_is_not_the_best_is_just_skipped():
    tracker = _tracker(records={P1: (16, 4), P2: (80, 20)})
    for _ in range(proxy.MAX_CONSECUTIVE_FAILURES):
        tracker.record(P1, False)
    assert tracker.is_benched(P1)
    assert tracker.choose(HEARD)[0] == P2


# -------------------------------------------------------------- records ----
def test_record_remembers_the_latest_scanner_and_who_chose_it():
    tracker = _tracker()
    tracker.record(P1, True, proxy.CHOICE_EXPLORE)
    assert (tracker.last_source, tracker.last_choice) == (P1, proxy.CHOICE_EXPLORE)


def test_reset_forgets_every_record_but_keeps_the_lock():
    tracker = _tracker(locked=P2, records={P1: (18, 2), P2: (1, 19)})
    tracker.reset()
    assert tracker.stats == {}
    assert tracker.locked == P2


def test_records_survive_a_save_and_load():
    clock = Clock()
    tracker = _tracker(records={P1: (12.5, 3.25)}, clock=clock)
    for _ in range(3):
        tracker.record(P1, False)
    restored = _tracker(clock=clock)
    restored.load(tracker.as_dict())
    assert restored.summary() == tracker.summary()
    assert restored.stats[P1].consecutive_failures == 3


def test_records_from_before_the_forgetting_are_taken_over():
    # Saved by v1.3.0+benjagit.19 and earlier: attempts and successes.
    clock = Clock()
    tracker = _tracker(clock=clock)
    tracker.load(
        {P1: {"attempts": 40, "successes": 30, "consecutive_failures": 2,
              "last_failure": 5.0}}
    )
    stats = tracker.stats[P1]
    assert (stats.successes, stats.failures) == (30.0, 10.0)
    # They start to fade from now, not from an unknown time in the past.
    assert stats.updated == clock.t
    assert stats.consecutive_failures == 2


def test_unreadable_saved_records_are_skipped():
    tracker = _tracker()
    tracker.load("nonsense")
    tracker.load({P1: {"successes": "x"}, P2: None, P3: {"successes": 2, "failures": 1}})
    assert list(tracker.stats) == [P3]


def test_summary_shows_counts_rate_and_what_is_expected():
    tracker = _tracker(records={P1: (15, 5), P2: (0, 2)})
    summary = tracker.summary({P1: -68, P2: -90})
    assert summary[P1] == {
        "attempts": 20,
        "successes": 15,
        "success_rate": 0.75,
        "expected": round(tracker.expected(P1, -68), 2),
        "signal": -68,
        "benched": False,
        "mapped": True,
    }
    assert summary[P2]["mapped"] is False
    assert summary[P2]["expected"] < 0.1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
