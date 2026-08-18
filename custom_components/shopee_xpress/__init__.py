"""Shopee Xpress parcel tracker custom component for Home Assistant."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ShopeeXpressApiClient
from .const import CONF_MARKET, DOMAIN, MARKETS, PLATFORMS
from .coordinator import ShopeeXpressCoordinator, _refresh_interval
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)


@dataclass
class ShopeeXpressData:
    """Runtime data attached to the Shopee Xpress config entry."""

    client: ShopeeXpressApiClient
    coordinator: ShopeeXpressCoordinator


type ShopeeXpressConfigEntry = ConfigEntry[ShopeeXpressData]


async def async_setup_entry(hass: HomeAssistant, entry: ShopeeXpressConfigEntry) -> bool:
    """Set up Shopee Xpress from a config entry."""
    market = entry.options.get(CONF_MARKET)
    market_config = MARKETS.get(market)
    if market_config is None:
        # A market removed from MARKETS (or a corrupted entry) leaves this
        # hub with no host to poll. Not a transient condition retrying would
        # fix, but ConfigEntryNotReady is still the right signal — it surfaces
        # as a clear repair prompt rather than a half-set-up entry.
        raise ConfigEntryNotReady(f"Unknown Shopee Xpress market: {market!r}")
    host, language_code = market_config

    # No auth: Shopee Xpress tracking is public, so the HA-managed session is
    # fine. Host and language_code are fixed for this hub's lifetime — a
    # number from one market's host does not resolve against another's.
    client = ShopeeXpressApiClient(
        async_get_clientsession(hass), host=host, language_code=language_code
    )
    coordinator = ShopeeXpressCoordinator(hass, client, entry)

    # Fetch initial data here, before forwarding to platforms. Raising
    # ConfigEntryNotReady from a forwarded platform is too late for HA to catch
    # cleanly (it logs a warning and half-sets-up the entry); doing the first
    # refresh here lets a transient failure fail the whole entry so HA retries
    # it with backoff.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = ShopeeXpressData(client=client, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Apply option changes (added/removed parcels, history) live via a
    # coordinator refresh — no reload — so per-parcel sensors appear and
    # disappear immediately. The update listener does NOT reload, so it does
    # not trip the config-entry-listener deprecation.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    async_setup_services(hass)

    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: ShopeeXpressConfigEntry
) -> None:
    """Apply changed options: retune the interval and refresh the coordinator."""
    coordinator = entry.runtime_data.coordinator
    coordinator.update_interval = _refresh_interval(entry)
    await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ShopeeXpressConfigEntry) -> bool:
    """Unload the Shopee Xpress config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    # The services are shared across every market's hub, so only remove them
    # once the last one is gone — unloading one hub must not break the others.
    others_loaded = any(
        other.entry_id != entry.entry_id and other.state is ConfigEntryState.LOADED
        for other in hass.config_entries.async_entries(DOMAIN)
    )
    if not others_loaded:
        async_unload_services(hass)
    return True
