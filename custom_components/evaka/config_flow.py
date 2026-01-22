"""Config flow for Evaka integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback

from .api import EvakaApiError, validate_credentials
from .const import CONF_MUNICIPALITY, DOMAIN, MUNICIPALITIES

_LOGGER = logging.getLogger(__name__)


class EvakaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Evaka."""

    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return EvakaOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                valid = await validate_credentials(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    user_input[CONF_MUNICIPALITY],
                )

                if valid:
                    await self.async_set_unique_id(
                        f"evaka_{user_input[CONF_MUNICIPALITY]}_{user_input[CONF_USERNAME]}"
                    )
                    self._abort_if_unique_id_configured()

                    municipality_name = MUNICIPALITIES[user_input[CONF_MUNICIPALITY]][
                        "name"
                    ]
                    return self.async_create_entry(
                        title=f"Evaka - {municipality_name}",
                        data=user_input,
                    )
                else:
                    errors["base"] = "invalid_auth"

            except EvakaApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        municipality_options = {
            key: data["name"] for key, data in MUNICIPALITIES.items()
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MUNICIPALITY): vol.In(municipality_options),
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )


class EvakaOptionsFlow(OptionsFlow):
    """Handle options flow for Evaka."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options - update credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                valid = await validate_credentials(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                    self.config_entry.data[CONF_MUNICIPALITY],
                )

                if valid:
                    new_data = {**self.config_entry.data}
                    new_data[CONF_USERNAME] = user_input[CONF_USERNAME]
                    new_data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data=new_data
                    )
                    return self.async_create_entry(title="", data={})
                else:
                    errors["base"] = "invalid_auth"

            except EvakaApiError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=self.config_entry.data.get(CONF_USERNAME, ""),
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )
