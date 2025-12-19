import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import CONF_CONNECTION_TYPE, DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Signal sensor platform."""
    host = config_entry.data["host"]
    port = config_entry.data["port"]
    number = config_entry.data["number"]
    conn_type = config_entry.data.get(CONF_CONNECTION_TYPE, "websocket")
    
    session = async_get_clientsession(hass)

    if conn_type == "websocket":
        sensor = SignalWSSensor(number)
        async_add_entities([sensor])
        
        ws_url = f"ws://{host}:{port}/v1/receive/{number}"
        
        async def listen_ws():
            await asyncio.sleep(5)
            reconnect_delay = 5
            
            while True:
                try:
                    sensor.update_status("connecting") # New helper method
                    async with session.ws_connect(ws_url, heartbeat=30) as ws:
                        sensor.update_status("connected")
                        reconnect_delay = 5
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = msg.json()
                                sensor.update_from_data(data)
                                hass.bus.async_fire("signal_received", data)
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                except Exception as e:
                    sensor.update_status(f"error: {str(e)}")
                    _LOGGER.error("Signal WS Error: %s", e)
                
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)

        config_entry.async_on_unload(hass.loop.create_task(listen_ws()).cancel)

    else:
        # REST Mode Polling
        rest_url = f"http://{host}:{port}/v1/receive/{number}?send_read_receipts=true"
        
        # Get poll interval from options (default 10s)
        scan_interval = config_entry.options.get("scan_interval", 10)

        async def async_update_data():
            try:
                # Use the new rest_url with the receipt flag
                async with session.get(rest_url, timeout=15) as response:
                    if response.status != 200:
                        return None
                    
                    data = await response.json(content_type=None)
                    
                    if data and isinstance(data, list) and len(data) > 0:
                        _LOGGER.debug("Signal API Poll Result: %s messages", len(data))
                        for msg in data:
                            hass.bus.async_fire("signal_received", msg)
                        return data # Return the full list to the coordinator
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

        # Listener to update interval on-the-fly without restart
        async def update_listener(hass, entry):
            new_interval = entry.options.get("scan_interval", 10)
            coordinator.update_interval = timedelta(seconds=new_interval)
            _LOGGER.info("Signal poll interval updated to %s seconds", new_interval)

        config_entry.async_on_unload(config_entry.add_update_listener(update_listener))

        # Start the coordinator and add the sensor
        await coordinator.async_config_entry_first_refresh()
        async_add_entities([SignalRestSensor(coordinator, number)])

    return True

class SignalWSSensor(SensorEntity):
    """WebSocket based sensor for real-time push."""
    def __init__(self, number):
        self._attr_name = f"Signal {number}"
        self._attr_unique_id = f"signal_ws_{number}"
        self._attr_native_value = "Waiting..."
        self._attr_extra_state_attributes = {}

    def update_status(self, status):
        """Update the connection status in attributes."""
        self._attr_extra_state_attributes["connection_status"] = status
        self.async_write_ha_state()

    def update_from_data(self, data):
        """Update the sensor only if it's a real message."""
        envelope = data.get("envelope", {})
        data_message = envelope.get("dataMessage", {})
        
        # FILTER: Nur fortfahren, wenn eine 'dataMessage' existiert und Text enthält
        if not data_message or "message" not in data_message:
            _LOGGER.debug("Signal: Event ignoriert (kein Nachrichtentext)")
            return

        msg_text = data_message.get("message")
        
        # Falls die Nachricht leer ist (z.B. nur ein Anhang ohne Text), 
        # kannst du entscheiden, ob du sie trotzdem sehen willst.
        if msg_text:
            self._attr_native_value = msg_text
            self._attr_extra_state_attributes = {
                "last_received": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": envelope.get("sourceName", envelope.get("source")),
                "source_number": envelope.get("source"),
                "full_envelope": envelope,
                "connection_status": "connected"
            }
            # Nur jetzt wird der Zustand in Home Assistant wirklich aktualisiert
            self.async_write_ha_state()

class SignalRestSensor(CoordinatorEntity, SensorEntity):
    """REST based sensor with batch history and receipts."""
    def __init__(self, coordinator, number):
        super().__init__(coordinator)
        self._attr_name = f"Signal {number}"
        self._attr_unique_id = f"signal_rest_{number}"
        self._state = "Listening..."
        self._attributes = {
            "last_received": "Never",
            "recent_messages": []
        }

    @property
    def native_value(self):
        """Return the latest message as the sensor state."""
        if self.coordinator.data:
            messages = self.coordinator.data
            last_envelope = messages[-1].get("envelope", {})
            
            # Update the main state to the newest message text
            self._state = last_envelope.get("dataMessage", {}).get("message", "New Msg")
            
            # Store metadata and EVERY message text from the batch
            self._attributes["last_received"] = datetime.now().strftime("%H:%M:%S")
            self._attributes["source"] = last_envelope.get("sourceName", last_envelope.get("source"))
            self._attributes["batch_size"] = len(messages)
            
            # This captures every message in the poll
            self._attributes["recent_messages"] = [
                m.get("envelope", {}).get("dataMessage", {}).get("message", "") 
                for m in messages
            ]
            
        return self._state

    @property
    def extra_state_attributes(self):
        return self._attributes