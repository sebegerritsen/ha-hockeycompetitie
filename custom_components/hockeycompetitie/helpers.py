"""Shared helpers: one request throttle for every team in this Home Assistant."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util.hass_dict import HassKey

from .api import KnhbClient, RequestThrottle
from .const import DOMAIN

DATA_THROTTLE: HassKey[RequestThrottle] = HassKey(f"{DOMAIN}_throttle")


def async_get_client(
    hass: HomeAssistant,
    *,
    device_uuid: str | None = None,
    token: str | None = None,
    on_token_change: Callable[[str, str], None] | None = None,
) -> KnhbClient:
    """Return an API client that shares the rate limit with all others.

    The API limits requests per IP address, so all config entries (and config flows)
    of this Home Assistant go through one throttle.
    """
    if (throttle := hass.data.get(DATA_THROTTLE)) is None:
        throttle = hass.data[DATA_THROTTLE] = RequestThrottle()
    return KnhbClient(
        async_get_clientsession(hass),
        device_uuid=device_uuid,
        token=token,
        throttle=throttle,
        on_token_change=on_token_change,
    )
