"""Tests that config entry setup does not wait for the first BLE poll.

With many thermostats behind one shared BLE lock, awaiting a poll in
async_setup_entry kept Home Assistant in "starting" until bootstrap gave up
after 300 s. Setup must finish on the cached reading and poll once Home
Assistant has started.

Home Assistant and voluptuous are stubbed, so this runs without either.

Run: python tests/test_setup.py (or python -m pytest tests/).
"""

import asyncio
import importlib.util
import os
import sys
import types

_DIR = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "danfoss_eco"
)


def _stub(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    return module


def _anything(*args, **kwargs):
    return _anything


started_callbacks = []


def async_at_started(hass, at_start_cb):
    started_callbacks.append(at_start_cb)
    return lambda: None


_stub(
    "voluptuous",
    Schema=_anything,
    Required=_anything,
    Optional=_anything,
    All=_anything,
    Coerce=_anything,
    Range=_anything,
)
_stub("homeassistant")
_stub("homeassistant.components", bluetooth=types.SimpleNamespace(
    async_register_callback=lambda *a, **k: (lambda: None),
    BluetoothScanningMode=types.SimpleNamespace(PASSIVE="passive"),
))
_stub("homeassistant.config_entries", ConfigEntry=types.SimpleNamespace(
    __class_getitem__=classmethod(lambda cls, item: cls)
))
_stub(
    "homeassistant.const",
    Platform=types.SimpleNamespace(
        BINARY_SENSOR="binary_sensor",
        BUTTON="button",
        CLIMATE="climate",
        NUMBER="number",
        SENSOR="sensor",
        SWITCH="switch",
    ),
)
_stub(
    "homeassistant.core",
    HomeAssistant=object,
    ServiceCall=object,
    callback=lambda fn: fn,
)
_stub("homeassistant.helpers")
_stub(
    "homeassistant.helpers.config_validation",
    config_entry_only_config_schema=_anything,
    string=_anything,
    datetime=_anything,
    ensure_list=_anything,
)
_stub("homeassistant.helpers.device_registry")
_stub("homeassistant.helpers.start", async_at_started=async_at_started)
_stub("homeassistant.util", dt=types.SimpleNamespace())
sys.modules["homeassistant.helpers"].config_validation = sys.modules[
    "homeassistant.helpers.config_validation"
]
sys.modules["homeassistant.helpers"].device_registry = sys.modules[
    "homeassistant.helpers.device_registry"
]


class FakeCoordinator:
    """Coordinator whose poll never returns, like a thermostat out of range."""

    instances = []

    def __init__(self, hass, entry):
        self.address = "00:04:2F:00:00:00"
        self.cache_loaded = False
        self.refresh_started = False
        FakeCoordinator.instances.append(self)

    async def async_load_cache(self):
        self.cache_loaded = True

    async def async_refresh(self):
        self.refresh_started = True
        await asyncio.Event().wait()

    def async_device_seen(self, *args):
        pass

    def async_cancel_retry(self):
        pass


pkg = types.ModuleType("danfoss_eco")
pkg.__path__ = [_DIR]
sys.modules["danfoss_eco"] = pkg
_stub("danfoss_eco.ble", EtrvError=Exception)
_stub("danfoss_eco.coordinator", EtrvCoordinator=FakeCoordinator)


def _load(mod: str, name: str):
    spec = importlib.util.spec_from_file_location(
        f"danfoss_eco.{name}", os.path.join(_DIR, f"{mod}.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"danfoss_eco.{name}"] = module
    spec.loader.exec_module(module)
    return module


_load("const", "const")
integration = _load("__init__", "__init__")


class FakeEntry:
    def __init__(self):
        self.entry_id = "entry"
        self.runtime_data = None
        self.background_tasks = []

    def async_on_unload(self, func):
        pass

    def add_update_listener(self, listener):
        return lambda: None

    def async_create_background_task(self, hass, coro, name):
        self.background_tasks.append((asyncio.ensure_future(coro), name))


def _hass(forwarded: list):
    async def forward(entry, platforms):
        forwarded.append(entry)

    return types.SimpleNamespace(
        config_entries=types.SimpleNamespace(async_forward_entry_setups=forward),
        services=types.SimpleNamespace(has_service=lambda *a: True),
    )


def test_setup_does_not_wait_for_first_poll():
    async def run():
        started_callbacks.clear()
        FakeCoordinator.instances.clear()
        forwarded = []
        hass = _hass(forwarded)
        entry = FakeEntry()

        ok = await asyncio.wait_for(integration.async_setup_entry(hass, entry), 1)

        coordinator = FakeCoordinator.instances[0]
        assert ok is True
        assert coordinator.cache_loaded
        assert forwarded == [entry]
        assert not coordinator.refresh_started
        assert entry.background_tasks == []
        return hass, entry, coordinator

    asyncio.run(run())


def test_first_poll_runs_in_background_once_started():
    async def run():
        started_callbacks.clear()
        FakeCoordinator.instances.clear()
        hass = _hass([])
        entry = FakeEntry()
        await asyncio.wait_for(integration.async_setup_entry(hass, entry), 1)
        coordinator = FakeCoordinator.instances[0]

        assert len(started_callbacks) == 1
        started_callbacks[0](hass)
        await asyncio.sleep(0)

        assert coordinator.refresh_started
        assert len(entry.background_tasks) == 1
        task, name = entry.background_tasks[0]
        assert coordinator.address in name
        task.cancel()

    asyncio.run(run())


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("all good")
