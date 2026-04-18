"""API helper for Signal Messenger."""
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_HOST, CONF_PORT, CONF_NUMBER

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
    url = f"http://{host}:{port}{endpoint}"

    try:
        kwargs = {"timeout": timeout}
        if payload is not None:
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