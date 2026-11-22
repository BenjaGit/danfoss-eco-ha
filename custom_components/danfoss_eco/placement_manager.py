"""Runs placement tests and keeps their results (see placement.py).

One manager for the whole integration: a test covers every thermostat at
once. Results are kept in Home Assistant's storage and shown as states, so a
dashboard can list and compare them:

- sensor.danfoss_eco_placement_test: "running" or "idle", with the running
  test's name, note, end time and connects so far.
- sensor.danfoss_eco_placement_test_<id>: one per kept test, the test's name
  as state and its whole result as attributes.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_integration

from .ble import connectable_scanners, scanner_signals
from .const import DOMAIN
from .placement import PlacementTest, _iso

_LOGGER = logging.getLogger(__name__)

DATA_KEY = f"{DOMAIN}_placement"
STORE_KEY = f"{DOMAIN}.placement_tests"
STATUS_ENTITY = f"sensor.{DOMAIN}_placement_test"
SAMPLE_INTERVAL = timedelta(seconds=60)
# Older tests are dropped beyond this many.
MAX_TESTS = 200


def _short(name: str) -> str:
    """'bt-proxy-1 (B8:27:EB:..)' -> 'bt-proxy-1'."""
    return name.split(" (")[0]


class PlacementManager:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, 1, STORE_KEY)
        self.tests: list[dict[str, Any]] = []
        self.run: PlacementTest | None = None
        self._unsubs: list[CALLBACK_TYPE] = []

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        self.tests = [t for t in stored.get("tests", []) if isinstance(t, dict)]
        for test in self.tests:
            self._publish_test(test)
        self._publish_status()
        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._async_on_stop)

    async def _async_on_stop(self, _event) -> None:
        await self.async_stop(interrupted=True)

    def _coordinators(self) -> list:
        return [
            entry.runtime_data
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if getattr(entry, "runtime_data", None) is not None
        ]

    # ------------------------------------------------------------- start ----
    async def async_start(
        self, name: str, note: str, minutes: float, reset: bool
    ) -> str:
        """Start a test; a running one is ended and kept first."""
        await self.async_stop(interrupted=True)
        coordinators = self._coordinators()
        integration = await async_get_integration(self.hass, DOMAIN)
        if reset:
            for coordinator in coordinators:
                await coordinator.async_reset_proxy_stats()
        polls = sorted(
            {
                round(c.update_interval.total_seconds() / 60)
                for c in coordinators
                if c.update_interval is not None
            }
        )
        run = PlacementTest(
            name,
            note,
            time.time(),
            minutes * 60,
            {
                "version": str(integration.version),
                "poll_minutes": polls,
                "proxy_stats_reset": reset,
            },
        )
        for coordinator in coordinators:
            last = coordinator.last_success
            run.add_thermostat(
                coordinator.address,
                coordinator.config_entry.title,
                last.timestamp() if last is not None else None,
            )
        self.run = run
        self._unsubs = [
            async_track_time_interval(self.hass, self._sample, SAMPLE_INTERVAL),
            async_call_later(self.hass, minutes * 60, self._async_time_up),
        ]
        self._sample()
        _LOGGER.info("Placement test %s started: %s", run.test_id, name)
        return run.test_id

    async def _async_time_up(self, _now) -> None:
        await self.async_stop()

    # -------------------------------------------------------------- stop ----
    async def async_stop(self, *, interrupted: bool = False) -> None:
        """End the running test, if any, and keep its result."""
        run, self.run = self.run, None
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        if run is None:
            return
        names = {
            source: _short(name)
            for source, name in connectable_scanners(self.hass).items()
        }
        result = run.result(time.time(), names, interrupted=interrupted)
        self.tests.append(result)
        for dropped in self.tests[:-MAX_TESTS]:
            self.hass.states.async_remove(self._entity_id(dropped))
        self.tests = self.tests[-MAX_TESTS:]
        await self._async_save()
        self._publish_test(result)
        self._publish_status()
        _LOGGER.info("Placement test %s ended", run.test_id)

    async def async_delete(self, test_id: str) -> bool:
        for test in self.tests:
            if test.get("id") == test_id:
                self.tests.remove(test)
                self.hass.states.async_remove(self._entity_id(test))
                await self._async_save()
                self._publish_status()
                return True
        return False

    async def async_set_note(
        self, test_id: str, note: str | None, name: str | None
    ) -> bool:
        for test in self.tests:
            if test.get("id") == test_id:
                if note is not None:
                    test["note"] = note
                if name is not None:
                    test["name"] = name
                await self._async_save()
                self._publish_test(test)
                return True
        return False

    async def _async_save(self) -> None:
        await self._store.async_save({"tests": self.tests})

    # ----------------------------------------------------------- collect ----
    @callback
    def connect(self, address: str, source: str, success: bool) -> None:
        if self.run is not None:
            self.run.connect(address, source, success)

    @callback
    def read(self, address: str) -> None:
        if self.run is not None:
            self.run.read(address, time.time())

    @callback
    def _sample(self, _now=None) -> None:
        run = self.run
        if run is None:
            return
        scanners = connectable_scanners(self.hass)
        for address in run.valves:
            heard = scanner_signals(self.hass, address)
            run.signal(address, {source: heard.get(source) for source in scanners})
        self._publish_status()

    # ----------------------------------------------------------- publish ----
    def _entity_id(self, test: dict[str, Any]) -> str:
        return f"{STATUS_ENTITY}_{test.get('id')}"

    @callback
    def _publish_test(self, test: dict[str, Any]) -> None:
        self.hass.states.async_set(
            self._entity_id(test),
            str(test.get("name") or test.get("id"))[:255],
            {**test, "friendly_name": f"Placement test {test.get('name')}"},
        )

    @callback
    def _publish_status(self) -> None:
        run = self.run
        attributes: dict[str, Any] = {
            "friendly_name": "Danfoss Eco placement test",
            "tests": len(self.tests),
            "latest": self.tests[-1].get("id") if self.tests else None,
        }
        if run is not None:
            names = connectable_scanners(self.hass)
            now = time.time()
            attributes.update(
                {
                    "id": run.test_id,
                    "name": run.name,
                    "note": run.note,
                    "started": _iso(run.started),
                    "ends": _iso(run.ends),
                    "minutes_left": max(0, round((run.ends - now) / 60)),
                    "connects": {
                        _short(names.get(source, source)): {
                            "successes": total[0],
                            "attempts": total[1],
                        }
                        for source, total in sorted(run.progress().items())
                    },
                }
            )
        self.hass.states.async_set(
            STATUS_ENTITY, "running" if run is not None else "idle", attributes
        )


async def async_get_manager(hass: HomeAssistant) -> PlacementManager:
    """The one manager, created and loaded on first use."""
    manager = hass.data.get(DATA_KEY)
    if manager is None:
        manager = hass.data[DATA_KEY] = PlacementManager(hass)
        await manager.async_load()
    return manager
