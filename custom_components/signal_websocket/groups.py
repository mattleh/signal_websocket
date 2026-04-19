import logging
import urllib.parse
from datetime import timedelta
from typing import Any
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .api import async_call_signal_api
from .const import (
    CONF_SELECTED_GROUPS,
    CONF_NUMBER,
    CONF_HOST,
    CONF_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Signal groups sensor."""
    number = config_entry.data.get("number", "")

    async def async_update_data():
        try:
            return await async_call_signal_api(hass, f"/v1/groups/{number}", entry=config_entry, timeout=15)
        except Exception as e:
            _LOGGER.debug("Groups poll failed: %s", e)
            return None

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"signal_groups_{number}",
        update_method=async_update_data,
        update_interval=timedelta(minutes=30),
    )

    await coordinator.async_config_entry_first_refresh()

    # Store coordinator to allow manual refresh from services
    hass.data[DOMAIN][config_entry.entry_id]["group_coordinator"] = coordinator

    # Prune orphaned entities from the registry that are no longer selected
    selected_groups = config_entry.options.get(CONF_SELECTED_GROUPS, [])
    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, config_entry.entry_id)
    for entry in entries:
        # Match individual group sensors: signal_group_{entry_id}_{id}
        # We exclude the summary sensor which starts with 'signal_groups_'
        if entry.unique_id.startswith("signal_group_") and not entry.unique_id.startswith("signal_groups_"):
            # Extract group ID from unique_id: f"signal_group_{entry_id}_{id}"
            parts = entry.unique_id.split("_")
            if len(parts) >= 4:
                group_id = parts[-1]
                if group_id not in selected_groups:
                    ent_reg.async_remove(entry.entity_id)

    groups = []
    if selected_groups:
        all_groups = coordinator.data or []
        groups = [g for g in all_groups if g.get("id") in selected_groups]
    seen_ids = {g["id"] for g in groups if g.get("id")}

    entities = [SignalGroupsSummarySensor(config_entry.entry_id, coordinator, number)]
    entities.extend(
        SignalGroupSensor(config_entry.entry_id, coordinator, number, group)
        for group in groups
        if group.get("id")
    )

    async_add_entities(entities)

    def _async_add_new_groups():
        selected_groups = config_entry.options.get(CONF_SELECTED_GROUPS, [])
        if not selected_groups:
            return
        new_groups = coordinator.data or []
        new_groups = [g for g in new_groups if g.get("id") in selected_groups]
        new_ids = {g["id"] for g in new_groups if g.get("id")} - seen_ids
        if not new_ids:
            return
        new_entities = [
            SignalGroupSensor(config_entry.entry_id, coordinator, number, group)
            for group in new_groups
            if group.get("id") in new_ids
        ]
        seen_ids.update(new_ids)
        async_add_entities(new_entities)

    config_entry.async_on_unload(coordinator.async_add_listener(_async_add_new_groups))


async def async_handle_group_service(hass: HomeAssistant, entry: ConfigEntry, call: ServiceCall) -> None:
    """Handle Signal group management services."""
    def _resolve_id(val: Any) -> str | None:
        """Resolve entity ID to actual number/id if needed."""
        if val is None:
            return None
        # If the UI/Script passes a list, take the first element
        if isinstance(val, list):
            if not val:
                return None
            val = val[0]
            
        val_str = str(val).strip()
        if not val_str or val_str.lower() == "none":
            return None

        if val_str.startswith("sensor."):
            if (state := hass.states.get(val_str)) is not None:
                val_str = str(state.attributes.get("id") or state.attributes.get("number") or val_str)
        
        return val_str

    sender = entry.data.get(CONF_NUMBER, "")
    group_id = _resolve_id(call.data.get("group_id"))
    endpoint = f"/v1/groups/{sender}"
    payload = {}

    # Determine HTTP method and specific endpoint based on the HA service call
    if call.service == "create_group":
        method = "post"
    elif call.service == "manage_group_membership":
        if not group_id:
            raise ServiceValidationError("Group ID is required for managing membership")
        operation = call.data.get("operation", "add")
        role = call.data.get("role", "member")
        sub_resource = "admins" if role == "admin" else "members"
        method = "delete" if operation == "remove" else "post"
        endpoint += f"/{urllib.parse.quote(group_id, safe='')}/{sub_resource}"
    elif call.service == "update_group":
        if not group_id:
            raise ServiceValidationError("Group ID is required for updates")
        method = "put"
        endpoint += f"/{urllib.parse.quote(group_id, safe='')}"
    elif call.service == "delete_group":
        if not group_id:
            raise ServiceValidationError("Group ID is required for deletion")
        method = "delete"
        endpoint += f"/{urllib.parse.quote(group_id, safe='')}"
    else:
        raise ServiceValidationError(f"Unknown group service: {call.service}")

    # Prepare strictly filtered payload based on service
    if "members" in call.data:
        raw_members = call.data["members"]
        if not isinstance(raw_members, list):
            raw_members = [raw_members]
        # Resolve any entity IDs provided in the members list
        payload["members"] = [_resolve_id(m) for m in raw_members]

    # Add metadata fields only for create or update operations
    if call.service in ("create_group", "update_group"):
        for field in ("name", "description", "expiration_time", "group_link"):
            if field in call.data:
                payload[field] = call.data[field]

    # Construct nested permissions object
    permissions = {}
    for field in ("add_members", "edit_group", "send_messages"):
        if field in call.data:
            permissions[field] = call.data[field]
    
    if permissions:
        payload["permissions"] = permissions

    await async_call_signal_api(hass, endpoint, entry=entry, method=method, payload=payload)

    # Handle post-deletion cleanup
    if call.service == "delete_group" and group_id:
        options = dict(entry.options)
        selected_groups = list(options.get(CONF_SELECTED_GROUPS, []))

        if group_id in selected_groups:
            selected_groups.remove(group_id)
            hass.config_entries.async_update_entry(
                entry, options={**options, CONF_SELECTED_GROUPS: selected_groups}
            )
        elif (data := hass.data.get(DOMAIN, {}).get(entry.entry_id)) and (coord := data.get("group_coordinator")):
            await coord.async_refresh()


class SignalGroupsSummarySensor(CoordinatorEntity, SensorEntity):
    """Summary sensor for Signal groups."""

    def __init__(self, entry_id, coordinator, number):
        super().__init__(coordinator)
        self._attr_name = f"Signal Groups {number}"
        self._attr_unique_id = f"signal_groups_{entry_id}_{number}"
        self._attr_native_value = "Loading..."
        self._previous_groups = []

    def _normalize_group(self, group):
        return {
            "id": group.get("id"),
            "name": group.get("name", "Unnamed"),
            "description": group.get("description"),
            "member_count": len(group.get("members", [])),
            "members": group.get("members", []),
        }

    def _diff_groups(self, old_groups, new_groups):
        old_by_id = {g["id"]: g for g in old_groups if g.get("id")}
        new_by_id = {g["id"]: g for g in new_groups if g.get("id")}

        added = [
            self._normalize_group(new_by_id[g_id])
            for g_id in new_by_id
            if g_id not in old_by_id
        ]
        removed = [
            self._normalize_group(old_by_id[g_id])
            for g_id in old_by_id
            if g_id not in new_by_id
        ]
        updated = []

        for g_id in new_by_id:
            if g_id in old_by_id:
                old = old_by_id[g_id]
                new = new_by_id[g_id]
                if (
                    old.get("name") != new.get("name")
                    or old.get("description") != new.get("description")
                    or old.get("members") != new.get("members")
                ):
                    updated.append(
                        {
                            "old": self._normalize_group(old),
                            "new": self._normalize_group(new),
                        }
                    )

        return {
            "added_groups": added,
            "removed_groups": removed,
            "updated_groups": updated,
            "changed_groups": added + removed + [u["new"] for u in updated],
        }

    @property
    def native_value(self):
        """Return the number of groups."""
        if self.coordinator.data:
            groups = self.coordinator.data
            sorted_groups = sorted(
                groups,
                key=lambda g: (g.get("name") or "", g.get("id") or ""),
            )
            self._attr_native_value = len(sorted_groups)
            changes = self._diff_groups(self._previous_groups, sorted_groups)
            self._previous_groups = sorted_groups
            self._attr_extra_state_attributes = {
                "groups": [self._normalize_group(g) for g in sorted_groups],
                "group_ids": [g["id"] for g in sorted_groups],
                **changes,
            }
            return self._attr_native_value

        self._attr_extra_state_attributes = {}
        return "No data"

    @property
    def extra_state_attributes(self):
        return getattr(self, "_attr_extra_state_attributes", {})


class SignalGroupSensor(CoordinatorEntity, SensorEntity):
    """Individual sensor for a Signal group."""

    def __init__(self, entry_id, coordinator, number, group):
        super().__init__(coordinator)
        self._owner_number = number
        self._group_id = group.get("id")
        self._group = group
        self._attr_name = f"Signal Group {group.get('name') or group.get('id')}"
        self._attr_unique_id = f"signal_group_{entry_id}_{group.get('id')}"
        self._attr_native_value = group.get("name") or group.get("id")

    @property
    def available(self):
        return bool(self.coordinator.data)

    @property
    def native_value(self):
        group = next(
            (g for g in (self.coordinator.data or []) if g.get("id") == self._group_id),
            self._group,
        )
        self._attr_native_value = group.get("name") or group.get("id")
        return self._attr_native_value

    @property
    def extra_state_attributes(self):
        group = next(
            (g for g in (self.coordinator.data or []) if g.get("id") == self._group_id),
            self._group,
        )
        return {
            "id": group.get("id"),
            "name": group.get("name", "Unnamed"),
            "description": group.get("description"),
            "member_count": len(group.get("members", [])),
            "members": group.get("members", []),
            "owner_number": self._owner_number,
        }
