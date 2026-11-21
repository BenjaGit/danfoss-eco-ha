"""Which Bluetooth proxy to connect a thermostat through.

Home Assistant picks the scanner with the best signal and a free slot, anew
for every connect. Here the choice is kept per thermostat and built from two
things.

Signal. How strongly a scanner hears the thermostat says most of what there
is to know: measured over 53 thermostat-scanner pairs (2026-11-21), connects
succeeded 86 % of the time above -60 dBm, 49 % around -72 dBm, 20 % around
-87 dBm and 1 % below -90 dBm, and the strongest scanner was also the one
with the best record for 16 of 18 thermostats. The signal is there for every
scanner all the time, so a new or moved proxy is judged at once.

Counted connects. A scanner can hear a thermostat well and still connect
badly (one on a steel rack next to an access point did), so every connect is
counted per scanner and corrects what the signal promised. Old connects
count for less and less: a proxy that was moved is judged on what it does
now.

The scanner is then drawn by chance, weighted by how good each one may be
given what is known (Thompson sampling). A scanner with a long good record
is nearly always used; one that is promising but barely tried gets its
share of connects; a hopeless one almost none. A scanner with connects
already waiting gives way to one that is nearly as good. A proxy can also be
locked in the options; a locked thermostat never connects through anything
else.

Nothing here imports Home Assistant, so the rules can be tested on their own.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

AUTO = "auto"

CHOICE_LEARNED = "learned"
CHOICE_SIGNAL = "signal"
CHOICE_LOCKED = "locked"
CHOICE_HA = "ha"
CHOICE_EXPLORE = "explore"

# A scanner is only used if it heard a connectable advertisement this recently.
# A proxy can connect at once while its Bluetooth stack still knows the valve,
# which is 30 s after the last report, and waits up to 12 s for the next one
# otherwise. Reports come 1-6 times a minute, so 90 s keeps a scanner that
# still hears the valve and drops one that would only spend the wait.
RECENT_ADVERT_S = 90
# Share of connects that succeed at a signal strength (dBm), measured
# 2026-11-21 with four Raspberry Pi proxies and 18 valves. Between the points
# the rate is interpolated; beyond them it stays at the end value.
SIGNAL_RATES = (
    (-93.0, 0.03),
    (-87.5, 0.20),
    (-82.5, 0.33),
    (-77.5, 0.42),
    (-72.5, 0.49),
    (-65.0, 0.76),
    (-55.0, 0.86),
    (-45.0, 0.90),
)
# Expected rate of a scanner with no signal reading.
UNKNOWN_SIGNAL_RATE = 0.3
# The signal counts as this many connects. Low, so a handful of real connects
# outweighs it: the signal swings several dB from minute to minute and cannot
# see what disturbs a connect.
PRIOR_WEIGHT = 4.0
# A connect counts half after this long. With polls every ten minutes that is
# some 70 connects behind a thermostat's usual scanner.
HALF_LIFE_S = 8 * 3600
# The choice is called learned, not taken from the signal, from this many
# counted connects.
MIN_ATTEMPTS = 5
# A record this small has faded away and is dropped.
FORGET_BELOW = 0.05
# Each connect already waiting for a scanner takes this much off its score:
# with two waiting, a scanner at 0.8 gives way to a free one above 0.4.
LOAD_WEIGHT = 0.5
# A scanner rests for BENCH_S after a run of failures that would happen by
# chance less than one time in fifty at its expected rate, but no fewer than
# MIN and no more than MAX: 8 in a row are rare for a scanner at 0.7 and
# ordinary for one at 0.25. After the rest it is tried once more; another
# failure rests it again.
BENCH_CHANCE = 0.02
MIN_CONSECUTIVE_FAILURES = 8
MAX_CONSECUTIVE_FAILURES = 16
BENCH_S = 1800


def prior_rate(rssi: float | None) -> float:
    """Share of connects expected to succeed at this signal strength."""
    if rssi is None:
        return UNKNOWN_SIGNAL_RATE
    if rssi <= SIGNAL_RATES[0][0]:
        return SIGNAL_RATES[0][1]
    for (low, low_rate), (high, high_rate) in zip(SIGNAL_RATES, SIGNAL_RATES[1:]):
        if rssi <= high:
            return low_rate + (high_rate - low_rate) * (rssi - low) / (high - low)
    return SIGNAL_RATES[-1][1]


@dataclass
class ProxyStats:
    """Connect record of one scanner for one thermostat.

    The counts are as of `updated` and fade from then on; read them through
    `faded`.
    """

    successes: float = 0.0
    failures: float = 0.0
    updated: float = 0.0
    consecutive_failures: int = 0
    last_failure: float = 0.0

    def faded(self, now: float) -> tuple[float, float]:
        """Successes and failures, each worth less the older it is."""
        keep = 0.5 ** (max(0.0, now - self.updated) / HALF_LIFE_S)
        return self.successes * keep, self.failures * keep


class ProxyTracker:
    """Per-thermostat connect records and the choice that follows from them."""

    def __init__(
        self,
        locked: str | None = None,
        *,
        sample: Callable[[float, float], float] = random.betavariate,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.set_locked(locked)
        self.stats: dict[str, ProxyStats] = {}
        self._sample = sample
        self._now = now
        # The scanner the latest connect went through, and who chose it.
        self.last_source: str | None = None
        self.last_choice: str | None = None

    def set_locked(self, locked: str | None) -> None:
        self.locked = locked if locked and locked != AUTO else None

    # ------------------------------------------------------------ belief ----
    def _belief(self, source: str, rssi: float | None) -> tuple[float, float]:
        """What is known about a scanner, as successes and failures.

        The signal stands in for PRIOR_WEIGHT connects; the counted ones are
        added to it.
        """
        prior = prior_rate(rssi)
        successes, failures = self._counts(source)
        return prior * PRIOR_WEIGHT + successes, (1 - prior) * PRIOR_WEIGHT + failures

    def _counts(self, source: str) -> tuple[float, float]:
        stats = self.stats.get(source)
        return stats.faded(self._now()) if stats is not None else (0.0, 0.0)

    def expected(self, source: str, rssi: float | None = None) -> float:
        """Share of connects through this scanner expected to succeed."""
        good, bad = self._belief(source, rssi)
        return good / (good + bad)

    def is_mapped(self, source: str) -> bool:
        """Whether enough connects are counted to speak of a learned choice."""
        return sum(self._counts(source)) >= MIN_ATTEMPTS

    def is_benched(self, source: str, rssi: float | None = None) -> bool:
        stats = self.stats.get(source)
        if stats is None or stats.consecutive_failures < MIN_CONSECUTIVE_FAILURES:
            return False
        if self._now() - stats.last_failure >= BENCH_S:
            return False
        rate = min(0.95, max(0.05, self.expected(source, rssi)))
        unlikely = math.ceil(math.log(BENCH_CHANCE) / math.log(1 - rate))
        limit = min(
            MAX_CONSECUTIVE_FAILURES, max(MIN_CONSECUTIVE_FAILURES, unlikely)
        )
        return stats.consecutive_failures >= limit

    # ------------------------------------------------------------ choice ----
    def choose(
        self,
        heard: Mapping[str, float],
        signals: Mapping[str, float] | None = None,
        load: Mapping[str, int] | None = None,
    ) -> tuple[str | None, str]:
        """Pick the scanner for the next connect.

        `heard` maps each connectable scanner to the age in seconds of its
        latest advertisement from the thermostat, `signals` to the strength
        of that advertisement, `load` to the connects it has in hand or
        waiting. Returns (scanner, who chose it); the scanner is None when
        Home Assistant is to choose.
        """
        signals = signals or {}
        standing, by = self.assigned(heard, signals)
        if standing is None or by == CHOICE_LOCKED:
            return standing, by
        load = load or {}
        best: tuple[float, str] | None = None
        for source, age in heard.items():
            if age > RECENT_ADVERT_S or self.is_benched(source, signals.get(source)):
                continue
            drawn = self._sample(*self._belief(source, signals.get(source)))
            score = drawn / (1 + LOAD_WEIGHT * load.get(source, 0))
            if best is None or (score, source) > best:
                best = (score, source)
        if best is None or best[1] == standing:
            return standing, by
        return best[1], CHOICE_EXPLORE

    def assigned(
        self, heard: Mapping[str, float], signals: Mapping[str, float] | None = None
    ) -> tuple[str | None, str]:
        """The scanner the thermostat is assigned to right now.

        The one expected to do best, without the chance in choose and
        without regard to who is waiting.
        """
        # A lock is absolute. If the locked scanner cannot reach the
        # thermostat the connect fails; it never moves to another scanner,
        # or the lock would mean no more than "automatic".
        if self.locked is not None:
            return self.locked, CHOICE_LOCKED
        signals = signals or {}
        recent = [source for source, age in heard.items() if age <= RECENT_ADVERT_S]
        if not recent:
            return None, CHOICE_HA
        best = max(recent, key=lambda s: (self.expected(s, signals.get(s)), s))
        # A resting best scanner hands the choice to Home Assistant, not to
        # the runner-up. Seen on a valve with records 13/49, 1/49 and 0/48:
        # the runner-ups were tried in turn until all three were resting.
        if self.is_benched(best, signals.get(best)):
            return None, CHOICE_HA
        return best, CHOICE_LEARNED if self.is_mapped(best) else CHOICE_SIGNAL

    # ----------------------------------------------------------- records ----
    def record(self, source: str, success: bool, choice: str = CHOICE_HA) -> None:
        """Count one connect through `source`."""
        now = self._now()
        stats = self.stats.setdefault(source, ProxyStats(updated=now))
        stats.successes, stats.failures = stats.faded(now)
        stats.updated = now
        if success:
            stats.successes += 1
            stats.consecutive_failures = 0
        else:
            stats.failures += 1
            stats.consecutive_failures += 1
            stats.last_failure = now
        self.last_source = source
        self.last_choice = choice

    def reset(self) -> None:
        """Forget every counted connect, e.g. after proxies were moved."""
        self.stats.clear()

    def _kept(self) -> dict[str, ProxyStats]:
        """Records that have not faded away, sorted by scanner."""
        return {
            source: stats
            for source, stats in sorted(self.stats.items())
            if sum(self._counts(source)) >= FORGET_BELOW or self.is_benched(source)
        }

    # ------------------------------------------------------- persistence ----
    def as_dict(self) -> dict[str, Any]:
        return {
            source: {
                "successes": s.successes,
                "failures": s.failures,
                "updated": s.updated,
                "consecutive_failures": s.consecutive_failures,
                "last_failure": s.last_failure,
            }
            for source, s in self._kept().items()
        }

    def load(self, raw: Any) -> None:
        """Restore records saved by as_dict; anything unreadable is skipped.

        Up to v1.3.0+benjagit.19 a record was attempts and successes without
        a time. Those are taken over and fade from now on.
        """
        if not isinstance(raw, dict):
            return
        now = self._now()
        for source, item in raw.items():
            try:
                successes = max(0.0, float(item["successes"]))
                if "failures" in item:
                    failures = max(0.0, float(item["failures"]))
                else:
                    failures = max(0.0, float(item["attempts"]) - successes)
                self.stats[str(source)] = ProxyStats(
                    successes=successes,
                    failures=failures,
                    updated=float(item.get("updated", now)),
                    consecutive_failures=max(
                        0, int(item.get("consecutive_failures", 0))
                    ),
                    last_failure=float(item.get("last_failure", 0.0)),
                )
            except (KeyError, TypeError, ValueError, AttributeError):
                continue

    def summary(
        self, signals: Mapping[str, float] | None = None
    ) -> dict[str, dict[str, Any]]:
        """Record per scanner, for the connection sensor and diagnostics.

        The counts are the faded ones, rounded: connects of the last hours
        in full, older ones in part.
        """
        signals = signals or {}
        summary: dict[str, dict[str, Any]] = {}
        for source in self._kept():
            successes, failures = self._counts(source)
            attempts = successes + failures
            rssi = signals.get(source)
            summary[source] = {
                "attempts": round(attempts),
                "successes": min(round(attempts), round(successes)),
                "success_rate": round(successes / attempts, 2) if attempts else None,
                "expected": round(self.expected(source, rssi), 2),
                "signal": rssi,
                "benched": self.is_benched(source, rssi),
                "mapped": self.is_mapped(source),
            }
        return summary
