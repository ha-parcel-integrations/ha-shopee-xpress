"""Services for the Shopee Xpress parcel tracker integration.

`shopee_xpress.track_parcel` / `shopee_xpress.untrack_parcel` let you add or
remove a tracked parcel without opening the integration options — so a
Lovelace button can start tracking a parcel straight from a dashboard.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .config_flow import normalize_tracking_code, warn_unrecognised_tracking_code
from .const import CONF_MARKET, CONF_PARCELS, CONF_TRACKING_CODE, DOMAIN

SERVICE_TRACK_PARCEL = "track_parcel"
SERVICE_UNTRACK_PARCEL = "untrack_parcel"

_TRACK_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TRACKING_CODE): cv.string,
        vol.Optional(CONF_MARKET): cv.string,
    }
)
_UNTRACK_SCHEMA = vol.Schema({vol.Required(CONF_TRACKING_CODE): cv.string})


def _resolve_entry(hass: HomeAssistant, market: str | None):
    """Pick the Shopee Xpress hub to act on.

    With one hub, that hub. With several (one per market), the ``market``
    argument selects it; if omitted and ambiguous, raise so the caller knows
    to specify one — a market from another hub is never picked implicitly.
    """
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("Shopee Xpress is not set up")
    if market:
        target = market.upper()
        for entry in entries:
            if entry.options.get(CONF_MARKET) == target:
                return entry
        raise ServiceValidationError(f"No Shopee Xpress hub for market {target}")
    if len(entries) == 1:
        return entries[0]
    raise ServiceValidationError(
        "Multiple Shopee Xpress hubs are set up — pass market to choose one"
    )


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the Shopee Xpress services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_TRACK_PARCEL):
        return

    async def _track(call: ServiceCall) -> None:
        tracking_code = normalize_tracking_code(call.data[CONF_TRACKING_CODE])
        warn_unrecognised_tracking_code(tracking_code)
        entry = _resolve_entry(hass, call.data.get(CONF_MARKET))

        parcels = [dict(p) for p in entry.options.get(CONF_PARCELS, [])]
        if any(p[CONF_TRACKING_CODE] == tracking_code for p in parcels):
            return  # already tracked — no-op
        parcels.append({CONF_TRACKING_CODE: tracking_code})
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_PARCELS: parcels}
        )

    async def _untrack(call: ServiceCall) -> None:
        tracking_code = normalize_tracking_code(call.data[CONF_TRACKING_CODE])
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError("Shopee Xpress is not set up")
        # Remove the parcel from whichever hub(s) track it.
        for entry in entries:
            current = entry.options.get(CONF_PARCELS, [])
            kept = [p for p in current if p[CONF_TRACKING_CODE] != tracking_code]
            if len(kept) != len(current):
                hass.config_entries.async_update_entry(
                    entry, options={**entry.options, CONF_PARCELS: kept}
                )

    hass.services.async_register(
        DOMAIN, SERVICE_TRACK_PARCEL, _track, schema=_TRACK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UNTRACK_PARCEL, _untrack, schema=_UNTRACK_SCHEMA
    )


def async_unload_services(hass: HomeAssistant) -> None:
    """Remove the Shopee Xpress services (called once the last hub unloads)."""
    for service in (SERVICE_TRACK_PARCEL, SERVICE_UNTRACK_PARCEL):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
