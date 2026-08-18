"""Tests for Shopee Xpress diagnostics."""
from unittest.mock import MagicMock

from custom_components.shopee_xpress.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.shopee_xpress.parcels import REQUESTED_CODE_KEY, normalize_parcel

from .payloads import MY_CODE, VN_CODE, my_data, vn_data


async def test_diagnostics_redacts_and_counts(hass):
    """Diagnostics get pasted into public issues — nothing identifying may survive."""
    entry = MagicMock()
    entry.options = {"parcels": [{"tracking_code": MY_CODE}], "market": "MY"}
    incoming_parcel = normalize_parcel(
        {**my_data(), REQUESTED_CODE_KEY: MY_CODE}, market="MY", include_history=True
    )
    entry.runtime_data.coordinator.data = [incoming_parcel]
    entry.runtime_data.coordinator.delivered = []

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["counts"] == {"incoming_active": 1, "delivered": 0}
    # the user's own registered tracking code is redacted in entry_options...
    assert result["entry_options"]["parcels"][0]["tracking_code"] == "**REDACTED**"
    # market is not sensitive and survives, or diagnostics lose all context
    assert result["entry_options"]["market"] == "MY"
    # ...and every tracking-number identifier is redacted in the payload
    assert result["incoming"][0]["barcode"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["spx_tn"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["sls_tn"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["resolved_number"] == "**REDACTED**"
    # non-identifying fields survive, or the diagnostics would be useless
    assert result["incoming"][0]["status"] == "delivered"
    assert result["incoming"][0]["raw"]["market"] == "MY"


async def test_diagnostics_redacts_raw_status_which_can_embed_a_name(hass):
    """`raw_status` is the carrier's own free text (`_describe_status_text()`)
    and can carry a person's name inline even when the structured receiver
    field is empty — it must be redacted unconditionally, both at the
    top level and inside every `history[]` entry."""
    entry = MagicMock()
    entry.options = {"parcels": [], "market": "VN"}
    parcel = normalize_parcel(
        {**vn_data(), REQUESTED_CODE_KEY: VN_CODE}, market="VN", include_history=True
    )
    assert parcel["raw_status"] is not None  # sanity: there is something to redact
    entry.runtime_data.coordinator.data = []
    entry.runtime_data.coordinator.delivered = [parcel]

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["delivered"][0]["raw_status"] == "**REDACTED**"
    assert result["delivered"][0]["history"]
    for event in result["delivered"][0]["history"]:
        if event["raw_status"] is not None:
            assert event["raw_status"] == "**REDACTED**"
    # the underlying raw exception description field is redacted too
    assert result["delivered"][0]["raw"]["standard_reason_description"] in (
        None, "**REDACTED**"
    )


async def test_diagnostics_counts_reflect_empty_lists(hass):
    entry = MagicMock()
    entry.options = {"parcels": [], "market": "MY"}
    entry.runtime_data.coordinator.data = []
    entry.runtime_data.coordinator.delivered = []

    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["counts"] == {"incoming_active": 0, "delivered": 0}
    assert result["incoming"] == []
    assert result["delivered"] == []
