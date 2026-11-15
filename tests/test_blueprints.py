"""Run the blueprints as automations, with a test event in place of the phone notification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.hockeycompetitie.const import DOMAIN, UPDATE_INTERVAL_SOON

from .conftest import NOW
from .test_features import _stored

BLUEPRINTS = Path(__file__).parent.parent / "blueprints" / "automation" / "hockeycompetitie"
NOTIFY = "    domain: mobile_app\n    type: notify\n"

pytestmark = pytest.mark.usefixtures("dutch_time")


def _install(hass: HomeAssistant, tmp_path: Path, name: str) -> None:
    """Copy a blueprint into the config dir, its notification replaced by an event."""
    text = (BLUEPRINTS / name).read_text(encoding="utf-8")
    head, _, tail = text.partition("  - device_id: !input notify_device\n" + NOTIFY)
    assert tail, f"{name} has no phone notification as its last action"
    text = (
        head
        + "  - event: knhb_test_notify\n    event_data:\n"
        + "".join(f"  {line}\n" if line else "\n" for line in tail.splitlines())
    )
    target = tmp_path / "blueprints" / "automation" / "hockeycompetitie" / name
    target.parent.mkdir(parents=True)
    target.write_text(text, encoding="utf-8")
    hass.config.config_dir = str(tmp_path)


async def _automation(hass: HomeAssistant, name: str, inputs: dict[str, Any]) -> None:
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": f"hockeycompetitie/{name}",
                    "input": {"notify_device": "phone", **inputs},
                }
            }
        },
    )
    await hass.async_block_till_done()


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_match_update_notify(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    tmp_path: Path,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Each kind of change gives a readable notification; unwanted kinds are skipped."""
    freezer.move_to(NOW)
    _install(hass, tmp_path, "match_update_notify.yaml")
    await _automation(
        hass,
        "match_update_notify.yaml",
        {
            "update_entity": "event.voorbeeld_jo14_2_match_update",
            "event_types": ["cancelled", "rescheduled", "location_changed", "result"],
        },
    )
    sent = async_capture_events(hass, "knhb_test_notify")
    hass_storage[f"{DOMAIN}.{config_entry.entry_id}"] = _stored(
        config_entry,
        {
            9002: {"status": "scheduled", "score": None},
            9003: {"field": "Veld 9"},
            9004: {"status": "scheduled"},
            9005: {"start": "2026-11-28T11:00:00+01:00"},
        },
    )
    await _setup(hass, config_entry)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert [(e.data["title"], e.data["message"]) for e in sent] == [
        ("Fictief JO14-3 2–2, SO 3–4 Voorbeeld JO14-2", "Gelijkgespeeld · Jongens O14 Test"),
        (
            "Andere locatie: Voorbeeld JO14-2 – Fictief JO14-3",
            "Sportpark Voorbeeld, Veld 2 (was Sportpark Voorbeeld, Veld 9) · za 14-11 12:00",
        ),
        ("Afgelast: De Proef JO14-1 – Voorbeeld JO14-2", "za 21-11 09:00 · Sportpark Voorbeeld"),
        (
            "Verplaatst: Proefstad JO14-1 – Voorbeeld JO14-2",
            "za 28-11 10:00 (was za 28-11 11:00) · Sportpark Voorbeeld",
        ),
    ]


async def test_meet_time_reminder(
    hass: HomeAssistant,
    tmp_path: Path,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """An hour before the meet time a reminder with venue and weather goes out, once."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    freezer.tick(UPDATE_INTERVAL_SOON)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    _install(hass, tmp_path, "meet_time_reminder.yaml")
    await _automation(
        hass,
        "meet_time_reminder.yaml",
        {"meet_time_entity": "sensor.voorbeeld_jo14_2_meet_time", "lead_time": 60},
    )
    sent = async_capture_events(hass, "knhb_test_notify")

    freezer.move_to("2026-11-14T09:29:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert sent == []

    for minute in ("09:30", "09:31"):
        freezer.move_to(f"2026-11-14T{minute}:00+00:00")
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert [(e.data["title"], e.data["message"]) for e in sent] == [
        (
            "Verzamelen 11:30: Voorbeeld JO14-2 – Fictief JO14-3",
            "Aanvang 12:00 · Sportpark Voorbeeld, Veld 2 (Voorbeeldlaan 1, 1234AB Voorbeeldstad)"
            " · 8 °C, 40% kans op neerslag",
        )
    ]


@pytest.mark.parametrize("expected_lingering_timers", [True])  # the automation's time trigger
async def test_match_day_summary(
    hass: HomeAssistant,
    tmp_path: Path,
    freezer: FrozenDateTimeFactory,
    mock_api: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """On match days the summary goes out at the set time, in English if asked."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    freezer.tick(UPDATE_INTERVAL_SOON)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    _install(hass, tmp_path, "match_day_summary.yaml")
    await _automation(
        hass,
        "match_day_summary.yaml",
        {
            "match_today_entity": "binary_sensor.voorbeeld_jo14_2_match_today",
            "time": "09:30:00",
            "language": "en",
        },
    )
    sent = async_capture_events(hass, "knhb_test_notify")
    freezer.move_to("2026-11-14T08:30:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [(e.data["title"], e.data["message"]) for e in sent] == [
        (
            "Hockey today: Voorbeeld JO14-2",
            "Fictief JO14-3 (home) · kick-off 12:00, meet 11:30 · Sportpark Voorbeeld"
            " · 8 °C, 40% chance of rain",
        )
    ]
