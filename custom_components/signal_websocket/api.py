"""API helper for Signal Messenger."""
import asyncio
import base64
import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from yarl import URL
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_HOST, CONF_PORT, CONF_NUMBER, MAX_ATTACHMENT_SIZE, CONF_RECEIVE_GROUPS

_LOGGER = logging.getLogger(__name__)

async def async_call_signal_api(
    hass: HomeAssistant,
    endpoint: str,
    *,
    entry: ConfigEntry | None = None,
    host: str | None = None,
    port: int | None = None,
    method: str = "get",
    payload: dict | None = None,
    timeout: int = 20,
) -> Any:
    """Shared API helper for Signal Messenger."""
    if entry:
        host = entry.data.get(CONF_HOST, host)
        port = entry.data.get(CONF_PORT, port)

    session = async_get_clientsession(hass)
    
    # We build the URL by explicitly providing the path and marking it as encoded.
    # This prevents double-encoding of % characters (common in group IDs) 
    # while ensuring '+' is correctly treated as '%2B' for the Signal API.
    url = URL.build(
        scheme="http",
        host=host,
        port=port,
        path="/" + endpoint.lstrip("/").replace("+", "%2B"),
        encoded=True,
    )

    try:
        kwargs = {"timeout": timeout}
        if payload:  # Only add JSON if payload is not empty
            kwargs["json"] = payload

        async with getattr(session, method)(url, **kwargs) as resp:
            if resp.status == 204:
                return None

            # Special case for raw bytes (attachments)
            if "attachments" in endpoint and method == "get":
                if resp.status == 200:
                    return await resp.read()
                raise HomeAssistantError(f"Failed to download attachment: {resp.status}")

            response_text = await resp.text()
            if resp.status not in (200, 201):
                _LOGGER.error("Signal API error on %s: %s", endpoint, response_text)
                raise HomeAssistantError(f"Signal API error: {response_text}")

            if "application/json" in resp.content_type:
                data = await resp.json()
                if isinstance(data, dict) and "error" in data:
                    _LOGGER.error("Signal API reported an error: %s", data["error"])
                    raise HomeAssistantError(f"Signal API reported an error: {data['error']}")
                return data

            return response_text
    except HomeAssistantError:
        raise
    except Exception as err:
        _LOGGER.error("Failed to connect to Signal API on %s: %s", endpoint, err)
        raise HomeAssistantError(f"Could not connect to Signal API: {err}")

class SignalMessageReceiver:
    """Manager for the incoming Signal message stream (WS or REST)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the receiver."""
        self.hass = hass
        self.entry = entry
        self.status = "initializing"
        self.last_message = "Waiting..."
        self.extra_attributes = {}
        self.ws_available = False
        self.formatted_number = None
        self.ws_url = None
        self.coordinator: DataUpdateCoordinator | None = None
        self._sensor_callback = None

    async def async_setup(self) -> None:
        """Determine connection type and initialize."""
        host = self.entry.data.get(CONF_HOST, "127.0.0.1")
        port = self.entry.data.get(CONF_PORT, 8080)
        number = self.entry.data.get(CONF_NUMBER, "")
        session = async_get_clientsession(self.hass)

        # Ensure number has the '+' prefix
        self.formatted_number = number
        if self.formatted_number.isdigit() and not self.formatted_number.startswith("+"):
            self.formatted_number = f"+{self.formatted_number}"

        # WebSocket path requires manual encoding of the '+' prefix
        safe_number = self.formatted_number.replace("+", "%2B")
        self.ws_url = f"ws://{host}:{port}/v1/receive/{safe_number}"
        
        try:
            async with session.ws_connect(self.ws_url, timeout=aiohttp.ClientTimeout(total=5)) as test_ws:
                await test_ws.close()
            self.ws_available = True
            _LOGGER.info("WebSocket connection available for %s", number)
        except Exception as e:
            _LOGGER.info("WebSocket not available for %s, falling back to REST: %s", number, e)

        if not self.ws_available:
            from .const import CONF_SCAN_INTERVAL
            scan_interval = self.entry.options.get(CONF_SCAN_INTERVAL, 10)
            self.coordinator = DataUpdateCoordinator(
                self.hass,
                _LOGGER,
                name=f"signal_poll_{number}",
                update_method=self._async_update_rest_data,
                update_interval=timedelta(seconds=scan_interval),
            )
            await self.coordinator.async_config_entry_first_refresh()

    async def _async_update_rest_data(self) -> Any:
        """Poll data via REST."""
        endpoint = f"/v1/receive/{self.formatted_number}?send_read_receipts=true"
        try:
            data = await async_call_signal_api(self.hass, endpoint, entry=self.entry, timeout=15)
            if data and isinstance(data, list) and len(data) > 0:
                for msg in data:
                    self.hass.bus.async_fire("signal_received", msg)
                # Update internal state with latest message
                self.update_from_data(data[-1])
                return data
            return None
        except Exception as e:
            _LOGGER.debug("Signal REST poll skip: %s", e)
            return None

    async def listen_ws(self) -> None:
        """Listen for messages via WebSocket."""
        session = async_get_clientsession(self.hass)
        reconnect_delay = 5

        while True:
            try:
                self.status = "connecting"
                if self._sensor_callback: self._sensor_callback()
                async with session.ws_connect(self.ws_url, heartbeat=30) as ws:
                    self.status = "connected"
                    if self._sensor_callback: self._sensor_callback()
                    reconnect_delay = 5
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = msg.json()
                            self.update_from_data(data)
                            self.hass.bus.async_fire("signal_received", data)
                            # Trigger manual read receipt for WebSocket messages
                            self.hass.async_create_task(self._async_send_read_receipt(data))
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                            break
            except Exception as e:
                self.status = f"error: {str(e)}"
                if self._sensor_callback: self._sensor_callback()
                _LOGGER.error("Signal WS Error: %s", e)
            
            reconnect_delay = min(reconnect_delay * 2, 60)
            await asyncio.sleep(reconnect_delay)

    async def _async_send_read_receipt(self, data: dict) -> None:
        """Send a read receipt for a received message."""
        envelope = data.get("envelope", {})
        data_message = envelope.get("dataMessage", {})

        # Only send receipts for actual data messages with content
        if not data_message or "message" not in data_message:
            return

        source = envelope.get("source")
        timestamp = envelope.get("timestamp")

        if not source or not timestamp:
            return

        payload = {
            "receipt_type": "read",
            "recipient": source,
            "timestamp": timestamp,
        }
        endpoint = f"/v1/receipts/{self.formatted_number}"
        try:
            await async_call_signal_api(self.hass, endpoint, entry=self.entry, method="post", payload=payload)
        except Exception as err:
            _LOGGER.debug("Failed to send automatic read receipt: %s", err)

    def update_from_data(self, data: dict) -> None:
        """Process a raw Signal message envelope into state."""
        envelope = data.get("envelope", {})
        data_message = envelope.get("dataMessage", {})

        if not data_message or "message" not in data_message:
            return

        group_id = data_message.get("groupInfo", {}).get("groupId")
        if group_id:
            receive_groups = self.entry.options.get(CONF_RECEIVE_GROUPS, [])
            if group_id not in receive_groups:
                _LOGGER.debug("Ignoring group message event: monitoring is not enabled for group %s", group_id)
                return

        self.last_message = data_message.get("message")
        self.extra_attributes = {
            "last_received": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": envelope.get("sourceName", envelope.get("source")),
            "source_number": envelope.get("source"),
            "full_envelope": envelope,
            "connection_status": self.status,
        }
        if self._sensor_callback:
            self._sensor_callback()

async def async_process_attachments(hass: HomeAssistant, data: dict[str, Any], raise_on_error: bool = False) -> list[str]:
    """Process urls and local files into base64 attachments."""
    base64_attachments = list(data.get("base64_attachments", []))

    # 1. Fetch from URLs
    if urls := data.get("urls"):
        session = async_get_clientsession(hass)
        verify_ssl = data.get("verify_ssl", True)
        headers = {"User-Agent": "HomeAssistant/SignalWebSocket"}
        for url in urls:
            if not str(url).startswith(("http://", "https://")):
                msg = f"Invalid URL for attachment: {url}. Must be a full absolute URL"
                if raise_on_error:
                    raise HomeAssistantError(msg)
                _LOGGER.warning(msg)
                continue
            try:
                async with session.get(url, ssl=verify_ssl, timeout=15, headers=headers) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        if len(content) <= MAX_ATTACHMENT_SIZE:
                            base64_attachments.append(base64.b64encode(content).decode("utf-8"))
                        else:
                            msg = f"Attachment from {url} exceeds 50MB limit"
                            if raise_on_error:
                                raise HomeAssistantError(msg)
                            _LOGGER.warning(msg)
                    else:
                        msg = f"Failed to fetch attachment from {url}: {resp.status}"
                        if raise_on_error:
                            raise HomeAssistantError(msg)
                        _LOGGER.warning(msg)
            except Exception as err:
                if isinstance(err, HomeAssistantError):
                    raise
                msg = f"Could not fetch attachment from {url}: {err}"
                if raise_on_error:
                    raise HomeAssistantError(msg)
                _LOGGER.warning(msg)

    # 2. Read local files
    if local_files := data.get("attachments"):
        def _read_files():
            results = []
            for filename in local_files:
                if not hass.config.is_allowed_path(filename):
                    msg = f"Path not allowed (check allowlist_external_dirs): {filename}"
                    if raise_on_error:
                        raise HomeAssistantError(msg)
                    _LOGGER.warning(msg)
                    continue
                try:
                    with open(filename, "rb") as f:
                        content = f.read()
                        if len(content) <= MAX_ATTACHMENT_SIZE:
                            results.append(base64.b64encode(content).decode("utf-8"))
                        else:
                            msg = f"Local file {filename} exceeds 50MB limit"
                            if raise_on_error:
                                raise HomeAssistantError(msg)
                            _LOGGER.warning(msg)
                except Exception as err:
                    if isinstance(err, HomeAssistantError):
                        raise
                    msg = f"Error reading local file {filename}: {err}"
                    if raise_on_error:
                        raise HomeAssistantError(msg)
                    _LOGGER.error(msg)
            return results
        
        local_results = await hass.async_add_executor_job(_read_files)
        base64_attachments.extend(local_results)

    return base64_attachments