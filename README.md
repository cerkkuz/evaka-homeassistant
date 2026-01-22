# Evaka Daycare Calendar for Home Assistant

> **⚠️ DISCLAIMER: This is a hobby project. Use at your own risk.**
>
> This integration is provided "as-is" without any warranty. It is not officially supported, maintained professionally, or guaranteed to work. The author takes no responsibility for any issues, data loss, or problems that may arise from using this integration. By using this software, you accept full responsibility for any consequences.

A Home Assistant custom integration that fetches calendar events from the Finnish Evaka daycare system and displays them in your Home Assistant calendar.

## Prerequisites

**You must have 'Email login' (Sähköpostilla kirjautuminen) enabled in your Evaka profile settings.** This feature allows login with username/password instead of Suomi.fi strong authentication.

To enable it:
1. Log into Evaka using Suomi.fi authentication
2. Go to your profile settings
3. Enable "Sähköpostilla kirjautuminen" (Email login)
4. Set your username and password

## Supported Municipalities

- Espoo
- Oulu
- Tampere
- Turku

## Installation

### HACS (Recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed
2. Add this repository as a custom repository in HACS:
   - Go to HACS -> Integrations -> Menu (three dots) -> Custom repositories
   - URL: `https://github.com/cerkkuz/evaka-homeassistant`
   - Category: Integration
3. Search for "Evaka" in HACS and install
4. Restart Home Assistant
5. Go to Settings -> Devices & Services -> Add Integration -> Search for "Evaka"

### Manual Installation

1. Copy the `custom_components/evaka` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Go to Settings -> Devices & Services -> Add Integration -> Search for "Evaka"

## Configuration

The integration uses a config flow wizard. When adding the integration, you'll be asked for:

1. **Municipality**: Select your city
2. **Email/Username**: Your Evaka weak login username (usually your email)
3. **Password**: Your Evaka weak login password

## Testing Before Installation

Before installing in Home Assistant, you can test the API connection:

```bash
cd evaka_integration
pip install aiohttp
python3 test_evaka.py
```

This will verify your credentials and API connectivity.

## Features

- **Calendar Entity**: Shows all daycare events in Home Assistant calendar
- **Automatic Updates**: Events refresh hourly
- **Auto Re-login**: Automatically re-authenticates if session expires
- **Finnish Language Support**: UI available in Finnish and English

## Troubleshooting

### Invalid Username or Password
- Verify your credentials on the Evaka website first
- Make sure you're using the weak login credentials, not Suomi.fi

### Weak Login Not Enabled (403 Error)
- Log into Evaka using Suomi.fi strong authentication
- Go to profile settings and enable "Sähköpostilla kirjautuminen"
- Set up your username and password there

### No Events Showing
- Check Home Assistant logs for errors
- Verify events exist in Evaka for the upcoming weeks

### Account Locked (429 Error)
- Too many failed login attempts
- Wait and try again later

## Technical Details

This integration uses the Evaka citizen API:
- Authentication: Weak login (username/password)
- Endpoint: `/api/citizen/auth/weak-login`
- Calendar endpoint: `/api/citizen/calendar-events`
- Polling interval: 1 hour

## License

MIT License - see below.

## Disclaimer

**This is a hobby project developed in spare time for personal use.**

- This is an **unofficial** integration
- **Not affiliated with** or endorsed by Evaka, any municipality, or Home Assistant
- **No warranty** - provided "as-is"
- **No support guaranteed** - issues may or may not be addressed
- **Use at your own risk** - the author is not responsible for any problems
- **API may change** - Evaka's API is undocumented and may break at any time
- **Security** - your credentials are stored locally in Home Assistant; review the code if concerned

By using this integration, you acknowledge that you understand these terms and accept full responsibility for its use.
