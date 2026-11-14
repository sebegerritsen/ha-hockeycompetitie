"""Coordinator: fetches one team's matches and standing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    KnhbClient,
    KnhbConnectionError,
    KnhbError,
    KnhbNotFoundError,
    KnhbRateLimitError,
    KnhbResponseError,
)
from .changes import MatchChange, MatchState, detect_changes, updated_states
from .const import (
    CATEGORY_YOUNGEST,
    CLUB_REFRESH_INTERVAL,
    CONF_CATEGORY,
    CONF_CLUB_ID,
    CONF_HOCKEY_TYPE,
    CONF_MEET_MINUTES_AWAY,
    CONF_MEET_MINUTES_HOME,
    CONF_POULE_CHECKED,
    CONF_POULE_ID,
    CONF_TEAM_ID,
    DEFAULT_MEET_MINUTES,
    DOMAIN,
    EXTRA_POULE_REFRESH_INTERVAL,
    HOCKEY_TYPE_INDOOR,
    LOGGER,
    MATCH_DURATION,
    MATCH_DURATION_SHORT,
    RESULT_WAIT,
    STORAGE_VERSION,
    UPDATE_INTERVAL,
    UPDATE_INTERVAL_IDLE,
    UPDATE_INTERVAL_MATCH,
    UPDATE_INTERVAL_SOON,
    WEATHER_AHEAD,
    WEATHER_REFRESH,
)
from .models import STATUSES_DONE, Match, MatchStatus, MatchWeather, Standing

type KnhbConfigEntry = ConfigEntry[KnhbCoordinator]

# Poll more often from this long before a match starts.
MATCH_LEAD = timedelta(minutes=30)
# Statuses whose score counts as a result (a live score does not).
RESULT_STATUSES = frozenset({MatchStatus.FINAL, MatchStatus.RESULT, MatchStatus.DISCONTINUED})
NOT_PLAYED = frozenset({MatchStatus.CANCELLED, MatchStatus.EXPIRED})


def match_duration(hockey_type: str | None, category: str | None) -> timedelta:
    """Return the calendar slot length: indoor and the youngest play shorter matches."""
    if hockey_type == HOCKEY_TYPE_INDOOR or category == CATEGORY_YOUNGEST:
        return MATCH_DURATION_SHORT
    return MATCH_DURATION


@dataclass(slots=True)
class TeamData:
    """Everything known about one team."""

    team_id: int
    match_duration: timedelta
    matches: list[Match]
    standings: list[Standing] = field(default_factory=list)
    competition: str | None = None
    poule: str | None = None
    poule_id: int | None = None
    # All matches of the team's current pool, for the opponents' form.
    poule_matches: list[Match] = field(default_factory=list)
    team_logo: str | None = None
    # Weather forecast of the next match (`weather_match_id`).
    weather: MatchWeather | None = None
    weather_match_id: int | None = None
    # What changed since the previous update.
    changes: list[MatchChange] = field(default_factory=list)

    @property
    def standing(self) -> Standing | None:
        """Return the team's own row in the standings."""
        return self.standing_of(self.team_id)

    def standing_of(self, team_id: int | None) -> Standing | None:
        """Return a team's row in the standings."""
        if team_id is None:
            return None
        return next((row for row in self.standings if row.team.id == team_id), None)

    def match_end(self, match: Match) -> datetime | None:
        """Return when a match is expected to end."""
        return match.start + self.match_duration if match.start else None

    def upcoming(self, now: datetime) -> list[Match]:
        """Return the match being played now and the ones after it."""
        return [
            match
            for match in self.matches
            if match.start is not None
            and match.status not in NOT_PLAYED
            and match.status not in RESULT_STATUSES
            and match.start + self.match_duration > now
        ]

    def next_match(self, now: datetime) -> Match | None:
        """Return the match being played now, or else the next one."""
        return next(iter(self.upcoming(now)), None)

    def matches_on(self, day: date) -> list[Match]:
        """Return the team's matches (not cancelled) on a day, in local time."""
        return [
            match
            for match in self.matches
            if match.start is not None
            and match.status != MatchStatus.CANCELLED
            and dt_util.as_local(match.start).date() == day
        ]

    def last_result(self) -> Match | None:
        """Return the most recent match with a result."""
        return next(
            (
                match
                for match in reversed(self.matches)
                if match.status in RESULT_STATUSES and match.has_score
            ),
            None,
        )

    def form(self, team_id: int | None, count: int = 5) -> list[str]:
        """Return a team's last results, oldest first, as win, draw or loss."""
        if team_id is None:
            return []
        source = self.matches if team_id == self.team_id else self.poule_matches
        results = [
            result
            for match in source
            if match.involves(team_id)
            and match.status in RESULT_STATUSES
            and (result := match_result(match, team_id)) is not None
        ]
        return results[-count:]

    def previous_meeting(self, match: Match) -> Match | None:
        """Return the last earlier match with a result against the same opponent."""
        opponent = match.opponent(self.team_id).id
        if opponent is None or match.start is None:
            return None
        return next(
            (
                earlier
                for earlier in reversed(self.matches)
                if earlier.id != match.id
                and earlier.start is not None
                and earlier.start < match.start
                and earlier.opponent(self.team_id).id == opponent
                and earlier.status in RESULT_STATUSES
                and earlier.has_score
            ),
            None,
        )


def match_result(match: Match, team_id: int) -> str | None:
    """Return win, draw or loss for a team (on the score; a shoot-out keeps a draw)."""
    if (goals := match.goals(team_id)) is None:
        return None
    goals_for, goals_against = goals
    if goals_for > goals_against:
        return "win"
    if goals_for < goals_against:
        return "loss"
    return "draw"


def _sort_key(match: Match) -> tuple[bool, datetime]:
    return (match.start is None, match.start or datetime.max.replace(tzinfo=dt_util.UTC))


class KnhbCoordinator(DataUpdateCoordinator[TeamData]):
    """Fetches a team's page (standings and matches) and its other pools of the season."""

    config_entry: KnhbConfigEntry

    def __init__(self, hass: HomeAssistant, entry: KnhbConfigEntry, client: KnhbClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.team_id: int = entry.data[CONF_TEAM_ID]
        self.match_duration = match_duration(
            entry.data.get(CONF_HOCKEY_TYPE), entry.data.get(CONF_CATEGORY)
        )
        # Other pools of this season: poule id -> (fetched at, own matches)
        self._extra: dict[int, tuple[datetime, list[Match]]] = {}
        # Weather of the next match: (match id, fetched at, forecast)
        self._weather: tuple[int, datetime, MatchWeather | None] | None = None
        # The matches as last seen, to notice changes; kept across restarts.
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._states: dict[int, MatchState] = {}

    async def _async_setup(self) -> None:
        """Load the matches as they were before Home Assistant stopped."""
        stored = await self._store.async_load()
        matches = stored.get("matches") if isinstance(stored, dict) else None
        if isinstance(matches, dict):
            for key, value in matches.items():
                if str(key).isdigit() and (state := MatchState.from_dict(value)) is not None:
                    self._states[int(key)] = state

    def meet_time(self, match: Match | None) -> datetime | None:
        """Return when the team meets for a match: kick-off minus the configured minutes."""
        if match is None or match.start is None:
            return None
        options = self.config_entry.options
        if match.is_home(self.team_id):
            minutes = options.get(CONF_MEET_MINUTES_HOME, DEFAULT_MEET_MINUTES)
        else:
            minutes = options.get(CONF_MEET_MINUTES_AWAY, DEFAULT_MEET_MINUTES)
        return match.start - timedelta(minutes=minutes)

    async def _async_update_data(self) -> TeamData:
        try:
            data, deferred = await self._fetch(dt_util.utcnow())
        except KnhbRateLimitError as err:
            raise UpdateFailed(
                retry_after=err.retry_after,
                translation_domain=DOMAIN,
                translation_key="rate_limited",
            ) from err
        except KnhbNotFoundError as err:
            raise UpdateFailed(translation_domain=DOMAIN, translation_key="team_not_found") from err
        except KnhbConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err
        except KnhbError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="unexpected_response",
                translation_placeholders={"error": str(err)},
            ) from err
        self.update_interval = self._next_interval(data, dt_util.utcnow(), deferred)
        return data

    async def _fetch(self, now: datetime) -> tuple[TeamData, bool]:
        """Fetch the team's data; also return whether some work was put off till soon.

        The first refresh after start-up fetches only the team page, so that a Home
        Assistant with several teams starts with one request per team; the club check
        and the season's other pools follow a minute later.
        """
        starting = self.data is None
        deferred = False
        if self._club_check_due(now):
            if starting:
                deferred = True
            else:
                await self._refresh_poule_id(now)
        poule_id: int = self.config_entry.data[CONF_POULE_ID]
        try:
            page = await self.client.get_team_page(poule_id, self.team_id)
        except KnhbNotFoundError as err:
            # The pool is gone: look the team up in its club again, then retry once.
            if await self._refresh_poule_id(now) == poule_id:
                raise KnhbResponseError(f"Pool {poule_id} not found") from err
            poule_id = self.config_entry.data[CONF_POULE_ID]
            page = await self.client.get_team_page(poule_id, self.team_id)

        matches = {match.id: match for match in page.own_matches(self.team_id)}
        if await self._fetch_extra_poules(page.same_season_poules(), now):
            deferred = True
        for _fetched, extra_matches in self._extra.values():
            for match in extra_matches:
                matches.setdefault(match.id, match)

        primary = next((p for p in page.poules if p.id == poule_id), None)
        if primary is None and page.poules:
            primary = page.poules[0]
        own = sorted(matches.values(), key=_sort_key)
        data = TeamData(
            team_id=self.team_id,
            match_duration=self.match_duration,
            matches=own,
            standings=primary.standings if primary else [],
            competition=(primary.competition if primary else None) or page.competition,
            poule=primary.name if primary else None,
            poule_id=poule_id,
            poule_matches=sorted(primary.matches, key=_sort_key) if primary else [],
            team_logo=next(
                (
                    (m.home if m.is_home(self.team_id) else m.away).logo
                    for m in own
                    if (m.home if m.is_home(self.team_id) else m.away).logo
                ),
                None,
            ),
        )
        if await self._update_weather(data.next_match(now), now, starting):
            deferred = True
        if self._weather is not None:
            data.weather_match_id, _fetched, data.weather = self._weather
        data.changes = detect_changes(self._states, own)
        await self._remember(own, now)
        return data, deferred

    async def _update_weather(self, match: Match | None, now: datetime, starting: bool) -> bool:
        """Fetch the weather forecast of the next match when due; return whether deferred."""
        if match is None or match.start is None or match.start - now > WEATHER_AHEAD:
            self._weather = None
            return False
        cached = self._weather if self._weather and self._weather[0] == match.id else None
        if cached is not None and now - cached[1] < WEATHER_REFRESH:
            return False
        if starting:
            return True
        try:
            detail = await self.client.get_match(match.id)
        except KnhbRateLimitError:
            return True
        except KnhbError as err:
            LOGGER.debug("Could not fetch the weather for match %s: %s", match.id, err)
            self._weather = (match.id, now, cached[2] if cached else None)
            return False
        self._weather = (match.id, now, detail.weather)
        return False

    async def _remember(self, matches: list[Match], now: datetime) -> None:
        """Remember the matches as they are now, and store them if anything changed.

        Saved at once (it rarely changes), so a reload right after a change does not
        report the change again.
        """
        states = updated_states(self._states, matches, now)
        if states == self._states:
            return
        self._states = states
        await self._store.async_save(
            {"matches": {str(key): value.as_dict() for key, value in states.items()}}
        )

    def _club_check_due(self, now: datetime) -> bool:
        checked = self.config_entry.data.get(CONF_POULE_CHECKED)
        checked_at = dt_util.parse_datetime(checked) if checked else None
        return checked_at is None or now - checked_at >= CLUB_REFRESH_INTERVAL

    async def _refresh_poule_id(self, now: datetime) -> int:
        """Look up the team's current pool in its club's team list, and store it."""
        entry_data = self.config_entry.data
        detail = await self.client.get_club(entry_data[CONF_CLUB_ID])
        team = next((t for t in detail.teams if t.id == self.team_id), None)
        if team is None:
            raise KnhbNotFoundError(f"Team {self.team_id} is no longer in its club")
        poule_id = team.recent_poule_id or entry_data[CONF_POULE_ID]
        if poule_id != entry_data[CONF_POULE_ID]:
            LOGGER.debug("Team %s moved to pool %s", self.team_id, poule_id)
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={
                **entry_data,
                CONF_POULE_ID: poule_id,
                CONF_POULE_CHECKED: now.isoformat(),
            },
        )
        return poule_id

    async def _fetch_extra_poules(self, poule_ids: list[int], now: datetime) -> bool:
        """Fetch the team's other pools of this season that are due.

        Returns whether some are still to be fetched: the first refresh after start-up
        skips them, to keep Home Assistant's start-up light on the API.
        """
        for poule_id in list(self._extra):
            if poule_id not in poule_ids:
                del self._extra[poule_id]
        due = [pid for pid in poule_ids if self._extra_due(pid, now)]
        if not due:
            return False
        if self.data is None:
            return True
        for poule_id in due:
            try:
                page = await self.client.get_team_page(poule_id, self.team_id)
            except KnhbRateLimitError:
                LOGGER.debug("Rate limited, fetching pool %s later", poule_id)
                return True
            except KnhbError as err:
                # Try again with the regular refresh of these pools, not on every update.
                LOGGER.debug("Could not fetch pool %s: %s", poule_id, err)
                self._extra[poule_id] = (now, [])
                continue
            self._extra[poule_id] = (now, page.own_matches(self.team_id))
        return False

    def _extra_due(self, poule_id: int, now: datetime) -> bool:
        if (cached := self._extra.get(poule_id)) is None:
            return True
        fetched, matches = cached
        if now - fetched >= EXTRA_POULE_REFRESH_INTERVAL:
            return True
        return any(_around_match(match, now) for match in matches)

    def _next_interval(self, data: TeamData, now: datetime, deferred: bool) -> timedelta:
        """Poll more often around the team's own matches, less often without any."""
        if deferred:
            return UPDATE_INTERVAL_SOON
        if any(_around_match(match, now) for match in data.matches):
            return UPDATE_INTERVAL_MATCH
        upcoming = [
            match.start
            for match in data.matches
            if match.start and match.start > now and match.status not in STATUSES_DONE
        ]
        if not upcoming:
            return UPDATE_INTERVAL_IDLE
        until_lead = min(upcoming) - MATCH_LEAD - now
        if until_lead < UPDATE_INTERVAL:
            return max(until_lead, UPDATE_INTERVAL_SOON)
        return UPDATE_INTERVAL


def _around_match(match: Match, now: datetime) -> bool:
    """Return whether a match is about to start, playing, or waiting for its result."""
    if match.start is None or match.status in STATUSES_DONE:
        return False
    return match.start - MATCH_LEAD <= now <= match.start + RESULT_WAIT
