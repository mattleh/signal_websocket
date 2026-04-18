import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import DOMAIN, CONF_HOST, CONF_PORT, CONF_NUMBER
from .api import async_call_signal_api
from .conversation import SignalConversationManager
from .groups import async_handle_group_service
from .contacts import async_handle_contact_service

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "notify"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Signal WebSocket from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Initialize conversation manager
    conv_manager = SignalConversationManager(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = {"conv_manager": conv_manager}

    # Register event listener for incoming messages
    entry.async_on_unload(
        hass.bus.async_listen("signal_received", conv_manager.async_handle_message)
    )

    async def async_handle_send_message(call: ServiceCall) -> None:
        """Handle the send_message service call."""
        sender = entry.data.get(CONF_NUMBER, "")

        def _sanitize_recipient(r: Any) -> str:
            val = str(r).strip()
            # If it's all digits and doesn't start with +, it's likely a phone number missing the prefix
            if val.isdigit() and not val.startswith("+"):
                return f"+{val}"
            return val

        # Collect recipients from various possible fields
        raw_recipients = call.data.get("recipients", [])
        recipients = [_sanitize_recipient(r) for r in (raw_recipients if isinstance(raw_recipients, list) else [raw_recipients])]

        if group_id := call.data.get("group_id"):
            recipients.append(_sanitize_recipient(group_id))
            
        # Resolve entity IDs if provided
        for entity_field in ["contact_entity_id", "group_entity_id"]:
            ent_ids = call.data.get(entity_field, [])
            if isinstance(ent_ids, str):
                ent_ids = [ent_ids]
                
            for ent_id in ent_ids:
                if (state := hass.states.get(ent_id)) is not None:
                    if val := (state.attributes.get("number") or state.attributes.get("id")):
                        recipients.append(_sanitize_recipient(val))
        if not recipients:
            raise ServiceValidationError("No recipients provided for Signal message")

        base_payload = {
            "message": call.data.get("message", ""),
            "number": sender,
        }

        # Add optional API fields
        optional_fields = ["base64_attachments", "sticker", "text_mode", "view_once", "notify_self"]
        for field in optional_fields:
            if field in call.data:
                base_payload[field] = call.data[field]

        # Separate phone numbers and other IDs (groups/usernames) to prevent API error
        phones = [r for r in recipients if r.startswith("+")]
        others = [r for r in recipients if not r.startswith("+")]

        for batch in [phones, others]:
            if batch:
                payload = {**base_payload, "recipients": batch}
                await async_call_signal_api(hass, "/v2/send", entry=entry, method="post", payload=payload)

    async def async_handle_remote_delete(call: ServiceCall) -> None:
        """Handle remote delete service."""
        payload = {
            "recipient": str(call.data.get("recipient", "")),
            "target_timestamp": call.data["target_timestamp"]
        }
        endpoint = f"/v1/remote-delete/{entry.data[CONF_NUMBER]}"
        await async_call_signal_api(hass, endpoint, entry=entry, method="delete", payload=payload)

    async def async_handle_typing_indicator(call: ServiceCall) -> None:
        """Handle typing indicator service."""
        sender = entry.data.get(CONF_NUMBER, "")
        method = "put" if call.data["action"] == "start" else "delete"
        payload = {"recipient": call.data["recipient"]}
        await async_call_signal_api(hass, f"/v1/typing-indicator/{sender}", entry=entry, method=method, payload=payload)

    async def async_handle_registration_service(call: ServiceCall) -> None:
        """Handle number registration and verification."""
        number = call.data["number"]
        if call.service == "register_number":
            endpoint = f"/v1/register/{number}"
            payload = {k: v for k, v in call.data.items() if k != "number"}
            await async_call_signal_api(hass, endpoint, entry=entry, method="post", payload=payload)
        else:
            token = call.data["token"]
            endpoint = f"/v1/register/{number}/verify/{token}"
            payload = {"pin": call.data.get("pin")}
            await async_call_signal_api(hass, endpoint, entry=entry, method="post", payload=payload)

    hass.services.async_register(DOMAIN, "send_message", async_handle_send_message)
    hass.services.async_register(DOMAIN, "remote_delete", async_handle_remote_delete)
    hass.services.async_register(DOMAIN, "set_typing_indicator", async_handle_typing_indicator)
    
    # Group Management
    for service in ("create_group", "add_group_members", "remove_group_members", "update_group", "delete_group"):
        hass.services.async_register(DOMAIN, service, lambda call: async_handle_group_service(hass, entry, call))
    
    # Contacts & Profile
    for service in ("sync_contacts", "update_contact", "remove_contact", "update_profile"):
        hass.services.async_register(DOMAIN, service, lambda call: async_handle_contact_service(hass, entry, call))

    # Registration
    hass.services.async_register(DOMAIN, "register_number", async_handle_registration_service)
    hass.services.async_register(DOMAIN, "verify_number", async_handle_registration_service)

    # Register update listener to handle options changes
    entry.async_on_unload(entry.add_update_listener(update_listener))

    # Forward the setup to the sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if entry.entry_id in hass.data[DOMAIN]:
            hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entry from an older version to the current version."""
    _LOGGER.debug(
        "Migrating config entry from version %s", config_entry.version
    )

    # Handle migration from VERSION 1 to VERSION 2.
    if config_entry.version < 2:
        _LOGGER.info("Migrating config entry to version 2")
        return True

    return True
