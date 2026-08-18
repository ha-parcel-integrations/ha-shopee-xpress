"""Tests for Shopee Xpress setup and unload."""
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shopee_xpress.api import ShopeeXpressApiError
from custom_components.shopee_xpress.const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_MARKET,
    CONF_PARCELS,
    CONF_TRACKING_CODE,
    DOMAIN,
)

from .payloads import ID_CODE, MY_CODE, id_data
from .payloads import my_data as _sample

OTHER_CODE = "TH000000000000"


def _entry(parcels: list[dict], *, market: str = "MY") -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_MARKET: market,
            CONF_PARCELS: parcels,
            # Keep-most-recent-100 so the delivered-retention filter never
            # trims the (old, fixed-date) sample parcels these tests assert on.
            CONF_DELIVERED_FILTER_TYPE: "parcels",
            CONF_DELIVERED_FILTER_AMOUNT: 100,
        },
    )


async def test_setup_and_unload(hass):
    entry = _entry([{CONF_TRACKING_CODE: MY_CODE}])
    entry.add_to_hass(hass)

    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(return_value=_sample()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED

    # The delivered parcel produced the summary sensors, not an active one.
    incoming = hass.states.get("sensor.shopee_xpress_my_incoming_parcels")
    assert incoming is not None
    assert incoming.state == "0"
    delivered = hass.states.get("sensor.shopee_xpress_my_delivered_parcels")
    assert delivered.state == "1"

    # Services registered on setup...
    assert hass.services.has_service(DOMAIN, "track_parcel")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED

    # ...and removed on unload (last hub gone).
    assert not hass.services.has_service(DOMAIN, "track_parcel")


async def test_device_is_named_after_its_market(hass):
    from homeassistant.helpers import device_registry as dr

    entry = _entry([{CONF_TRACKING_CODE: MY_CODE}], market="VN")
    entry.add_to_hass(hass)
    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(return_value=_sample()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    device = next(
        iter(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id))
    )
    assert device.name == "Shopee Xpress (VN)"


async def test_setup_raises_config_entry_not_ready_for_unknown_market(hass):
    entry = _entry([], market="ZZ")
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    # ConfigEntryNotReady always yields SETUP_RETRY (HA schedules a retry),
    # never SETUP_ERROR — the point is that it's recoverable, not fatal.
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_retries_when_first_refresh_fails(hass):
    """When the first data fetch fails, setup retries from the entry itself.

    The first refresh runs in __init__.py before platforms are forwarded, so a
    failure raises ConfigEntryNotReady from the entry setup (SETUP_RETRY) rather
    than — too late — from a forwarded platform.
    """
    entry = _entry([{CONF_TRACKING_CODE: MY_CODE}])
    entry.add_to_hass(hass)

    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(side_effect=ShopeeXpressApiError("Shopee Xpress unreachable")),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_per_parcel_sensor_spawn_and_remove(hass):
    entry = _entry([{CONF_TRACKING_CODE: ID_CODE}])
    entry.add_to_hass(hass)

    mock = AsyncMock(return_value=id_data())
    with patch("custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel", new=mock):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        assert registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{ID_CODE}"
        )

        # The next poll returns a different tracking code: the summary sensor
        # spawns a new per-parcel sensor and removes the stale one.
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_PARCELS: [{CONF_TRACKING_CODE: OTHER_CODE}]}
        )
        mock.return_value = id_data(OTHER_CODE)
        await entry.runtime_data.coordinator.async_request_refresh()
        await hass.async_block_till_done()

        assert registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{OTHER_CODE}"
        )
        assert (
            registry.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_{ID_CODE}"
            )
            is None
        )


async def test_options_update_applies_live_without_reload(hass):
    """Adding a parcel via options refreshes the coordinator immediately."""
    entry = _entry([{CONF_TRACKING_CODE: ID_CODE}])
    entry.add_to_hass(hass)

    mock = AsyncMock(return_value=id_data())
    with patch("custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel", new=mock):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        mock.side_effect = lambda code: id_data(code)
        hass.config_entries.async_update_entry(
            entry,
            options={
                **entry.options,
                CONF_PARCELS: [
                    {CONF_TRACKING_CODE: ID_CODE},
                    {CONF_TRACKING_CODE: OTHER_CODE},
                ],
            },
        )
        await hass.async_block_till_done()

    incoming = hass.states.get("sensor.shopee_xpress_my_incoming_parcels")
    assert incoming.state == "2"


async def test_services_stay_registered_while_another_hub_is_loaded(hass):
    """Unloading one of several hubs must not break the others' services.

    Setting up the first entry of a domain that has never been loaded before
    also bootstraps every other already-registered entry of that domain in
    the same pass (standard HA behaviour for the component's first setup) —
    so only one explicit ``async_setup`` call is needed here.
    """
    entry_a = _entry([{CONF_TRACKING_CODE: MY_CODE}], market="MY")
    entry_b = _entry([{CONF_TRACKING_CODE: OTHER_CODE}], market="TH")
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)

    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(return_value=_sample()),
    ):
        assert await hass.config_entries.async_setup(entry_a.entry_id)
        await hass.async_block_till_done()

    assert entry_a.state is ConfigEntryState.LOADED
    assert entry_b.state is ConfigEntryState.LOADED
    assert hass.services.has_service(DOMAIN, "track_parcel")


async def test_unload_entry_returns_false_when_platform_unload_fails(hass):
    """Unit-tested directly against `async_unload_entry` rather than through
    the full config-entry state machine: HA treats a failed platform-unload
    as the entry's new (non-recoverable) FAILED_UNLOAD state, and there is no
    real coordinator/timer here to worry about leaving lingering."""
    from custom_components.shopee_xpress import async_unload_entry

    entry = _entry([{CONF_TRACKING_CODE: MY_CODE}])
    entry.add_to_hass(hass)

    with patch.object(
        hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=False)
    ):
        result = await async_unload_entry(hass, entry)

    assert result is False


async def test_stale_per_parcel_sensor_removed_on_next_setup(hass):
    """A barcode tracked in a previous session that is no longer polled must
    not leave a ghost sensor behind in the entity registry."""
    entry = _entry([{CONF_TRACKING_CODE: ID_CODE}])
    entry.add_to_hass(hass)
    registry = er.async_get(hass)

    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(return_value=id_data()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{ID_CODE}")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    # The registry entry survives an unload; drop the parcel from options so
    # the next setup's first poll never sees that barcode again.
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_PARCELS: []}
    )
    with patch(
        "custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel",
        new=AsyncMock(return_value=id_data()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{ID_CODE}") is None
