"""Async API client for Evaka using weak login (username/password)."""

import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from .const import CSRF_HEADER, MUNICIPALITIES

_LOGGER = logging.getLogger(__name__)


class EvakaApiError(Exception):
    """Exception for Evaka API errors."""


class EvakaAuthError(EvakaApiError):
    """Exception for authentication errors."""


class EvakaSessionExpiredError(EvakaAuthError):
    """Exception when session has expired."""


class EvakaApi:
    """Async client for Evaka API using weak login."""

    def __init__(
        self,
        username: str,
        password: str,
        municipality: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the API client."""
        self._username = username
        self._password = password
        self._municipality = municipality
        self._base_url = MUNICIPALITIES[municipality]["base_url"]
        self._external_session = session
        self._internal_session: aiohttp.ClientSession | None = None
        self._cookie_jar: aiohttp.CookieJar | None = None
        self._logged_in = False
        self._user_info: dict[str, Any] | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._external_session:
            return self._external_session

        if self._internal_session is None:
            self._cookie_jar = aiohttp.CookieJar()
            self._internal_session = aiohttp.ClientSession(
                cookie_jar=self._cookie_jar
            )

        return self._internal_session

    async def close(self) -> None:
        """Close the internal session if we created one."""
        if self._internal_session:
            await self._internal_session.close()
            self._internal_session = None
            self._cookie_jar = None

    async def login(self) -> bool:
        """Authenticate with Evaka using weak login (username/password)."""
        session = await self._get_session()

        try:
            url = f"{self._base_url}/api/citizen/auth/weak-login"
            data = {
                "username": self._username,
                "password": self._password,
            }

            headers = {
                "Content-Type": "application/json",
                **CSRF_HEADER,
            }

            async with session.post(url, json=data, headers=headers) as response:
                if response.status == 200:
                    _LOGGER.info("Successfully logged into Evaka")
                    self._logged_in = True

                    # Get user info
                    await self._fetch_auth_status()
                    return True

                elif response.status == 401:
                    _LOGGER.error("Invalid username or password")
                    return False

                elif response.status == 403:
                    _LOGGER.error(
                        "Weak login is not enabled. Please enable it in your Evaka profile."
                    )
                    return False

                elif response.status == 429:
                    _LOGGER.error("Too many login attempts. Account temporarily locked.")
                    return False

                else:
                    text = await response.text()
                    _LOGGER.error("Login failed with status %s: %s", response.status, text)
                    return False

        except aiohttp.ClientError as err:
            _LOGGER.error("Connection error during login: %s", err)
            raise EvakaApiError(f"Connection error: {err}") from err

    async def _fetch_auth_status(self) -> None:
        """Fetch and store auth status."""
        session = await self._get_session()

        try:
            url = f"{self._base_url}/api/citizen/auth/status"
            async with session.get(url, headers=CSRF_HEADER) as response:
                if response.status == 200:
                    data = await response.json()
                    self._logged_in = data.get("loggedIn", False)
                    self._user_info = data.get("user")

        except aiohttp.ClientError as err:
            _LOGGER.error("Error fetching auth status: %s", err)

    async def ensure_logged_in(self) -> bool:
        """Ensure we are logged in, attempting login if needed."""
        if self._logged_in:
            # Verify session is still valid
            session = await self._get_session()
            try:
                url = f"{self._base_url}/api/citizen/auth/status"
                async with session.get(url, headers=CSRF_HEADER) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("loggedIn"):
                            return True
            except aiohttp.ClientError:
                pass

            self._logged_in = False

        # Need to login
        return await self.login()

    async def get_calendar_events(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch calendar events from Evaka."""
        if not await self.ensure_logged_in():
            raise EvakaAuthError("Failed to authenticate")

        session = await self._get_session()

        if start_date is None:
            start_date = datetime.now()
        if end_date is None:
            end_date = datetime.now() + timedelta(weeks=4)

        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        url = f"{self._base_url}/api/citizen/calendar-events"
        params = {"start": start_str, "end": end_str}

        try:
            async with session.get(url, params=params, headers=CSRF_HEADER) as response:
                if response.status == 401:
                    self._logged_in = False
                    # Try to re-login once
                    if await self.login():
                        return await self.get_calendar_events(start_date, end_date)
                    raise EvakaSessionExpiredError("Session expired and re-login failed")

                if response.status != 200:
                    _LOGGER.error("Failed to fetch events: %s", response.status)
                    return []

                events = await response.json()
                _LOGGER.debug("Retrieved %d events from Evaka", len(events))
                return events

        except aiohttp.ClientError as err:
            _LOGGER.error("Connection error fetching events: %s", err)
            raise EvakaApiError(f"Connection error: {err}") from err

    async def get_children(self) -> list[dict[str, Any]]:
        """Fetch list of children from Evaka."""
        if not await self.ensure_logged_in():
            raise EvakaAuthError("Failed to authenticate")

        session = await self._get_session()
        url = f"{self._base_url}/api/citizen/children"

        try:
            async with session.get(url, headers=CSRF_HEADER) as response:
                if response.status == 401:
                    self._logged_in = False
                    if await self.login():
                        return await self.get_children()
                    raise EvakaSessionExpiredError("Session expired and re-login failed")

                if response.status != 200:
                    _LOGGER.error("Failed to fetch children: %s", response.status)
                    return []

                children = await response.json()
                _LOGGER.debug("Retrieved %d children from Evaka", len(children))
                return children

        except aiohttp.ClientError as err:
            _LOGGER.error("Connection error fetching children: %s", err)
            raise EvakaApiError(f"Connection error: {err}") from err

    async def get_messages(
        self,
        page: int = 1,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Fetch messages from Evaka.

        Returns dict with:
        - data: list of message threads
        - total: total number of messages
        - pages: total number of pages
        """
        if not await self.ensure_logged_in():
            raise EvakaAuthError("Failed to authenticate")

        session = await self._get_session()
        url = f"{self._base_url}/api/citizen/messages/received"
        params = {"page": page}

        try:
            async with session.get(url, params=params, headers=CSRF_HEADER) as response:
                if response.status == 401:
                    self._logged_in = False
                    if await self.login():
                        return await self.get_messages(page, limit)
                    raise EvakaSessionExpiredError("Session expired and re-login failed")

                if response.status != 200:
                    _LOGGER.error("Failed to fetch messages: %s", response.status)
                    return {"data": [], "total": 0, "pages": 0}

                result = await response.json()
                messages = result.get("data", [])[:limit]
                _LOGGER.debug("Retrieved %d messages from Evaka", len(messages))
                return {
                    "data": messages,
                    "total": result.get("total", 0),
                    "pages": result.get("pages", 0),
                }

        except aiohttp.ClientError as err:
            _LOGGER.error("Connection error fetching messages: %s", err)
            raise EvakaApiError(f"Connection error: {err}") from err

    async def get_unread_message_count(self) -> int:
        """Get count of unread messages."""
        if not await self.ensure_logged_in():
            raise EvakaAuthError("Failed to authenticate")

        session = await self._get_session()
        url = f"{self._base_url}/api/citizen/messages/unread-count"

        try:
            async with session.get(url, headers=CSRF_HEADER) as response:
                if response.status == 401:
                    self._logged_in = False
                    if await self.login():
                        return await self.get_unread_message_count()
                    raise EvakaSessionExpiredError("Session expired and re-login failed")

                if response.status != 200:
                    _LOGGER.error("Failed to fetch unread count: %s", response.status)
                    return 0

                # The API might return just a number or a JSON object
                text = await response.text()
                try:
                    return int(text)
                except ValueError:
                    data = await response.json()
                    return data.get("count", 0)

        except aiohttp.ClientError as err:
            _LOGGER.error("Connection error fetching unread count: %s", err)
            return 0

    async def get_daily_schedule(self, date: datetime | None = None) -> list[dict[str, Any]]:
        """Fetch schedule for a specific day.

        Returns events for the given date (defaults to today).
        """
        if date is None:
            date = datetime.now()

        start_str = date.strftime("%Y-%m-%d")
        end_str = start_str  # Same day

        events = await self.get_calendar_events(date, date)
        return events

    async def get_weekly_schedule(
        self,
        start_date: datetime | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch schedule for 2 weeks (current + next).

        Returns events grouped by day. Fetches 2 weeks to ensure
        we always have next Monday's data available on Fridays.
        """
        if start_date is None:
            start_date = datetime.now()

        # Get to Monday of the current week
        days_since_monday = start_date.weekday()
        monday = start_date - timedelta(days=days_since_monday)
        # Fetch 2 weeks (14 days) to include next Monday
        end_date = monday + timedelta(days=13)

        events = await self.get_calendar_events(monday, end_date)

        # Group events by date (14 days)
        weekly: dict[str, list[dict[str, Any]]] = {}
        for i in range(14):
            day = monday + timedelta(days=i)
            day_str = day.strftime("%Y-%m-%d")
            weekly[day_str] = []

        for event in events:
            period = event.get("period", {})
            event_date = period.get("start", "")[:10]  # Get YYYY-MM-DD part
            if event_date in weekly:
                weekly[event_date].append(event)

        return weekly

    @property
    def user_info(self) -> dict[str, Any] | None:
        """Return the logged in user info."""
        return self._user_info

    @property
    def is_logged_in(self) -> bool:
        """Return whether we are logged in."""
        return self._logged_in


async def validate_credentials(
    username: str,
    password: str,
    municipality: str,
) -> bool:
    """Validate Evaka credentials."""
    api = EvakaApi(username, password, municipality)
    try:
        result = await api.login()
        return result
    except EvakaApiError:
        return False
    finally:
        await api.close()
