"""Tests that a repeated failed poll still refreshes the entities.

Home Assistant's DataUpdateCoordinator skips its listeners when an update fails
and the previous one failed too. The connection sensor then kept showing the
first failure (consecutive_failures 1, the first error) for as long as the
eTRV stayed unreachable, which hid how many retries had run. The coordinator
now notifies its listeners itself on every failure after the first.

Home Assistant is stubbed, so this runs without it.

Run: python tests/test_failure_updates.py (or python -m pytest tests/).
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


class _Generic:
    def __class_getitem__(cls, item):
        return cls


class UpdateFailed(Exception):
    pass


class EtrvError(Exception):
    pass


if "danfoss_eco.coordinator" not in sys.modules:
    _stub("homeassistant")
    _stub("homeassistant.components", bluetooth=types.SimpleNamespace())
    _stub("homeassistant.config_entries", ConfigEntry=_Generic)
    _stub(
        "homeassistant.core",
        CALLBACK_TYPE=object,
        HomeAssistant=object,
        callback=lambda fn: fn,
    )
    _stub("homeassistant.helpers")
    _stub("homeassistant.helpers.debounce", Debouncer=object)
    _stub("homeassistant.helpers.event", async_call_later=lambda *a, **k: None)
    _stub("homeassistant.helpers.storage", Store=_Generic)
    _stub(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=_Generic,
        UpdateFailed=UpdateFailed,
    )
    _stub("homeassistant.util", dt=types.SimpleNamespace())

    pkg = types.ModuleType("danfoss_eco")
    pkg.__path__ = [_DIR]
    sys.modules["danfoss_eco"] = pkg
    _stub(
        "danfoss_eco.ble",
        EtrvClient=object,
        EtrvError=EtrvError,
        last_connectable_signal=lambda *a: (None, None),
    )

    def _load(name: str):
        spec = importlib.util.spec_from_file_location(
            f"danfoss_eco.{name}", os.path.join(_DIR, f"{name}.py")
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"danfoss_eco.{name}"] = module
        spec.loader.exec_module(module)
        return module

    _load("const")
    _load("pending")
    _load("protocol")
    _load("coordinator")

coordinator = sys.modules["danfoss_eco.coordinator"]
_EtrvError = coordinator.EtrvError
_UpdateFailed = coordinator.UpdateFailed


class _FailingClient:
    async def read_state(self, build_writes=None):
        raise _EtrvError("Not connected")


def _coordinator(previous_update_success: bool):
    c = object.__new__(coordinator.EtrvCoordinator)
    c.address = "00:04:2F:0F:09:A2"
    c.client = _FailingClient()
    c.pending = coordinator.PendingWrites()
    c.consecutive_failures = 0 if previous_update_success else 3
    c.last_error = None
    c.last_update_success = previous_update_success
    c.notified = 0
    c._expire_pending = lambda: None
    c._arm_retry = lambda: None

    def notify():
        c.notified += 1

    c.async_update_listeners = notify
    return c


def _poll(c) -> None:
    try:
        asyncio.run(c._async_update_data())
    except _UpdateFailed:
        return
    raise AssertionError("expected UpdateFailed")


def test_repeated_failure_notifies_listeners():
    c = _coordinator(previous_update_success=False)
    _poll(c)
    assert c.consecutive_failures == 4
    assert c.notified == 1


def test_first_failure_leaves_notifying_to_home_assistant():
    c = _coordinator(previous_update_success=True)
    _poll(c)
    assert c.consecutive_failures == 1
    assert c.notified == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
