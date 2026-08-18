"""The device every entity of this integration belongs to.

One place, because sensors, the button and the calendar must all land on the
*same* device entry.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo

from .const import CONF_MARKET, DOMAIN

ATTRIBUTION = "Data provided by Shopee Xpress"


def build_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the DeviceInfo shared by every entity of this hub.

    One device per market (a hub is bound to exactly one), named after it so
    multiple hubs are distinguishable. No ``configuration_url``: no public
    tracking page path has been confirmed on any of this carrier's hosts, and
    inventing one is exactly the trap this integration's own payload mapping
    was built to avoid.
    """
    market = entry.options.get(CONF_MARKET)
    name = f"Shopee Xpress ({market})" if market else "Shopee Xpress"
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=name,
        manufacturer="Shopee Xpress",
        entry_type=DeviceEntryType.SERVICE,
    )
