import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .api import async_call_signal_api
from .contacts import async_setup_entry as async_setup_contacts
from .groups import async_setup_entry as async_setup_groups

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Signal sensor platform."""
    host = config_entry.data.get("host", "127.0.0.1")
    port = config_entry.data.get("port", 8080)
    number = config_entry.data.get("number", "")

    session = async_get_clientsession(hass)
    scan_interval = config_entry.options.get("scan_interval", 10)

    # Try WebSocket first.
    ws_url = f"ws://{host}:{port}/v1/receive/{number}"
    ws_available = False
    try:
        # Perform a quick test connect with a short timeout.
        async with session.ws_connect(
            ws_url, timeout=aiohttp.ClientTimeout(total=5)
        ) as test_ws:
            await test_ws.close()
        ws_available = True
        _LOGGER.info("WebSocket connection available, using real-time mode")
    except Exception as e:
        _LOGGER.info("WebSocket not available, falling back to REST polling: %s", e)

    if ws_available:
        sensor = SignalWSSensor(config_entry.entry_id, number)
        async_add_entities([sensor])

        async def listen_ws():
            await asyncio.sleep(5)
            reconnect_delay = 5

            while True:
                try:
                    sensor.update_status("connecting")
                    async with session.ws_connect(ws_url, heartbeat=30) as ws:
                        sensor.update_status("connected")
                        reconnect_delay = 5
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = msg.json()
                                sensor.update_from_data(data)
                                hass.bus.async_fire("signal_received", data)
                            elif msg.type in (
                                aiohttp.WSMsgType.CLOSE,
                                aiohttp.WSMsgType.ERROR,
                            ):
                                break
                except Exception as e:
                    sensor.update_status(f"error: {str(e)}")
                    _LOGGER.error("Signal WS Error: %s", e)
                reconnect_delay = min(reconnect_delay * 2, 60)
            
                await asyncio.sleep(reconnect_delay)

        config_entry.async_create_background_task(hass, listen_ws(), "signal_ws_listener")
    else:
        # Use REST mode for polling.
        rest_url = f"http://{host}:{port}/v1/receive/{number}?send_read_receipts=true"

        async def async_update_data():
            try:
                endpoint = f"/v1/receive/{number}?send_read_receipts=true"
                data = await async_call_signal_api(hass, endpoint, entry=config_entry, timeout=15)
                if data and isinstance(data, list) and len(data) > 0:
                    for msg in data:
                        hass.bus.async_fire("signal_received", msg)
                    return data
                return None
            except Exception as e:
                _LOGGER.debug("Signal poll skip (likely empty or timeout): %s", e)
                return None

        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"signal_poll_{number}",
            update_method=async_update_data,
            update_interval=timedelta(seconds=scan_interval),
        )

        # Start the coordinator and add the sensor.
        await coordinator.async_config_entry_first_refresh()
        async_add_entities(
            [SignalRestSensor(config_entry.entry_id, coordinator, number)]
        )

    await async_setup_contacts(hass, config_entry, async_add_entities)
    await async_setup_groups(hass, config_entry, async_add_entities)


class SignalWSSensor(SensorEntity):
    """WebSocket based sensor for real-time push."""

    def __init__(self, entry_id, number):
        self._attr_name = f"Signal {number}"
        self._attr_unique_id = f"signal_ws_{entry_id}_{number}"
        self._attr_native_value = "Waiting..."
        self._attr_extra_state_attributes = {}

    def update_status(self, status):
        """Update the connection status in attributes."""
        if not self.hass:
            return
        self._attr_extra_state_attributes["connection_status"] = status
        self.async_write_ha_state()

    def update_from_data(self, data):
        """Update the sensor only if it's a real message."""
        envelope = data.get("envelope", {})
        data_message = envelope.get("dataMessage", {})

        # Filter: Only proceed if a dataMessage exists and contains text.
        if not data_message or "message" not in data_message:
            _LOGGER.debug("Signal: Event ignored (no message text)")
            return

        msg_text = data_message.get("message")

        # If the message is empty (for example, attachment-only), keep the event
        # but do not update the sensor text.
        if msg_text:
            if not self.hass:
                return
            self._attr_native_value = msg_text
            self._attr_extra_state_attributes = {
                "last_received": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": envelope.get("sourceName", envelope.get("source")),
                "source_number": envelope.get("source"),
                "full_envelope": envelope,
                "connection_status": "connected",
            }
            self.async_write_ha_state()


class SignalRestSensor(CoordinatorEntity, SensorEntity):
    """REST based sensor."""

    def __init__(self, entry_id, coordinator, number):
        super().__init__(coordinator)
        self._attr_name = f"Signal {number}"
        self._attr_unique_id = f"signal_rest_{entry_id}_{number}"
        self._attr_native_value = "Listening..."
        self._attr_extra_state_attributes = {"last_received": "Never"}

    @property
    def native_value(self):
        """Return the latest message as the sensor state."""
        if self.coordinator.data:
            messages = self.coordinator.data
            if messages:
                last_envelope = messages[-1].get("envelope", {})
                self._attr_native_value = last_envelope.get("dataMessage", {}).get(
                    "message", "New Msg"
                )
                self._attr_extra_state_attributes["last_received"] = (
                    datetime.now().strftime("%H:%M:%S")
                )
                self._attr_extra_state_attributes["source"] = last_envelope.get(
                    "sourceName", last_envelope.get("source")
                )

        return self._attr_native_value

    @property
    def extra_state_attributes(self):
        return self._attr_extra_state_attributes
