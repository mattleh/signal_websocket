import logging
from typing import Any

from homeassistant.components.notify import (
    ATTR_TARGET,
    NotifyEntity,
    NotifyEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import async_call_signal_api, async_process_attachments

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Signal notify platform."""
    number = config_entry.data.get("number", "")
    async_add_entities([SignalNotifyEntity(config_entry, number)])


class SignalNotifyEntity(NotifyEntity):
    """Signal notification entity."""

    _attr_has_entity_name = True
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, config_entry: ConfigEntry, number: str) -> None:
        """Initialize the entity."""
        self._config_entry = config_entry
        self._number = number
        self._attr_name = f"Notify {number}"
        self._attr_unique_id = f"signal_notify_{config_entry.entry_id}_{number}"

    async def async_send_message(
        self,
        message: str,
        title: str | None = None,
        data: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Send a Signal message using the notify service."""

        # Resolve targets: check kwargs (standard notify target) or data payload
        recipients = kwargs.get(ATTR_TARGET) or []
        if not recipients and data:
            recipients = data.get("recipients") or []

        def _sanitize_recipient(r: Any) -> str:
            val = str(r).strip()
            if val.isdigit() and not val.startswith("+"):
                return f"+{val}"
            return val

        recipients = [_sanitize_recipient(r) for r in (recipients if isinstance(recipients, list) else [recipients])]

        if not recipients:
            raise ServiceValidationError("No recipients provided for Signal notification")

        # Resolve entity IDs to numbers/ids if provided as targets
        resolved_recipients = []
        for target in recipients:
            if target.startswith("sensor."):
                if (state := self.hass.states.get(target)) is not None:
                    # Try to get 'number' (contacts) or 'id' (groups) from attributes
                    if value := (state.attributes.get("number") or state.attributes.get("id")):
                        resolved_recipients.append(str(value))
                        continue
            resolved_recipients.append(target)

        base_payload: dict[str, Any] = {
            "message": message,
            "number": self._number,
        }

        if data:
            # Map optional fields from API model provided in the request
            fields = [
                "edit_timestamp",
                "link_preview",
                "mentions",
                "notify_self",
                "quote_author",
                "quote_mentions",
                "quote_message",
                "quote_timestamp",
                "sticker",
                "text_mode",
                "view_once",
            ]
            for field in fields:
                if field in data:
                    base_payload[field] = data[field]

            # Process attachments using the shared helper
            base64_attachments = await async_process_attachments(self.hass, data)

            if base64_attachments:
                base_payload["base64_attachments"] = base64_attachments

        # Split recipients into phone numbers and others to avoid API mixing error
        phones = [r for r in resolved_recipients if r.startswith("+")]
        others = [r for r in resolved_recipients if not r.startswith("+")]

        for batch in [phones, others]:
            if not batch:
                continue
            payload = {**base_payload, "recipients": batch}
            try:
                await async_call_signal_api(self.hass, "/v2/send", entry=self._config_entry, method="post", payload=payload, timeout=30)
                _LOGGER.debug("Signal notification sent successfully from %s", self._number)
            except Exception as err:
                _LOGGER.error("Failed to send Signal notification: %s", err)