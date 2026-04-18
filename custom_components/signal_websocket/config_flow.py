from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv

from .api import async_call_signal_api
from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_NUMBER,
    CONF_SCAN_INTERVAL,
    CONF_SELECTED_CONTACTS,
    CONF_SELECTED_GROUPS,
    CONF_ENABLE_CONVERSATION,
    CONF_CONV_CONTACTS,
    CONF_CONV_GROUPS,
    CONF_CONV_VOICE_MESSAGES,
)

class SignalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Signal Messenger."""

    VERSION = 2

    def __init__(self):
        self.host = None
        self.port = None
        self.registered_number = None

    async def _get_accounts(self, host, port):
        try:
            accounts = await async_call_signal_api(self.hass, "/v1/accounts", host=host, port=port)
            return accounts if isinstance(accounts, list) else []
        except Exception:
            return []

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            self.host = user_input[CONF_HOST]
            self.port = user_input[CONF_PORT]
            return await self.async_step_account()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default="127.0.0.1"): str,
                vol.Required(CONF_PORT, default=8080): int,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_account(self, user_input=None):
        """Select or create account."""
        accounts = await self._get_accounts(self.host, self.port)
        account_options = []
        if accounts:
            account_options = [
                acc if isinstance(acc, str) else acc.get("number", str(acc))
                for acc in accounts
            ]
        account_options += ["Enter manually", "Register new"]

        if user_input is not None:
            choice = user_input["account"]
            if choice == "Enter manually":
                return await self.async_step_enter_number()
            elif choice == "Register new":
                return await self.async_step_register()
            else:
                # Selected an existing account.
                return self.async_create_entry(
                    title=f"Signal ({choice})",
                    data={
                        CONF_HOST: self.host,
                        CONF_PORT: self.port,
                        CONF_NUMBER: choice,
                    },
                )

        data_schema = vol.Schema(
            {
                vol.Required("account"): vol.In(account_options),
            }
        )

        return self.async_show_form(
            step_id="account",
            data_schema=data_schema,
        )

    async def async_step_enter_number(self, user_input=None):
        """Enter number manually."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"Signal ({user_input[CONF_NUMBER]})",
                data={
                    CONF_HOST: self.host,
                    CONF_PORT: self.port,
                    CONF_NUMBER: user_input[CONF_NUMBER],
                },
            )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NUMBER): str,
            }
        )

        return self.async_show_form(
            step_id="enter_number",
            data_schema=data_schema,
        )

    async def async_step_register(self, user_input=None):
        """Register a new number."""
        errors = {}
        if user_input is not None:
            payload = {}
            if "use_voice" in user_input and user_input["use_voice"]:
                payload["use_voice"] = True
            if "captcha" in user_input and user_input["captcha"]:
                payload["captcha"] = user_input["captcha"]

            try:
                await async_call_signal_api(
                    self.hass, f"/v1/register/{user_input[CONF_NUMBER]}",
                    host=self.host, port=self.port, method="post", payload=payload
                )
                self.registered_number = user_input[CONF_NUMBER]
                return await self.async_step_verify()
            except HomeAssistantError as e:
                errors["base"] = str(e)
            except Exception as e:
                errors["base"] = f"Registration error: {str(e)}"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NUMBER): str,
                vol.Optional("use_voice", default=False): bool,
                vol.Optional("captcha"): str,
            }
        )

        return self.async_show_form(
            step_id="register",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_verify(self, user_input=None):
        """Verify the registered number."""
        errors = {}
        if user_input is not None:
            payload = {}
            if "pin" in user_input and user_input["pin"]:
                payload["pin"] = user_input["pin"]

            try:
                await async_call_signal_api(
                    self.hass, f"/v1/register/{self.registered_number}/verify/{user_input['token']}",
                    host=self.host, port=self.port, method="post", payload=payload
                )
                return self.async_create_entry(
                    title=f"Signal ({self.registered_number})",
                    data={
                        CONF_HOST: self.host,
                        CONF_PORT: self.port,
                        CONF_NUMBER: self.registered_number,
                    },
                )
            except HomeAssistantError as e:
                errors["base"] = str(e)
            except Exception as e:
                errors["base"] = f"Verification error: {str(e)}"

        data_schema = vol.Schema(
            {
                vol.Required("token"): str,
                vol.Optional("pin"): str,
            }
        )

        return self.async_show_form(
            step_id="verify",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "SignalOptionsFlowHandler":
        """Create the options flow."""
        return SignalOptionsFlowHandler(config_entry)


class SignalOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Signal options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self.options = dict(config_entry.options)

    async def _get_contacts(self):
        """Fetch contacts from the API."""
        number = self.config_entry.data.get(CONF_NUMBER, "")
        try:
            contacts = await async_call_signal_api(self.hass, f"/v1/contacts/{number}", entry=self.config_entry)
            return {
                contact.get("number", ""): contact.get("name", contact.get("number", ""))
                for contact in contacts
            }
        except Exception:
            return {}

    async def _get_groups(self):
        """Fetch groups from the API."""
        number = self.config_entry.data.get(CONF_NUMBER, "")
        try:
            groups = await async_call_signal_api(self.hass, f"/v1/groups/{number}", entry=self.config_entry)
            return {
                group.get("id", ""): group.get("name", "Unnamed Group")
                for group in groups
            }
        except Exception:
            return {}

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            self.options.update({
                CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, 10),
                CONF_SELECTED_CONTACTS: user_input.get(CONF_SELECTED_CONTACTS, []),
                CONF_SELECTED_GROUPS: user_input.get(CONF_SELECTED_GROUPS, []),
                CONF_ENABLE_CONVERSATION: user_input.get(CONF_ENABLE_CONVERSATION, False),
            })

            if self.options.get(CONF_ENABLE_CONVERSATION):
                return await self.async_step_conversation()

            return self.async_create_entry(
                title="",
                data=self.options,
            )

        # Fetch contacts and groups.
        contacts = await self._get_contacts()
        groups = await self._get_groups()

        description_msg = "Polling interval used when WebSocket is unavailable and REST fallback is active."

        options_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(CONF_SCAN_INTERVAL, 10),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
                vol.Optional(
                    CONF_SELECTED_CONTACTS,
                    default=self.config_entry.options.get(CONF_SELECTED_CONTACTS, []),
                ): cv.multi_select(contacts),
                vol.Optional(
                    CONF_SELECTED_GROUPS,
                    default=self.config_entry.options.get(CONF_SELECTED_GROUPS, []),
                ): cv.multi_select(groups),
                vol.Optional(
                    CONF_ENABLE_CONVERSATION,
                    default=self.config_entry.options.get(CONF_ENABLE_CONVERSATION, False),
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            description_placeholders={"msg": description_msg},
        )

    async def async_step_conversation(self, user_input: dict[str, Any] | None = None):
        """Step to authorize specific contacts/groups for Assist."""
        if user_input is not None:
            self.options.update(user_input)
            return self.async_create_entry(title="", data=self.options)

        # Reuse the helpers to fetch options for the authorization list
        contacts = await self._get_contacts()
        groups = await self._get_groups()

        return self.async_show_form(
            step_id="conversation",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CONV_VOICE_MESSAGES,
                        default=self.config_entry.options.get(CONF_CONV_VOICE_MESSAGES, False),
                    ): bool,
                    vol.Optional(
                        CONF_CONV_CONTACTS,
                        default=self.config_entry.options.get(CONF_CONV_CONTACTS, []),
                    ): cv.multi_select(contacts),
                    vol.Optional(
                        CONF_CONV_GROUPS,
                        default=self.config_entry.options.get(CONF_CONV_GROUPS, []),
                    ): cv.multi_select(groups),
                }
            ),
        )
