"""Which Bluetooth proxy to connect a thermostat through.

Home Assistant picks the scanner with the best signal and a free slot. For
these valves that is often the wrong one: measured over 17 000 attempts, a
connect through a thermostat's best proxy succeeded 29 % of the time and
through any other only 8 %, and signal strength did not tell them apart.

So the outcome of every connect is counted per scanner, and the scanner with
the best record is used. Now and then Home Assistant chooses instead, which
keeps the counts of the other scanners alive. A proxy can also be locked in
the options.

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

# A scanner is only used if it heard a connectable advertisement this recently.
RECENT_ADVERT_S = 600
# A scanner needs this many counted connects before its record is trusted.
MIN_ATTEMPTS = 5
# Share of connects left to Home Assistant, so other scanners keep being tried.
EXPLORE_RATE = 0.1
# After this many failures in a row a scanner is rested for BENCH_S, then
# tried once more; another failure rests it again.
MAX_CONSECUTIVE_FAILURES = 3
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
        self.locked = locked if locked and locked != AUTO else None
        self.stats: dict[str, ProxyStats] = {}
        self._rng = rng
        self._now = now
        # The scanner the latest connect went through, and who chose it.
        self.last_source: str | None = None
        self.last_choice: str | None = None

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
        usable = [
            source
            for source, age in heard.items()
            if age <= RECENT_ADVERT_S and not self.is_benched(source)
        ]
        if self.locked is not None:
            if self.locked in usable:
                return self.locked, CHOICE_LOCKED
            return None, CHOICE_HA
        if self._rng() < EXPLORE_RATE:
            return None, CHOICE_HA
        proven = [
            source
            for source in usable
            if source in self.stats and self.stats[source].attempts >= MIN_ATTEMPTS
        ]
        if not proven:
            return None, CHOICE_HA
        best = max(
            proven, key=lambda s: (self.stats[s].rate, self.stats[s].attempts, s)
        )
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
            }
            for source, s in sorted(self.stats.items())
        }
