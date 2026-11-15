"""Base entity: one device per team."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CATEGORY,
    CONF_CLUB_NAME,
    CONF_HOCKEY_TYPE,
    CONF_TEAM_ID,
    DOMAIN,
    HOCKEY_TYPE_FIELD,
    HOCKEY_TYPE_INDOOR,
)
from .coordinator import KnhbCoordinator

HOCKEY_TYPE_NAMES = {HOCKEY_TYPE_FIELD: "Veld", HOCKEY_TYPE_INDOOR: "Zaal"}


class KnhbEntity(CoordinatorEntity[KnhbCoordinator]):
    """An entity of a team."""

    _attr_has_entity_name = True
    _attr_attribution = "Data: KNHB, hockey.nl"

    def __init__(self, coordinator: KnhbCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        data = entry.data
        team_id = data[CONF_TEAM_ID]
        self._attr_unique_id = f"{team_id}_{key}"
        model = " · ".join(
            part
            for part in (
                HOCKEY_TYPE_NAMES.get(data.get(CONF_HOCKEY_TYPE, "")),
                data.get(CONF_CATEGORY),
            )
            if part
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(team_id))},
            name=entry.title,
            manufacturer=data.get(CONF_CLUB_NAME),
            model=model or None,
            entry_type=DeviceEntryType.SERVICE,
        )
