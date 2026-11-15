"""The Hockeycompetitie integration: fixtures, results and standings of a KNHB team."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import CONF_DEVICE_UUID, CONF_TOKEN, DOMAIN, STORAGE_VERSION
from .coordinator import KnhbConfigEntry, KnhbCoordinator
from .helpers import async_get_client

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.EVENT,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: KnhbConfigEntry) -> bool:
    """Set up a team from a config entry."""

    @callback
    def _store_token(device_uuid: str, token: str) -> None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_DEVICE_UUID: device_uuid, CONF_TOKEN: token}
        )

    client = async_get_client(
        hass,
        device_uuid=entry.data.get(CONF_DEVICE_UUID),
        token=entry.data.get(CONF_TOKEN),
        on_token_change=_store_token,
    )
    coordinator = KnhbCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: KnhbConfigEntry) -> None:
    """Show changed options (meet time) at once; no reload needed."""
    entry.runtime_data.async_update_listeners()


async def async_unload_entry(hass: HomeAssistant, entry: KnhbConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: KnhbConfigEntry) -> None:
    """Remove the matches stored for change alerts."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
