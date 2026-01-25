"""Sensor platform for Evaka messages and schedule integration."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, TypedDict

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import EvakaApi, EvakaApiError
from .const import DOMAIN, MUNICIPALITIES

_LOGGER = logging.getLogger(__name__)

# Finnish day names (Monday=0 ... Sunday=6)
DAYS_FI = ["Maanantai", "Tiistai", "Keskiviikko", "Torstai", "Perjantai", "Lauantai", "Sunnuntai"]


def format_date_fi(dt: datetime) -> str:
    """Format date with Finnish day name."""
    day_name = DAYS_FI[dt.weekday()]
    return f"{day_name}, {dt.strftime('%d.%m.%Y')}"


class MessagesData(TypedDict):
    """Type for messages coordinator data."""

    messages: list[dict[str, Any]]
    total: int
    pages: int


class ScheduleData(TypedDict):
    """Type for schedule coordinator data."""

    daily: list[dict[str, Any]]
    weekly: dict[str, list[dict[str, Any]]]
    last_updated: str

# Update every 4 hours (or on HA restart)
SCAN_INTERVAL = timedelta(hours=4)

# Schedule updates more frequently (every hour) since it's time-sensitive
SCHEDULE_SCAN_INTERVAL = timedelta(hours=1)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Evaka sensors based on a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    api: EvakaApi = data["api"]
    municipality: str = data["municipality"]

    # Create coordinator for messages
    messages_coordinator = EvakaMessagesCoordinator(hass, api, entry)

    # Create coordinator for schedule
    schedule_coordinator = EvakaScheduleCoordinator(hass, api)

    # Fetch initial data
    await messages_coordinator.async_config_entry_first_refresh()
    await schedule_coordinator.async_config_entry_first_refresh()

    async_add_entities([
        EvakaMessagesSensor(messages_coordinator, municipality, entry),
        EvakaUnreadCountSensor(messages_coordinator, municipality, entry),
        EvakaDailyScheduleSensor(schedule_coordinator, municipality, entry),
        EvakaTomorrowScheduleSensor(schedule_coordinator, municipality, entry),
        EvakaWeeklyScheduleSensor(schedule_coordinator, municipality, entry),
    ])


class EvakaMessagesCoordinator(DataUpdateCoordinator[MessagesData]):
    """Coordinator for Evaka messages data with notification support."""

    def __init__(
        self, hass: HomeAssistant, api: EvakaApi, entry: ConfigEntry
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Evaka Messages",
            update_interval=SCAN_INTERVAL,
        )
        self._api = api
        self._entry = entry
        self._previous_unread_count: int | None = None
        self._previous_message_ids: set[str] = set()

    async def _async_update_data(self) -> MessagesData:
        """Fetch data from Evaka."""
        try:
            messages_data = await self._api.get_messages(page=1, limit=10)
            messages = messages_data.get("data", [])

            # Check for new messages and send notifications
            await self._check_and_notify_new_messages(messages)

            return {
                "messages": messages,
                "total": messages_data.get("total", 0),
                "pages": messages_data.get("pages", 0),
            }
        except EvakaApiError as err:
            raise UpdateFailed(f"Error fetching messages: {err}") from err

    async def _check_and_notify_new_messages(
        self, messages: list[dict[str, Any]]
    ) -> None:
        """Check for new messages and send push notifications."""
        current_message_ids: set[str] = set()
        new_messages: list[dict[str, Any]] = []

        for msg in messages:
            msg_id = msg.get("id")
            if msg_id:
                current_message_ids.add(msg_id)

                # Check if this is a new message we haven't seen
                if (
                    self._previous_message_ids
                    and msg_id not in self._previous_message_ids
                ):
                    # Check if it's unread
                    thread_messages = msg.get("messages", [])
                    if thread_messages:
                        latest = thread_messages[0]
                        if latest.get("readAt") is None:
                            new_messages.append(msg)

        # Send notifications for new unread messages
        for msg in new_messages:
            await self._send_notification(msg)

        # Update tracked message IDs
        self._previous_message_ids = current_message_ids

    async def _send_notification(self, msg: dict[str, Any]) -> None:
        """Send a Home Assistant notification for a new message."""
        title = msg.get("title", "New Evaka Message")
        urgent = msg.get("urgent", False)

        thread_messages = msg.get("messages", [])
        sender_name = "Unknown"
        content_preview = ""

        if thread_messages:
            latest = thread_messages[0]
            sender = latest.get("sender", {})
            sender_name = sender.get("name", "Unknown")
            content = latest.get("content", "")
            content_preview = content[:150].replace("\n", " ").strip()
            if len(content) > 150:
                content_preview += "..."

        # Get children names
        children = msg.get("children", [])
        child_names = ", ".join(
            f"{c.get('firstName', '')}" for c in children
        )

        # Build notification message
        notification_title = f"{'🚨 URGENT: ' if urgent else ''}Evaka: {title}"
        notification_message = f"From: {sender_name}"
        if child_names:
            notification_message += f"\nChild: {child_names}"
        if content_preview:
            notification_message += f"\n\n{content_preview}"

        # Send persistent notification
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": notification_title,
                "message": notification_message,
                "notification_id": f"evaka_message_{msg.get('id', 'unknown')}",
            },
        )

        _LOGGER.info("Sent notification for new Evaka message: %s", title)


class EvakaScheduleCoordinator(DataUpdateCoordinator[ScheduleData]):
    """Coordinator for Evaka schedule data."""

    def __init__(self, hass: HomeAssistant, api: EvakaApi) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Evaka Schedule",
            update_interval=SCHEDULE_SCAN_INTERVAL,
        )
        self._api = api

    async def _async_update_data(self) -> ScheduleData:
        """Fetch schedule data from Evaka."""
        try:
            today = datetime.now()
            daily = await self._api.get_daily_schedule(today)
            weekly = await self._api.get_weekly_schedule(today)

            return {
                "daily": daily,
                "weekly": weekly,
                "last_updated": today.isoformat(),
            }
        except EvakaApiError as err:
            raise UpdateFailed(f"Error fetching schedule: {err}") from err


class EvakaMessagesSensor(CoordinatorEntity[EvakaMessagesCoordinator], SensorEntity):
    """Sensor showing Evaka messages for e-paper and other displays."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:email-multiple"

    def __init__(
        self,
        coordinator: EvakaMessagesCoordinator,
        municipality: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._municipality = municipality
        self._entry = entry
        self._attr_unique_id = f"evaka_messages_{municipality}_{entry.entry_id}"
        municipality_name = MUNICIPALITIES[municipality]["name"]
        self._attr_name = f"Evaka {municipality_name} Messages"

    @property
    def native_value(self) -> int:
        """Return the total number of messages."""
        if self.coordinator.data:
            return self.coordinator.data.get("total", 0)
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return message data as attributes for e-paper displays.

        Provides messages in a format optimized for ESPHome e-paper displays.
        """
        if not self.coordinator.data:
            return {"messages": [], "message_count": 0}

        messages = self.coordinator.data.get("messages", [])
        formatted_messages = []

        for msg in messages:
            # Get the latest message in the thread
            thread_messages = msg.get("messages", [])
            if not thread_messages:
                continue

            latest = thread_messages[0]
            sent_at = latest.get("sentAt", "")

            # Parse the datetime
            try:
                dt = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
                date_str = dt.strftime("%d.%m.%Y")
                time_str = dt.strftime("%H:%M")
            except (ValueError, AttributeError):
                date_str = ""
                time_str = ""

            # Get sender name
            sender = latest.get("sender", {})
            sender_name = sender.get("name", "Unknown")

            # Get content preview (first 200 chars)
            content = latest.get("content", "")
            content_preview = content[:200].replace("\n", " ").strip()
            if len(content) > 200:
                content_preview += "..."

            # Get children names
            children = msg.get("children", [])
            child_names = [
                f"{c.get('firstName', '')} {c.get('lastName', '')}"
                for c in children
            ]

            # Check if read
            is_read = latest.get("readAt") is not None

            formatted_messages.append({
                "id": msg.get("id"),
                "title": msg.get("title", "No title"),
                "sender": sender_name,
                "date": date_str,
                "time": time_str,
                "urgent": msg.get("urgent", False),
                "type": msg.get("messageType", "MESSAGE"),
                "content_preview": content_preview,
                "content_full": content,
                "children": child_names,
                "is_read": is_read,
                "has_attachments": len(latest.get("attachments", [])) > 0,
            })

        # Count unread messages
        unread_count = sum(1 for m in formatted_messages if not m["is_read"])

        # Create a simple text summary for e-paper (first 3 messages)
        epaper_text = []
        for m in formatted_messages[:3]:
            urgent_marker = "[!] " if m["urgent"] else ""
            read_marker = "" if m["is_read"] else "* "
            epaper_text.append(
                f"{read_marker}{urgent_marker}{m['date']} {m['title'][:30]}"
            )

        return {
            "messages": formatted_messages,
            "message_count": len(formatted_messages),
            "unread_count": unread_count,
            "total_messages": self.coordinator.data.get("total", 0),
            "epaper_summary": "\n".join(epaper_text),
            "latest_title": (
                formatted_messages[0]["title"] if formatted_messages else ""
            ),
            "latest_sender": (
                formatted_messages[0]["sender"] if formatted_messages else ""
            ),
            "latest_date": (
                formatted_messages[0]["date"] if formatted_messages else ""
            ),
            "latest_content": (
                formatted_messages[0]["content_preview"]
                if formatted_messages
                else ""
            ),
            "latest_urgent": (
                formatted_messages[0]["urgent"] if formatted_messages else False
            ),
        }


class EvakaUnreadCountSensor(CoordinatorEntity[EvakaMessagesCoordinator], SensorEntity):
    """Sensor showing unread message count - perfect for badges."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:email-alert"

    def __init__(
        self,
        coordinator: EvakaMessagesCoordinator,
        municipality: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._municipality = municipality
        self._entry = entry
        self._attr_unique_id = f"evaka_unread_{municipality}_{entry.entry_id}"
        municipality_name = MUNICIPALITIES[municipality]["name"]
        self._attr_name = f"Evaka {municipality_name} Unread"

    @property
    def native_value(self) -> int:
        """Return the count of unread messages."""
        if not self.coordinator.data:
            return 0

        messages = self.coordinator.data.get("messages", [])
        unread = 0
        for msg in messages:
            thread_messages = msg.get("messages", [])
            if thread_messages:
                latest = thread_messages[0]
                if latest.get("readAt") is None:
                    unread += 1
        return unread

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        messages = self.coordinator.data.get("messages", [])
        urgent_unread = 0
        for msg in messages:
            if msg.get("urgent", False):
                thread_messages = msg.get("messages", [])
                if thread_messages:
                    latest = thread_messages[0]
                    if latest.get("readAt") is None:
                        urgent_unread += 1

        return {
            "urgent_unread": urgent_unread,
            "total_messages": self.coordinator.data.get("total", 0),
        }


class EvakaDailyScheduleSensor(CoordinatorEntity[EvakaScheduleCoordinator], SensorEntity):
    """Sensor showing today's daycare schedule."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-today"

    def __init__(
        self,
        coordinator: EvakaScheduleCoordinator,
        municipality: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._municipality = municipality
        self._entry = entry
        self._attr_unique_id = (
            f"evaka_daily_schedule_{municipality}_{entry.entry_id}"
        )
        municipality_name = MUNICIPALITIES[municipality]["name"]
        self._attr_name = f"Evaka {municipality_name} Today"

    @property
    def native_value(self) -> int:
        """Return the number of events today."""
        if self.coordinator.data:
            return len(self.coordinator.data.get("daily", []))
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return today's schedule as attributes."""
        if not self.coordinator.data:
            return {"events": [], "event_count": 0, "summary": "No data"}

        daily_events = self.coordinator.data.get("daily", [])
        formatted_events = []
        today_str = format_date_fi(datetime.now())

        for event in daily_events:
            period = event.get("period", {})
            start_str = period.get("start", "")
            end_str = period.get("end", start_str)

            # Parse times
            start_time = ""
            end_time = ""
            if "T" in start_str:
                try:
                    dt = datetime.fromisoformat(
                        start_str.replace("Z", "+00:00")
                    )
                    start_time = dt.strftime("%H:%M")
                except ValueError:
                    pass
            if "T" in end_str:
                try:
                    dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    end_time = dt.strftime("%H:%M")
                except ValueError:
                    pass

            formatted_events.append({
                "title": event.get("title", "Event"),
                "description": event.get("description", ""),
                "start_time": start_time,
                "end_time": end_time,
                "all_day": "T" not in start_str,
            })

        # Create e-paper friendly summary
        if formatted_events:
            summary_lines = [today_str]
            for e in formatted_events[:5]:
                if e["start_time"]:
                    summary_lines.append(
                        f"{e['start_time']}-{e['end_time']}: {e['title'][:25]}"
                    )
                else:
                    summary_lines.append(f"• {e['title'][:30]}")
            epaper_summary = "\n".join(summary_lines)
        else:
            epaper_summary = f"{today_str}\nNo events today"

        return {
            "date": today_str,
            "events": formatted_events,
            "event_count": len(formatted_events),
            "epaper_summary": epaper_summary,
            "first_event": (
                formatted_events[0]["title"] if formatted_events else ""
            ),
            "first_event_time": (
                formatted_events[0]["start_time"] if formatted_events else ""
            ),
        }


class EvakaTomorrowScheduleSensor(CoordinatorEntity[EvakaScheduleCoordinator], SensorEntity):
    """Sensor showing tomorrow's (or next Monday's) daycare schedule."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-arrow-right"

    def __init__(
        self,
        coordinator: EvakaScheduleCoordinator,
        municipality: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._municipality = municipality
        self._entry = entry
        self._attr_unique_id = (
            f"evaka_tomorrow_schedule_{municipality}_{entry.entry_id}"
        )
        municipality_name = MUNICIPALITIES[municipality]["name"]
        self._attr_name = f"Evaka {municipality_name} Tomorrow"

    def _get_next_daycare_day(self) -> tuple[datetime, str]:
        """Get the next daycare day (tomorrow, or Monday if Friday/weekend).

        Returns tuple of (target_date, label).
        """
        today = datetime.now()
        weekday = today.weekday()  # Monday=0, Sunday=6

        if weekday == 4:  # Friday -> next Monday
            next_day = today + timedelta(days=3)
            label = "Maanantai"
        elif weekday == 5:  # Saturday -> next Monday
            next_day = today + timedelta(days=2)
            label = "Maanantai"
        elif weekday == 6:  # Sunday -> next Monday
            next_day = today + timedelta(days=1)
            label = "Maanantai"
        else:  # Mon-Thu -> tomorrow
            next_day = today + timedelta(days=1)
            label = "Huomenna"

        return next_day, label

    @property
    def native_value(self) -> int:
        """Return the number of events for next daycare day."""
        if not self.coordinator.data:
            return 0

        next_day, _ = self._get_next_daycare_day()
        next_day_str = next_day.strftime("%Y-%m-%d")
        weekly = self.coordinator.data.get("weekly", {})

        return len(weekly.get(next_day_str, []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return next daycare day's schedule as attributes."""
        if not self.coordinator.data:
            return {"events": [], "event_count": 0, "summary": "No data"}

        next_day, label = self._get_next_daycare_day()
        next_day_str = next_day.strftime("%Y-%m-%d")
        display_date = format_date_fi(next_day)

        weekly = self.coordinator.data.get("weekly", {})
        day_events = weekly.get(next_day_str, [])

        formatted_events = []
        for event in day_events:
            period = event.get("period", {})
            start_str = period.get("start", "")
            end_str = period.get("end", start_str)

            start_time = ""
            end_time = ""
            if "T" in start_str:
                try:
                    dt = datetime.fromisoformat(
                        start_str.replace("Z", "+00:00")
                    )
                    start_time = dt.strftime("%H:%M")
                except ValueError:
                    pass
            if "T" in end_str:
                try:
                    dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    end_time = dt.strftime("%H:%M")
                except ValueError:
                    pass

            formatted_events.append({
                "title": event.get("title", "Event"),
                "description": event.get("description", ""),
                "start_time": start_time,
                "end_time": end_time,
                "all_day": "T" not in start_str,
            })

        # Create e-paper friendly summary
        if formatted_events:
            summary_lines = [display_date]
            for e in formatted_events[:5]:
                if e["start_time"]:
                    summary_lines.append(
                        f"{e['start_time']}-{e['end_time']}: {e['title'][:25]}"
                    )
                else:
                    summary_lines.append(f"• {e['title'][:30]}")
            epaper_summary = "\n".join(summary_lines)
        else:
            epaper_summary = f"{display_date}\nEi tapahtumia"

        return {
            "date": display_date,
            "label": label,
            "is_next_week": label == "Maanantai",
            "events": formatted_events,
            "event_count": len(formatted_events),
            "epaper_summary": epaper_summary,
            "first_event": (
                formatted_events[0]["title"] if formatted_events else ""
            ),
            "first_event_time": (
                formatted_events[0]["start_time"] if formatted_events else ""
            ),
        }


class EvakaWeeklyScheduleSensor(CoordinatorEntity[EvakaScheduleCoordinator], SensorEntity):
    """Sensor showing this week's daycare schedule."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-week"

    def __init__(
        self,
        coordinator: EvakaScheduleCoordinator,
        municipality: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._municipality = municipality
        self._entry = entry
        self._attr_unique_id = (
            f"evaka_weekly_schedule_{municipality}_{entry.entry_id}"
        )
        municipality_name = MUNICIPALITIES[municipality]["name"]
        self._attr_name = f"Evaka {municipality_name} Week"

    @property
    def native_value(self) -> int:
        """Return the total number of events this week."""
        if self.coordinator.data:
            weekly = self.coordinator.data.get("weekly", {})
            return sum(len(events) for events in weekly.values())
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return this week's schedule as attributes."""
        if not self.coordinator.data:
            return {"week": {}, "total_events": 0, "summary": "No data"}

        weekly = self.coordinator.data.get("weekly", {})
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        day_names_fi = ["Ma", "Ti", "Ke", "To", "Pe", "La", "Su"]

        formatted_week = {}
        epaper_lines = []

        # Sort dates and filter to show upcoming weekdays only
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")
        sorted_dates = sorted(weekly.keys())

        # Filter to only future/today dates that are weekdays (Mon-Fri)
        upcoming_dates = []
        for date_str in sorted_dates:
            if date_str >= today_str:
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    if dt.weekday() < 5:  # Monday=0 to Friday=4
                        upcoming_dates.append(date_str)
                except ValueError:
                    pass

        # Use upcoming weekdays for display
        sorted_dates = upcoming_dates[:7] if upcoming_dates else sorted_dates[:7]

        for i, date_str in enumerate(sorted_dates):
            events = weekly.get(date_str, [])

            # Parse date for display and get correct day name
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                display_date = dt.strftime("%d.%m")
                weekday_idx = dt.weekday()
                day_name = day_names[weekday_idx]
                day_name_fi = day_names_fi[weekday_idx]
            except ValueError:
                display_date = date_str
                day_name = "?"
                day_name_fi = "?"

            day_events = []
            for event in events:
                period = event.get("period", {})
                start_str = period.get("start", "")

                start_time = ""
                if "T" in start_str:
                    try:
                        evt_dt = datetime.fromisoformat(
                            start_str.replace("Z", "+00:00")
                        )
                        start_time = evt_dt.strftime("%H:%M")
                    except ValueError:
                        pass

                day_events.append({
                    "title": event.get("title", "Event"),
                    "time": start_time,
                })

            formatted_week[date_str] = {
                "day_name": day_name,
                "day_name_fi": day_name_fi,
                "display_date": display_date,
                "events": day_events,
                "event_count": len(day_events),
            }

            # E-paper line for this day
            if day_events:
                event_titles = ", ".join(e["title"][:15] for e in day_events[:2])
                epaper_lines.append(f"{day_name_fi} {display_date}: {event_titles}")
            else:
                epaper_lines.append(f"{day_name_fi} {display_date}: -")

        # Calculate week number
        today = datetime.now()
        week_number = today.isocalendar()[1]

        # Individual day lines for e-paper (no newlines)
        day_attrs = {}
        for i, line in enumerate(epaper_lines[:7]):  # Max 7 days (Mon-Sun)
            day_attrs[f"day{i+1}"] = line

        return {
            "week_number": week_number,
            "week": formatted_week,
            "total_events": sum(
                d["event_count"] for d in formatted_week.values()
            ),
            "epaper_summary": "\n".join(epaper_lines),
            "days_with_events": sum(
                1 for d in formatted_week.values() if d["event_count"] > 0
            ),
            **day_attrs,  # Add day1, day2, ... day7 attributes
        }
