"""BLE transport for Danfoss Eco eTRV devices.

Uses Home Assistant's bluetooth stack, so it works with local adapters and
ESPHome Bluetooth proxies alike. Measured on real Eco 2 units (2026-08):
connect + service discovery ~3 s, characteristic reads <1 s - comfortably
inside proxy GATT limits despite the device's slow-BLE reputation (which
stems from BlueZ hosts).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
import time
from collections.abc import AsyncIterator, Callable

from bleak.exc import BleakCharacteristicNotFoundError, BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    close_stale_connections_by_address,
    establish_connection,
)
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import (
    SECRET_KEY_LENGTH,
    UUID_BATTERY,
    UUID_CURRENT_TIME,
    UUID_ERRORS,
    UUID_NAME,
    UUID_PIN,
    UUID_SCHEDULE_1,
    UUID_SCHEDULE_2,
    UUID_SCHEDULE_3,
    UUID_SECRET_KEY,
    UUID_SETTINGS,
    UUID_TEMPERATURE,
)
from .crypto import EtrvCryptoError, etrv_decode, etrv_encode
from .proxy import CHOICE_HA, CHOICE_LOCKED, ProxyTracker

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 45.0

# A proxy has very few connection slots and one radio. Letting three
# thermostats dial out through it at the same time is the fastest way to
# produce "no backend with an available connection slot", so connections are
# serialized per scanner. Different scanners connect side by side: with one
# lock for the whole house, 18 valves at 12-15 s per attempt took 3.5 minutes
# a round. The None key is for connects whose scanner is not known beforehand
# (pairing, or a thermostat no scanner lists).
_BLE_LOCKS: dict[str | None, asyncio.Lock] = {}


def _lock_for(source: str | None) -> asyncio.Lock:
    lock = _BLE_LOCKS.get(source)
    if lock is None:
        lock = _BLE_LOCKS[source] = asyncio.Lock()
    return lock

# After a write, re-read the characteristic we touched so the entity shows the
# value the device actually accepted rather than the value we hoped for.
_REREAD_KEYS = {
    UUID_TEMPERATURE: "temperature",
    UUID_SETTINGS: "settings",
    UUID_CURRENT_TIME: "time",
    UUID_ERRORS: "errors",
}
_SCHEDULE_UUIDS = (UUID_SCHEDULE_1, UUID_SCHEDULE_2, UUID_SCHEDULE_3)

# Give the valve a moment to commit a write before reading it back.
WRITE_SETTLE_S = 0.5


def last_connectable_signal(
    hass: HomeAssistant, address: str
) -> tuple[int | None, str | None]:
    """RSSI and source of the latest advertisement from a connectable scanner.

    Passive scanners (Shelly BLU gateways and the like) can hear a valve better
    than the proxy that has to connect to it, so they are left out: the signal
    shown should describe the link every poll actually uses.
    """
    info = bluetooth.async_last_service_info(hass, address, connectable=True)
    if info is None:
        return None, None
    return info.rssi, info.source


def signal_via(
    hass: HomeAssistant, address: str, source: str | None
) -> tuple[int | None, str | None]:
    """RSSI of `address` as heard by the scanner that just read it.

    Each thermostat is read through a chosen scanner, which is often not the
    one with the strongest signal, so the latest advertisement from any
    scanner would describe a link that was not used. Falls back to that when
    the scanner is unknown or no longer lists the thermostat.
    """
    if source is not None:
        for device in bluetooth.async_scanner_devices_by_address(hass, address, True):
            if device.scanner.source == source:
                return device.advertisement.rssi, source
    return last_connectable_signal(hass, address)


def scanner_name(hass: HomeAssistant, source: str | None) -> str | None:
    """Readable name of a scanner, or its address if it is gone."""
    if source is None:
        return None
    scanner = bluetooth.async_scanner_by_source(hass, source)
    return getattr(scanner, "name", None) or source


def connectable_scanners(hass: HomeAssistant) -> dict[str, str]:
    """Address and name of every scanner that can connect."""
    return {
        scanner.source: scanner.name
        for scanner in bluetooth.async_current_scanners(hass)
        if scanner.connectable
    }


def advert_ages(hass: HomeAssistant, address: str) -> dict[str, float]:
    """Seconds since each connectable scanner last heard `address`."""
    now = time.monotonic()
    ages: dict[str, float] = {}
    for device in bluetooth.async_scanner_devices_by_address(hass, address, True):
        scanner = device.scanner
        try:
            seen = scanner.discovered_device_timestamps.get(address)
        except Exception:  # noqa: BLE001 - scanner without timestamps
            seen = None
        # A scanner that lists the device without a timestamp still has it in
        # its (short-lived) discovery table, so treat it as heard just now.
        ages[scanner.source] = 0.0 if seen is None else max(0.0, now - seen)
    return ages


def strongest_scanner(hass: HomeAssistant, address: str) -> str | None:
    """The connectable scanner that hears `address` best.

    This is roughly the scanner Home Assistant would connect through. Naming
    it up front lets a connect that is left to Home Assistant queue behind
    that scanner's other connects instead of dialling out beside them.
    """
    devices = bluetooth.async_scanner_devices_by_address(hass, address, True)
    if not devices:
        return None
    best = max(devices, key=lambda device: device.advertisement.rssi)
    return best.scanner.source


def route(
    hass: HomeAssistant, address: str, tracker: ProxyTracker, *, explore: bool = True
) -> tuple[str | None, str]:
    """Scanner for a connect to `address`, and who chose it.

    With explore off this is the standing assignment, without the occasional
    connect left to Home Assistant.
    """
    ages = advert_ages(hass, address)
    source, choice = tracker.choose(ages) if explore else tracker.assigned(ages)
    if source is None:
        source = strongest_scanner(hass, address)
    return source, choice


def routed_client_class(
    address: str,
    source: str | None,
    choice: str,
    attempts: list[tuple[str, str]],
) -> type:
    """Client class that connects through `source` instead of HA's pick.

    Home Assistant's client wrapper ignores which scanner a BLEDevice came
    from: on every connect it ranks all scanners that hear the address by
    signal and free slots and takes the first. That ranking lives in one
    method, which is replaced here. The scanner each connect attempt really
    used is appended to `attempts` as (scanner, who chose it), also when Home
    Assistant chose, so every attempt can be counted against the right proxy.
    """

    class RoutedClient(BleakClientWithServiceCache):
        def _async_get_best_available_backend_and_device(self, manager):
            backend = None
            if source is not None:
                try:
                    for device in manager.async_scanner_devices_by_address(
                        address, True
                    ):
                        if device.scanner.source == source:
                            backend = self._async_get_backend_for_ble_device(
                                manager, device.scanner, device.ble_device
                            )
                            break
                except Exception as err:  # noqa: BLE001 - HA internals moved
                    _LOGGER.debug("%s: cannot route via %s: %s", address, source, err)
                    backend = None
            via = choice
            if backend is None and choice == CHOICE_LOCKED:
                # A lock never moves to another scanner.
                raise BleakError(
                    f"locked proxy {source} does not hear {address} "
                    "or has no free connection slot"
                )
            if backend is None:
                # No such scanner any more, or it has no free slot.
                via = CHOICE_HA
                backend = super()._async_get_best_available_backend_and_device(
                    manager
                )
            attempts.append((backend.scanner.source, via))
            _LOGGER.debug(
                "%s: connecting via %s (%s)", address, backend.scanner.name, via
            )
            return backend

    return RoutedClient


class EtrvError(Exception):
    """Communication failure."""


class EtrvNotFoundError(EtrvError):
    """No connectable BLEDevice available."""


class EtrvCharacteristicMissing(EtrvError):
    """A characteristic is missing from the (possibly stale) service table."""


class EtrvButtonNotPressed(EtrvError):
    """Secret-key characteristic absent - pairing button was not pressed."""


class EtrvClient:
    """Short-lived-connection client for one eTRV."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        secret_key: bytes | None,
        pin: int = 0,
        tracker: ProxyTracker | None = None,
    ) -> None:
        self._hass = hass
        self.address = address
        self._key = secret_key
        self._pin = pin
        # Without a tracker (pairing) Home Assistant picks the scanner.
        self._tracker = tracker
        self._route: tuple[str | None, str] = (None, CHOICE_HA)

    @contextlib.asynccontextmanager
    async def _slot(self) -> AsyncIterator[None]:
        """Pick the scanner and wait for its turn.

        The scanner is chosen before queueing, so thermostats bound for
        different scanners do not wait for each other.
        """
        tracker = getattr(self, "_tracker", None)
        self._route = (None, CHOICE_HA)
        if tracker is not None:
            self._route = route(self._hass, self.address, tracker)
        async with _lock_for(self._route[0]):
            yield

    async def _connect(self) -> BleakClientWithServiceCache:
        ble_device = bluetooth.async_ble_device_from_address(
            self._hass, self.address, connectable=True
        )
        if ble_device is None:
            raise EtrvNotFoundError(
                f"{self.address} is not seen by any Bluetooth adapter/proxy"
            )
        try:
            await close_stale_connections_by_address(self.address)
        except Exception:  # noqa: BLE001 - best effort
            pass
        tracker = self._tracker
        client_class: type = BleakClientWithServiceCache
        attempts: list[tuple[str, str]] = []
        if tracker is not None:
            source, choice = self._route
            client_class = routed_client_class(
                self.address, source, choice, attempts
            )
        try:
            client = await establish_connection(
                client_class,
                ble_device,
                self.address,
                max_attempts=2,
            )
        except (BleakError, TimeoutError) as err:
            self._count(attempts, connected=False)
            raise EtrvError(f"Cannot connect to {self.address}: {err}") from err
        except BaseException:
            # Cancelled mid-connect: the attempts made so far still failed.
            self._count(attempts, connected=False)
            raise
        try:
            pin_bytes = struct.pack(">I", self._pin)
            await client.write_gatt_char(UUID_PIN, pin_bytes, response=True)
        except BleakCharacteristicNotFoundError as err:
            # The link itself worked; the stale service table is not the
            # proxy's doing.
            self._count(attempts, connected=True)
            await self._clear_service_cache(client)
            await client.disconnect()
            raise EtrvCharacteristicMissing(f"PIN write failed: {err}") from err
        except BleakError as err:
            # Connected, but the link died before the first write went through.
            self._count(attempts, connected=False)
            await client.disconnect()
            raise EtrvError(f"PIN write failed: {err}") from err
        self._count(attempts, connected=True)
        return client

    def _count(self, attempts: list[tuple[str, str]], *, connected: bool) -> None:
        """Count this connect once against each scanner it went through.

        establish_connection retries inside one call, but a proxy refuses a
        new attempt for a few seconds after a failure, so the retry fails at
        once without reaching the radio. Counting it would double every
        failure. Only the scanner of the last attempt can have succeeded.
        """
        if self._tracker is None or not attempts:
            return
        last_source = attempts[-1][0]
        for source, choice in dict(attempts).items():
            self._tracker.record(source, connected and source == last_source, choice)
        attempts.clear()

    async def _read(self, client, uuid: str, *, decode: bool = True) -> bytes:
        try:
            data = bytes(await client.read_gatt_char(uuid))
        except BleakCharacteristicNotFoundError as err:
            raise EtrvCharacteristicMissing(f"Read {uuid[4:8]} failed: {err}") from err
        except BleakError as err:
            raise EtrvError(f"Read {uuid[4:8]} failed: {err}") from err
        if not decode:
            return data
        if self._key is None:
            raise EtrvError("Secret key not configured")
        try:
            return etrv_decode(data, self._key)
        except EtrvCryptoError as err:
            raise EtrvError(str(err)) from err

    async def _write(self, client, uuid: str, payload: bytes) -> None:
        if self._key is None:
            raise EtrvError("Secret key not configured")
        try:
            await client.write_gatt_char(
                uuid, etrv_encode(payload, self._key), response=True
            )
        except BleakCharacteristicNotFoundError as err:
            raise EtrvCharacteristicMissing(f"Write {uuid[4:8]} failed: {err}") from err
        except BleakError as err:
            raise EtrvError(f"Write {uuid[4:8]} failed: {err}") from err

    async def _read_all(self, client) -> dict[str, object]:
        """Read every characteristic we care about over an open connection."""
        battery = (await self._read(client, UUID_BATTERY, decode=False))[0]
        temperature = await self._read(client, UUID_TEMPERATURE)
        settings = await self._read(client, UUID_SETTINGS)
        errors = await self._read(client, UUID_ERRORS)
        device_time = await self._read(client, UUID_CURRENT_TIME)
        schedule: tuple[bytes, bytes, bytes] | None = None
        try:
            schedule = await self._read_schedule(client)
        except EtrvError as err:
            _LOGGER.debug("%s: schedule read skipped: %s", self.address, err)
        return {
            "battery": battery,
            "temperature": temperature,
            "settings": settings,
            "errors": errors,
            "time": device_time,
            "schedule": schedule,
        }

    async def _read_schedule(self, client) -> tuple[bytes, bytes, bytes]:
        return (
            await self._read(client, UUID_SCHEDULE_1),
            await self._read(client, UUID_SCHEDULE_2),
            await self._read(client, UUID_SCHEDULE_3),
        )

    async def read_state(
        self,
        build_writes: Callable[[dict[str, object]], list[tuple[str, bytes]]] | None = None,
    ) -> dict[str, object]:
        """One connection: full state read, plus any queued writes.

        The Danfoss Eco is a sleepy battery device, so everything happens in a
        single connection per poll to minimise radio wake-ups. `build_writes`
        gets the freshly read payloads and returns the writes to perform - the
        settings block is a read-modify-write, so queued changes must be
        applied to what the device holds *now*, not to a cached copy that may
        be hours old.

        The schedule is best-effort: devices that lack those characteristics
        still return state.
        """
        async with self._slot():
            client = await self._connect()
            try:
                raw = await self._read_all(client)
                if build_writes is None:
                    return raw
                ops = build_writes(raw)
                if not ops:
                    return raw
                written: set[str] = set()
                for uuid, payload in ops:
                    await self._write(client, uuid, payload)
                    written.add(uuid)
                _LOGGER.debug("%s: flushed %d queued write(s)", self.address, len(ops))
                await asyncio.sleep(WRITE_SETTLE_S)
                for uuid in written:
                    if (key := _REREAD_KEYS.get(uuid)) is not None:
                        raw[key] = await self._read(client, uuid)
                if written.intersection(_SCHEDULE_UUIDS):
                    raw["schedule"] = await self._read_schedule(client)
                return raw
            except EtrvCharacteristicMissing:
                # The service table is cached across connections (and survives
                # a config entry reload). If discovery was ever incomplete,
                # every poll fails on the same missing characteristic until
                # the cache is dropped, so drop it and let the next poll
                # re-discover.
                await self._clear_service_cache(client)
                raise
            finally:
                await client.disconnect()

    async def _clear_service_cache(self, client) -> None:
        try:
            await client.clear_cache()
            _LOGGER.debug("%s: cleared cached service table", self.address)
        except Exception as err:  # noqa: BLE001 - best effort
            _LOGGER.debug("%s: clearing service cache failed: %s", self.address, err)

    async def read_name(self) -> str | None:
        from .protocol import parse_name

        async with self._slot():
            # Best effort: during pairing this runs right after the key read,
            # when the valve often refuses a second connection. A missing name
            # must not discard a key that was already retrieved.
            try:
                client = await self._connect()
            except EtrvError as err:
                _LOGGER.debug("%s: name read skipped: %s", self.address, err)
                return None
            try:
                return parse_name(await self._read(client, UUID_NAME))
            except EtrvError:
                return None
            finally:
                await client.disconnect()

    async def retrieve_secret_key(self) -> bytes:
        """Read the secret key. The pairing button must have been pressed.

        The key characteristic only appears in the GATT table while the
        pairing window is open, so callers should instruct the user to press
        the timer button right before/while this runs.
        """
        async with self._slot():
            client = await self._connect()
            try:
                char = client.services.get_characteristic(UUID_SECRET_KEY)
                if char is None:
                    # A cached (stale) service table can hide the key char -
                    # drop the cache so the next attempt re-discovers.
                    try:
                        await client.clear_cache()
                    except Exception:  # noqa: BLE001
                        pass
                    raise EtrvButtonNotPressed(
                        "Pairing window closed - key characteristic not present"
                    )
                data = bytes(await client.read_gatt_char(UUID_SECRET_KEY))
                if len(data) < SECRET_KEY_LENGTH:
                    raise EtrvError(f"Short secret key: {len(data)} bytes")
                key = data[:SECRET_KEY_LENGTH]
                self._key = key
                return key
            except BleakError as err:
                raise EtrvError(f"Secret key read failed: {err}") from err
            finally:
                await client.disconnect()
