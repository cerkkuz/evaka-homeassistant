"""Constants for the Evaka integration."""

DOMAIN = "evaka"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_MUNICIPALITY = "municipality"

# Supported municipalities and their base URLs
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

DEFAULT_SCAN_INTERVAL = 3600  # 1 hour in seconds
CALENDAR_NAME = "Evaka Calendar"

# API Headers
CSRF_HEADER = {"x-evaka-csrf": "1"}
