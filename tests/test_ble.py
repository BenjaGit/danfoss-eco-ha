"""Tests for the BLE transport's stale service cache handling.

bleak and Home Assistant are stubbed, so this runs without either installed.

Run: python tests/test_ble.py (or python -m pytest tests/).
"""

import asyncio
import importlib.util
import os
import sys
import types

_DIR = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "danfoss_eco"
)


class BleakError(Exception):
    pass


class BleakCharacteristicNotFoundError(BleakError):
    pass


def _stub(name: str, **attrs) -> None:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module


_stub("bleak")
_stub(
    "bleak.exc",
    BleakError=BleakError,
    BleakCharacteristicNotFoundError=BleakCharacteristicNotFoundError,
)
_stub(
    "bleak_retry_connector",
    BleakClientWithServiceCache=object,
    close_stale_connections_by_address=None,
    establish_connection=None,
)
_stub("homeassistant")
_stub("homeassistant.components", bluetooth=None)
_stub("homeassistant.core", HomeAssistant=object)

pkg = types.ModuleType("danfoss_eco")
pkg.__path__ = [_DIR]
sys.modules["danfoss_eco"] = pkg


def _load(mod: str):
    spec = importlib.util.spec_from_file_location(
        f"danfoss_eco.{mod}", os.path.join(_DIR, f"{mod}.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"danfoss_eco.{mod}"] = module
    spec.loader.exec_module(module)
    return module


_load("const")
_load("crypto")
_load("proxy")
ble = _load("ble")
UUID_ERRORS = sys.modules["danfoss_eco.const"].UUID_ERRORS
KEY = bytes(16)


class FakeClient:
    """Service table without one characteristic, like a stale BlueZ cache."""

    def __init__(self, missing: set[str]):
        self.missing = missing
        self.cache_cleared = False
        self.disconnected = False

    async def read_gatt_char(self, uuid):
        if uuid in self.missing:
            raise BleakCharacteristicNotFoundError(
                f"Characteristic {uuid} was not found!"
            )
        return bytes(8)

    async def write_gatt_char(self, uuid, data, response=True):
        if uuid in self.missing:
            raise BleakCharacteristicNotFoundError(
                f"Characteristic {uuid} was not found!"
            )

    async def clear_cache(self):
        self.cache_cleared = True
        return True

    async def disconnect(self):
        self.disconnected = True


def _read_state(missing: set[str]) -> tuple[FakeClient, Exception | None]:
    client = FakeClient(missing)
    etrv = ble.EtrvClient.__new__(ble.EtrvClient)
    etrv.address = "00:04:2F:00:00:00"
    etrv._key = KEY

    async def connect():
        return client

    etrv._connect = connect
    try:
        asyncio.run(etrv.read_state())
    except ble.EtrvError as err:
        return client, err
    return client, None


def test_missing_characteristic_clears_service_cache():
    client, err = _read_state({UUID_ERRORS})
    assert isinstance(err, ble.EtrvCharacteristicMissing), err
    assert client.cache_cleared
    assert client.disconnected


def test_missing_schedule_keeps_service_cache():
    # The schedule is best-effort; devices without it must not re-discover
    # services on every poll.
    client, err = _read_state({ble.UUID_SCHEDULE_1})
    assert err is None, err
    assert not client.cache_cleared


def test_successful_poll_keeps_service_cache():
    client, err = _read_state(set())
    assert err is None, err
    assert not client.cache_cleared
    assert client.disconnected


def test_missing_pin_characteristic_clears_service_cache():
    # Seen on real hardware: the stale table can lack the PIN characteristic,
    # so the poll fails while connecting, before any read.
    client = FakeClient({ble.UUID_PIN})
    etrv = ble.EtrvClient.__new__(ble.EtrvClient)
    etrv.address = "00:04:2F:00:00:00"
    etrv._key = KEY
    etrv._pin = 0
    etrv._tracker = None

    async def establish_connection(*args, **kwargs):
        return client

    async def close_stale(address):
        pass

    patched = {
        "bluetooth": types.SimpleNamespace(
            async_ble_device_from_address=lambda *a, **k: object()
        ),
        "establish_connection": establish_connection,
        "close_stale_connections_by_address": close_stale,
    }
    saved = {name: getattr(ble, name) for name in patched}
    etrv._hass = None
    try:
        for name, value in patched.items():
            setattr(ble, name, value)
        asyncio.run(etrv._connect())
    except ble.EtrvCharacteristicMissing:
        pass
    else:
        raise AssertionError("expected EtrvCharacteristicMissing")
    finally:
        for name, value in saved.items():
            setattr(ble, name, value)
    assert client.cache_cleared
    assert client.disconnected


def test_read_name_returns_none_when_connect_fails():
    # Seen on real hardware during pairing: the key read succeeds, the valve
    # drops the link, and the follow-up connection for the name fails. That
    # must fall back to a default name instead of aborting the pairing.
    etrv = ble.EtrvClient.__new__(ble.EtrvClient)
    etrv.address = "00:04:2F:00:00:00"
    etrv._key = KEY

    async def connect():
        raise ble.EtrvError("Cannot connect: Disconnected")

    etrv._connect = connect
    assert asyncio.run(etrv.read_name()) is None



def test_signal_comes_from_connectable_scanners_only():
    # A passive scanner (e.g. a Shelly BLU gateway) may hear the valve better
    # than the proxy that actually connects to it. The signal sensor must show
    # the link the integration uses, not the best advertisement anywhere.
    calls = []

    def last_service_info(hass, address, connectable):
        calls.append(connectable)
        return types.SimpleNamespace(rssi=-61, source="B8:27:EB:73:3A:1F")

    saved = ble.bluetooth
    ble.bluetooth = types.SimpleNamespace(async_last_service_info=last_service_info)
    try:
        assert ble.last_connectable_signal(None, "00:04:2F:00:00:00") == (
            -61,
            "B8:27:EB:73:3A:1F",
        )
        ble.bluetooth = types.SimpleNamespace(
            async_last_service_info=lambda *a, **k: None
        )
        assert ble.last_connectable_signal(None, "00:04:2F:00:00:00") == (None, None)
    finally:
        ble.bluetooth = saved
    assert calls == [True]


class FakeScanner:
    def __init__(self, source: str, free: bool = True):
        self.source = source
        self.name = f"proxy {source}"
        self.free = free


class FakeManager:
    """The part of Home Assistant's Bluetooth manager the routing uses."""

    def __init__(self, scanners: list[FakeScanner]):
        self.scanners = scanners

    def async_scanner_devices_by_address(self, address, connectable):
        return [
            types.SimpleNamespace(scanner=scanner, ble_device=object())
            for scanner in self.scanners
        ]


class FakeHaClient:
    """Stands in for Home Assistant's client wrapper.

    Like the real one it takes the scanner with the best signal, which the
    tests place first in the list.
    """

    def _async_get_backend_for_ble_device(self, manager, scanner, ble_device):
        return types.SimpleNamespace(scanner=scanner) if scanner.free else None

    def _async_get_best_available_backend_and_device(self, manager):
        return types.SimpleNamespace(scanner=manager.scanners[0])


def _route(source, scanners, choice="learned"):
    attempts: list[tuple[str, str]] = []
    saved = ble.BleakClientWithServiceCache
    ble.BleakClientWithServiceCache = FakeHaClient
    try:
        cls = ble.routed_client_class("00:04:2F:00:00:00", source, choice, attempts)
    finally:
        ble.BleakClientWithServiceCache = saved
    backend = cls()._async_get_best_available_backend_and_device(
        FakeManager(scanners)
    )
    return backend.scanner.source, attempts


def test_connect_goes_through_the_chosen_scanner():
    # Home Assistant would take "A" (best signal); the tracker chose "B".
    used, attempts = _route("B", [FakeScanner("A"), FakeScanner("B")])
    assert used == "B"
    assert attempts == [("B", "learned")]


def test_chosen_scanner_without_free_slot_falls_back_to_home_assistant():
    used, attempts = _route("B", [FakeScanner("A"), FakeScanner("B", free=False)])
    assert used == "A"
    assert attempts == [("A", "ha")]


def test_chosen_scanner_that_is_gone_falls_back_to_home_assistant():
    used, attempts = _route("C", [FakeScanner("A"), FakeScanner("B")], "locked")
    assert used == "A"
    assert attempts == [("A", "ha")]


def test_no_choice_leaves_the_scanner_to_home_assistant_and_records_it():
    used, attempts = _route(None, [FakeScanner("A"), FakeScanner("B")], "ha")
    assert used == "A"
    assert attempts == [("A", "ha")]


def _connect_with_tracker(outcomes: list[bool], pin_error: Exception | None = None):
    """Run _connect with a tracker; each outcome is one connect attempt via "B"."""
    proxy = sys.modules["danfoss_eco.proxy"]
    tracker = proxy.ProxyTracker(rng=lambda: 0.99)
    for _ in range(proxy.MIN_ATTEMPTS):
        tracker.record("B", True)
    before = tracker.stats["B"].attempts

    class PinClient(FakeClient):
        async def write_gatt_char(self, uuid, data, response=True):
            if pin_error is not None:
                raise pin_error

    async def establish_connection(client_class, device, name, max_attempts):
        client = client_class()
        manager = FakeManager([FakeScanner("A"), FakeScanner("B")])
        for ok in outcomes:
            client._async_get_best_available_backend_and_device(manager)
            if ok:
                return PinClient(set())
        raise BleakError("failed to connect")

    async def close_stale(address):
        pass

    patched = {
        "bluetooth": types.SimpleNamespace(
            async_ble_device_from_address=lambda *a, **k: object()
        ),
        "establish_connection": establish_connection,
        "close_stale_connections_by_address": close_stale,
        "advert_ages": lambda hass, address: {"A": 1.0, "B": 2.0},
        "BleakClientWithServiceCache": FakeHaClient,
    }
    etrv = ble.EtrvClient(None, "00:04:2F:00:00:00", KEY, 0, tracker)
    saved = {name: getattr(ble, name) for name in patched}
    error = None
    try:
        for name, value in patched.items():
            setattr(ble, name, value)

        async def connect():
            async with etrv._slot():
                await etrv._connect()

        asyncio.run(connect())
    except ble.EtrvError as err:
        error = err
    finally:
        for name, value in saved.items():
            setattr(ble, name, value)
    stats = tracker.stats["B"]
    return stats.attempts - before, stats.successes - before, tracker, error


def test_successful_connect_is_counted_for_the_scanner_used():
    attempts, successes, tracker, error = _connect_with_tracker([True])
    assert error is None
    assert (attempts, successes) == (1, 1)
    assert (tracker.last_source, tracker.last_choice) == ("B", "learned")
    assert "A" not in tracker.stats


def test_retry_inside_one_connect_is_counted_once():
    # The proxy refuses the immediate retry without trying, so two attempts
    # in one connect are one real attempt.
    attempts, successes, _, error = _connect_with_tracker([False, True])
    assert error is None
    assert (attempts, successes) == (1, 1)


def test_failed_connect_is_one_failure_however_many_retries():
    attempts, successes, tracker, error = _connect_with_tracker([False, False])
    assert isinstance(error, ble.EtrvError)
    assert (attempts, successes) == (1, 0)
    assert tracker.stats["B"].consecutive_failures == 1


def test_connect_that_moved_to_another_scanner_counts_both():
    proxy = sys.modules["danfoss_eco.proxy"]
    tracker = proxy.ProxyTracker()
    etrv = ble.EtrvClient(None, "00:04:2F:00:00:00", KEY, 0, tracker)
    etrv._count([("B", "learned"), ("A", "ha")], connected=True)
    assert (tracker.stats["B"].attempts, tracker.stats["B"].successes) == (1, 0)
    assert (tracker.stats["A"].attempts, tracker.stats["A"].successes) == (1, 1)
    assert (tracker.last_source, tracker.last_choice) == ("A", "ha")


def test_link_that_dies_before_the_first_write_counts_as_failed():
    attempts, successes, _, error = _connect_with_tracker(
        [True], pin_error=BleakError("Not connected")
    )
    assert isinstance(error, ble.EtrvError)
    assert (attempts, successes) == (1, 0)


def test_stale_service_table_is_not_held_against_the_scanner():
    attempts, successes, _, error = _connect_with_tracker(
        [True], pin_error=BleakCharacteristicNotFoundError("not found")
    )
    assert isinstance(error, ble.EtrvCharacteristicMissing)
    assert (attempts, successes) == (1, 1)


def test_advert_ages_come_from_each_connectable_scanner():
    now = ble.time.monotonic()

    def scanner(source, seen):
        return types.SimpleNamespace(
            scanner=types.SimpleNamespace(
                source=source,
                discovered_device_timestamps=(
                    {} if seen is None else {"00:04:2F:00:00:00": seen}
                ),
            )
        )

    calls = []

    def devices(hass, address, connectable):
        calls.append(connectable)
        return [scanner("A", now - 30), scanner("B", now - 900), scanner("C", None)]

    saved = ble.bluetooth
    ble.bluetooth = types.SimpleNamespace(async_scanner_devices_by_address=devices)
    try:
        ages = ble.advert_ages(None, "00:04:2F:00:00:00")
    finally:
        ble.bluetooth = saved
    assert calls == [True]
    assert 29 < ages["A"] < 32
    assert 899 < ages["B"] < 902
    assert ages["C"] == 0.0


def _run_two_reads(route_a: str, route_b: str) -> int:
    """Two thermostats read at once; returns how many were connected together."""
    proxy = sys.modules["danfoss_eco.proxy"]
    state = {"open": 0, "peak": 0}

    class SlowClient(FakeClient):
        async def disconnect(self):
            state["open"] -= 1

    def client(address: str):
        etrv = ble.EtrvClient(None, address, KEY, 0, proxy.ProxyTracker())

        async def connect():
            state["open"] += 1
            state["peak"] = max(state["peak"], state["open"])
            await asyncio.sleep(0.01)
            return SlowClient(set())

        etrv._connect = connect
        return etrv

    routes = {"00:04:2F:00:00:01": route_a, "00:04:2F:00:00:02": route_b}
    saved = ble.route
    ble.route = lambda hass, address, tracker: (routes[address], "learned")
    try:

        async def both():
            await asyncio.gather(*(client(a).read_state() for a in routes))

        asyncio.run(both())
    finally:
        ble.route = saved
        ble._BLE_LOCKS.clear()
    return state["peak"]


def test_thermostats_on_different_scanners_are_read_side_by_side():
    assert _run_two_reads("A", "B") == 2


def test_thermostats_on_the_same_scanner_take_turns():
    assert _run_two_reads("A", "A") == 1


def test_connect_left_to_home_assistant_queues_behind_the_strongest_scanner():
    # Home Assistant connects through the best signal, so that scanner's lock
    # is the one to wait for; otherwise two valves would dial out through it.
    proxy = sys.modules["danfoss_eco.proxy"]

    def device(source, rssi):
        return types.SimpleNamespace(
            scanner=types.SimpleNamespace(
                source=source, discovered_device_timestamps={}
            ),
            advertisement=types.SimpleNamespace(rssi=rssi),
        )

    saved = ble.bluetooth
    ble.bluetooth = types.SimpleNamespace(
        async_scanner_devices_by_address=lambda hass, address, connectable: [
            device("A", -80),
            device("B", -62),
        ]
    )
    try:
        # No records yet: nothing is proven, so Home Assistant chooses.
        assert ble.route(None, "00:04:2F:00:00:00", proxy.ProxyTracker()) == (
            "B",
            "ha",
        )
        ble.bluetooth = types.SimpleNamespace(
            async_scanner_devices_by_address=lambda *a: []
        )
        assert ble.route(None, "00:04:2F:00:00:00", proxy.ProxyTracker()) == (
            None,
            "ha",
        )
    finally:
        ble.bluetooth = saved


class RecordingClient(FakeClient):
    """Remembers writes and returns them on the next read, like the valve."""

    def __init__(self, values: dict[str, bytes]):
        super().__init__(set())
        self.values = values

    async def read_gatt_char(self, uuid):
        return self.values.get(uuid, bytes(8))

    async def write_gatt_char(self, uuid, data, response=True):
        self.values[uuid] = bytes(data)


def test_written_error_register_is_read_back():
    # A clock sync clears E10 by writing the error register. The poll that
    # carries the write must show the register as it is after the write, or
    # E10 stays on screen for another poll interval.
    crypto = sys.modules["danfoss_eco.crypto"]
    e10 = bytes.fromhex("0200000000000000")
    client = RecordingClient({UUID_ERRORS: crypto.etrv_encode(e10, KEY)})
    etrv = ble.EtrvClient.__new__(ble.EtrvClient)
    etrv.address = "00:04:2F:00:00:00"
    etrv._key = KEY

    async def connect():
        return client

    etrv._connect = connect
    saved = ble.WRITE_SETTLE_S
    ble.WRITE_SETTLE_S = 0
    try:
        raw = asyncio.run(
            etrv.read_state(build_writes=lambda raw: [(UUID_ERRORS, bytes(8))])
        )
    finally:
        ble.WRITE_SETTLE_S = saved
    assert raw["errors"] == bytes(8)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("all good")
