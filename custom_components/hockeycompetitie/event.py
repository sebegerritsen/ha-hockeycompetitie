"""Event entity: a match was cancelled, moved, or has a result."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .calendar import score_text
from .changes import ChangeType, MatchChange
from .coordinator import KnhbConfigEntry, KnhbCoordinator, TeamData, match_result
from .entity import KnhbEntity
from .sensor import match_attributes

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KnhbConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the team's event entity."""
    async_add_entities([KnhbMatchUpdate(entry.runtime_data)])


class KnhbMatchUpdate(KnhbEntity, EventEntity):
    """Fires when one of the team's matches is cancelled, back on, moved, or has a result."""

    _attr_translation_key = "match_update"

    def __init__(self, coordinator: KnhbCoordinator) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator, "match_update")
        self._attr_event_types = [change.value for change in ChangeType]
        # Changes belong to one update: collect each update's once, fire when ready.
        self._seen: TeamData | None = None
        self._pending: list[MatchChange] = []
        self._ready = False

    async def async_added_to_hass(self) -> None:
        """Report what the first update found (what changed while Home Assistant was off).

        Not right away: state written while the entity is being added is dropped, and
        during start-up automations may not be running yet.
        """
        await super().async_added_to_hass()
        self._collect()
        self.async_on_remove(async_call_later(self.hass, 0, self._async_added))

    @callback
    def _async_added(self, _now: datetime) -> None:
        self.async_on_remove(async_at_started(self.hass, self._async_ready))

    @callback
    def _async_ready(self, _hass: HomeAssistant) -> None:
        self._ready = True
        self._fire()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._collect()
        self._fire()
        super()._handle_coordinator_update()

    @callback
    def _collect(self) -> None:
        data = self.coordinator.data
        if data is None or data is self._seen:
            return
        self._seen = data
        self._pending.extend(data.changes)

    @callback
    def _fire(self) -> None:
        if not self._ready:
            return
        while self._pending:
            change = self._pending.pop(0)
            self._trigger_event(change.type.value, self._attributes(change))
            self.async_write_ha_state()

    def _attributes(self, change: MatchChange) -> dict[str, Any]:
        match, before = change.match, change.previous
        attributes = match_attributes(self.coordinator, match)
        attributes["meet_time"] = _iso(self.coordinator.meet_time(match))
        if change.type in (ChangeType.RESCHEDULED, ChangeType.REINSTATED):
            attributes["previous_start"] = _iso(
                dt_util.parse_datetime(before.start) if before.start else None
            )
        if change.type == ChangeType.LOCATION_CHANGED:
            attributes["previous_venue"] = before.facility
            attributes["previous_field"] = before.field
        if change.type == ChangeType.RESULT:
            attributes["score"] = score_text(match)
            attributes["result"] = match_result(match, self.coordinator.team_id)
        return attributes


def _iso(moment: datetime | None) -> str | None:
    return dt_util.as_local(moment).isoformat() if moment else None
