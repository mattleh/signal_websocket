import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import DOMAIN, CONF_CONNECTION_TYPE

# Add "CONF_SCAN_INTERVAL" to your imports from .const if you put it there
CONF_SCAN_INTERVAL = "scan_interval"

class SignalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Signal Messenger."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Optional: Add validation here to check if the host is reachable
            return self.async_create_entry(
                title=f"Signal ({user_input['number']})", 
                data=user_input
            )

        # Define the form schema
        data_schema = vol.Schema({
            vol.Required("host", default="127.0.0.1"): str,
            vol.Required("port", default=8080): int,
            vol.Required("number"): str,
            vol.Required(CONF_CONNECTION_TYPE, default="websocket"): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        {"value": "websocket", "label": "WebSocket (Real-time Push)"},
                        {"value": "rest", "label": "REST API (Periodic Polling)"},
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="connection_type",
                )
            ),
        })

        return self.async_show_form(
            step_id="user", 
            data_schema=data_schema, 
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Create the options flow."""
        # FIX: No arguments passed here
        return SignalOptionsFlowHandler()

class SignalOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Signal options."""

    # FIX: We removed __init__ entirely. 
    # self.config_entry is automatically provided by Home Assistant.

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Access connection_type from the existing entry data
        conn_type = self.config_entry.data.get("connection_type")
        
        options_schema = {}
        description_msg = ""

        if conn_type == "rest":
            description_msg = "Adjust the polling frequency for the REST API."
            options_schema = {
                vol.Optional(
                    "scan_interval",
                    default=self.config_entry.options.get("scan_interval", 10),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
            }
        else:
            # WebSocket Mode
            description_msg = "You are using WebSockets. Messages are received instantly in real-time, so no polling interval is needed."

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(options_schema),
            description_placeholders={"msg": description_msg}
        )