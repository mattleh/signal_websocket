import logging

from homeassistant.components.sensor import SensorEntity

from .const import DOMAIN
from .contacts import async_setup_entry as async_setup_contacts
from .groups import async_setup_entry as async_setup_groups

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Signal sensor platform."""
    number = config_entry.data.get("number", "")
    receiver = hass.data[DOMAIN][config_entry.entry_id]["receiver"]

    async_add_entities([SignalMessageSensor(config_entry.entry_id, number, receiver)])

    await async_setup_contacts(hass, config_entry, async_add_entities)
    await async_setup_groups(hass, config_entry, async_add_entities)


class SignalMessageSensor(SensorEntity):
    """Unified Signal Message sensor."""

    def __init__(self, entry_id, number, receiver):
        """Initialize the sensor."""
        self.coordinator = receiver.coordinator
        self.receiver = receiver
        self._attr_name = f"Signal {number}"
        self._attr_unique_id = f"signal_msg_{entry_id}_{number}"

    async def async_added_to_hass(self) -> None:
        """Handle being added to Home Assistant."""
        await super().async_added_to_hass()

        if self.coordinator:
            # REST Mode: Listen to coordinator updates
            self.async_on_remove(
                self.coordinator.async_add_listener(self.async_write_ha_state)
            )
        else:
            # WebSocket Mode: Register callback in receiver
            self.receiver._sensor_callback = self.async_write_ha_state

    async def async_will_remove_from_hass(self) -> None:
        """Handle being removed from Home Assistant."""
        if not self.coordinator:
            self.receiver._sensor_callback = None
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self.coordinator:
            return self.coordinator.last_update_success
        # In WebSocket mode, check the receiver status
        return self.receiver.status == "connected"

    @property
    def native_value(self):
        """Return last message text."""
        return self.receiver.last_message

    @property
    def extra_state_attributes(self):
        """Return attributes from receiver."""
        attrs = self.receiver.extra_attributes.copy()
        attrs["connection_status"] = self.receiver.status
        return attrs
