import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError, HomeAssistantError
from .const import DOMAIN, CONF_NUMBER
from .api import async_call_signal_api, async_process_attachments, SignalMessageReceiver
from .conversation import SignalConversationManager
from .groups import async_handle_group_service
from .contacts import async_handle_contact_service

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "notify"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Signal WebSocket from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Initialize the centralized receiver
    receiver = SignalMessageReceiver(hass, entry)
    await receiver.async_setup()
    
    if receiver.ws_available:
        entry.async_create_background_task(hass, receiver.listen_ws(), "signal_ws_listener")
    
    # Initialize conversation manager
    conv_manager = SignalConversationManager(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = {"conv_manager": conv_manager, "receiver": receiver}

    # Register event listener for incoming messages
    entry.async_on_unload(
        hass.bus.async_listen("signal_received", conv_manager.async_handle_message)
    )

    async def async_handle_send_message(call: ServiceCall) -> None:
        """Handle the send_message service call."""
        sender = entry.data.get(CONF_NUMBER, "")

        def _sanitize_recipient(r: Any) -> str | None:
            if r is None:
                return None
            val = str(r).strip()
            if not val or val.lower() == "none":
                return None
            # If it's all digits and doesn't start with +, it's likely a phone number missing the prefix
            if val.isdigit() and not val.startswith("+"):
                return f"+{val}"
            return val

        # Collect recipients from various possible fields
        raw_recipients = call.data.get("recipients", [])
        recipients = [res for r in (raw_recipients if isinstance(raw_recipients, list) else [raw_recipients]) if (res := _sanitize_recipient(r))]

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
                        if sanitized := _sanitize_recipient(val):
                            recipients.append(sanitized)
        if not recipients:
            raise ServiceValidationError("No recipients provided for Signal message")

        base_payload = {
            "message": call.data.get("message", ""),
            "number": sender,
        }

        # Process attachments using the shared helper
        base64_attachments = await async_process_attachments(hass, call.data)

        if base64_attachments:
            base_payload["base64_attachments"] = base64_attachments

        # Add remaining optional API fields
        optional_fields = [
            "sticker", "text_mode", "view_once", "notify_self", "link_preview",
            "quote_author", "quote_message", "quote_timestamp", "edit_timestamp", "mentions"
        ]
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

    hass.services.async_register(DOMAIN, "send_message", async_handle_send_message)
    
    # Define wrapper handlers to ensure coroutines are properly awaited by Home Assistant
    async def handle_group_service(call: ServiceCall) -> None:
        await async_handle_group_service(hass, entry, call)

    async def handle_contact_service(call: ServiceCall) -> None:
        await async_handle_contact_service(hass, entry, call)

    # Group Management
    for service in ("create_group", "manage_group_membership", "update_group", "delete_group"):
        hass.services.async_register(DOMAIN, service, handle_group_service)
    
    # Contacts & Profile
    for service in ("sync_contacts", "update_contact", "remove_contact"):
        hass.services.async_register(DOMAIN, service, handle_contact_service)

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
