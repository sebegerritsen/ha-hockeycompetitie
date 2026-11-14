"""Diagnostics: the config entry (device token redacted) and what the coordinator holds."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_UUID, CONF_TOKEN
from .coordinator import KnhbConfigEntry

TO_REDACT = {CONF_DEVICE_UUID, CONF_TOKEN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: KnhbConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data: dict[str, Any] | None = None
    if coordinator.data is not None:
        data = asdict(coordinator.data)
        data["match_duration"] = str(coordinator.data.match_duration)
        data["poule_matches"] = len(coordinator.data.poule_matches)
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "update_interval": str(coordinator.update_interval),
        "last_update_success": coordinator.last_update_success,
        "data": data,
    }
