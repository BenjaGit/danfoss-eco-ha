"""Tests that a placement test is started, fed, ended and kept.

Home Assistant is stubbed, so this runs without it.

Run: python -m pytest tests/.
"""

import asyncio
import importlib.util
import os
import sys
import types
from datetime import UTC, datetime, timedelta

_DIR = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "danfoss_eco"
)
P1 = "B8:27:EB:73:3A:1F"
A = "00:04:2F:00:00:01"


def _stub(name: str, **attrs) -> None:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module


class FakeStore:
    saved: dict = {}

    def __init__(self, hass, version, key):
        self.key = key

    async def async_load(self):
        return FakeStore.saved.get(self.key)

    async def async_save(self, data):
        FakeStore.saved[self.key] = data


timers: list = []


def _timer(hass, when, action):
    timers.append((when, action))
    return lambda: timers.remove((when, action))


def _load_manager():
    """Load the manager with stubs, then put back what other tests stubbed."""
    names = [
        "homeassistant", "homeassistant.const", "homeassistant.core",
        "homeassistant.helpers", "homeassistant.helpers.event",
        "homeassistant.helpers.storage", "homeassistant.loader",
        "danfoss_eco", "danfoss_eco.ble", "danfoss_eco.const",
        "danfoss_eco.placement", "danfoss_eco.placement_manager",
    ]
    saved = {name: sys.modules.get(name) for name in names}

    async def get_integration(hass, domain):
        return types.SimpleNamespace(version="1.3.0+test")

    _stub("homeassistant")
    _stub("homeassistant.const", EVENT_HOMEASSISTANT_STOP="stop")
    _stub("homeassistant.core", CALLBACK_TYPE=object, HomeAssistant=object,
          callback=lambda f: f)
    _stub("homeassistant.helpers")
    _stub("homeassistant.helpers.event", async_call_later=_timer,
          async_track_time_interval=_timer)
    _stub("homeassistant.helpers.storage", Store=FakeStore)
    _stub("homeassistant.loader", async_get_integration=get_integration)
    pkg = types.ModuleType("danfoss_eco")
    pkg.__path__ = [_DIR]
    sys.modules["danfoss_eco"] = pkg
    _stub("danfoss_eco.ble",
          connectable_scanners=lambda hass: {P1: f"bt-proxy-1 ({P1})"},
          scanner_signals=lambda hass, address: {P1: -64})
    _stub("danfoss_eco.const", DOMAIN="danfoss_eco")
    loaded = {}
    for mod in ("placement", "placement_manager"):
        spec = importlib.util.spec_from_file_location(
            f"danfoss_eco.{mod}", os.path.join(_DIR, f"{mod}.py")
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"danfoss_eco.{mod}"] = module
        spec.loader.exec_module(module)
        loaded[mod] = module
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module
    return loaded["placement_manager"]


manager_module = _load_manager()


class FakeStates:
    def __init__(self):
        self.states = {}

    def async_set(self, entity_id, state, attributes):
        self.states[entity_id] = (state, attributes)

    def async_remove(self, entity_id):
        self.states.pop(entity_id, None)


class FakeCoordinator:
    def __init__(self):
        self.address = A
        self.update_interval = timedelta(minutes=1)
        self.last_success = datetime.now(UTC)
        self.config_entry = types.SimpleNamespace(title="Radiator kontor 1")
        self.resets = 0

    async def async_reset_proxy_stats(self):
        self.resets += 1


def _hass(coordinator):
    return types.SimpleNamespace(
        data={},
        states=FakeStates(),
        bus=types.SimpleNamespace(async_listen_once=lambda *a: None),
        config_entries=types.SimpleNamespace(
            async_entries=lambda domain: [
                types.SimpleNamespace(runtime_data=coordinator)
            ]
        ),
    )


def _run(coro):
    return asyncio.run(coro)


def test_a_test_is_started_fed_ended_and_kept():
    async def run():
        FakeStore.saved.clear()
        timers.clear()
        coordinator = FakeCoordinator()
        hass = _hass(coordinator)
        manager = await manager_module.async_get_manager(hass)
        assert await manager_module.async_get_manager(hass) is manager
        status = manager_module.STATUS_ENTITY
        assert hass.states.states[status][0] == "idle"

        test_id = await manager.async_start("Rack", "off the rack", 30, False)
        state, attributes = hass.states.states[status]
        assert state == "running"
        assert attributes["name"] == "Rack" and attributes["minutes_left"] == 30
        assert coordinator.resets == 0
        # A sampler and the end of the test are scheduled.
        assert len(timers) == 2

        manager.connect(A, P1, True)
        manager.connect(A, P1, False)
        manager.read(A)
        manager._sample()
        assert hass.states.states[status][1]["connects"] == {
            "bt-proxy-1": {"successes": 1, "attempts": 2}
        }

        await manager.async_stop()
        assert timers == []
        assert hass.states.states[status][0] == "idle"
        state, result = hass.states.states[f"{status}_{test_id}"]
        assert state == "Rack"
        assert result["note"] == "off the rack"
        assert result["version"] == "1.3.0+test"
        assert result["poll_minutes"] == [1]
        assert result["proxy_stats_reset"] is False
        pair = result["thermostats"]["Radiator kontor 1"]["scanners"]["bt-proxy-1"]
        assert pair == {"attempts": 2, "successes": 1, "signal": -64, "heard_pct": 100}
        assert result["thermostats"]["Radiator kontor 1"]["reads"] == 1
        kept = {k: v for k, v in result.items() if k != "friendly_name"}
        assert FakeStore.saved[manager_module.STORE_KEY]["tests"] == [kept]
        return hass, test_id

    _run(run())


def test_kept_tests_come_back_after_a_restart_and_can_be_edited_and_deleted():
    async def run():
        FakeStore.saved.clear()
        timers.clear()
        first = _hass(FakeCoordinator())
        manager = await manager_module.async_get_manager(first)
        test_id = await manager.async_start("Rack", "", 30, False)
        await manager.async_stop(interrupted=True)

        hass = _hass(FakeCoordinator())
        manager = await manager_module.async_get_manager(hass)
        entity = f"{manager_module.STATUS_ENTITY}_{test_id}"
        assert hass.states.states[entity][1]["interrupted"] is True
        assert hass.states.states[manager_module.STATUS_ENTITY][1]["tests"] == 1

        assert await manager.async_set_note(test_id, "AP-Rack was off", None)
        assert hass.states.states[entity][1]["note"] == "AP-Rack was off"
        assert not await manager.async_set_note("nope", "x", None)

        assert await manager.async_delete(test_id)
        assert entity not in hass.states.states
        assert FakeStore.saved[manager_module.STORE_KEY]["tests"] == []
        assert not await manager.async_delete(test_id)

    _run(run())


def test_starting_a_test_ends_the_running_one_and_can_reset_the_proxy_choice():
    async def run():
        FakeStore.saved.clear()
        timers.clear()
        coordinator = FakeCoordinator()
        hass = _hass(coordinator)
        manager = await manager_module.async_get_manager(hass)
        await manager.async_start("First", "", 30, False)
        manager.run.started -= 1  # the next test starts a second later
        await manager.async_start("Second", "", 10, True)
        assert coordinator.resets == 1
        assert [t["name"] for t in manager.tests] == ["First"]
        assert manager.tests[0]["interrupted"] is True
        assert manager.run.name == "Second"
        assert len(timers) == 2
        await manager.async_stop()
        assert manager.tests[1]["proxy_stats_reset"] is True

    _run(run())
