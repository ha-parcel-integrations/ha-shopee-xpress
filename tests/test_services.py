"""Tests for the Shopee Xpress services (track_parcel / untrack_parcel)."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shopee_xpress.const import (
    CONF_MARKET,
    CONF_PARCELS,
    CONF_TRACKING_CODE,
    DOMAIN,
)
from custom_components.shopee_xpress.services import async_setup_services

from .payloads import MY_CODE, my_data

_SAMPLE = my_data()


async def _setup(hass, parcels: list[dict] | None = None, *, market: str = "MY") -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={CONF_MARKET: market, CONF_PARCELS: parcels or []},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(return_value=_SAMPLE),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_track_parcel_adds_to_options(hass):
    entry = await _setup(hass)
    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(return_value=_SAMPLE),
    ):
        await hass.services.async_call(
            DOMAIN,
            "track_parcel",
            {CONF_TRACKING_CODE: "TH000000000000"},
            blocking=True,
        )
        await hass.async_block_till_done()

    parcels = entry.options[CONF_PARCELS]
    assert parcels == [{CONF_TRACKING_CODE: "TH000000000000"}]


async def test_track_parcel_normalizes_code(hass):
    entry = await _setup(hass)
    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(return_value=_SAMPLE),
    ):
        await hass.services.async_call(
            DOMAIN,
            "track_parcel",
            {CONF_TRACKING_CODE: "th 000000-000000"},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert entry.options[CONF_PARCELS] == [
        {CONF_TRACKING_CODE: "TH000000000000"}
    ]


async def test_track_parcel_never_rejects_unrecognised_shape(hass):
    """Warn-only, never blocking — a maintainer decision, not an oversight."""
    entry = await _setup(hass)
    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(return_value=_SAMPLE),
    ):
        await hass.services.async_call(
            DOMAIN, "track_parcel", {CONF_TRACKING_CODE: "zz"}, blocking=True
        )
        await hass.async_block_till_done()

    assert entry.options[CONF_PARCELS] == [{CONF_TRACKING_CODE: "ZZ"}]


async def test_track_parcel_duplicate_is_noop(hass):
    entry = await _setup(hass)
    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(return_value=_SAMPLE),
    ):
        for _ in range(2):
            await hass.services.async_call(
                DOMAIN,
                "track_parcel",
                {CONF_TRACKING_CODE: "TH000000000000"},
                blocking=True,
            )
            await hass.async_block_till_done()

    assert len(entry.options[CONF_PARCELS]) == 1


async def test_untrack_parcel_removes_from_options(hass):
    entry = await _setup(hass, parcels=[{CONF_TRACKING_CODE: MY_CODE}])
    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(return_value=_SAMPLE),
    ):
        await hass.services.async_call(
            DOMAIN,
            "untrack_parcel",
            {CONF_TRACKING_CODE: MY_CODE},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert entry.options[CONF_PARCELS] == []


async def test_untrack_unknown_code_is_noop(hass):
    entry = await _setup(hass, parcels=[{CONF_TRACKING_CODE: MY_CODE}])
    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(return_value=_SAMPLE),
    ):
        await hass.services.async_call(
            DOMAIN,
            "untrack_parcel",
            {CONF_TRACKING_CODE: "TH999999999999"},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert len(entry.options[CONF_PARCELS]) == 1


async def test_track_parcel_no_entries_raises(hass):
    """The service is registered (so this reaches `_resolve_entry`) but no
    hub exists — a scenario the last-unload teardown wouldn't normally leave
    behind, tested directly rather than assumed."""
    async_setup_services(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "track_parcel", {CONF_TRACKING_CODE: MY_CODE}, blocking=True
        )


# ---------------------------------------------------------------------------
# multi-hub disambiguation
# ---------------------------------------------------------------------------


async def _setup_two_hubs(hass) -> tuple[MockConfigEntry, MockConfigEntry]:
    entry_my = MockConfigEntry(domain=DOMAIN, options={CONF_MARKET: "MY", CONF_PARCELS: []})
    entry_th = MockConfigEntry(domain=DOMAIN, options={CONF_MARKET: "TH", CONF_PARCELS: []})
    entry_my.add_to_hass(hass)
    entry_th.add_to_hass(hass)
    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(return_value=_SAMPLE),
    ):
        assert await hass.config_entries.async_setup(entry_my.entry_id)
        await hass.async_block_till_done()
    return entry_my, entry_th


async def test_track_parcel_requires_market_when_ambiguous(hass):
    await _setup_two_hubs(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "track_parcel", {CONF_TRACKING_CODE: MY_CODE}, blocking=True
        )


async def test_track_parcel_market_selects_the_right_hub(hass):
    entry_my, entry_th = await _setup_two_hubs(hass)
    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(return_value=_SAMPLE),
    ):
        await hass.services.async_call(
            DOMAIN,
            "track_parcel",
            {CONF_TRACKING_CODE: "TH111111111111", CONF_MARKET: "th"},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert entry_th.options[CONF_PARCELS] == [{CONF_TRACKING_CODE: "TH111111111111"}]
    assert entry_my.options[CONF_PARCELS] == []


async def test_track_parcel_unknown_market_raises(hass):
    await _setup_two_hubs(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "track_parcel",
            {CONF_TRACKING_CODE: MY_CODE, CONF_MARKET: "zz"},
            blocking=True,
        )


async def test_untrack_parcel_removes_from_every_hub_that_tracks_it(hass):
    """untrack has no market argument — it sweeps every hub, by design."""
    entry_my = MockConfigEntry(
        domain=DOMAIN, options={CONF_MARKET: "MY", CONF_PARCELS: [{CONF_TRACKING_CODE: "DUPE000000001"}]}
    )
    entry_th = MockConfigEntry(
        domain=DOMAIN, options={CONF_MARKET: "TH", CONF_PARCELS: [{CONF_TRACKING_CODE: "DUPE000000001"}]}
    )
    entry_my.add_to_hass(hass)
    entry_th.add_to_hass(hass)
    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(return_value=_SAMPLE),
    ):
        assert await hass.config_entries.async_setup(entry_my.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            DOMAIN,
            "untrack_parcel",
            {CONF_TRACKING_CODE: "DUPE000000001"},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert entry_my.options[CONF_PARCELS] == []
    assert entry_th.options[CONF_PARCELS] == []


async def test_untrack_parcel_no_entries_raises(hass):
    async_setup_services(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "untrack_parcel", {CONF_TRACKING_CODE: MY_CODE}, blocking=True
        )
