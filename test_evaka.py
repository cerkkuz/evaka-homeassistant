#!/usr/bin/env python3
"""
Standalone test script for Evaka API.
Run this to verify credentials and API connectivity before installing in Home Assistant.

Usage:
    python3 test_evaka.py

Requirements:
    pip install aiohttp
"""

import asyncio
import getpass
import sys
from datetime import datetime, timedelta

import aiohttp

# Supported municipalities
MUNICIPALITIES = {
    "espoo": {
        "name": "Espoo",
        "base_url": "https://espoonvarhaiskasvatus.fi",
    },
    "oulu": {
        "name": "Oulu",
        "base_url": "https://varhaiskasvatus.ouka.fi",
    },
    "tampere": {
        "name": "Tampere",
        "base_url": "https://varhaiskasvatus.tampere.fi",
    },
    "turku": {
        "name": "Turku",
        "base_url": "https://varhaiskasvatus.turku.fi",
    },
}

CSRF_HEADER = {"x-evaka-csrf": "1"}


class EvakaTestClient:
    """Test client for Evaka API."""

    def __init__(self, username: str, password: str, municipality: str):
        self.username = username
        self.password = password
        self.municipality = municipality
        self.base_url = MUNICIPALITIES[municipality]["base_url"]
        self.session = None
        self.logged_in = False
        self.user_info = None

    async def __aenter__(self):
        jar = aiohttp.CookieJar()
        self.session = aiohttp.ClientSession(cookie_jar=jar)
        return self

    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()

    async def test_connection(self) -> bool:
        """Test basic connectivity to Evaka."""
        print(f"\n[1/7] Testing connection to {self.base_url}...")
        try:
            async with self.session.get(
                self.base_url, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    print(f"      OK - Connected successfully (HTTP {response.status})")
                    return True
                else:
                    print(f"      WARNING - Unexpected status: {response.status}")
                    return True
        except aiohttp.ClientError as e:
            print(f"      FAILED - Connection error: {e}")
            return False

    async def test_login(self) -> bool:
        """Test weak login authentication."""
        print(f"\n[2/7] Testing weak login (username/password)...")
        try:
            url = f"{self.base_url}/api/citizen/auth/weak-login"
            data = {
                "username": self.username,
                "password": self.password,
            }
            headers = {
                "Content-Type": "application/json",
                **CSRF_HEADER,
            }

            async with self.session.post(url, json=data, headers=headers) as response:
                if response.status == 200:
                    print("      OK - Login successful!")
                    self.logged_in = True

                    # Get user info
                    async with self.session.get(
                        f"{self.base_url}/api/citizen/auth/status",
                        headers=CSRF_HEADER
                    ) as status_resp:
                        if status_resp.status == 200:
                            status_data = await status_resp.json()
                            self.user_info = status_data.get("user", {}).get("details", {})
                            name = f"{self.user_info.get('firstName', '')} {self.user_info.get('lastName', '')}"
                            print(f"      Logged in as: {name.strip()}")

                    return True

                elif response.status == 401:
                    print("      FAILED - Invalid username or password")
                    return False

                elif response.status == 403:
                    print("      FAILED - Weak login is not enabled for this account")
                    print("      Please enable 'Email login' in your Evaka profile settings")
                    return False

                elif response.status == 429:
                    print("      FAILED - Too many login attempts, account temporarily locked")
                    return False

                else:
                    text = await response.text()
                    print(f"      FAILED - HTTP {response.status}: {text[:100]}")
                    return False

        except Exception as e:
            print(f"      FAILED - Error: {e}")
            return False

    async def test_calendar(self) -> bool:
        """Test fetching calendar events."""
        print(f"\n[3/7] Testing calendar API...")
        if not self.logged_in:
            print("      SKIPPED - Not logged in")
            return False

        try:
            now = datetime.now()
            end = now + timedelta(weeks=4)
            start_str = now.strftime("%Y-%m-%d")
            end_str = end.strftime("%Y-%m-%d")

            url = f"{self.base_url}/api/citizen/calendar-events"
            params = {"start": start_str, "end": end_str}

            async with self.session.get(url, params=params, headers=CSRF_HEADER) as response:
                if response.status == 401:
                    print("      FAILED - Session expired")
                    return False

                if response.status != 200:
                    print(f"      FAILED - HTTP {response.status}")
                    return False

                events = await response.json()
                print(f"      OK - Retrieved {len(events)} events")

                if events:
                    print("\n      Upcoming events:")
                    for event in events[:5]:
                        title = event.get("title", "No title")
                        period = event.get("period", {})
                        start = period.get("start", "Unknown date")
                        print(f"        - {start}: {title}")

                return True

        except Exception as e:
            print(f"      FAILED - Error: {e}")
            return False

    async def test_children(self) -> bool:
        """Test fetching children info."""
        print(f"\n[4/7] Testing children API...")
        if not self.logged_in:
            print("      SKIPPED - Not logged in")
            return False

        try:
            url = f"{self.base_url}/api/citizen/children"

            async with self.session.get(url, headers=CSRF_HEADER) as response:
                if response.status == 401:
                    print("      FAILED - Session expired")
                    return False

                if response.status != 200:
                    print(f"      FAILED - HTTP {response.status}")
                    return False

                children = await response.json()
                print(f"      OK - Found {len(children)} children")

                if children:
                    print("\n      Children:")
                    for child in children:
                        first_name = child.get("firstName", "?")
                        last_name = child.get("lastName", "?")
                        print(f"        - {first_name} {last_name}")

                return True

        except Exception as e:
            print(f"      FAILED - Error: {e}")
            return False

    async def test_messages(self) -> bool:
        """Test fetching messages."""
        print(f"\n[5/7] Testing messages API...")
        if not self.logged_in:
            print("      SKIPPED - Not logged in")
            return False

        try:
            url = f"{self.base_url}/api/citizen/messages/received"
            params = {"page": 1}

            async with self.session.get(url, params=params, headers=CSRF_HEADER) as response:
                if response.status == 401:
                    print("      FAILED - Session expired")
                    return False

                if response.status != 200:
                    print(f"      FAILED - HTTP {response.status}")
                    text = await response.text()
                    print(f"      Response: {text[:200]}")
                    return False

                result = await response.json()
                messages = result.get("data", [])
                total = result.get("total", 0)
                print(f"      OK - Retrieved {len(messages)} messages (total: {total})")

                if messages:
                    print("\n      Recent messages:")
                    unread_count = 0
                    for msg in messages[:5]:
                        title = msg.get("title", "No title")
                        urgent = msg.get("urgent", False)
                        thread_messages = msg.get("messages", [])

                        is_read = True
                        sender_name = "Unknown"
                        sent_at = ""

                        if thread_messages:
                            latest = thread_messages[0]
                            is_read = latest.get("readAt") is not None
                            sender = latest.get("sender", {})
                            sender_name = sender.get("name", "Unknown")
                            sent_at = latest.get("sentAt", "")[:10]

                        if not is_read:
                            unread_count += 1

                        urgent_marker = "[URGENT] " if urgent else ""
                        read_marker = "[NEW] " if not is_read else ""
                        print(f"        - {read_marker}{urgent_marker}{sent_at} - {title[:40]}")
                        print(f"          From: {sender_name}")

                    print(f"\n      Unread messages: {unread_count}")

                return True

        except Exception as e:
            print(f"      FAILED - Error: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def test_daily_schedule(self) -> bool:
        """Test fetching daily schedule."""
        print(f"\n[6/7] Testing daily schedule...")
        if not self.logged_in:
            print("      SKIPPED - Not logged in")
            return False

        try:
            today = datetime.now()
            start_str = today.strftime("%Y-%m-%d")

            url = f"{self.base_url}/api/citizen/calendar-events"
            params = {"start": start_str, "end": start_str}

            async with self.session.get(url, params=params, headers=CSRF_HEADER) as response:
                if response.status == 401:
                    print("      FAILED - Session expired")
                    return False

                if response.status != 200:
                    print(f"      FAILED - HTTP {response.status}")
                    return False

                events = await response.json()
                print(f"      OK - Today ({start_str}) has {len(events)} events")

                if events:
                    print("\n      Today's events:")
                    for event in events:
                        title = event.get("title", "No title")
                        period = event.get("period", {})
                        start = period.get("start", "")

                        # Extract time if present
                        time_str = ""
                        if "T" in start:
                            try:
                                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                                time_str = dt.strftime("%H:%M")
                            except:
                                pass

                        if time_str:
                            print(f"        - {time_str}: {title}")
                        else:
                            print(f"        - {title}")
                else:
                    print("      No events today")

                return True

        except Exception as e:
            print(f"      FAILED - Error: {e}")
            return False

    async def test_weekly_schedule(self) -> bool:
        """Test fetching weekly schedule."""
        print(f"\n[7/7] Testing weekly schedule...")
        if not self.logged_in:
            print("      SKIPPED - Not logged in")
            return False

        try:
            today = datetime.now()
            # Get to Monday of current week
            days_since_monday = today.weekday()
            monday = today - timedelta(days=days_since_monday)
            sunday = monday + timedelta(days=6)

            start_str = monday.strftime("%Y-%m-%d")
            end_str = sunday.strftime("%Y-%m-%d")

            url = f"{self.base_url}/api/citizen/calendar-events"
            params = {"start": start_str, "end": end_str}

            async with self.session.get(url, params=params, headers=CSRF_HEADER) as response:
                if response.status == 401:
                    print("      FAILED - Session expired")
                    return False

                if response.status != 200:
                    print(f"      FAILED - HTTP {response.status}")
                    return False

                events = await response.json()
                week_num = today.isocalendar()[1]
                print(f"      OK - Week {week_num} ({start_str} to {end_str}) has {len(events)} events")

                # Group by date
                day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                weekly = {}
                for i in range(7):
                    day = monday + timedelta(days=i)
                    day_str = day.strftime("%Y-%m-%d")
                    weekly[day_str] = []

                for event in events:
                    period = event.get("period", {})
                    event_date = period.get("start", "")[:10]
                    if event_date in weekly:
                        weekly[event_date].append(event)

                print("\n      Weekly overview:")
                for i, (date_str, day_events) in enumerate(sorted(weekly.items())):
                    day_name = day_names[i] if i < len(day_names) else "?"
                    display_date = date_str[5:]  # MM-DD

                    if day_events:
                        titles = ", ".join(e.get("title", "?")[:20] for e in day_events[:2])
                        if len(day_events) > 2:
                            titles += f" (+{len(day_events)-2} more)"
                        print(f"        {day_name} {display_date}: {titles}")
                    else:
                        print(f"        {day_name} {display_date}: -")

                return True

        except Exception as e:
            print(f"      FAILED - Error: {e}")
            return False


async def main():
    print("=" * 70)
    print("Evaka Integration Test Script")
    print("=" * 70)

    print("\nThis script tests your Evaka credentials and all API endpoints")
    print("before installing the Home Assistant integration.")

    # Select municipality
    print("\nAvailable municipalities:")
    for i, (key, data) in enumerate(MUNICIPALITIES.items(), 1):
        print(f"  {i}. {data['name']}")

    while True:
        try:
            choice = input("\nSelect municipality (1-4): ").strip()
            idx = int(choice) - 1
            municipality = list(MUNICIPALITIES.keys())[idx]
            break
        except (ValueError, IndexError):
            print("Invalid choice, try again")

    # Get credentials
    username = input("Email/Username: ").strip()
    try:
        password = getpass.getpass("Password: ")
    except Exception:
        password = input("Password (will be visible): ").strip()

    print("\n" + "=" * 70)
    print(f"Testing Evaka API for {MUNICIPALITIES[municipality]['name']}")
    print("=" * 70)

    async with EvakaTestClient(username, password, municipality) as client:
        results = {
            "Connection": await client.test_connection(),
            "Login": await client.test_login(),
            "Calendar": await client.test_calendar(),
            "Children": await client.test_children(),
            "Messages": await client.test_messages(),
            "Daily Schedule": await client.test_daily_schedule(),
            "Weekly Schedule": await client.test_weekly_schedule(),
        }

    print("\n" + "=" * 70)
    print("Test Results Summary")
    print("=" * 70)
    all_passed = True
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        symbol = "+" if passed else "x"
        print(f"  [{symbol}] {test_name}: {status}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 70)
    if all_passed:
        print("All tests passed!")
        print("You can now install the integration in Home Assistant.")
        print("\nEntities that will be created:")
        print("  - sensor.evaka_<municipality>_messages    (message list with attributes)")
        print("  - sensor.evaka_<municipality>_unread      (unread message count)")
        print("  - sensor.evaka_<municipality>_today       (today's schedule)")
        print("  - sensor.evaka_<municipality>_week        (weekly schedule)")
        print("  - calendar.evaka_<municipality>           (calendar events)")
    else:
        print("Some tests failed. Please check your credentials and try again.")
        if not results.get("Login"):
            print("\nTip: Make sure 'Email login' is enabled in your Evaka profile.")
    print("=" * 70)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
