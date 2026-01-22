"""Calendar platform for Evaka integration."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import EvakaApi, EvakaApiError, EvakaAuthError
from .const import DOMAIN, MUNICIPALITIES

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Evaka calendar based on a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    api: EvakaApi = data["api"]
    municipality: str = data["municipality"]

    async_add_entities([EvakaCalendarEntity(api, municipality, entry)], True)


class EvakaCalendarEntity(CalendarEntity):
    """Representation of an Evaka calendar."""

    _attr_has_entity_name = True

    def __init__(
        self,
        api: EvakaApi,
        municipality: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the Evaka calendar."""
        self._api = api
        self._municipality = municipality
        self._entry = entry
        self._events: list[CalendarEvent] = []
        self._attr_unique_id = f"evaka_calendar_{municipality}_{entry.entry_id}"
        municipality_name = MUNICIPALITIES[municipality]["name"]
        self._attr_name = f"Evaka {municipality_name}"
        self._authenticated = True

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        now = dt_util.now()
        for event in sorted(self._events, key=lambda e: e.start):
            end = event.end
            if isinstance(end, datetime):
                if end > now:
                    return event
            else:
                # It's a date, compare with today
                if end >= now.date():
                    return event
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "authenticated": self._authenticated,
            "municipality": self._municipality,
            "event_count": len(self._events),
        }

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        try:
            raw_events = await self._api.get_calendar_events(start_date, end_date)
            self._authenticated = True
            return self._convert_events(raw_events)
        except EvakaAuthError as err:
            _LOGGER.error("Authentication error: %s", err)
            self._authenticated = False
            return []
        except EvakaApiError as err:
            _LOGGER.error("Error fetching events: %s", err)
            return []

    async def async_update(self) -> None:
        """Update the calendar events."""
        try:
            now = datetime.now()
            end = now + timedelta(weeks=4)
            raw_events = await self._api.get_calendar_events(now, end)
            self._events = self._convert_events(raw_events)
            self._authenticated = True
            _LOGGER.debug("Updated Evaka calendar with %d events", len(self._events))
        except EvakaAuthError as err:
            _LOGGER.error("Authentication error: %s", err)
            self._authenticated = False
        except EvakaApiError as err:
            _LOGGER.error("Error updating calendar: %s", err)

    def _convert_events(self, raw_events: list[dict[str, Any]]) -> list[CalendarEvent]:
        """Convert raw Evaka events to CalendarEvent objects."""
        events = []
        for event in raw_events:
            try:
                period = event.get("period", {})
                start_str = period.get("start")
                end_str = period.get("end", start_str)

                if not start_str:
                    continue

                # Parse the datetime strings
                start = self._parse_datetime(start_str)
                end = self._parse_datetime(end_str)

                # Check if it's an all-day event (date only, no time)
                is_all_day = "T" not in start_str

                if is_all_day:
                    start = start.date() if isinstance(start, datetime) else start
                    end = end.date() if isinstance(end, datetime) else end
                    # For all-day events, add one day to end to make it inclusive
                    if start == end:
                        end = end + timedelta(days=1)

                events.append(
                    CalendarEvent(
                        start=start,
                        end=end,
                        summary=event.get("title", "Evaka Event"),
                        description=event.get("description", ""),
                    )
                )
            except (KeyError, ValueError) as err:
                _LOGGER.warning("Error parsing event: %s - %s", event, err)

        return events

    def _parse_datetime(self, dt_str: str) -> datetime:
        """Parse a datetime string from Evaka."""
        if "T" in dt_str:
            # ISO format with time
            if dt_str.endswith("Z"):
                dt_str = dt_str[:-1] + "+00:00"
            return datetime.fromisoformat(dt_str)
        else:
            # Date only
            return datetime.strptime(dt_str, "%Y-%m-%d")
