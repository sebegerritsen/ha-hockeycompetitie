"""Tests for the config flow."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.hockeycompetitie.config_flow import team_label, team_sort_key
from custom_components.hockeycompetitie.const import (
    CONF_CATEGORY,
    CONF_CLUB_ID,
    CONF_CLUB_NAME,
    CONF_DEVICE_UUID,
    CONF_HOCKEY_TYPE,
    CONF_POULE_CHECKED,
    CONF_POULE_ID,
    CONF_TEAM_ID,
    CONF_TEAM_NAME,
    CONF_TEAM_SHORT_NAME,
    CONF_TOKEN,
    DOMAIN,
)
from custom_components.hockeycompetitie.models import Team

from .conftest import URL_CLUB, URL_CLUBS, URL_REGISTER, load_fixture


async def _start(hass: HomeAssistant) -> dict[str, Any]:
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})


def _options(result: dict[str, Any], key: str) -> list[dict[str, str]]:
    schema = result["data_schema"].schema
    selector = next(value for marker, value in schema.items() if marker == key)
    return selector.config["options"]


async def test_one_club_found(hass: HomeAssistant, mock_api: AiohttpClientMocker) -> None:
    """A search with one hit goes straight to that club's teams."""
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"query": "voorbeeldstad"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "team"
    # Field before indoor, seniors before juniors before the youngest; no team
    # without a competition.
    assert [option["label"] for option in _options(result, CONF_TEAM_ID)] == [
        "D1 · Veld · Senioren",
        "JO14-2 · Veld · Junioren",
        "MO10-1 · Veld · Jongste jeugd",
        "zJO14-2 · Zaal · Junioren",
    ]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TEAM_ID: "1001"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Voorbeeld JO14-2"
    assert result["result"].unique_id == "1001"
    data = result["data"]
    assert data[CONF_POULE_CHECKED]
    assert data[CONF_DEVICE_UUID]
    assert {k: v for k, v in data.items() if k not in (CONF_POULE_CHECKED, CONF_DEVICE_UUID)} == {
        CONF_CLUB_ID: "HV00AA1",
        CONF_CLUB_NAME: "HC Voorbeeld",
        CONF_TEAM_ID: 1001,
        CONF_TEAM_NAME: "Voorbeeld JO14-2",
        CONF_TEAM_SHORT_NAME: "JO14-2",
        CONF_HOCKEY_TYPE: "VE",
        CONF_CATEGORY: "Junioren",
        CONF_POULE_ID: 5001,
        CONF_TOKEN: "new-token",
    }


async def test_several_clubs_found(hass: HomeAssistant, mock_api: AiohttpClientMocker) -> None:
    """A search with several hits asks which club."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "HC "})
    assert result["step_id"] == "club"
    assert [option["label"] for option in _options(result, CONF_CLUB_ID)] == [
        "HC Fictief · Nergenshuizen",
        "HC Voorbeeld · Voorbeeldstad",
        "MHC De Proef · Testdorp",
    ]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CLUB_ID: "HV00AA1"}
    )
    assert result["step_id"] == "team"
    assert result["description_placeholders"] == {"club": "HC Voorbeeld"}


async def test_no_club_found(hass: HomeAssistant, mock_api: AiohttpClientMocker) -> None:
    """A search without hits asks again, without fetching the clubs again."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "xyz"})
    assert result["step_id"] == "user"
    assert result["errors"] == {"query": "no_clubs_found"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"query": "Voorbeeld"}
    )
    assert result["step_id"] == "team"
    clubs_calls = [call for call in mock_api.mock_calls if str(call[1]) == URL_CLUBS]
    assert len(clubs_calls) == 1


async def test_cannot_connect(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A connection error shows an error and lets the user try again."""
    aioclient_mock.post(URL_REGISTER, json={"token": "new-token"}, status=201)
    aioclient_mock.get(URL_CLUBS, exc=TimeoutError())
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"query": "voorbeeld"}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(URL_CLUBS, json=load_fixture("clubs.json"))
    aioclient_mock.get(URL_CLUB, json=load_fixture("club.json"))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"query": "voorbeeld"}
    )
    assert result["step_id"] == "team"


async def test_rate_limited(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Hitting the rate limit says so."""
    aioclient_mock.post(URL_REGISTER, json={"token": "new-token"}, status=201)
    aioclient_mock.get(URL_CLUBS, status=429, headers={"Retry-After": "300"})
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"query": "voorbeeld"}
    )
    assert result["errors"] == {"base": "rate_limited"}


async def test_club_error(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """An error fetching the club's teams shows on the club step."""
    aioclient_mock.post(URL_REGISTER, json={"token": "new-token"}, status=201)
    aioclient_mock.get(URL_CLUBS, json=load_fixture("clubs.json"))
    aioclient_mock.get(URL_CLUB, status=502)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"query": "voorbeeld"}
    )
    assert result["step_id"] == "club"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_already_configured(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """A team can be added only once."""
    config_entry.add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"query": "voorbeeld"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TEAM_ID: "1001"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_club_without_teams(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A club without teams in a competition aborts."""
    club = load_fixture("club.json")
    club["data"]["teams"] = [t | {"recent_poule_id": None} for t in club["data"]["teams"]]
    aioclient_mock.post(URL_REGISTER, json={"token": "new-token"}, status=201)
    aioclient_mock.get(URL_CLUBS, json=load_fixture("clubs.json"))
    aioclient_mock.get(URL_CLUB, json=club)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"query": "voorbeeld"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_teams"


def test_team_label_and_sort() -> None:
    """Labels name type and age group; numbers in names sort as numbers."""

    def team(short: str, hockey_type: str = "VE", category: str = "Junioren") -> Team:
        return Team(1, short, short, hockey_type, category, 1, "X", None)

    assert team_label(team("JO14-2")) == "JO14-2 · Veld · Junioren"
    names = ["JO16-1", "JO8-1", "JO10-2", "JO10-10"]
    teams = sorted((team(name) for name in names), key=team_sort_key)
    assert [t.short_name for t in teams] == ["JO8-1", "JO10-2", "JO10-10", "JO16-1"]
