"""Tests for change alerts, meet time, match today, weather, opponent info and options."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.hockeycompetitie.const import (
    CONF_MEET_MINUTES_AWAY,
    CONF_MEET_MINUTES_HOME,
    DOMAIN,
    UPDATE_INTERVAL,
    UPDATE_INTERVAL_SOON,
)

from .conftest import NOW, URL_MATCH, URL_TEAM_PAGE, calls_to, load_fixture

EVENT = "event.voorbeeld_jo14_2_match_update"
MEET_TIME = "sensor.voorbeeld_jo14_2_meet_time"
NEXT_MATCH = "sensor.voorbeeld_jo14_2_next_match"
STANDING = "sensor.voorbeeld_jo14_2_standing"
WEATHER = "sensor.voorbeeld_jo14_2_weather_at_next_match"
MATCH_TODAY = "binary_sensor.voorbeeld_jo14_2_match_today"

pytestmark = pytest.mark.usefixtures("dutch_time")


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _fired(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Collect the events the event entity fires."""
    fired: list[dict[str, Any]] = []

    @callback  # in the event loop, in order (a plain function would run in a thread)
    def listener(event: Event) -> None:
        new = event.data["new_state"]
        if event.data["entity_id"] == EVENT and new and new.state not in ("unknown", "unavailable"):
            fired.append(dict(new.attributes))

    hass.bus.async_listen(EVENT_STATE_CHANGED, listener)
    return fired


def _stored(entry: MockConfigEntry, changes: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Return storage as it was before a restart: the fixture's matches, with changes."""
    matches = {}
    page = load_fixture("team_page.json")["data"]["poules"][0]["matches"]
    for match in page:
        if 1001 not in (match["home"]["id"], match["away"]["id"]):
            continue
        final = match["status"] == "final"
        matches[str(match["id"])] = {
            "status": match["status"],
            "start": match["date"],
            "facility": "Sportpark Voorbeeld",
            "field": match["location"]["field"]["name"],
            "score": [match["score"]["home"], match["score"]["away"]] if final else None,
        } | changes.get(match["id"], {})
    return {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"matches": matches},
    }


async def test_changes_while_stopped_are_reported(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """What changed since Home Assistant last saw the matches fires at start-up."""
    freezer.move_to(NOW)
    hass_storage[f"{DOMAIN}.{config_entry.entry_id}"] = _stored(
        config_entry,
        {
            9002: {"status": "scheduled", "score": None},
            9003: {"field": "Veld 9"},
            9004: {"status": "scheduled"},
            9005: {"start": "2026-11-28T11:00:00+01:00"},
        },
    )
    fired = _fired(hass)
    await _setup(hass, config_entry)
    assert fired == []  # reported just after the entity is added, not while
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert [(e["event_type"], e["match_id"]) for e in fired] == [
        ("result", 9002),
        ("location_changed", 9003),
        ("cancelled", 9004),
        ("rescheduled", 9005),
    ]
    result, moved, cancelled, rescheduled = fired
    assert result["score"] == "2–2, SO 3–4"
    assert result["result"] == "draw"
    assert moved["previous_field"] == "Veld 9"
    assert moved["field"] == "Veld 2"
    assert moved["meet_time"] == "2026-11-14T11:30:00+01:00"
    assert cancelled["opponent"] == "De Proef JO14-1"
    assert rescheduled["previous_start"] == "2026-11-28T11:00:00+01:00"
    assert rescheduled["start"] == "2026-11-28T10:00:00+01:00"

    # Saved as they are now: the next start-up reports nothing.
    stored = hass_storage[f"{DOMAIN}.{config_entry.entry_id}"]["data"]["matches"]
    assert stored["9004"]["status"] == "cancelled"
    fired.clear()
    await _tick(hass, freezer, UPDATE_INTERVAL_SOON)
    assert fired == []


async def test_change_between_updates(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    aioclient_mock: AiohttpClientMocker,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A match cancelled between two updates fires once; the first set-up fires nothing."""
    freezer.move_to(NOW)
    fired = _fired(hass)
    await _setup(hass, config_entry)
    await _tick(hass, freezer, UPDATE_INTERVAL_SOON)
    assert fired == []

    page = load_fixture("team_page.json")
    for match in page["data"]["poules"][0]["matches"]:
        if match["id"] == 9005:
            match["status"] = "cancelled"
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL_TEAM_PAGE, json=page)
    aioclient_mock.get(URL_MATCH, json=load_fixture("match_detail.json"))
    await _tick(hass, freezer, UPDATE_INTERVAL)
    assert [(e["event_type"], e["match_id"]) for e in fired] == [("cancelled", 9005)]

    await _tick(hass, freezer, UPDATE_INTERVAL)
    assert len(fired) == 1
    assert hass.states.get(EVENT).attributes["event_type"] == "cancelled"


async def test_meet_time_and_options(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The team meets 30 minutes before kick-off unless set otherwise; no reload needed."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    assert hass.states.get(MEET_TIME).state == "2026-11-14T10:30:00+00:00"
    assert hass.states.get(NEXT_MATCH).attributes["meet_time"] == "2026-11-14T11:30:00+01:00"

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MEET_MINUTES_HOME: 45.0, CONF_MEET_MINUTES_AWAY: 60.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_MEET_MINUTES_HOME: 45, CONF_MEET_MINUTES_AWAY: 60}
    await hass.async_block_till_done()
    assert hass.states.get(MEET_TIME).state == "2026-11-14T10:15:00+00:00"


async def test_match_today(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Match today is on all match day and goes off after midnight."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    state = hass.states.get(MATCH_TODAY)
    assert state.state == "on"
    assert state.attributes["opponent"] == "Fictief JO14-3"
    assert state.attributes["meet_time"] == "2026-11-14T11:30:00+01:00"

    freezer.move_to("2026-11-14T23:00:01+00:00")  # 00:00:01 in the Netherlands
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(MATCH_TODAY).state == "off"


async def test_weather(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The next match's forecast is fetched a minute after start-up, then every 3 hours."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    assert hass.states.get(WEATHER).state == "unknown"
    assert calls_to(mock_api, URL_MATCH) == 0

    await _tick(hass, freezer, UPDATE_INTERVAL_SOON)
    state = hass.states.get(WEATHER)
    assert state.state == "8.4"
    assert state.attributes["unit_of_measurement"] == "°C"
    assert state.attributes["precipitation_probability"] == 40
    assert state.attributes["description"] == "Een paar druppels, maar prima hockeyweer."
    assert state.attributes["match_id"] == 9003

    await _tick(hass, freezer, UPDATE_INTERVAL)
    assert calls_to(mock_api, URL_MATCH) == 1


async def test_no_weather_far_ahead(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """No forecast is fetched for a match more than 48 hours away."""
    freezer.move_to("2026-11-08T08:00:00+00:00")
    await _setup(hass, config_entry)
    await _tick(hass, freezer, UPDATE_INTERVAL_SOON)
    assert calls_to(mock_api, URL_MATCH) == 0
    assert hass.states.get(WEATHER).state == "unknown"


async def test_opponent_and_form(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The next match tells how the opponent is doing and how the last meeting went."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    state = hass.states.get(NEXT_MATCH)
    assert state.attributes["entity_picture"] == "https://example.invalid/logo.png"
    assert state.attributes["home_logo"] == "https://example.invalid/logo.png"
    assert state.attributes["opponent_rank"] == 3
    assert state.attributes["opponent_points"] == 1
    assert state.attributes["opponent_form"] == ["draw"]
    assert state.attributes["previous_meeting"] == "2–2, SO 3–4"
    assert state.attributes["previous_meeting_result"] == "draw"
    assert state.attributes["upcoming"] == [
        {
            "start": "2026-11-28T10:00:00+01:00",
            "opponent": "Proefstad JO14-1",
            "home_away": "away",
            "venue": "Sportpark Voorbeeld",
        }
    ]
    assert hass.states.get(STANDING).attributes["form"] == ["win", "draw"]

    state = hass.states.get("sensor.voorbeeld_jo14_2_next_opponent")
    assert state.state == "Fictief JO14-3"
    assert state.attributes["entity_picture"] == "https://example.invalid/logo.png"
    assert state.attributes["home_away"] == "home"
    assert state.attributes["opponent_rank"] == 3
    state = hass.states.get("sensor.voorbeeld_jo14_2_home_or_away")
    assert state.state == "home"
    assert state.attributes["opponent"] == "Fictief JO14-3"
    assert state.attributes["options"] == ["home", "away"]

    # The earlier pool of this season adds its result to the form.
    await _tick(hass, freezer, UPDATE_INTERVAL_SOON)
    assert hass.states.get(STANDING).attributes["form"] == ["win", "win", "draw"]
