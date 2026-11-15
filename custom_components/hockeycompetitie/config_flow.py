"""Config flow: search a club, pick one of its teams."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .api import KnhbClient, KnhbError, KnhbRateLimitError
from .const import (
    CONF_CATEGORY,
    CONF_CLUB_ID,
    CONF_CLUB_NAME,
    CONF_DEVICE_UUID,
    CONF_HOCKEY_TYPE,
    CONF_MEET_MINUTES_AWAY,
    CONF_MEET_MINUTES_HOME,
    CONF_POULE_CHECKED,
    CONF_POULE_ID,
    CONF_TEAM_ID,
    CONF_TEAM_NAME,
    CONF_TEAM_SHORT_NAME,
    CONF_TOKEN,
    DEFAULT_MEET_MINUTES,
    DOMAIN,
    HOCKEY_TYPE_FIELD,
    HOCKEY_TYPE_INDOOR,
)
from .entity import HOCKEY_TYPE_NAMES
from .helpers import async_get_client
from .models import Club, ClubDetail, Team

CONF_QUERY = "query"

HOCKEY_TYPE_ORDER = {HOCKEY_TYPE_FIELD: 0, HOCKEY_TYPE_INDOOR: 1}
CATEGORY_ORDER = {"Senioren": 0, "Junioren": 1, "Jongste jeugd": 2}
# Show a short list of clubs as radio buttons, a longer one as a dropdown.
LIST_MODE_MAX = 6


def club_label(club: Club) -> str:
    """Return a club's label, such as `HC Example · Utrecht`."""
    return f"{club.name} · {club.city}" if club.city else club.name


def team_label(team: Team) -> str:
    """Return a team's label, such as `JO14-2 · Veld · Junioren`."""
    parts = [
        team.short_name,
        HOCKEY_TYPE_NAMES.get(team.hockey_type or "", team.hockey_type),
        team.category,
    ]
    return " · ".join(part for part in parts if part)


def _natural_key(text: str) -> list[Any]:
    """Sort JO8 before JO10: compare the digits in a name as numbers."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", text)]


def team_sort_key(team: Team) -> tuple[Any, ...]:
    """Sort field before indoor, seniors before juniors before the youngest, then by name."""
    return (
        HOCKEY_TYPE_ORDER.get(team.hockey_type or "", 9),
        CATEGORY_ORDER.get(team.category or "", 9),
        _natural_key(team.short_name),
    )


class KnhbConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a team: search its club, then pick it from the club's teams."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> KnhbOptionsFlow:
        """Return the options flow."""
        return KnhbOptionsFlow()

    def __init__(self) -> None:
        """Initialize the flow."""
        self._client: KnhbClient | None = None
        self._clubs: list[Club] = []
        self._found: list[Club] = []
        self._club: ClubDetail | None = None

    @property
    def client(self) -> KnhbClient:
        """Return the flow's API client (it registers a device on first use)."""
        if self._client is None:
            self._client = async_get_client(self.hass)
        return self._client

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for (part of) the club's name or town."""
        errors: dict[str, str] = {}
        if user_input is not None:
            query = user_input[CONF_QUERY].strip()
            try:
                if not self._clubs:
                    self._clubs = await self.client.get_clubs()
            except KnhbRateLimitError:
                errors["base"] = "rate_limited"
            except KnhbError:
                errors["base"] = "cannot_connect"
            else:
                self._found = sorted(
                    (club for club in self._clubs if club.matches_query(query)),
                    key=lambda club: club.name.casefold(),
                )
                if not self._found:
                    errors[CONF_QUERY] = "no_clubs_found"
                elif len(self._found) == 1:
                    return await self.async_step_club({CONF_CLUB_ID: self._found[0].id})
                else:
                    return await self.async_step_club()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_QUERY): TextSelector()}), user_input
            ),
            errors=errors,
        )

    async def async_step_club(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick the club from the search results."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._club = await self.client.get_club(user_input[CONF_CLUB_ID])
            except KnhbRateLimitError:
                errors["base"] = "rate_limited"
            except KnhbError:
                errors["base"] = "cannot_connect"
            else:
                return await self.async_step_team()
        options = [SelectOptionDict(value=club.id, label=club_label(club)) for club in self._found]
        return self.async_show_form(
            step_id="club",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLUB_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST
                            if len(options) <= LIST_MODE_MAX
                            else SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_team(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick the team."""
        assert self._club is not None
        teams = sorted(
            (team for team in self._club.teams if team.recent_poule_id is not None),
            key=team_sort_key,
        )
        if not teams:
            return self.async_abort(
                reason="no_teams", description_placeholders={"club": self._club.club.name}
            )
        if user_input is not None:
            team = next(t for t in teams if str(t.id) == user_input[CONF_TEAM_ID])
            await self.async_set_unique_id(str(team.id))
            self._abort_if_unique_id_configured()
            assert team.recent_poule_id is not None
            return self.async_create_entry(
                title=team.name,
                data={
                    CONF_CLUB_ID: self._club.club.id,
                    CONF_CLUB_NAME: self._club.club.name,
                    CONF_TEAM_ID: team.id,
                    CONF_TEAM_NAME: team.name,
                    CONF_TEAM_SHORT_NAME: team.short_name,
                    CONF_HOCKEY_TYPE: team.hockey_type,
                    CONF_CATEGORY: team.category,
                    CONF_POULE_ID: team.recent_poule_id,
                    CONF_POULE_CHECKED: dt_util.utcnow().isoformat(),
                    CONF_DEVICE_UUID: self.client.device_uuid,
                    CONF_TOKEN: self.client.token,
                },
            )
        options = [SelectOptionDict(value=str(team.id), label=team_label(team)) for team in teams]
        return self.async_show_form(
            step_id="team",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TEAM_ID): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
            description_placeholders={"club": self._club.club.name},
        )


MEET_MINUTES_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=0, max=180, step=5, unit_of_measurement="min", mode=NumberSelectorMode.BOX
    )
)


class KnhbOptionsFlow(OptionsFlow):
    """Options: when the team meets before kick-off."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the meet time, home and away."""
        if user_input is not None:
            return self.async_create_entry(
                data={key: int(value) for key, value in user_input.items()}
            )
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MEET_MINUTES_HOME,
                        default=options.get(CONF_MEET_MINUTES_HOME, DEFAULT_MEET_MINUTES),
                    ): MEET_MINUTES_SELECTOR,
                    vol.Required(
                        CONF_MEET_MINUTES_AWAY,
                        default=options.get(CONF_MEET_MINUTES_AWAY, DEFAULT_MEET_MINUTES),
                    ): MEET_MINUTES_SELECTOR,
                }
            ),
        )
