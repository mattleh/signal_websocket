import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .api import async_call_signal_api
from .const import CONF_SELECTED_CONTACTS, CONF_NUMBER, CONF_HOST, CONF_PORT

_LOGGER = logging.getLogger(__name__)



async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Signal contacts sensor."""
    number = config_entry.data.get("number", "")

    async def async_update_data():
        try:
            return await async_call_signal_api(hass, f"/v1/contacts/{number}", entry=config_entry, timeout=15)
        except Exception as e:
            _LOGGER.debug("Contacts poll failed: %s", e)
            return None

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"signal_contacts_{number}",
        update_method=async_update_data,
        update_interval=timedelta(hours=1),
    )

    await coordinator.async_config_entry_first_refresh()

    # Prune orphaned entities from the registry that are no longer selected
    selected_contacts = config_entry.options.get(CONF_SELECTED_CONTACTS, [])
    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, config_entry.entry_id)
    for entry in entries:
        # Match individual contact sensors: signal_contact_{entry_id}_{number}
        # We exclude the summary sensor which starts with 'signal_contacts_'
        if entry.unique_id.startswith("signal_contact_") and not entry.unique_id.startswith("signal_contacts_"):
            # Extract number from unique_id: f"signal_contact_{entry_id}_{number}"
            parts = entry.unique_id.split("_")
            if len(parts) >= 4:
                num = parts[-1]
                if num not in selected_contacts:
                    ent_reg.async_remove(entry.entity_id)

    contacts = []
    if selected_contacts:
        all_contacts = coordinator.data or []
        contacts = [c for c in all_contacts if c.get("number") in selected_contacts]
    seen_numbers = {c["number"] for c in contacts if c.get("number")}

    entities = [SignalContactsSummarySensor(config_entry.entry_id, coordinator, number)]
    entities.extend(
        SignalContactSensor(config_entry.entry_id, coordinator, number, contact)
        for contact in contacts
        if contact.get("number")
    )

    async_add_entities(entities)

    def _async_add_new_contacts():
        selected_contacts = config_entry.options.get(CONF_SELECTED_CONTACTS, [])
        if not selected_contacts:
            return
        new_contacts = coordinator.data or []
        new_contacts = [
            c for c in new_contacts if c.get("number") in selected_contacts
        ]
        new_numbers = {
            c["number"] for c in new_contacts if c.get("number")
        } - seen_numbers
        if not new_numbers:
            return
        new_entities = [
            SignalContactSensor(config_entry.entry_id, coordinator, number, contact)
            for contact in new_contacts
            if contact.get("number") in new_numbers
        ]
        seen_numbers.update(new_numbers)
        async_add_entities(new_entities)

    config_entry.async_on_unload(coordinator.async_add_listener(_async_add_new_contacts))


async def async_handle_contact_service(hass: HomeAssistant, entry: ConfigEntry, call: ServiceCall) -> None:
    """Handle Signal contact and profile services."""
    sender = entry.data.get(CONF_NUMBER, "")
    method = "post"
    endpoint = f"/v1/contacts/{sender}"
    payload = {}

    if call.service == "sync_contacts":
        endpoint += "/sync"
    elif call.service == "update_contact":
        method = "put"
        payload = {"recipient": call.data["contact_number"], "name": call.data.get("name")}
    elif call.service == "remove_contact":
        method = "delete"
        payload = {"recipient": call.data["contact_number"]}
    elif call.service == "update_profile":
        method = "put"
        endpoint = f"/v1/profiles/{sender}"
        payload = {k: v for k, v in call.data.items()}

    await async_call_signal_api(hass, endpoint, entry=entry, method=method, payload=payload)


class SignalContactsSummarySensor(CoordinatorEntity, SensorEntity):
    """Summary sensor for Signal contacts."""

    def __init__(self, entry_id, coordinator, number):
        super().__init__(coordinator)
        self._attr_name = f"Signal Contacts {number}"
        self._attr_unique_id = f"signal_contacts_{entry_id}_{number}"
        self._attr_native_value = "Loading..."
        self._previous_contacts = []

    def _normalize_contact(self, contact):
        return {
            "number": contact.get("number"),
            "name": contact.get("name", "Unknown"),
            "username": contact.get("username"),
        }

    def _diff_contacts(self, old_contacts, new_contacts):
        old_by_number = {c["number"]: c for c in old_contacts if c.get("number")}
        new_by_number = {c["number"]: c for c in new_contacts if c.get("number")}

        added = [
            self._normalize_contact(new_by_number[num])
            for num in new_by_number
            if num not in old_by_number
        ]
        removed = [
            self._normalize_contact(old_by_number[num])
            for num in old_by_number
            if num not in new_by_number
        ]
        updated = []

        for num in new_by_number:
            if num in old_by_number:
                old = old_by_number[num]
                new = new_by_number[num]
                if old.get("name") != new.get("name") or old.get("username") != new.get(
                    "username"
                ):
                    updated.append(
                        {
                            "old": self._normalize_contact(old),
                            "new": self._normalize_contact(new),
                        }
                    )

        return {
            "added_contacts": added,
            "removed_contacts": removed,
            "updated_contacts": updated,
            "changed_contacts": added + removed + [u["new"] for u in updated],
        }

    @property
    def native_value(self):
        """Return the number of contacts."""
        if self.coordinator.data:
            contacts = self.coordinator.data
            sorted_contacts = sorted(
                contacts,
                key=lambda c: (c.get("name") or "", c.get("number") or ""),
            )
            self._attr_native_value = len(sorted_contacts)
            changes = self._diff_contacts(self._previous_contacts, sorted_contacts)
            self._previous_contacts = sorted_contacts
            self._attr_extra_state_attributes = {
                "contacts": [self._normalize_contact(c) for c in sorted_contacts],
                "contact_numbers": [c["number"] for c in sorted_contacts],
                **changes,
            }
            return self._attr_native_value

        self._attr_extra_state_attributes = {}
        return "No data"

    @property
    def extra_state_attributes(self):
        return getattr(self, "_attr_extra_state_attributes", {})


class SignalContactSensor(CoordinatorEntity, SensorEntity):
    """Individual sensor for a Signal contact."""

    def __init__(self, entry_id, coordinator, number, contact):
        super().__init__(coordinator)
        self._owner_number = number
        self._contact = contact
        self._attr_name = (
            f"Signal Contact {contact.get('name') or contact.get('number')}"
        )
        self._attr_unique_id = f"signal_contact_{entry_id}_{contact.get('number')}"
        self._attr_native_value = contact.get("name") or contact.get("number")

    @property
    def available(self):
        return bool(self.coordinator.data)

    @property
    def native_value(self):
        contact = next(
            (
                c
                for c in (self.coordinator.data or [])
                if c.get("number") == self._contact.get("number")
            ),
            self._contact,
        )
        self._attr_native_value = contact.get("name") or contact.get("number")
        return self._attr_native_value

    @property
    def extra_state_attributes(self):
        contact = next(
            (
                c
                for c in (self.coordinator.data or [])
                if c.get("number") == self._contact.get("number")
            ),
            self._contact,
        )
        return {
            "number": contact.get("number"),
            "name": contact.get("name", "Unknown"),
            "username": contact.get("username"),
            "owner_number": self._owner_number,
        }
