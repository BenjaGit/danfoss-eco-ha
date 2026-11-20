"""Select: lock a thermostat to one Bluetooth proxy."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DanfossEcoConfigEntry
from .ble import connectable_scanners
from .const import CONF_PREFERRED_PROXY
from .coordinator import EtrvCoordinator
from .entity import EtrvEntity
from .proxy import AUTO


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DanfossEcoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([EtrvProxySelect(entry.runtime_data)])


class EtrvProxySelect(EtrvEntity, SelectEntity):
    """Same setting as "Preferred Bluetooth proxy" in the options.

    The options are the scanners that can connect right now, by name, plus
    "auto". A locked scanner that is offline stays in the list under its
    address, so the lock is neither hidden nor lost.
    """

    _attr_translation_key = "preferred_proxy"
    _attr_entity_category = EntityCategory.CONFIG
    _always_available = True

    def __init__(self, coordinator: EtrvCoordinator) -> None:
        super().__init__(coordinator, "preferred_proxy")

    def _scanners(self) -> dict[str, str]:
        """Scanner address -> the option shown for it."""
        scanners = connectable_scanners(self.hass)
        locked = self.coordinator.proxies.locked
        if locked is not None:
            scanners.setdefault(locked, locked)
        return scanners

    @property
    def options(self) -> list[str]:
        return [AUTO, *sorted(self._scanners().values())]

    @property
    def current_option(self) -> str:
        locked = self.coordinator.proxies.locked
        if locked is None:
            return AUTO
        return self._scanners()[locked]

    async def async_select_option(self, option: str) -> None:
        source = AUTO
        if option != AUTO:
            source = next(
                address for address, name in self._scanners().items() if name == option
            )
        entry = self.coordinator.config_entry
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_PREFERRED_PROXY: source}
        )
