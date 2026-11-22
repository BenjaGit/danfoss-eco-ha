"""A placement test: how well the proxies reach the thermostats for a while.

Moving a proxy, switching an access point off or adding a proxy changes how
the thermostats are reached. A test measures one such arrangement over a set
time and keeps the result with a name and a note, so arrangements can be
compared later instead of remembered.

For every thermostat and scanner it collects the signal strength and how
much of the time the scanner heard the thermostat, the connects and how many
succeeded, and per thermostat how old its latest reading was.

Nothing here imports Home Assistant, so the sums can be tested on their own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# A reading older than this counts as stale.
STALE_AFTER_S = 300.0


@dataclass
class _Pair:
    """One thermostat as one scanner reaches it."""

    attempts: int = 0
    successes: int = 0
    samples: int = 0
    heard: int = 0
    rssi_sum: float = 0.0


@dataclass
class _Valve:
    name: str
    # Time of the latest successful read before the test, if known.
    last_read: float | None
    reads: list[float] = field(default_factory=list)
    pairs: dict[str, _Pair] = field(default_factory=dict)


def _iso(when: float) -> str:
    return datetime.fromtimestamp(when, UTC).isoformat(timespec="seconds")


class PlacementTest:
    """Numbers collected while one test runs. Times are Unix seconds."""

    def __init__(
        self,
        name: str,
        note: str,
        started: float,
        duration_s: float,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.note = note
        self.started = started
        self.duration_s = duration_s
        self.meta = dict(meta or {})
        self.valves: dict[str, _Valve] = {}

    @property
    def test_id(self) -> str:
        return datetime.fromtimestamp(self.started, UTC).strftime("%Y%m%dt%H%M%S")

    @property
    def ends(self) -> float:
        return self.started + self.duration_s

    # ----------------------------------------------------------- collect ----
    def add_thermostat(
        self, address: str, name: str, last_read: float | None = None
    ) -> None:
        self.valves.setdefault(address, _Valve(name=name, last_read=last_read))

    def _pair(self, address: str, source: str) -> _Pair | None:
        valve = self.valves.get(address)
        return None if valve is None else valve.pairs.setdefault(source, _Pair())

    def connect(self, address: str, source: str, success: bool) -> None:
        """Count one connect to `address` through `source`."""
        pair = self._pair(address, source)
        if pair is not None:
            pair.attempts += 1
            pair.successes += int(success)

    def signal(self, address: str, readings: Mapping[str, float | None]) -> None:
        """One sample of every scanner: its RSSI, or None if it hears nothing."""
        for source, rssi in readings.items():
            pair = self._pair(address, source)
            if pair is None:
                continue
            pair.samples += 1
            if rssi is not None:
                pair.heard += 1
                pair.rssi_sum += rssi

    def read(self, address: str, when: float) -> None:
        """The thermostat was read successfully at `when`."""
        valve = self.valves.get(address)
        if valve is not None and when >= self.started:
            valve.reads.append(when)

    # ------------------------------------------------------------ result ----
    def _ages(self, valve: _Valve, end: float) -> tuple[float, float, float]:
        """Mean age of the latest reading, share of time stale, longest gap.

        Until the first read of the test the age runs from the last read
        before it, or from the start of the test when that is unknown.
        """
        last = valve.last_read if valve.last_read is not None else self.started
        last = min(last, self.started)
        area = stale = longest = 0.0
        at = self.started
        for when in [*sorted(valve.reads), end]:
            when = min(when, end)
            if when > at:
                area += ((when - last) ** 2 - (at - last) ** 2) / 2
                stale += max(0.0, when - max(at, last + STALE_AFTER_S))
                longest = max(longest, when - last)
            at, last = when, when
        span = max(1.0, end - self.started)
        return area / span, stale / span, longest

    def progress(self) -> dict[str, list[int]]:
        """Successes and attempts per scanner so far."""
        totals: dict[str, list[int]] = {}
        for valve in self.valves.values():
            for source, pair in valve.pairs.items():
                total = totals.setdefault(source, [0, 0])
                total[0] += pair.successes
                total[1] += pair.attempts
        return totals

    def result(
        self,
        now: float,
        scanner_names: Mapping[str, str] | None = None,
        *,
        interrupted: bool = False,
    ) -> dict[str, Any]:
        """Everything worth keeping about the test, ready to store."""
        end = min(now, self.ends) if not interrupted else now
        end = max(end, self.started)
        names = dict(scanner_names or {})
        hours = max(1.0, end - self.started) / 3600
        thermostats: dict[str, Any] = {}
        totals: dict[str, list[int]] = {}
        ages: list[float] = []
        stales: list[float] = []
        rates: list[float] = []
        for address, valve in sorted(self.valves.items(), key=lambda i: i[1].name):
            mean_age, stale, longest = self._ages(valve, end)
            reads = sum(1 for when in valve.reads if when <= end)
            ages.append(mean_age)
            stales.append(stale)
            rates.append(reads / hours)
            scanners: dict[str, Any] = {}
            for source, pair in sorted(valve.pairs.items()):
                total = totals.setdefault(source, [0, 0])
                total[0] += pair.successes
                total[1] += pair.attempts
                scanners[names.get(source, source)] = {
                    "attempts": pair.attempts,
                    "successes": pair.successes,
                    "signal": round(pair.rssi_sum / pair.heard) if pair.heard else None,
                    "heard_pct": (
                        round(100 * pair.heard / pair.samples) if pair.samples else None
                    ),
                }
            thermostats[valve.name] = {
                "address": address,
                "reads": reads,
                "reads_per_hour": round(reads / hours, 1),
                "mean_age_min": round(mean_age / 60, 1),
                "stale_pct": round(100 * stale),
                "longest_gap_min": round(longest / 60, 1),
                "scanners": scanners,
            }
        count = max(1, len(ages))
        return {
            "id": self.test_id,
            "name": self.name,
            "note": self.note,
            "started": _iso(self.started),
            "ended": _iso(end),
            "minutes": round((end - self.started) / 60),
            "interrupted": interrupted,
            **self.meta,
            "summary": {
                "thermostats": len(self.valves),
                "reads_per_hour": round(sum(rates) / count, 1),
                "mean_age_min": round(sum(ages) / count / 60, 1),
                "stale_pct": round(100 * sum(stales) / count),
            },
            "scanners": {
                names.get(source, source): {
                    "address": source,
                    "attempts": total[1],
                    "successes": total[0],
                    "rate_pct": round(100 * total[0] / total[1]) if total[1] else None,
                }
                for source, total in sorted(totals.items())
            },
            "thermostats": thermostats,
        }
