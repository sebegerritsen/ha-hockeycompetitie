"""Async client for the KNHB match data API behind hockey.nl (see docs/api.md)."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
import hashlib
from http import HTTPStatus
import logging
import re
import time
from typing import Any
import uuid

import aiohttp

from .models import Club, ClubDetail, MatchDetail, TeamPage

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://app.hockeyweerelt.nl"
API_VERSION = "8"
USER_AGENT = "ha-hockeycompetitie (+https://github.com/sebegerritsen/ha-hockeycompetitie)"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# The API allows 5 requests per minute per IP address. Stay below that, so that
# someone browsing hockey.nl on the same network does not run into the limit.
THROTTLE_REQUESTS = 4
THROTTLE_PERIOD = 60.0
# Wait for a 429's Retry-After inside a request only up to this many seconds.
MAX_RETRY_WAIT = 65.0

_PATH_STRIP = re.compile(r"[^a-zA-Z0-9\-/]+")
_QUERY_STRIP = re.compile(r"[^a-zA-Z0-9\-/=]+")


class KnhbError(Exception):
    """Base class for errors talking to the API."""


class KnhbConnectionError(KnhbError):
    """The API could not be reached, timed out or had a server error."""


class KnhbAuthError(KnhbError):
    """The API refused the device, even after registering again."""


class KnhbNotFoundError(KnhbError):
    """The requested club, pool or team does not exist (any more)."""


class KnhbRateLimitError(KnhbError):
    """The API's rate limit was hit."""

    def __init__(self, retry_after: float | None) -> None:
        """Initialize with the number of seconds to wait, if known."""
        super().__init__(f"Rate limited, retry after {retry_after} s")
        self.retry_after = retry_after


class KnhbResponseError(KnhbError):
    """The API answered something unexpected."""


def sign(timestamp: str, path: str, params: Mapping[str, str], device_uuid: str) -> str:
    """Return the request signature.

    sha1(timestamp + cleaned path + cleaned query + reversed device uuid), lowercase hex.
    """
    clean_path = _PATH_STRIP.sub("", path)
    query = "".join(
        _QUERY_STRIP.sub("", key) + "=" + _QUERY_STRIP.sub("", str(value))
        for key, value in params.items()
        if key
    )
    payload = f"{timestamp}{clean_path}{query}{device_uuid[::-1]}"
    return hashlib.sha1(payload.encode()).hexdigest()  # noqa: S324 - the API's scheme


class RequestThrottle:
    """Space requests out to at most `max_requests` per `period` seconds.

    Shared by every client in one Home Assistant instance, since the API limits
    per IP address. Also remembers a 429's Retry-After for everyone.
    """

    def __init__(
        self,
        max_requests: int = THROTTLE_REQUESTS,
        period: float = THROTTLE_PERIOD,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        """Initialize the throttle."""
        self._max_requests = max_requests
        self._period = period
        self._clock = clock
        self._sleep = sleep
        self._sent: deque[float] = deque()
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()

    def wait_time(self) -> float:
        """Return how long the next request would have to wait, in seconds."""
        now = self._clock()
        while self._sent and now - self._sent[0] >= self._period:
            self._sent.popleft()
        wait = self._blocked_until - now
        if len(self._sent) >= self._max_requests:
            wait = max(wait, self._period - (now - self._sent[0]))
        return max(wait, 0.0)

    async def acquire(self) -> None:
        """Wait until a request may be sent, and count it."""
        async with self._lock:
            while (wait := self.wait_time()) > 0:
                _LOGGER.debug("Throttling request for %.1f s", wait)
                await self._sleep(wait)
            self._sent.append(self._clock())

    def block(self, seconds: float) -> None:
        """Send nothing for the next `seconds` (after a 429)."""
        self._blocked_until = max(self._blocked_until, self._clock() + seconds)


class KnhbClient:
    """Client for the KNHB match data API, as an anonymous device."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        device_uuid: str | None = None,
        token: str | None = None,
        throttle: RequestThrottle | None = None,
        on_token_change: Callable[[str, str], None] | None = None,
    ) -> None:
        """Initialize the client.

        Without a device uuid and token it registers a new device on the first request.
        `on_token_change(device_uuid, token)` is called whenever it registers.
        """
        self._session = session
        self.device_uuid = device_uuid or str(uuid.uuid4())
        self.token = token
        self._throttle = throttle or RequestThrottle()
        self._on_token_change = on_token_change
        self._register_lock = asyncio.Lock()

    async def register(self) -> str:
        """Register this device and return the new token."""
        async with self._register_lock:
            try:
                async with self._session.post(
                    f"{BASE_URL}/device/register",
                    json={"uuid": self.device_uuid, "os": "Web"},
                    headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                    timeout=REQUEST_TIMEOUT,
                ) as resp:
                    if resp.status == HTTPStatus.TOO_MANY_REQUESTS:
                        raise KnhbRateLimitError(_retry_after(resp))
                    if resp.status >= HTTPStatus.INTERNAL_SERVER_ERROR:
                        raise KnhbConnectionError(f"Server error {resp.status}")
                    if resp.status >= HTTPStatus.BAD_REQUEST:
                        raise KnhbAuthError(f"Device registration refused: {resp.status}")
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError) as err:
                raise KnhbConnectionError(str(err) or type(err).__name__) from err
            except ValueError as err:
                raise KnhbResponseError("Registration answer is not JSON") from err
            token = data.get("token") if isinstance(data, dict) else None
            if not isinstance(token, str) or not token:
                raise KnhbResponseError("No token in the registration answer")
            self.token = token
            _LOGGER.debug("Registered device")
            if self._on_token_change is not None:
                self._on_token_change(self.device_uuid, token)
            return token

    async def get(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        """Send a signed GET request and return the JSON answer.

        Registers first if there is no token, and once more on a 401. Waits for a
        429's Retry-After once, if it is short.
        """
        params = dict(params or {})
        if not self.token:
            await self.register()
        reregistered = False
        rate_limited = False
        while True:
            used_token = self.token
            status, data, retry_after = await self._get_once(path, params)
            if status == HTTPStatus.UNAUTHORIZED and not reregistered:
                reregistered = True
                if self.token == used_token:  # not renewed by a parallel request
                    await self.register()
                continue
            if status == HTTPStatus.TOO_MANY_REQUESTS:
                wait = retry_after if retry_after is not None else THROTTLE_PERIOD
                self._throttle.block(wait)
                if rate_limited or wait > MAX_RETRY_WAIT:
                    raise KnhbRateLimitError(retry_after)
                rate_limited = True
                _LOGGER.debug("Rate limited on %s, retrying after %.0f s", path, wait)
                continue
            if status == HTTPStatus.UNAUTHORIZED:
                raise KnhbAuthError("The API refused the device token")
            if status == HTTPStatus.NOT_FOUND:
                raise KnhbNotFoundError(f"Not found: {path}")
            if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
                raise KnhbConnectionError(f"Server error {status} on {path}")
            if status >= HTTPStatus.BAD_REQUEST:
                raise KnhbResponseError(f"Unexpected status {status} on {path}")
            return data

    async def _get_once(self, path: str, params: dict[str, str]) -> tuple[int, Any, float | None]:
        await self._throttle.acquire()
        timestamp = str(int(time.time()))
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "X-HAPI-Authorization": self.token or "",
            "X-HAPI-Timestamp": timestamp,
            "X-HAPI-Signature": sign(timestamp, path, params, self.device_uuid),
            "X-HAPI-Version": API_VERSION,
        }
        try:
            async with self._session.get(
                f"{BASE_URL}{path}",
                params=params or None,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                if resp.status >= HTTPStatus.BAD_REQUEST:
                    return resp.status, None, _retry_after(resp)
                try:
                    data = await resp.json(content_type=None)
                except ValueError as err:
                    raise KnhbResponseError(f"Answer to {path} is not JSON") from err
                return resp.status, data, None
        except (aiohttp.ClientError, TimeoutError) as err:
            raise KnhbConnectionError(str(err) or type(err).__name__) from err

    async def get_clubs(self) -> list[Club]:
        """Return all clubs."""
        data = _data(await self.get("/clubs"), list)
        return [
            club
            for item in data
            if isinstance(item, dict) and (club := Club.from_api(item)) is not None
        ]

    async def get_club(self, club_id: str) -> ClubDetail:
        """Return a club with its teams."""
        detail = ClubDetail.from_api(_data(await self.get(f"/clubs/{club_id}"), dict))
        if detail is None:
            raise KnhbResponseError(f"Club {club_id} has no id in the answer")
        return detail

    async def get_team_page(self, poule_id: int, team_id: int) -> TeamPage:
        """Return a team's page in a pool: standings and all matches of the pool."""
        data = _data(await self.get(f"/poules/{poule_id}/teams/{team_id}"), dict)
        return TeamPage.from_api(data)

    async def get_match(self, match_id: int) -> MatchDetail:
        """Return a match with its details: weather forecast, result approvals."""
        detail = MatchDetail.from_api(_data(await self.get(f"/matches/{match_id}"), dict))
        if detail is None:
            raise KnhbResponseError(f"Match {match_id} has no id in the answer")
        return detail


def _data[T](answer: Any, kind: type[T]) -> T:
    """Return the `data` member of an answer, checking its type."""
    data = answer.get("data") if isinstance(answer, dict) else None
    if not isinstance(data, kind):
        raise KnhbResponseError(f"Expected {kind.__name__} in 'data'")
    return data


def _retry_after(resp: aiohttp.ClientResponse) -> float | None:
    value = resp.headers.get("Retry-After")
    try:
        return max(float(value), 0.0) if value is not None else None
    except ValueError:
        return None
