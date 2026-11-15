"""Data models for the KNHB match data API, parsed leniently from its JSON.

The API is not officially documented (see docs/api.md), so every field is optional here:
a missing or renamed field gives None instead of an exception.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

NL_TZ = ZoneInfo("Europe/Amsterdam")


class MatchStatus(StrEnum):
    """Status of a match, as the hockey.nl match centre knows them."""

    SCHEDULED = "scheduled"
    ANNOUNCED = "announced"
    LIVE = "live"
    RESULT = "result"
    FINAL = "final"
    DISCONTINUED = "discontinued"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, value: Any) -> MatchStatus:
        """Return the status for an API value, UNKNOWN for anything new."""
        try:
            return cls(str(value).lower())
        except ValueError:
            return cls.UNKNOWN


# Statuses in which the score is meaningful (a scheduled match reports 0-0).
STATUSES_WITH_SCORE = frozenset(
    {MatchStatus.LIVE, MatchStatus.RESULT, MatchStatus.FINAL, MatchStatus.DISCONTINUED}
)
# Statuses after which nothing changes any more.
STATUSES_DONE = frozenset(
    {
        MatchStatus.FINAL,
        MatchStatus.DISCONTINUED,
        MatchStatus.CANCELLED,
        MatchStatus.EXPIRED,
    }
)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=NL_TZ)
    return parsed


@dataclass(frozen=True, slots=True)
class Club:
    """A club, from GET /clubs."""

    id: str
    name: str
    friendly_name: str | None
    city: str | None
    logo: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Club | None:
        """Parse a club; None if it has no id."""
        club_id = _str(data.get("federation_reference_id"))
        if club_id is None:
            return None
        return cls(
            id=club_id,
            name=_str(data.get("name")) or club_id,
            friendly_name=_str(data.get("friendly_name")),
            city=_str(data.get("city")),
            logo=_str(data.get("logo")),
        )

    def matches_query(self, query: str) -> bool:
        """Return whether a search text occurs in the club's name or city."""
        needle = query.casefold().strip()
        return any(
            needle in value.casefold()
            for value in (self.name, self.friendly_name, self.city)
            if value
        )


@dataclass(frozen=True, slots=True)
class Team:
    """A team of a club, from GET /clubs/{id}."""

    id: int
    name: str
    short_name: str
    hockey_type: str | None
    category: str | None
    recent_poule_id: int | None
    club_id: str | None
    logo: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Team | None:
        """Parse a team; None if it has no id."""
        team_id = _int(data.get("id"))
        if team_id is None:
            return None
        name = _str(data.get("name")) or str(team_id)
        return cls(
            id=team_id,
            name=name,
            short_name=_str(data.get("short_name")) or name,
            hockey_type=_str(data.get("hockey_type")),
            category=_str(data.get("category_group_name")),
            recent_poule_id=_int(data.get("recent_poule_id")),
            club_id=_str(data.get("federation_reference_id")),
            logo=_str(data.get("logo")),
        )


@dataclass(frozen=True, slots=True)
class ClubDetail:
    """A club with its teams, from GET /clubs/{id}."""

    club: Club
    teams: list[Team]

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ClubDetail | None:
        """Parse club details; None if the club has no id."""
        club = Club.from_api(data)
        if club is None:
            return None
        teams = [
            team
            for item in _list(data.get("teams"))
            if (team := Team.from_api(_dict(item))) is not None
        ]
        return cls(club=club, teams=teams)


@dataclass(frozen=True, slots=True)
class TeamRef:
    """A team as it appears in a match or a standing."""

    id: int | None
    name: str
    short_name: str | None
    club_id: str | None
    logo: str | None

    @classmethod
    def from_api(cls, data: Any) -> TeamRef:
        """Parse a team reference."""
        data = _dict(data)
        name = _str(data.get("name")) or _str(data.get("short_name")) or "?"
        return cls(
            id=_int(data.get("id")),
            name=name,
            short_name=_str(data.get("short_name")),
            club_id=_str(data.get("federation_reference_id")),
            logo=_str(data.get("logo")),
        )


@dataclass(frozen=True, slots=True)
class Match:
    """A match."""

    id: int
    start: datetime | None
    status: MatchStatus
    home: TeamRef
    away: TeamRef
    score_home: int | None
    score_away: int | None
    shootout_home: int | None
    shootout_away: int | None
    facility: str | None
    address: str | None
    field: str | None
    field_type: str | None
    remarks: str | None
    competition: str | None
    poule: str | None
    poule_id: int | None
    round: int | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Match | None:
        """Parse a match; None if it has no id."""
        match_id = _int(data.get("id"))
        if match_id is None:
            return None
        status = MatchStatus.parse(data.get("status"))
        score = _dict(data.get("score"))
        shootouts = _dict(data.get("shootouts"))
        has_score = status in STATUSES_WITH_SCORE
        shootout_home = _int(shootouts.get("home"))
        shootout_away = _int(shootouts.get("away"))
        has_shootout = has_score and bool(shootout_home or shootout_away)
        location = _dict(data.get("location"))
        facility = _dict(location.get("facility"))
        pitch = _dict(location.get("field"))
        remarks = _dict(data.get("remarks"))
        address = _str(facility.get("address"))
        return cls(
            id=match_id,
            start=_datetime(data.get("date")),
            status=status,
            home=TeamRef.from_api(data.get("home")),
            away=TeamRef.from_api(data.get("away")),
            score_home=_int(score.get("home")) if has_score else None,
            score_away=_int(score.get("away")) if has_score else None,
            shootout_home=shootout_home if has_shootout else None,
            shootout_away=shootout_away if has_shootout else None,
            facility=_str(facility.get("name")),
            address=", ".join(line.strip() for line in address.splitlines() if line.strip())
            if address
            else None,
            field=_str(pitch.get("name")),
            field_type=_str(pitch.get("type")),
            remarks="\n".join(
                text for text in (_str(remarks.get("official")), _str(remarks.get("info"))) if text
            )
            or None,
            competition=_str(data.get("competition_name")),
            poule=_str(data.get("poule_name")),
            poule_id=_int(data.get("poule_id")),
            round=_int(data.get("round")),
        )

    @property
    def has_score(self) -> bool:
        """Return whether the match has a score."""
        return self.score_home is not None and self.score_away is not None

    def involves(self, team_id: int) -> bool:
        """Return whether the team plays in this match."""
        return team_id in (self.home.id, self.away.id)

    def is_home(self, team_id: int) -> bool:
        """Return whether the team plays at home."""
        return self.home.id == team_id

    def opponent(self, team_id: int) -> TeamRef:
        """Return the other team."""
        return self.away if self.is_home(team_id) else self.home

    def goals(self, team_id: int) -> tuple[int, int] | None:
        """Return (goals for, goals against) from the team's point of view."""
        if self.score_home is None or self.score_away is None:
            return None
        if self.is_home(team_id):
            return self.score_home, self.score_away
        return self.score_away, self.score_home


@dataclass(frozen=True, slots=True)
class Standing:
    """A row of a pool's standings."""

    rank: int | None
    team: TeamRef
    played: int | None
    points: int | None
    wins: int | None
    draws: int | None
    losses: int | None
    goals_for: int | None
    goals_against: int | None
    rank_change: int | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Standing:
        """Parse a standings row."""
        return cls(
            rank=_int(data.get("rank")),
            team=TeamRef.from_api(data.get("team")),
            played=_int(data.get("played")),
            points=_int(data.get("points")),
            wins=_int(data.get("wins")),
            draws=_int(data.get("draws")),
            losses=_int(data.get("losses")),
            goals_for=_int(data.get("goals_for")),
            goals_against=_int(data.get("goals_against")),
            rank_change=_int(data.get("rank_change")),
        )

    @property
    def goal_difference(self) -> int | None:
        """Return goals for minus goals against."""
        if self.goals_for is None or self.goals_against is None:
            return None
        return self.goals_for - self.goals_against


@dataclass(frozen=True, slots=True)
class Poule:
    """A pool: its standings and all its matches."""

    id: int | None
    name: str | None
    competition: str | None
    standings: list[Standing]
    matches: list[Match]

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Poule:
        """Parse a pool."""
        competition = _dict(data.get("competition"))
        return cls(
            id=_int(data.get("id")),
            name=_str(data.get("name")),
            competition=_str(competition.get("name")),
            standings=[Standing.from_api(_dict(item)) for item in _list(data.get("standings"))],
            matches=[
                match
                for item in _list(data.get("matches"))
                if (match := Match.from_api(_dict(item))) is not None
            ],
        )


@dataclass(frozen=True, slots=True)
class PouleRef:
    """Another pool the team plays or played in (the team page's neighbors)."""

    poule_id: int
    season_id: int | None
    name: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PouleRef | None:
        """Parse a pool reference; None if it has no pool id."""
        poule_id = _int(data.get("poule_id"))
        if poule_id is None:
            return None
        return cls(
            poule_id=poule_id,
            season_id=_int(data.get("season_id")),
            name=_str(data.get("name")),
        )


@dataclass(frozen=True, slots=True)
class TeamPage:
    """A team's page in one pool, from GET /poules/{poule_id}/teams/{team_id}."""

    poule_id: int | None
    season_id: int | None
    competition: str | None
    poules: list[Poule]
    neighbors: list[PouleRef] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> TeamPage:
        """Parse a team page."""
        return cls(
            poule_id=_int(data.get("poule_id")),
            season_id=_int(data.get("season_id")),
            competition=_str(data.get("name")),
            poules=[Poule.from_api(_dict(item)) for item in _list(data.get("poules"))],
            neighbors=[
                ref
                for item in _list(data.get("neighbors"))
                if (ref := PouleRef.from_api(_dict(item))) is not None
            ],
        )

    def own_matches(self, team_id: int) -> list[Match]:
        """Return the team's own matches in all pools of this page."""
        return [
            match for poule in self.poules for match in poule.matches if match.involves(team_id)
        ]

    def same_season_poules(self) -> list[int]:
        """Return the other pools of this season (cup rounds, an earlier period)."""
        if self.season_id is None:
            return []
        return [
            ref.poule_id
            for ref in self.neighbors
            if ref.season_id == self.season_id and ref.poule_id != self.poule_id
        ]


def _float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


@dataclass(frozen=True, slots=True)
class MatchWeather:
    """The weather forecast for a match, as the KNHB gives it with the match details."""

    condition: str | None
    temperature: float | None
    temperature_apparent: float | None
    precipitation_type: str | None
    precipitation_chance: float | None
    precipitation_amount: float | None
    humidity: float | None
    rating: str | None
    grade: float | None
    description: str | None
    icon: str | None

    @classmethod
    def from_api(cls, data: Any) -> MatchWeather | None:
        """Parse the weather; None if there is none."""
        if not isinstance(data, dict) or not data:
            return None
        icon = _dict(data.get("icon"))
        return cls(
            condition=_str(data.get("condition_code")),
            temperature=_float(data.get("temperature")),
            temperature_apparent=_float(data.get("temperature_apparent")),
            precipitation_type=_str(data.get("precipitation_type")),
            precipitation_chance=_float(data.get("precipitation_chance")),
            precipitation_amount=_float(data.get("precipitation_amount")),
            humidity=_float(data.get("humidity")),
            rating=_str(data.get("rating")),
            grade=_float(data.get("grade")),
            description=_str(data.get("description")),
            icon=_str(icon.get("raster")),
        )


@dataclass(frozen=True, slots=True)
class MatchDetail:
    """A match with its details, from GET /matches/{id}."""

    match: Match
    weather: MatchWeather | None
    approved_by_home: bool | None
    approved_by_away: bool | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> MatchDetail | None:
        """Parse match details; None if the match has no id."""
        match = Match.from_api(data)
        if match is None:
            return None
        home = data.get("approved_by_home_team")
        away = data.get("approved_by_away_team")
        return cls(
            match=match,
            weather=MatchWeather.from_api(data.get("weather")),
            approved_by_home=home if isinstance(home, bool) else None,
            approved_by_away=away if isinstance(away, bool) else None,
        )
