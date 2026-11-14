"""Calendar with every match of the team."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import KnhbConfigEntry, KnhbCoordinator, TeamData
from .entity import KnhbEntity
from .models import Match, MatchStatus

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KnhbConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the team's calendar."""
    async_add_entities([KnhbCalendar(entry.runtime_data)])


def score_text(match: Match) -> str | None:
    """Return the score as home–away, with shoot-outs if there were any."""
    if match.score_home is None or match.score_away is None:
        return None
    text = f"{match.score_home}–{match.score_away}"
    if match.shootout_home is not None and match.shootout_away is not None:
        text += f", SO {match.shootout_home}–{match.shootout_away}"
    return text


def match_event(data: TeamData, match: Match) -> CalendarEvent | None:
    """Return the calendar event of a match, None if it has no time or was cancelled.

    Cancelled matches are left out: Home Assistant calendars don't return cancelled
    events, so automations on the calendar don't fire for them.
    """
    if match.start is None or match.status == MatchStatus.CANCELLED:
        return None
    summary = f"{match.home.name} – {match.away.name}"
    if score := score_text(match):
        summary += f" ({score})"
    pitch = match.field
    if pitch and match.field_type and match.field_type not in pitch:
        pitch = f"{pitch} ({match.field_type})"
    competition = " – ".join(part for part in (match.competition, match.poule) if part)
    description = "\n".join(part for part in (pitch, competition, match.remarks) if part)
    location = ", ".join(part for part in (match.facility, match.address) if part)
    start = dt_util.as_local(match.start)
    return CalendarEvent(
        start=start,
        end=start + data.match_duration,
        summary=summary,
        description=description or None,
        location=location or None,
        uid=f"knhb_hockey_{match.id}",
    )


class KnhbCalendar(KnhbEntity, CalendarEntity):
    """All matches of a team: past, with scores, and upcoming."""

    _attr_name = None
    _attr_translation_key = "matches"

    def __init__(self, coordinator: KnhbCoordinator) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator, "calendar")

    def _events(self) -> list[CalendarEvent]:
        data = self.coordinator.data
        return [event for match in data.matches if (event := match_event(data, match)) is not None]

    @property
    def event(self) -> CalendarEvent | None:
        """Return the match being played now, or else the next one."""
        now = dt_util.now()
        return next((event for event in self._events() if event.end > now), None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return the matches between two moments."""
        return [
            event for event in self._events() if event.start < end_date and event.end > start_date
        ]
