"""Config flow for the Shopee Xpress parcel tracker integration.

Setup asks for one thing — the market — and creates the hub immediately, the
same shape as ``ha-dragonfly``'s zero-input setup, just with the one input
Shopee Xpress actually needs (Dragonfly has none; Shopee Xpress runs a
separate backend per market, so *which* backend has to be chosen up front).
Tracking codes are added afterward, in the options flow, mirroring how the
rest of this repo — and the rest of the suite — separates "which hub" from
"which parcels". Adding one there is a plain add, exactly like every other
carrier in this suite: normalise it, log (never show) a one-shot warning if
its shape is unrecognised, store it. No fetch happens at add-time — see
CLAUDE.md for why the input-collision visibility idea from an earlier
revision of this flow was cut rather than relocated.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.helpers.translation import async_get_translations

from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_INCLUDE_HISTORY,
    CONF_MARKET,
    CONF_PARCELS,
    CONF_TRACKING_CODE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    DEFAULT_INCLUDE_HISTORY,
    DOMAIN,
    MARKETS,
)

_LOGGER = logging.getLogger(__name__)

# Every real spx_tn seen is `[A-Z]{2,5}` + 10-13 digits + an optional trailing
# letter — and this shape has already been wrong twice (once on prefix
# length, once on digit count), each time discovered by the very next market
# captured. A pure-digit input (an order/client id, a second identifier
# namespace confirmed on the wire) is accepted as a first-class shape, not a
# malformation. Warn on neither shape matching; never reject either one — six
# markets are a minority of this carrier's footprint, and a stricter pattern
# has never survived contact with a new one.
_TRACKING_CODE_RE = re.compile(r"^[A-Z]{2,5}\d{10,13}[A-Z]?$")

_warned_formats: set[str] = set()


def normalize_tracking_code(value: str) -> str:
    """Return the tracking code upper-cased with separators stripped."""
    return re.sub(r"[^A-Z0-9]+", "", (value or "").upper())


def valid_tracking_code(value: str) -> bool:
    """Whether ``value`` matches a known Shopee Xpress identifier shape.

    Informational only — see the module docstring. Never used to reject
    input; only to decide whether :func:`warn_unrecognised_tracking_code`
    logs.
    """
    return bool(_TRACKING_CODE_RE.match(value)) or value.isdigit()


def warn_unrecognised_tracking_code(value: str) -> None:
    """Log once per unrecognised shape — never shown to the user.

    The maintainer cut the config-flow warning for this deliberately: short
    or ambiguous input is accepted and looked up like any other, with no
    on-screen message. The server-side one-shot log this function writes is
    the pre-1.0 vocabulary-building obligation, which is unrelated and stays.
    """
    if valid_tracking_code(value) or value in _warned_formats:
        return
    _warned_formats.add(value)
    _LOGGER.warning(
        "Shopee Xpress tracking code %r matches neither the known "
        "alphanumeric shape nor a pure-digit id. Accepting it anyway — this "
        "pattern has been wrong before and is never used to reject input.",
        value,
    )


async def _sorted_market_options(hass: HomeAssistant) -> list[str]:
    """Return ``MARKETS`` keys (lower-cased), sorted by translated country name.

    `const.py`'s `MARKETS` happens to be in English-alphabetical order
    (Brazil, Indonesia, Malaysia, Philippines, Thailand, Vietnam), which is
    not alphabetical in every locale this repo ships — Dutch sorts
    "Filipijnen" (PH) second, not fourth. Reading this integration's own
    ``selector.market.options.*`` strings via HA's translation loader (the
    same source `strings.json` / `translations/*.json` already carry, so
    there is nothing to keep in sync by hand) and sorting by the translated
    name gets the dropdown right for the active language rather than baking
    in one locale's order. Falls back to English when the active language
    isn't one of the locales this repo ships translations for (or couldn't
    be determined) — the six English names are always available since
    `strings.json` doubles as the English translation source.
    """
    def _key(code: str) -> str:
        # The translation cache keys every string with a `component.<domain>.`
        # prefix ahead of the same path strings.json uses, regardless of how
        # many integrations were asked for — confirmed against the real
        # loader rather than assumed from its flattening helper alone.
        return f"component.{DOMAIN}.selector.{CONF_MARKET}.options.{code.lower()}"

    language = hass.config.language or "en"
    names = await async_get_translations(hass, language, "selector", integrations=[DOMAIN])
    if not any(_key(code) in names for code in MARKETS):
        names = await async_get_translations(hass, "en", "selector", integrations=[DOMAIN])
    codes = sorted(MARKETS, key=lambda code: names.get(_key(code), code))
    return [code.lower() for code in codes]


def _market_selector(options: list[str]) -> selector.SelectSelector:
    """Return the market dropdown selector for the given (pre-sorted) options.

    Option values are lower-cased for the translation keys HA expects from a
    selector; the stored value stays the upper-case ISO2 used everywhere else
    in this integration.
    """
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            translation_key=CONF_MARKET,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _current_parcels(entry: ConfigEntry) -> list[dict[str, str]]:
    """Return a mutable copy of the tracked parcels list."""
    return [dict(item) for item in entry.options.get(CONF_PARCELS, [])]


class ShopeeXpressConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI-driven configuration flow for the Shopee Xpress integration.

    Shopee Xpress runs one backend per market — a number from one market's
    host does not resolve against another's, and the error envelope cannot
    tell a wrong host from a broken backend, so there is nothing safe to fall
    back to. Setup is therefore a single required market picker; any number
    of hubs are allowed, including more than one for the same market (the
    maintainer does not want that technically enforced — entities are keyed
    on `entry.entry_id`, not the market, so nothing collides).
    """

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> ShopeeXpressOptionsFlowHandler:
        """Return the options flow handler."""
        return ShopeeXpressOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create a Shopee Xpress hub for one market.

        No account and no parcel to look up yet, so — like Dragonfly's
        zero-input setup — the entry is created immediately once the market
        is picked; tracking codes are added afterward via the options flow,
        the `shopee_xpress.track_parcel` service or a dashboard button.
        """
        if user_input is not None:
            market = user_input[CONF_MARKET].upper()
            return self.async_create_entry(
                title=f"Shopee Xpress ({market})",
                data={},
                options={
                    CONF_MARKET: market,
                    CONF_PARCELS: [],
                    CONF_DELIVERED_FILTER_TYPE: DEFAULT_DELIVERED_FILTER_TYPE,
                    CONF_DELIVERED_FILTER_AMOUNT: DEFAULT_DELIVERED_FILTER_AMOUNT,
                    CONF_INCLUDE_HISTORY: DEFAULT_INCLUDE_HISTORY,
                },
            )

        options = await _sorted_market_options(self.hass)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_MARKET): _market_selector(options)}),
        )


class ShopeeXpressOptionsFlowHandler(OptionsFlow):
    """Manage tracked parcels, history and polling in one sectioned form.

    The hub's market is fixed at setup and not editable here — changing it
    would mean every already-tracked code silently starts resolving against a
    different host. Add a second hub for a second market instead.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and handle the single sectioned options form."""
        errors: dict[str, str] = {}
        parcels = _current_parcels(self.config_entry)

        if user_input is not None:
            parcels_section = user_input.get("parcels", {})
            delivered_section = user_input.get("delivered", {})
            history_section = user_input.get("history", {})

            # Remove first, then add — so re-adding a just-removed code works.
            to_remove = set(parcels_section.get("remove", []))
            parcels = [p for p in parcels if p[CONF_TRACKING_CODE] not in to_remove]

            add_code = normalize_tracking_code(parcels_section.get("add") or "")
            if add_code:
                warn_unrecognised_tracking_code(add_code)
                if any(p[CONF_TRACKING_CODE] == add_code for p in parcels):
                    errors["base"] = "already_tracked"
                else:
                    parcels.append({CONF_TRACKING_CODE: add_code})

            if not errors:
                return self.async_create_entry(
                    title="",
                    data={
                        # An options flow's `data` replaces `entry.options`
                        # wholesale rather than merging into it — the market
                        # must be carried forward explicitly or it resets.
                        CONF_MARKET: self.config_entry.options.get(CONF_MARKET),
                        CONF_PARCELS: parcels,
                        CONF_DELIVERED_FILTER_TYPE: delivered_section[
                            CONF_DELIVERED_FILTER_TYPE
                        ],
                        CONF_DELIVERED_FILTER_AMOUNT: int(
                            delivered_section[CONF_DELIVERED_FILTER_AMOUNT]
                        ),
                        CONF_INCLUDE_HISTORY: bool(
                            history_section[CONF_INCLUDE_HISTORY]
                        ),
                    },
                )

        current = self.config_entry.options

        parcels_fields: dict[Any, Any] = {vol.Optional("add", default=""): str}
        if parcels:
            parcels_fields[vol.Optional("remove", default=[])] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=p[CONF_TRACKING_CODE],
                            label=p[CONF_TRACKING_CODE],
                        )
                        for p in parcels
                    ],
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )

        schema = vol.Schema(
            {
                vol.Required("parcels"): section(
                    vol.Schema(parcels_fields), {"collapsed": False}
                ),
                vol.Required("delivered"): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_DELIVERED_FILTER_TYPE,
                                default=current.get(
                                    CONF_DELIVERED_FILTER_TYPE,
                                    DEFAULT_DELIVERED_FILTER_TYPE,
                                ),
                            ): selector.SelectSelector(
                                selector.SelectSelectorConfig(
                                    options=["days", "parcels"],
                                    translation_key=CONF_DELIVERED_FILTER_TYPE,
                                    mode=selector.SelectSelectorMode.LIST,
                                )
                            ),
                            vol.Required(
                                CONF_DELIVERED_FILTER_AMOUNT,
                                default=current.get(
                                    CONF_DELIVERED_FILTER_AMOUNT,
                                    DEFAULT_DELIVERED_FILTER_AMOUNT,
                                ),
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=1, max=365, step=1, mode=selector.NumberSelectorMode.BOX
                                )
                            ),
                        }
                    ),
                    {"collapsed": True},
                ),
                vol.Required("history"): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_INCLUDE_HISTORY,
                                default=current.get(
                                    CONF_INCLUDE_HISTORY, DEFAULT_INCLUDE_HISTORY
                                ),
                            ): selector.BooleanSelector(),
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )

        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors
        )
