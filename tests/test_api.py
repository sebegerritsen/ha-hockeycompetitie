"""Tests for the API client: signing, registration, errors and the throttle."""

from __future__ import annotations

import hashlib
from http import HTTPStatus

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.knhb_hockey.api import (
    KnhbAuthError,
    KnhbClient,
    KnhbConnectionError,
    KnhbNotFoundError,
    KnhbRateLimitError,
    KnhbResponseError,
    RequestThrottle,
    sign,
)

from .conftest import (
    DEVICE_UUID,
    POULE_ID,
    TEAM_ID,
    URL_CLUB,
    URL_CLUBS,
    URL_REGISTER,
    URL_TEAM_PAGE,
    load_fixture,
)


class FakeTime:
    """A clock and sleep that move only when slept on."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make_client(hass: HomeAssistant, **kwargs) -> KnhbClient:
    kwargs.setdefault("device_uuid", DEVICE_UUID)
    kwargs.setdefault("token", "stored-token")
    kwargs.setdefault("throttle", RequestThrottle(max_requests=1000))
    return KnhbClient(async_get_clientsession(hass), **kwargs)


def test_sign() -> None:
    """The signature follows docs/api.md."""
    expected = hashlib.sha1(
        b"1700000000/poules/123/teams/456" + DEVICE_UUID[::-1].encode()
    ).hexdigest()
    assert sign("1700000000", "/poules/123/teams/456", {}, DEVICE_UUID) == expected


def test_sign_query() -> None:
    """Query parameters are cleaned and concatenated without separators."""
    expected = hashlib.sha1(
        b"1700000000/poules/123filterdateStart=2026-11-14filterdateEnd=2026-11-21"
        + DEVICE_UUID[::-1].encode()
    ).hexdigest()
    params = {"filter[dateStart]": "2026-11-14", "filter[dateEnd]": "2026-11-21", "": "x"}
    assert sign("1700000000", "/poules/123", params, DEVICE_UUID) == expected


async def test_signed_headers(hass: HomeAssistant, mock_api: AiohttpClientMocker) -> None:
    """A request carries the token, timestamp, signature and API version."""
    client = make_client(hass)
    clubs = await client.get_clubs()

    assert [club.id for club in clubs] == ["HV00AA1", "HV00BB2", "HV00CC3"]
    _method, _url, _data, headers = mock_api.mock_calls[-1]
    assert headers["X-HAPI-Authorization"] == "stored-token"
    assert headers["X-HAPI-Version"] == "8"
    assert headers["X-HAPI-Signature"] == sign(
        headers["X-HAPI-Timestamp"], "/clubs", {}, DEVICE_UUID
    )


async def test_registers_without_token(hass: HomeAssistant, mock_api: AiohttpClientMocker) -> None:
    """Without a token the client registers a device first, and reports the token."""
    seen: list[tuple[str, str]] = []
    client = make_client(
        hass,
        device_uuid=None,
        token=None,
        on_token_change=lambda device, token: seen.append((device, token)),
    )
    await client.get_clubs()

    assert mock_api.mock_calls[0][0].lower() == "post"
    assert mock_api.mock_calls[0][2] == {"uuid": client.device_uuid, "os": "Web"}
    assert seen == [(client.device_uuid, "new-token")]
    assert mock_api.mock_calls[1][3]["X-HAPI-Authorization"] == "new-token"


async def test_reregisters_on_401(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A 401 registers again and retries once."""
    answers = iter(
        [
            AiohttpClientMockResponse("get", URL_CLUBS, status=HTTPStatus.UNAUTHORIZED),
            AiohttpClientMockResponse("get", URL_CLUBS, json=load_fixture("clubs.json")),
        ]
    )

    async def respond(method, url, data):
        return next(answers)

    aioclient_mock.get(URL_CLUBS, side_effect=respond)
    aioclient_mock.post(URL_REGISTER, json={"token": "new-token"}, status=201)
    client = make_client(hass)

    assert len(await client.get_clubs()) == 3
    assert client.token == "new-token"
    assert [call[0].lower() for call in aioclient_mock.mock_calls] == ["get", "post", "get"]


async def test_401_twice(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A second 401 after registering again is an auth error."""
    aioclient_mock.get(URL_CLUBS, status=HTTPStatus.UNAUTHORIZED)
    aioclient_mock.post(URL_REGISTER, json={"token": "new-token"}, status=201)
    with pytest.raises(KnhbAuthError):
        await make_client(hass).get_clubs()


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (HTTPStatus.NOT_FOUND, KnhbNotFoundError),
        (HTTPStatus.BAD_GATEWAY, KnhbConnectionError),
        (HTTPStatus.BAD_REQUEST, KnhbResponseError),
    ],
)
async def test_http_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status: int, error: type
) -> None:
    """HTTP errors map to typed errors."""
    aioclient_mock.get(URL_CLUB, status=status)
    with pytest.raises(error):
        await make_client(hass).get_club("HV00AA1")


async def test_connection_error(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A network error is a connection error."""
    aioclient_mock.get(URL_CLUBS, exc=TimeoutError())
    with pytest.raises(KnhbConnectionError):
        await make_client(hass).get_clubs()


@pytest.mark.parametrize("answer", [{"data": {"not": "a list"}}, ["no data"], {}])
async def test_unexpected_answer(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, answer: object
) -> None:
    """An answer of the wrong shape is a response error."""
    aioclient_mock.get(URL_CLUBS, json=answer)
    with pytest.raises(KnhbResponseError):
        await make_client(hass).get_clubs()


async def test_not_json(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """An answer that is not JSON is a response error."""
    aioclient_mock.get(URL_CLUBS, text="<html>maintenance</html>")
    with pytest.raises(KnhbResponseError):
        await make_client(hass).get_clubs()


async def test_rate_limited_long_wait(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 429 with a long Retry-After is raised at once, and blocks the throttle."""
    fake = FakeTime()
    throttle = RequestThrottle(clock=fake.clock, sleep=fake.sleep)
    aioclient_mock.get(
        URL_CLUBS, status=HTTPStatus.TOO_MANY_REQUESTS, headers={"Retry-After": "300"}
    )
    with pytest.raises(KnhbRateLimitError) as err:
        await make_client(hass, throttle=throttle).get_clubs()
    assert err.value.retry_after == 300
    assert throttle.wait_time() == 300


async def test_rate_limited_short_wait(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 429 with a short Retry-After waits and retries once."""
    fake = FakeTime()
    throttle = RequestThrottle(clock=fake.clock, sleep=fake.sleep)
    answers = iter(
        [
            AiohttpClientMockResponse(
                "get",
                URL_CLUBS,
                status=HTTPStatus.TOO_MANY_REQUESTS,
                headers={"Retry-After": "20"},
            ),
            AiohttpClientMockResponse("get", URL_CLUBS, json=load_fixture("clubs.json")),
        ]
    )

    async def respond(method, url, data):
        return next(answers)

    aioclient_mock.get(URL_CLUBS, side_effect=respond)
    assert len(await make_client(hass, throttle=throttle).get_clubs()) == 3
    assert fake.slept == [20]


async def test_get_club_and_team_page(hass: HomeAssistant, mock_api: AiohttpClientMocker) -> None:
    """Club details and team pages parse into models."""
    client = make_client(hass)
    detail = await client.get_club("HV00AA1")
    assert detail.club.name == "HC Voorbeeld"
    assert {team.id for team in detail.teams} == {1001, 1002, 1003, 1004, 1005}

    page = await client.get_team_page(POULE_ID, TEAM_ID)
    assert page.poule_id == POULE_ID
    assert [m.id for m in page.own_matches(TEAM_ID)] == [9001, 9002, 9003, 9004, 9005]
    assert page.same_season_poules() == [4001]
    assert str(mock_api.mock_calls[-1][1]) == URL_TEAM_PAGE


async def test_throttle_spaces_requests() -> None:
    """The throttle lets `max_requests` through per period, then waits."""
    fake = FakeTime()
    throttle = RequestThrottle(3, 60, clock=fake.clock, sleep=fake.sleep)
    for _ in range(3):
        await throttle.acquire()
    assert fake.slept == []

    await throttle.acquire()
    assert fake.slept == [60]

    fake.now += 30
    throttle.block(45)
    assert throttle.wait_time() == 45
