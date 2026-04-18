"""Conversation handling for Signal Messenger."""
import logging
from homeassistant.components import conversation
from homeassistant.core import HomeAssistant, Event
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .assist import async_transcribe
from .api import async_call_signal_api
from .const import CONF_ENABLE_CONVERSATION, CONF_CONV_CONTACTS, CONF_CONV_GROUPS, CONF_NUMBER, CONF_CONV_VOICE_MESSAGES

_LOGGER = logging.getLogger(__name__)

class SignalConversationManager:
    """Manages conversations between Signal and Home Assistant Assist."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.entry = entry
        self._conversation_ids: dict[str, str] = {}

    async def async_handle_message(self, event: Event) -> None:
        """Handle incoming Signal messages and forward to Assist if enabled."""
        if not self.entry.options.get(CONF_ENABLE_CONVERSATION):
            return

        data = event.data
        envelope = data.get("envelope", {})
        data_message = envelope.get("dataMessage", {})
        
        message_text = data_message.get("message")
        source = envelope.get("source")

        if not source:
            return

        # Handle Voice Messages if no text is present
        if not message_text and self.entry.options.get(CONF_CONV_VOICE_MESSAGES):
            attachments = data_message.get("attachments", [])
            for attachment in attachments:
                filename = attachment.get("filename", "")
                attachment_id = attachment.get("id", filename)
                if (
                    attachment.get("contentType") == "audio/aac"
                    and filename.startswith("signal")
                    and filename.endswith("m4a")
                ):
                    _LOGGER.debug("Audio message detected, attempting transcription: %s (ID: %s)", filename, attachment_id)
                    audio_content = await self._async_download_attachment(attachment_id)
                    if audio_content:
                        message_text = await async_transcribe(self.hass, audio_content)
                        if message_text and message_text.strip():
                            _LOGGER.debug("Transcribed voice message: %s", message_text)
                            break

        if not message_text or not message_text.strip():
            return

        message_text = message_text.strip()

        # Restriction: Only authorized contacts or groups
        conv_contacts = self.entry.options.get(CONF_CONV_CONTACTS, [])
        conv_groups = self.entry.options.get(CONF_CONV_GROUPS, [])
        
        group_id = data_message.get("groupInfo", {}).get("groupId")
        
        # Decide target and authorization based on whether it's a group or direct message
        if group_id:
            if group_id not in conv_groups:
                _LOGGER.debug("Ignoring group message: group %s not authorized for Assist", group_id)
                return
            target = group_id
        else:
            if source not in conv_contacts:
                _LOGGER.debug("Ignoring message from %s: not authorized for Assist", source)
                return
            target = source

        _LOGGER.debug("Forwarding Signal message from %s to Assist", target)

        # Use the source or group_id as the key for conversation context
        previous_id = self._conversation_ids.get(target)

        # Get agent and language from options
        agent_id = self.entry.options.get("conv_agent_id")
        if agent_id == "default":
            agent_id = None
        language = self.entry.options.get("conv_language", self.hass.config.language)

        try:
            result = await conversation.async_converse(
                self.hass,
                text=message_text,
                conversation_id=previous_id,
                context=event.context,
                agent_id=agent_id,
                language=language,
            )
            
            # Store the ID for continuation
            self._conversation_ids[target] = result.conversation_id
            
            # Send response back via Signal
            response_dict = result.response.as_dict()
            reply_text = response_dict.get("speech", {}).get("plain", {}).get("speech")
            
            if reply_text:
                await self._async_send_reply(target, reply_text)
                
        except Exception as err:
            _LOGGER.error("Error in Signal Assist bridge: %s", err)

    async def _async_download_attachment(self, attachment_id: str) -> bytes | None:
        """Download an attachment from the Signal API."""
        try:
            endpoint = f"/v1/attachments/{attachment_id}"
            return await async_call_signal_api(self.hass, endpoint, entry=self.entry, method="get", timeout=30)
        except Exception as err:
            _LOGGER.error("Error downloading Signal attachment: %s", err)
        return None

    async def _async_send_reply(self, recipient: str, message: str) -> None:
        """Helper to send a reply back to Signal."""
        sender = self.entry.data.get(CONF_NUMBER)
        
        # Ensure recipient has the '+' if it's a phone number
        target = str(recipient).strip()
        if target.isdigit() and not target.startswith("+"):
            target = f"+{target}"
            
        payload = {"message": message, "number": sender, "recipients": [target]}

        await async_call_signal_api(self.hass, "/v2/send", entry=self.entry, method="post", payload=payload)