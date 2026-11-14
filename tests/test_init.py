"""Tests for setting up a team: coordinator, sensors, calendar, diagnostics."""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import json_bytes
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.knhb_hockey.const import (
    CONF_POULE_CHECKED,
    CONF_POULE_ID,
    CONF_TOKEN,
    UPDATE_INTERVAL,
    UPDATE_INTERVAL_IDLE,
    UPDATE_INTERVAL_MATCH,
    UPDATE_INTERVAL_SOON,
)
from custom_components.knhb_hockey.diagnostics import async_get_config_entry_diagnostics

from .conftest import (
    NOW,
    URL_CLUB,
    URL_CLUBS,
    URL_EXTRA_PAGE,
    URL_MATCH,
    URL_REGISTER,
    URL_TEAM_PAGE,
    calls_to,
    load_fixture,
)

CALENDAR = "calendar.voorbeeld_jo14_2"
NEXT_MATCH = "sensor.voorbeeld_jo14_2_next_match"
LAST_RESULT = "sensor.voorbeeld_jo14_2_last_result"
STANDING = "sensor.voorbeeld_jo14_2_standing"

pytestmark = pytest.mark.usefixtures("dutch_time")


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_setup_and_entities(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The team gets a calendar and three sensors from one request."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    # Only the team page: the club was checked an hour ago, the extra pool comes later.
    assert [str(call[1]) for call in mock_api.mock_calls] == [URL_TEAM_PAGE]

    state = hass.states.get(NEXT_MATCH)
    assert state.state == "2026-11-14T11:00:00+00:00"
    assert state.attributes["opponent"] == "Fictief JO14-3"
    assert state.attributes["home_away"] == "home"
    assert state.attributes["field"] == "Veld 2"
    assert state.attributes["venue"] == "Sportpark Voorbeeld"
    assert state.attributes["address"] == "Voorbeeldlaan 1, 1234AB Voorbeeldstad"
    assert state.attributes["remarks"] == "Graag 30 minuten eerder aanwezig"
    assert state.attributes["end"] == "2026-11-14T13:30:00+01:00"

    state = hass.states.get(LAST_RESULT)
    assert state.state == "draw"
    assert state.attributes["score"] == "2–2, SO 3–4"
    assert state.attributes["home_away"] == "away"
    assert state.attributes["goals_for"] == 2

    state = hass.states.get(STANDING)
    assert state.state == "2"
    assert state.attributes["points"] == 4
    assert state.attributes["goal_difference"] == 2
    assert state.attributes["teams"] == 4
    assert state.attributes["table"][0] == {
        "rank": 1,
        "team": "De Proef JO14-1",
        "played": 2,
        "points": 6,
        "goal_difference": 6,
    }

    state = hass.states.get(CALENDAR)
    assert state.state == "off"
    assert state.attributes["message"] == "Voorbeeld JO14-2 – Fictief JO14-3"
    assert state.attributes["location"] == (
        "Sportpark Voorbeeld, Voorbeeldlaan 1, 1234AB Voorbeeldstad"
    )
    assert state.attributes["description"] == (
        "Veld 2 (Kunstgras)\nJongens O14 Test – Jongens O14 Test - Poule A\n"
        "Graag 30 minuten eerder aanwezig"
    )


async def test_calendar_events(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The calendar lists own matches with scores, without cancelled matches."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {"entity_id": CALENDAR, "start_date_time": "2026-10-01T00:00:00", "duration": {"days": 60}},
        blocking=True,
        return_response=True,
    )
    events = response[CALENDAR]["events"]
    assert [event["summary"] for event in events] == [
        "Voorbeeld JO14-2 – De Proef JO14-1 (3–1)",
        "Fictief JO14-3 – Voorbeeld JO14-2 (2–2, SO 3–4)",
        "Voorbeeld JO14-2 – Fictief JO14-3",
        "Proefstad JO14-1 – Voorbeeld JO14-2",
    ]
    assert events[0]["start"] == "2026-10-31T10:00:00+01:00"
    assert events[0]["end"] == "2026-10-31T11:30:00+01:00"
    assert events[0]["description"].startswith("Veld 1 (Waterveld)\n")


async def test_extra_poule_fetched_after_start(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The season's other pool is fetched a minute after start-up, then every 6 hours."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    coordinator = config_entry.runtime_data
    assert coordinator.update_interval == UPDATE_INTERVAL_SOON
    assert calls_to(mock_api, URL_EXTRA_PAGE) == 0

    await _tick(hass, freezer, UPDATE_INTERVAL_SOON)
    assert calls_to(mock_api, URL_EXTRA_PAGE) == 1
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {"entity_id": CALENDAR, "start_date_time": "2026-09-01T00:00:00", "duration": {"days": 30}},
        blocking=True,
        return_response=True,
    )
    assert [e["summary"] for e in response[CALENDAR]["events"]] == [
        "Voorbeeld JO14-2 – Nergenshuizen JO14-2 (5–0)"
    ]
    # Next match at 12:00, so poll often from 11:30: in 2.5 h at 08:01 UTC is too far.
    assert coordinator.update_interval == UPDATE_INTERVAL

    await _tick(hass, freezer, UPDATE_INTERVAL)
    assert calls_to(mock_api, URL_EXTRA_PAGE) == 1
    assert calls_to(mock_api, URL_TEAM_PAGE) == 3


async def test_polls_often_around_match(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """From half an hour before a match until its result, poll every 5 minutes."""
    freezer.move_to("2026-11-14T10:45:00+00:00")
    await _setup(hass, config_entry)
    await _tick(hass, freezer, UPDATE_INTERVAL_SOON)
    assert config_entry.runtime_data.update_interval == UPDATE_INTERVAL_MATCH
    assert hass.states.get(CALENDAR).state == "off"

    # Kick-off at 12:00 (11:00 UTC): the calendar turns on, polling stays frequent.
    await _tick(hass, freezer, timedelta(minutes=15))
    assert hass.states.get(CALENDAR).state == "on"
    assert config_entry.runtime_data.update_interval == UPDATE_INTERVAL_MATCH


async def test_idle_without_upcoming_matches(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """After the last match of the season, poll every 2 hours."""
    freezer.move_to("2026-12-20T10:00:00+00:00")
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_POULE_CHECKED: "2026-12-20T09:00:00+00:00"}
    )
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _tick(hass, freezer, UPDATE_INTERVAL_SOON)
    assert config_entry.runtime_data.update_interval == UPDATE_INTERVAL_IDLE
    assert hass.states.get(NEXT_MATCH).state == "unknown"
    assert hass.states.get(LAST_RESULT).state == "draw"


async def test_club_checked_twice_a_day(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The team's pool is looked up in its club when the last check is 12 h old.

    Not during start-up, which fetches only the team page, but a minute later.
    """
    freezer.move_to("2026-11-14T19:30:00+00:00")
    await _setup(hass, config_entry)
    assert calls_to(mock_api, URL_CLUB) == 0
    assert config_entry.runtime_data.update_interval == UPDATE_INTERVAL_SOON

    await _tick(hass, freezer, UPDATE_INTERVAL_SOON)
    assert calls_to(mock_api, URL_CLUB) == 1
    assert config_entry.data[CONF_POULE_CHECKED] == "2026-11-14T19:31:00+00:00"

    await _tick(hass, freezer, UPDATE_INTERVAL_IDLE)
    assert calls_to(mock_api, URL_CLUB) == 1


async def test_moved_to_new_poule(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """When the pool is gone, the team is looked up again and followed to its new pool."""
    freezer.move_to(NOW)
    club = load_fixture("club.json")
    for team in club["data"]["teams"]:
        if team["id"] == 1001:
            team["recent_poule_id"] = 6001
    aioclient_mock.get(URL_TEAM_PAGE, status=HTTPStatus.NOT_FOUND)
    aioclient_mock.get(URL_CLUB, json=club)
    aioclient_mock.get(URL_TEAM_PAGE.replace("5001", "6001"), json=load_fixture("team_page.json"))
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.data[CONF_POULE_ID] == 6001


async def test_team_gone(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A team that is no longer in its club fails setup (and is retried)."""
    freezer.move_to(NOW)
    club = load_fixture("club.json")
    club["data"]["teams"] = [t for t in club["data"]["teams"] if t["id"] != 1001]
    aioclient_mock.get(URL_TEAM_PAGE, status=HTTPStatus.NOT_FOUND)
    aioclient_mock.get(URL_CLUB, json=club)
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_new_token_is_stored(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A token from registering again is saved in the config entry."""
    freezer.move_to(NOW)
    calls = 0

    async def respond(method, url, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return AiohttpClientMockResponse("get", url, status=HTTPStatus.UNAUTHORIZED)
        return AiohttpClientMockResponse("get", url, json=load_fixture("team_page.json"))

    aioclient_mock.get(URL_TEAM_PAGE, side_effect=respond)
    aioclient_mock.post(URL_REGISTER, json={"token": "new-token"}, status=201)
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.data[CONF_TOKEN] == "new-token"


@pytest.mark.parametrize(
    ("status", "headers"),
    [
        (HTTPStatus.TOO_MANY_REQUESTS, {"Retry-After": "300"}),
        (HTTPStatus.SERVICE_UNAVAILABLE, {}),
    ],
)
async def test_setup_retry(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    status: int,
    headers: dict[str, str],
) -> None:
    """Rate limiting and server errors retry the setup later."""
    freezer.move_to(NOW)
    aioclient_mock.get(URL_TEAM_PAGE, status=status, headers=headers)
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unavailable_after_error_and_back(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Entities go unavailable on a failed update and recover on the next."""
    freezer.move_to(NOW)
    aioclient_mock.get(URL_TEAM_PAGE, json=load_fixture("team_page.json"))
    aioclient_mock.get(URL_EXTRA_PAGE, json=load_fixture("team_page_extra.json"))
    aioclient_mock.get(URL_MATCH, json=load_fixture("match_detail.json"))
    await _setup(hass, config_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(URL_TEAM_PAGE, exc=TimeoutError())
    await _tick(hass, freezer, UPDATE_INTERVAL_SOON)
    assert hass.states.get(STANDING).state == "unavailable"

    aioclient_mock.clear_requests()
    aioclient_mock.get(URL_TEAM_PAGE, json=load_fixture("team_page.json"))
    aioclient_mock.get(URL_EXTRA_PAGE, json=load_fixture("team_page_extra.json"))
    aioclient_mock.get(URL_MATCH, json=load_fixture("match_detail.json"))
    await _tick(hass, freezer, UPDATE_INTERVAL)
    assert hass.states.get(STANDING).state == "2"


async def test_unload(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A team can be unloaded."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Diagnostics hide the device token and uuid."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    json_bytes(diagnostics)  # what Home Assistant does with it; must not raise
    assert diagnostics["entry"]["token"] == "**REDACTED**"
    assert diagnostics["entry"]["device_uuid"] == "**REDACTED**"
    assert len(diagnostics["data"]["matches"]) == 5
    assert "stored-token" not in str(diagnostics)


async def test_not_requested_without_need(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Setting up never fetches the full club list."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    await _tick(hass, freezer, UPDATE_INTERVAL_SOON)
    assert calls_to(mock_api, URL_CLUBS) == 0


async def test_extra_poule_error_not_retried_every_update(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A pool that fails is tried again with the 6-hourly refresh, not every update."""
    freezer.move_to("2026-11-14T06:00:00+00:00")
    aioclient_mock.get(URL_TEAM_PAGE, json=load_fixture("team_page.json"))
    aioclient_mock.get(URL_EXTRA_PAGE, status=HTTPStatus.BAD_GATEWAY)
    aioclient_mock.get(URL_MATCH, json=load_fixture("match_detail.json"))
    await _setup(hass, config_entry)
    await _tick(hass, freezer, UPDATE_INTERVAL_SOON)
    assert calls_to(aioclient_mock, URL_EXTRA_PAGE) == 1
    assert hass.states.get(STANDING).state == "2"

    await _tick(hass, freezer, UPDATE_INTERVAL)
    assert calls_to(aioclient_mock, URL_EXTRA_PAGE) == 1


async def test_poule_gone_but_still_listed(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A 404 on the pool the club still lists is retried later."""
    freezer.move_to(NOW)
    aioclient_mock.get(URL_TEAM_PAGE, status=HTTPStatus.NOT_FOUND)
    aioclient_mock.get(URL_CLUB, json=load_fixture("club.json"))
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert calls_to(aioclient_mock, URL_CLUB) == 1
