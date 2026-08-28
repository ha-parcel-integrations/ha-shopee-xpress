"""Tests for the Shopee Xpress config and options flow.

Setup is market-only, single-step, entry created immediately (no fetch) — see
``config_flow.py``'s module docstring for why (the input-collision visibility
idea from an earlier revision was cut, not relocated). Adding a tracking code
happens entirely in the options flow, and is likewise a plain add with no
fetch.
"""
import logging

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shopee_xpress import config_flow as config_flow_module
from custom_components.shopee_xpress.config_flow import (
    _sorted_market_options,
    normalize_tracking_code,
    valid_tracking_code,
)
from custom_components.shopee_xpress.const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_INCLUDE_HISTORY,
    CONF_MARKET,
    CONF_PARCELS,
    CONF_TRACKING_CODE,
    DOMAIN,
    MARKETS,
)


@pytest.fixture(autouse=True)
def _reset_format_warnings():
    config_flow_module._warned_formats.clear()
    yield
    config_flow_module._warned_formats.clear()


# ---------------------------------------------------------------------------
# tracking-code validation — warn-only, never reject
# ---------------------------------------------------------------------------


def test_normalize_tracking_code_strips_and_uppercases():
    assert normalize_tracking_code("my 000000-000000") == "MY000000000000"
    assert normalize_tracking_code("") == ""
    assert normalize_tracking_code(None) == ""


@pytest.mark.parametrize(
    "code",
    [
        "BR000000000000Y",   # 2 letters + 12 digits + 1 letter
        "MY000000000000",    # 2 letters + 12 digits
        "TH000000000000",    # 2 letters + 12 digits
        "SPEPH000000000000", # 5 letters + 12 digits (Philippines)
        "SPXID000000000000", # 5 letters + 12 digits (Indonesia)
        "SPXVN00000000000C", # 5 letters + 11 digits + 1 letter (Vietnam) —
                              # the shape that broke the regex twice already;
                              # a regression test for that history.
        "123456789",          # pure-digit order/client id — first-class input
    ],
)
def test_valid_tracking_code_accepts_every_captured_shape(code):
    assert valid_tracking_code(code) is True


def test_valid_tracking_code_rejects_neither_shape():
    assert valid_tracking_code("NOT-A-VALID-CODE!!") is False


def test_warn_unrecognised_tracking_code_never_raises_or_blocks(caplog):
    caplog.set_level(logging.WARNING)
    config_flow_module.warn_unrecognised_tracking_code("???")
    config_flow_module.warn_unrecognised_tracking_code("???")
    assert caplog.text.count("???") == 1
    assert "never used to reject" in caplog.text


def test_warn_unrecognised_tracking_code_silent_for_known_shapes(caplog):
    caplog.set_level(logging.WARNING)
    config_flow_module.warn_unrecognised_tracking_code("MY000000000000")
    assert caplog.text == ""


# ---------------------------------------------------------------------------
# _sorted_market_options — locale-aware dropdown sort
# ---------------------------------------------------------------------------


async def test_sorted_market_options_english_matches_code_order(hass):
    hass.config.language = "en"
    assert await _sorted_market_options(hass) == ["br", "id", "my", "ph", "th", "vn"]


async def test_sorted_market_options_dutch_is_not_code_order(hass):
    """Brazilië, Filipijnen, Indonesië, Maleisië, Thailand, Vietnam — PH sorts
    second in Dutch, not fourth as it does in the code-alphabetical order."""
    hass.config.language = "nl"
    assert await _sorted_market_options(hass) == ["br", "ph", "id", "my", "th", "vn"]


async def test_sorted_market_options_unshipped_locale_falls_back_to_english(hass):
    hass.config.language = "de"
    assert await _sorted_market_options(hass) == ["br", "id", "my", "ph", "th", "vn"]


async def test_sorted_market_options_falls_back_when_lookup_is_truly_empty(hass, monkeypatch):
    """HA's own translation loader already substitutes English for a locale
    this repo doesn't ship (confirmed against the real loader — see
    ``test_sorted_market_options_unshipped_locale_falls_back_to_english``),
    so this integration's own fallback line is a defensive backstop for a
    lookup that comes back with nothing at all, exercised here directly."""

    async def _empty(hass, language, category, integrations=None):
        return {}

    monkeypatch.setattr(config_flow_module, "async_get_translations", _empty)
    hass.config.language = "en"
    # No translations available anywhere -> every code falls back to itself
    # as the sort key, which is still deterministic and never raises.
    assert await _sorted_market_options(hass) == ["br", "id", "my", "ph", "th", "vn"]


async def test_sorted_market_options_returns_every_market_exactly_once(hass):
    hass.config.language = "nl"
    options = await _sorted_market_options(hass)
    assert sorted(options) == sorted(code.lower() for code in MARKETS)


# ---------------------------------------------------------------------------
# config flow — setup asks for the market only
# ---------------------------------------------------------------------------


async def test_user_flow_shows_market_selector(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert CONF_MARKET in result["data_schema"].schema


async def test_user_flow_creates_hub_with_empty_parcels_and_defaults(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MARKET: "my"}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "Shopee Xpress (MY)"
    assert result["options"][CONF_MARKET] == "MY"
    assert result["options"][CONF_PARCELS] == []
    assert result["options"][CONF_DELIVERED_FILTER_TYPE] == "days"
    assert result["options"][CONF_DELIVERED_FILTER_AMOUNT] == 7
    assert result["options"][CONF_INCLUDE_HISTORY] is False


async def test_user_flow_stores_market_upper_cased(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MARKET: "vn"}
    )
    assert result["options"][CONF_MARKET] == "VN"


async def test_second_hub_for_the_same_market_is_allowed(hass):
    """A deliberate maintainer call: not technically enforced as one-per-market."""
    MockConfigEntry(domain=DOMAIN, options={CONF_MARKET: "MY", CONF_PARCELS: []}).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MARKET: "my"}
    )
    assert result["type"] == "create_entry"

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 2
    assert all(e.options[CONF_MARKET] == "MY" for e in entries)


async def test_hubs_for_different_markets_are_independent(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MARKET: "br"}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MARKET: "vn"}
    )

    markets = {e.options[CONF_MARKET] for e in hass.config_entries.async_entries(DOMAIN)}
    assert markets == {"BR", "VN"}


# ---------------------------------------------------------------------------
# options flow — plain add / remove, market carried forward, market-picker
# never appears again
# ---------------------------------------------------------------------------


def _hub(parcels: list[dict], *, market: str = "MY") -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        options={CONF_MARKET: market, CONF_PARCELS: parcels},
    )


def _init_input(
    *, add="", remove=None, history=False,
    filter_type="days", amount=7,
) -> dict:
    """Build the sectioned options-form submission."""
    parcels: dict = {"add": add}
    if remove is not None:
        parcels["remove"] = remove
    return {
        "parcels": parcels,
        "delivered": {
            CONF_DELIVERED_FILTER_TYPE: filter_type,
            CONF_DELIVERED_FILTER_AMOUNT: amount,
        },
        "history": {CONF_INCLUDE_HISTORY: history},
    }


async def _open_options_step(hass, entry, step_id: str):
    """Start the options flow and select one of its two top-level routes."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "menu"
    assert result["menu_options"] == ["parcels", "settings"]
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step_id}
    )


async def test_options_parcel_list_can_be_cleared(hass):
    """A submitted empty list removes the final manually tracked parcel."""
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_PARCELS: [{CONF_TRACKING_CODE: "EXAMPLE111111"}]})
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "parcels")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_codes": []}
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == []


async def test_options_settings_preserve_parcel_list(hass):
    """Saving settings must never replace the manually tracked parcel list."""
    parcels = [{CONF_TRACKING_CODE: "EXAMPLE111111"}]
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_PARCELS: parcels})
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "settings")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DELIVERED_FILTER_TYPE: "days", CONF_DELIVERED_FILTER_AMOUNT: 7, CONF_INCLUDE_HISTORY: False}
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == parcels
