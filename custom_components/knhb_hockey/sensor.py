"""Sensors: next match, meet time, weather, last result and standing of the team."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .calendar import score_text
from .coordinator import KnhbConfigEntry, KnhbCoordinator, match_result
from .entity import KnhbEntity
from .models import Match

PARALLEL_UPDATES = 0

RESULT_WIN = "win"
RESULT_DRAW = "draw"
RESULT_LOSS = "loss"
HOME = "home"
AWAY = "away"
# Upcoming matches listed with the next match.
UPCOMING_COUNT = 5


def _iso(moment: datetime | None) -> str | None:
    return dt_util.as_local(moment).isoformat() if moment else None


def match_attributes(coordinator: KnhbCoordinator, match: Match | None) -> dict[str, Any]:
    """Return the attributes describing a match from the team's point of view."""
    if match is None:
        return {}
    data = coordinator.data
    opponent = match.opponent(data.team_id)
    return {
        "opponent": opponent.name,
        "home_away": "home" if match.is_home(data.team_id) else "away",
        "home_team": match.home.name,
        "away_team": match.away.name,
        "start": _iso(match.start),
        "end": _iso(data.match_end(match)),
        "venue": match.facility,
        "address": match.address,
        "field": match.field,
        "competition": match.competition,
        "poule": match.poule,
        "remarks": match.remarks,
        "status": match.status.value,
        "match_id": match.id,
        "opponent_logo": opponent.logo,
    }


def next_match_attributes(coordinator: KnhbCoordinator, now: datetime) -> dict[str, Any]:
    """Return the next match, what is known of the opponent, and the matches after it."""
    data = coordinator.data
    upcoming = data.upcoming(now)
    if not upcoming:
        return {}
    match = upcoming[0]
    opponent = match.opponent(data.team_id)
    opponent_row = data.standing_of(opponent.id)
    previous = data.previous_meeting(match)
    return {
        **match_attributes(coordinator, match),
        "meet_time": _iso(coordinator.meet_time(match)),
        "opponent_rank": opponent_row.rank if opponent_row else None,
        "opponent_points": opponent_row.points if opponent_row else None,
        "opponent_form": data.form(opponent.id),
        "previous_meeting": score_text(previous) if previous else None,
        "previous_meeting_result": match_result(previous, data.team_id) if previous else None,
        "upcoming": [
            {
                "start": _iso(later.start),
                "opponent": later.opponent(data.team_id).name,
                "home_away": "home" if later.is_home(data.team_id) else "away",
                "venue": later.facility,
            }
            for later in upcoming[1 : 1 + UPCOMING_COUNT]
        ],
    }


def result_attributes(coordinator: KnhbCoordinator, match: Match | None) -> dict[str, Any]:
    """Return the attributes of the last result."""
    if match is None:
        return {}
    goals = match.goals(coordinator.data.team_id)
    return {
        **match_attributes(coordinator, match),
        "score": score_text(match),
        "goals_for": goals[0] if goals else None,
        "goals_against": goals[1] if goals else None,
    }


def standing_attributes(coordinator: KnhbCoordinator) -> dict[str, Any]:
    """Return the team's numbers in the standings, its form, and the whole table."""
    data = coordinator.data
    form = data.form(data.team_id)
    if (row := data.standing) is None:
        return {"form": form} if form else {}
    return {
        "points": row.points,
        "played": row.played,
        "wins": row.wins,
        "draws": row.draws,
        "losses": row.losses,
        "goals_for": row.goals_for,
        "goals_against": row.goals_against,
        "goal_difference": row.goal_difference,
        "rank_change": row.rank_change,
        "form": form,
        "teams": len(data.standings),
        "competition": data.competition,
        "poule": data.poule,
        "table": [
            {
                "rank": other.rank,
                "team": other.team.name,
                "played": other.played,
                "points": other.points,
                "goal_difference": other.goal_difference,
            }
            for other in data.standings
        ],
    }


def weather_attributes(coordinator: KnhbCoordinator, now: datetime) -> dict[str, Any]:
    """Return the forecast details for the next match."""
    data = coordinator.data
    match = data.next_match(now)
    if (weather := data.weather) is None or match is None or data.weather_match_id != match.id:
        return {}
    return {
        "condition": weather.condition,
        "apparent_temperature": weather.temperature_apparent,
        "precipitation_type": weather.precipitation_type,
        "precipitation_probability": weather.precipitation_chance,
        "precipitation": weather.precipitation_amount,
        "humidity": weather.humidity,
        "rating": weather.rating,
        "grade": weather.grade,
        "description": weather.description,
        "match_id": match.id,
        "start": _iso(match.start),
    }


def _weather_value(coordinator: KnhbCoordinator, now: datetime) -> float | None:
    data = coordinator.data
    match = data.next_match(now)
    if data.weather is None or match is None or data.weather_match_id != match.id:
        return None
    return data.weather.temperature


def _result_value(coordinator: KnhbCoordinator, now: datetime) -> str | None:
    match = coordinator.data.last_result()
    return match_result(match, coordinator.data.team_id) if match else None


def _opponent_value(coordinator: KnhbCoordinator, now: datetime) -> str | None:
    match = coordinator.data.next_match(now)
    return match.opponent(coordinator.data.team_id).name if match else None


def _home_away_value(coordinator: KnhbCoordinator, now: datetime) -> str | None:
    match = coordinator.data.next_match(now)
    if match is None:
        return None
    return HOME if match.is_home(coordinator.data.team_id) else AWAY


def opponent_attributes(coordinator: KnhbCoordinator, now: datetime) -> dict[str, Any]:
    """Return how the next opponent is doing, and where and when the match is."""
    data = coordinator.data
    if (match := data.next_match(now)) is None:
        return {}
    opponent = match.opponent(data.team_id)
    row = data.standing_of(opponent.id)
    return {
        "home_away": HOME if match.is_home(data.team_id) else AWAY,
        "start": _iso(match.start),
        "venue": match.facility,
        "opponent_rank": row.rank if row else None,
        "opponent_points": row.points if row else None,
        "opponent_form": data.form(opponent.id),
    }


def _opponent_logo(coordinator: KnhbCoordinator, now: datetime) -> str | None:
    match = coordinator.data.next_match(now)
    return match.opponent(coordinator.data.team_id).logo if match else None


@dataclass(frozen=True, kw_only=True)
class KnhbSensorDescription(SensorEntityDescription):
    """Describes a team sensor."""

    value_fn: Callable[[KnhbCoordinator, datetime], StateType | datetime]
    attributes_fn: Callable[[KnhbCoordinator, datetime], dict[str, Any]] = lambda c, now: {}
    picture_fn: Callable[[KnhbCoordinator, datetime], str | None] | None = None


SENSORS: tuple[KnhbSensorDescription, ...] = (
    KnhbSensorDescription(
        key="next_match",
        translation_key="next_match",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c, now: (m := c.data.next_match(now)) and m.start,
        attributes_fn=next_match_attributes,
        picture_fn=_opponent_logo,
    ),
    KnhbSensorDescription(
        key="opponent",
        translation_key="opponent",
        value_fn=_opponent_value,
        attributes_fn=opponent_attributes,
        picture_fn=_opponent_logo,
    ),
    KnhbSensorDescription(
        key="home_away",
        translation_key="home_away",
        device_class=SensorDeviceClass.ENUM,
        options=[HOME, AWAY],
        value_fn=_home_away_value,
        attributes_fn=lambda c, now: match_attributes(c, c.data.next_match(now)),
    ),
    KnhbSensorDescription(
        key="meet_time",
        translation_key="meet_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c, now: c.meet_time(c.data.next_match(now)),
        attributes_fn=lambda c, now: match_attributes(c, c.data.next_match(now)),
    ),
    KnhbSensorDescription(
        key="match_weather",
        translation_key="match_weather",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        value_fn=_weather_value,
        attributes_fn=weather_attributes,
    ),
    KnhbSensorDescription(
        key="last_result",
        translation_key="last_result",
        device_class=SensorDeviceClass.ENUM,
        options=[RESULT_WIN, RESULT_DRAW, RESULT_LOSS],
        value_fn=_result_value,
        attributes_fn=lambda c, now: result_attributes(c, c.data.last_result()),
    ),
    KnhbSensorDescription(
        key="standing",
        translation_key="standing",
        value_fn=lambda c, now: (row := c.data.standing) and row.rank,
        attributes_fn=lambda c, now: standing_attributes(c),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KnhbConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the team's sensors."""
    coordinator = entry.runtime_data
    async_add_entities(KnhbSensor(coordinator, description) for description in SENSORS)


class KnhbSensor(KnhbEntity, SensorEntity):
    """A sensor of a team."""

    entity_description: KnhbSensorDescription
    _unrecorded_attributes = frozenset(
        {"table", "upcoming", "opponent_logo", "remarks", "description", "opponent_form", "form"}
    )

    def __init__(self, coordinator: KnhbCoordinator, description: KnhbSensorDescription) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator, dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the details."""
        return self.entity_description.attributes_fn(self.coordinator, dt_util.utcnow())

    @property
    def entity_picture(self) -> str | None:
        """Return a picture: the opponent's logo for the next match."""
        if self.entity_description.picture_fn is None:
            return None
        return self.entity_description.picture_fn(self.coordinator, dt_util.utcnow())
