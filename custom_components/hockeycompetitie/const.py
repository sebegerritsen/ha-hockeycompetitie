"""Constants for the Hockeycompetitie integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "hockeycompetitie"
LOGGER = logging.getLogger(__package__)

# Config entry data
CONF_CLUB_ID: Final = "club_id"
CONF_CLUB_NAME: Final = "club_name"
CONF_TEAM_ID: Final = "team_id"
CONF_TEAM_NAME: Final = "team_name"
CONF_TEAM_SHORT_NAME: Final = "team_short_name"
CONF_HOCKEY_TYPE: Final = "hockey_type"
CONF_CATEGORY: Final = "category"
CONF_POULE_ID: Final = "poule_id"
CONF_POULE_CHECKED: Final = "poule_checked"
CONF_DEVICE_UUID: Final = "device_uuid"
CONF_TOKEN: Final = "token"  # noqa: S105 - a config key, not a secret

# Hockey types as the API reports them
HOCKEY_TYPE_FIELD: Final = "VE"
HOCKEY_TYPE_INDOOR: Final = "ZA"

# Category group of the youngest age groups (shorter matches, no standings)
CATEGORY_YOUNGEST: Final = "Jongste jeugd"

# Polling. The API allows 5 requests per minute per IP address, shared by every
# team configured in this Home Assistant and by anyone on the same network using
# hockey.nl, so poll no more than needed (see docs/api.md).
UPDATE_INTERVAL: Final = timedelta(minutes=30)
UPDATE_INTERVAL_MATCH: Final = timedelta(minutes=5)
UPDATE_INTERVAL_IDLE: Final = timedelta(hours=2)
UPDATE_INTERVAL_SOON: Final = timedelta(minutes=1)
CLUB_REFRESH_INTERVAL: Final = timedelta(hours=12)
EXTRA_POULE_REFRESH_INTERVAL: Final = timedelta(hours=6)

# Matches are scheduled without an end time; these are calendar slot lengths.
MATCH_DURATION: Final = timedelta(minutes=90)
MATCH_DURATION_SHORT: Final = timedelta(minutes=60)

# How long after the start a match without a final result still counts as
# "around a match" (played, result not entered yet).
RESULT_WAIT: Final = timedelta(hours=3)

# Options: when the team meets, in minutes before kick-off
CONF_MEET_MINUTES_HOME: Final = "meet_minutes_home"
CONF_MEET_MINUTES_AWAY: Final = "meet_minutes_away"
DEFAULT_MEET_MINUTES: Final = 30

# The weather forecast comes with a match's details: fetch it for the next match
# from this long before it, at most this often.
WEATHER_AHEAD: Final = timedelta(hours=48)
WEATHER_REFRESH: Final = timedelta(hours=3)

# Changes to matches are remembered across restarts in .storage/hockeycompetitie.<entry id>
STORAGE_VERSION: Final = 1
