"""Fixtures for the Hockeycompetitie tests. All clubs, teams and people in them are made up."""

from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.hockeycompetitie.api import BASE_URL, RequestThrottle
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

FIXTURES = Path(__file__).parent / "fixtures"

CLUB_ID = "HV00AA1"
TEAM_ID = 1001
POULE_ID = 5001
EXTRA_POULE_ID = 4001
DEVICE_UUID = "0f0e0d0c-0b0a-4000-8000-000000000001"

# Saturday 14 November 2026, 09:00 in the Netherlands: the team plays at 12:00.
NOW = "2026-11-14T08:00:00+00:00"

URL_REGISTER = f"{BASE_URL}/device/register"
URL_CLUBS = f"{BASE_URL}/clubs"
URL_CLUB = f"{BASE_URL}/clubs/{CLUB_ID}"
URL_TEAM_PAGE = f"{BASE_URL}/poules/{POULE_ID}/teams/{TEAM_ID}"
URL_EXTRA_PAGE = f"{BASE_URL}/poules/{EXTRA_POULE_ID}/teams/{TEAM_ID}"
URL_MATCH = f"{BASE_URL}/matches/9003"


def load_fixture(name: str) -> Any:
    """Load a JSON fixture."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture(autouse=True)
def no_throttle() -> Generator[None]:
    """Don't space requests out in tests (the throttle has its own tests)."""
    with patch(
        "custom_components.hockeycompetitie.helpers.RequestThrottle",
        lambda: RequestThrottle(max_requests=1000),
    ):
        yield


@pytest.fixture
async def dutch_time(hass: Any) -> None:
    """Run Home Assistant in Dutch time."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")


@pytest.fixture
def entry_data() -> dict[str, Any]:
    """Return the data of a configured team."""
    return {
        CONF_CLUB_ID: CLUB_ID,
        CONF_CLUB_NAME: "HC Voorbeeld",
        CONF_TEAM_ID: TEAM_ID,
        CONF_TEAM_NAME: "Voorbeeld JO14-2",
        CONF_TEAM_SHORT_NAME: "JO14-2",
        CONF_HOCKEY_TYPE: "VE",
        CONF_CATEGORY: "Junioren",
        CONF_POULE_ID: POULE_ID,
        CONF_POULE_CHECKED: "2026-11-14T07:00:00+00:00",
        CONF_DEVICE_UUID: DEVICE_UUID,
        CONF_TOKEN: "stored-token",
    }


@pytest.fixture
def config_entry(entry_data: dict[str, Any]) -> MockConfigEntry:
    """Return a config entry for the team."""
    return MockConfigEntry(
        domain=DOMAIN, title="Voorbeeld JO14-2", unique_id=str(TEAM_ID), data=entry_data
    )


@pytest.fixture
def mock_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Answer every endpoint the integration uses with the fixtures."""
    aioclient_mock.post(URL_REGISTER, json={"token": "new-token"}, status=201)
    aioclient_mock.get(URL_CLUBS, json=load_fixture("clubs.json"))
    aioclient_mock.get(URL_CLUB, json=load_fixture("club.json"))
    aioclient_mock.get(URL_TEAM_PAGE, json=load_fixture("team_page.json"))
    aioclient_mock.get(URL_EXTRA_PAGE, json=load_fixture("team_page_extra.json"))
    aioclient_mock.get(URL_MATCH, json=load_fixture("match_detail.json"))
    return aioclient_mock


def calls_to(mock: AiohttpClientMocker, url: str) -> int:
    """Return how many requests went to a URL."""
    return sum(1 for _method, called, _data, _headers in mock.mock_calls if str(called) == url)
