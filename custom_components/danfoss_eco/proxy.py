"""Which Bluetooth proxy to connect a thermostat through.

Home Assistant picks the scanner with the best signal and a free slot. For
these valves that is often the wrong one: measured over 17 000 attempts, a
connect through a thermostat's best proxy succeeded 29 % of the time and
through any other only 8 %, and signal strength did not tell them apart.

So the outcome of every connect is counted per scanner, and the scanner with
the best record is used. Some connects go to the scanner with the fewest
counted attempts instead: half of them while a scanner is still unmapped for
the thermostat, one in ten after that, which keeps every record current. A proxy can also be locked in
the options; a locked thermostat never connects through anything else.

Nothing here imports Home Assistant, so the rules can be tested on their own.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

AUTO = "auto"

CHOICE_LEARNED = "learned"
CHOICE_LOCKED = "locked"
CHOICE_HA = "ha"
CHOICE_EXPLORE = "explore"

# A scanner is only used if it heard a connectable advertisement this recently.
# A proxy can connect at once while its Bluetooth stack still knows the valve,
# which is 30 s after the last report, and waits up to 12 s for the next one
# otherwise. Reports come 1-6 times a minute, so 90 s keeps a scanner that
# still hears the valve and drops one that would only spend the wait.
RECENT_ADVERT_S = 90
# A scanner needs this many counted connects before its record is trusted.
MIN_ATTEMPTS = 5
# Share of connects that go to the scanner with the fewest counted attempts,
# so every scanner keeps being measured.
EXPLORE_RATE = 0.1
# While a scanner that hears the thermostat is still unmapped, this share goes
# to the least-tried unmapped scanner instead. A scanner is mapped after
# MAP_ATTEMPTS connects, or after MAP_GIVE_UP connects without one success:
# good pairs connect 30-45 % of the time, so 10 failures in a row all but
# rule one out.
MAP_RATE = 0.5
MAP_ATTEMPTS = 20
MAP_GIVE_UP = 10
# After this many failures in a row a scanner is rested for BENCH_S, then
# tried once more; another failure rests it again. Even a thermostat's best
# proxy only connects about 3 times in 10, so 3 or 4 failures in a row are
# ordinary; 8 in a row happen by chance about 1 time in 17.
MAX_CONSECUTIVE_FAILURES = 8
BENCH_S = 1800
# Halve the counts when they get this large, so the record follows a proxy
# that was moved instead of averaging over its whole life.
DECAY_AT = 200


@dataclass
class ProxyStats:
    """Connect record of one scanner for one thermostat."""

    attempts: int = 0
    successes: int = 0
    consecutive_failures: int = 0
    last_failure: float = 0.0

    @property
    def rate(self) -> float:
        """Success rate with one imagined success and one imagined failure.

        The two extra attempts keep a scanner with 1 of 1 from outranking one
        with 40 of 100.
        """
        return (self.successes + 1) / (self.attempts + 2)


class ProxyTracker:
    """Per-thermostat connect records and the choice that follows from them."""

    def __init__(
        self,
        locked: str | None = None,
        *,
        rng: Callable[[], float] = random.random,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.set_locked(locked)
        self.stats: dict[str, ProxyStats] = {}
        self._rng = rng
        self._now = now
        # The scanner the latest connect went through, and who chose it.
        self.last_source: str | None = None
        self.last_choice: str | None = None

    def set_locked(self, locked: str | None) -> None:
        self.locked = locked if locked and locked != AUTO else None

    # ------------------------------------------------------------ choice ----
    def is_benched(self, source: str) -> bool:
        stats = self.stats.get(source)
        if stats is None or stats.consecutive_failures < MAX_CONSECUTIVE_FAILURES:
            return False
        return self._now() - stats.last_failure < BENCH_S

    def choose(self, heard: Mapping[str, float]) -> tuple[str | None, str]:
        """Pick the scanner for the next connect.

        `heard` maps each connectable scanner to the age in seconds of its
        latest advertisement from the thermostat. Returns (scanner, who chose
        it); the scanner is None when Home Assistant is to choose.
        """
        if self.locked is not None:
            return self.locked, CHOICE_LOCKED
        candidates = [
            source
            for source, age in heard.items()
            if age <= RECENT_ADVERT_S and not self.is_benched(source)
        ]
        unmapped = [source for source in candidates if not self.is_mapped(source)]
        if self._rng() < (MAP_RATE if unmapped else EXPLORE_RATE):
            pool = unmapped or candidates
            if pool:
                return min(pool, key=lambda s: (self._attempts(s), s)), CHOICE_EXPLORE
            return None, CHOICE_HA
        return self.assigned(heard)

    def _attempts(self, source: str) -> int:
        stats = self.stats.get(source)
        return stats.attempts if stats is not None else 0

    def is_mapped(self, source: str) -> bool:
        """Whether this scanner has been tried enough to be judged."""
        stats = self.stats.get(source)
        if stats is None:
            return False
        if stats.attempts >= MAP_ATTEMPTS:
            return True
        return stats.attempts >= MAP_GIVE_UP and stats.successes == 0

    def assigned(self, heard: Mapping[str, float]) -> tuple[str | None, str]:
        """The scanner the thermostat is assigned to right now.

        Same as choose, minus the connects spent on measuring other scanners.
        """
        # A lock is absolute. If the locked scanner cannot reach the
        # thermostat the connect fails; it never moves to another scanner,
        # or the lock would mean no more than "automatic".
        if self.locked is not None:
            return self.locked, CHOICE_LOCKED
        recent = [source for source, age in heard.items() if age <= RECENT_ADVERT_S]
        proven = [
            source
            for source in recent
            if source in self.stats and self.stats[source].attempts >= MIN_ATTEMPTS
        ]
        if not proven:
            return None, CHOICE_HA
        best = max(
            proven, key=lambda s: (self.stats[s].rate, self.stats[s].attempts, s)
        )
        # A resting best scanner hands the choice to Home Assistant, not to
        # the runner-up. Seen on a valve with records 13/49, 1/49 and 0/48:
        # the runner-ups were tried in turn until all three were resting.
        if self.is_benched(best):
            return None, CHOICE_HA
        return best, CHOICE_LEARNED

    # ----------------------------------------------------------- records ----
    def record(self, source: str, success: bool, choice: str = CHOICE_HA) -> None:
        """Count one connect through `source`."""
        stats = self.stats.setdefault(source, ProxyStats())
        stats.attempts += 1
        if success:
            stats.successes += 1
            stats.consecutive_failures = 0
        else:
            stats.consecutive_failures += 1
            stats.last_failure = self._now()
        if stats.attempts > DECAY_AT:
            stats.attempts //= 2
            stats.successes //= 2
        self.last_source = source
        self.last_choice = choice

    # ------------------------------------------------------- persistence ----
    def as_dict(self) -> dict[str, Any]:
        return {
            source: {
                "attempts": s.attempts,
                "successes": s.successes,
                "consecutive_failures": s.consecutive_failures,
                "last_failure": s.last_failure,
            }
            for source, s in self.stats.items()
        }

    def load(self, raw: Any) -> None:
        """Restore records saved by as_dict; anything unreadable is skipped."""
        if not isinstance(raw, dict):
            return
        for source, item in raw.items():
            try:
                attempts = max(0, int(item["attempts"]))
                self.stats[str(source)] = ProxyStats(
                    attempts=attempts,
                    successes=min(attempts, max(0, int(item["successes"]))),
                    consecutive_failures=max(
                        0, int(item.get("consecutive_failures", 0))
                    ),
                    last_failure=float(item.get("last_failure", 0.0)),
                )
            except (KeyError, TypeError, ValueError, AttributeError):
                continue

    def summary(self) -> dict[str, dict[str, Any]]:
        """Record per scanner, for the connection sensor and diagnostics."""
        return {
            source: {
                "attempts": s.attempts,
                "successes": s.successes,
                "success_rate": (
                    round(s.successes / s.attempts, 2) if s.attempts else None
                ),
                "benched": self.is_benched(source),
                "mapped": self.is_mapped(source),
            }
            for source, s in sorted(self.stats.items())
        }
