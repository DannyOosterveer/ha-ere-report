"""Phones that can receive a push notification about a new report."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

MOBILE_APP = "mobile_app"
NOTIFY = "notify"


async def async_admin_phones(hass: HomeAssistant) -> dict[str, str]:
    """Return {notify service: phone name} for app devices of administrators.

    The reports page is for administrators only, so a push to anyone else
    would link to a page they cannot open.
    """
    phones: dict[str, str] = {}
    for entry in hass.config_entries.async_entries(MOBILE_APP):
        name = entry.data.get("device_name")
        user_id = entry.data.get("user_id")
        if not name or not user_id:
            continue
        user = await hass.auth.async_get_user(user_id)
        if user is None or not user.is_active or not user.is_admin:
            continue
        # mobile_app names its notify services after the device name.
        service = f"{MOBILE_APP}_{slugify(name)}"
        if hass.services.has_service(NOTIFY, service):
            phones[service] = name
    return phones
