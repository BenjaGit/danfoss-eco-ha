"""Tests that a clock sync also clears the E10 "invalid time" flag.

The device keeps E10 raised after a battery swap even once its clock is right.
The official app clears it by writing the error characteristic right after the
time (captured with an Android btsnoop log: time write, then eight zero bytes
to UUID_ERRORS). The integration does the same on every clock sync, but only
clears E10 and leaves E9/E14/E15 as the device reported them.

Home Assistant is stubbed, so this runs without it.

Run: python tests/test_clock_sync.py (or python -m pytest tests/).
"""

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
    UpdateFailed=Exception,
)
_stub("homeassistant.util", dt=types.SimpleNamespace())

pkg = types.ModuleType("danfoss_eco")
pkg.__path__ = [_DIR]
sys.modules["danfoss_eco"] = pkg
_stub(
    "danfoss_eco.ble",
    EtrvClient=object,
    EtrvError=Exception,
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


const = _load("const")
_load("pending")
protocol = _load("protocol")
coordinator = _load("coordinator")

# Decrypted payloads from a real device (Kælder Trappe, 2026-10-18).
ERRORS_E10 = bytes.fromhex("0200000000000000")
SETTINGS = bytes.fromhex("530c380c001e00000000000000000000")
TEMPERATURE = bytes.fromhex("2424000000000000")
E10_AND_E14 = bytes.fromhex("2200000000000000")


def _raw(errors: bytes) -> dict:
    return {"errors": errors, "settings": SETTINGS, "temperature": TEMPERATURE}


def _coordinator(sync_time: bool):
    c = object.__new__(coordinator.EtrvCoordinator)
    c.address = "00:04:2F:6A:A5:9A"
    c.pending = coordinator.PendingWrites()
    if sync_time:
        c.pending.queue_sync_time()
    return c


def test_without_clears_only_the_named_flag():
    errors = protocol.Errors.parse(E10_AND_E14)
    assert errors.without("e10_invalid_time") == bytes.fromhex("2000000000000000")


def test_without_e10_matches_what_the_app_writes():
    errors = protocol.Errors.parse(ERRORS_E10)
    assert errors.without("e10_invalid_time") == bytes(8)


def test_time_sync_clears_e10_right_after_the_time():
    ops = _coordinator(sync_time=True)._writes_for(_raw(ERRORS_E10))
    assert [uuid for uuid, _ in ops] == [const.UUID_CURRENT_TIME, const.UUID_ERRORS]
    assert ops[1][1] == bytes(8)


def test_time_sync_keeps_other_flags():
    ops = _coordinator(sync_time=True)._writes_for(_raw(E10_AND_E14))
    assert dict(ops)[const.UUID_ERRORS] == bytes.fromhex("2000000000000000")


def test_time_sync_without_e10_does_not_touch_errors():
    ops = _coordinator(sync_time=True)._writes_for(_raw(bytes(8)))
    assert [uuid for uuid, _ in ops] == [const.UUID_CURRENT_TIME]


def test_e10_alone_is_not_cleared_without_a_time_sync():
    ops = _coordinator(sync_time=False)._writes_for(_raw(ERRORS_E10))
    assert ops == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
