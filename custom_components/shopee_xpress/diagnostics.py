"""Diagnostics support for the Shopee Xpress parcel tracker integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ShopeeXpressConfigEntry
from .parcels import REQUESTED_CODE_KEY

# Diagnostics are pasted into public issues, so redact anything that
# identifies a person, an address or a specific parcel. Over-redacting is
# cheap; under-redacting leaks a user's home address into a GitHub thread.
#
# Three things on this list are not obvious from their names. The three raw
# free-text description fields can carry a person's name inline even when the
# structured receiver fields are empty (one capture reads "...delivered to
# [name] [Receptionist]" with receiver_name blank) — kept here for defence in
# depth even though normalize_parcel() never surfaces those three key names
# literally. What it surfaces *instead* is the same risk under a different
# name: `raw_status` (top-level, and per entry in `history[]`) is exactly
# that free text, picked by `_describe_status_text()` — so `raw_status` is on
# this list too, unconditionally, even though for most parcels it is
# perfectly bland ("Out for delivery"). And a facility `full_address` is not
# always a facility — one hub address on file is a named individual's house.
# All three are redacted unconditionally rather than on a judgement call
# about whether a given value looks personal.
TO_REDACT = {
    # canonical fields we publish ourselves
    "barcode",
    "sender",
    "receiver",
    "raw_status",
    REQUESTED_CODE_KEY,
    # the user's own registered code, as stored in entry.options[parcels] —
    # the same class of sensitive value as spx_tn/sls_tn below, just in a
    # different location (the config, not a fetched payload)
    "tracking_code",
    # both tracking-number identifiers, and the merchant free-text one the
    # lookup parameter also matches against
    "spx_tn",
    "sls_tn",
    "customer_tracking_no",
    "resolved_number",
    # order identifiers
    "order_id",
    "client_order_id",
    # recipient
    "receiver_name",
    "receiver_type_name",
    # free text that can embed a name, a driver task id or internal wording
    "description",
    "buyer_description",
    "seller_description",
    "reason_desc",
    "standard_reason_description",
    # proof of delivery
    "epod",
    # driver_infos[] fields
    "pickup_driver_name",
    "pickup_driver_phone",
    "pickup_driver_photo",
    "pickup_driver_id",
    "license_plate_number",
    # facility location — can be a private address, not only a hub
    "location_name",
    "full_address",
    "lat",
    "lng",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ShopeeXpressConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the Shopee Xpress config entry.

    Redaction applies to the whole payload, so it also covers whatever a
    parcel the requester does not actually own would have carried — this
    integration's lookup parameter matches merchant free text as well as a
    tracking code, so a response is never assumed to belong to whoever
    triggered the fetch.
    """
    coordinator = entry.runtime_data.coordinator

    return {
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "counts": {
            "incoming_active": len(coordinator.data or []),
            "delivered": len(coordinator.delivered or []),
        },
        "incoming": async_redact_data(coordinator.data or [], TO_REDACT),
        "delivered": async_redact_data(coordinator.delivered or [], TO_REDACT),
    }
