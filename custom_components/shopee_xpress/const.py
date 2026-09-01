"""Constants for the Shopee Xpress parcel tracker integration."""
from enum import StrEnum

from homeassistant.const import Platform

DOMAIN = "shopee_xpress"


class ParcelStatus(StrEnum):
    """Carrier-agnostic parcel status.

    **Do not extend or rename these members.** Every integration in the parcel
    suite publishes exactly this vocabulary on the ``status`` field of each
    normalised parcel, so cross-carrier automations and the aggregator can
    target ``status: out_for_delivery`` regardless of carrier. Listed in
    roughly the order a parcel moves through.
    """

    REGISTERED = "registered"               # Sender announced the parcel; not handed over yet
    IN_TRANSIT = "in_transit"               # In the carrier's network
    OUT_FOR_DELIVERY = "out_for_delivery"   # On a delivery vehicle today
    AT_PICKUP_POINT = "at_pickup_point"     # Ready to collect at a pickup location
    DELIVERED = "delivered"                 # Handed over
    RETURNING = "returning"                 # Failed delivery, going back to sender
    PROBLEM = "problem"                     # Carrier reports an exception/issue
    UNKNOWN = "unknown"                     # Raw status we have not mapped yet


PLATFORMS = [Platform.BUTTON, Platform.CALENDAR, Platform.SENSOR]

# Every optional key the parcel contract defines. CAPABILITIES below must be a
# subset of this — it exists so a typo in CAPABILITIES fails a test instead of
# silently dropping a carrier off a table on the docs site.
KNOWN_CAPABILITIES = frozenset(
    {"weight", "dimensions", "delivery_window", "pickup_point", "url", "history"}
)

# What Shopee Xpress actually populates. weight/dimensions/pickup_point are
# never present in any market's payload (confirmed across six markets) — do not
# add them back without a capture that shows otherwise. delivery_window is
# populated in three of six markets and absent (never `None`-vs-error, just
# structurally missing) in the other three, but "populated in some markets" is
# what CAPABILITIES tracks. history is always buildable from the event list.
# url is never in the payload either, but — unlike those — is constructed
# rather than read: see TRACKING_URL below.
CAPABILITIES = frozenset({"delivery_window", "history", "url"})

# One JSON GET, no auth, keyed on a query parameter that resolves against
# several identifier namespaces at once (see MARKETS and the tracking-code
# validation in config_flow.py). {host}/{language_code} come from MARKETS.
TRACKING_API_URL = (
    "https://{host}/shipment/order/open/order/get_order_info"
    "?spx_tn={tracking_code}&language_code={language_code}"
)

# Consumer tracking deep-link, used to populate the parcel's ``url`` field.
# Same host as the API, a different, client-rendered path — the maintainer
# confirmed the pattern from their own device across all six markets. The
# page is a SPA that serves an identical shell for any path (confirmed by
# probe: a bogus code and a nonexistent path both 200 with the same HTML), so
# unlike the API this cannot be control-tested for content from the backend
# side — only that the domain serves the app at this path.
TRACKING_URL = "https://{host}/track?{tracking_code}"

# The hub's chosen market. One config entry = one market: the lookup only
# resolves against the host it was made to, and the failure mode when it
# doesn't is indistinguishable from a broken backend — so a wrong guess can't
# be recovered from inside the integration, only prevented by asking upfront.
CONF_MARKET = "market"

# ISO2 -> (host, language_code). Every entry here has answered with a real,
# complete parcel. The host suffix is not a template: three different shapes
# (`.com.<cc>`, `.co.<cc>`, a bare `.<cc>`) are already in use below, so a
# market is only added once its own host has been observed — never guessed
# from the pattern the others happen to follow. `language_code` is likewise a
# free-form per-market string, not an ISO code (Brazil's is a country code,
# Indonesia's and Vietnam's are both the same bare `en`), so it lives in the
# same table rather than being derived.
MARKETS: dict[str, tuple[str, str]] = {
    "BR": ("spx.com.br", "br"),
    "ID": ("spx.co.id", "en"),
    "MY": ("spx.com.my", "ms"),
    "PH": ("spx.ph", "en-ph"),
    "TH": ("spx.co.th", "th"),
    "VN": ("spx.vn", "en"),
}

# Every response's data block set differs by market *and* by which identifier
# the request used, and only these two survive in all of them.
ALWAYS_PRESENT_BLOCKS = frozenset({"sls_tracking_info"})
# Every other top-level block normalize_parcel treats as optional. `base_info`
# joined this set after a one-shot _check_payload_shape() warning surfaced it
# in production, never seen in any of the six original captures — meaning
# still unknown for its two keys (order_type, product_id), same "carry it in
# raw, do not branch on it" treatment already applied to order_max_update_limit.
OPTIONAL_DATA_BLOCKS = frozenset(
    {"order_info", "parcel_info", "edd_info", "fulfillment_info", "base_info"}
)
# The full top-level key set ever observed, used to log a response whose
# shape has drifted rather than silently reading None everywhere. `has_epod`
# joined this set alongside base_info — a boolean sibling of is_instant_order
# / is_shopee_market_order, and plausibly "does any record carry a populated
# epod" (every record's own epod has been "" in all six captures). Unlike the
# missing-block case that was removed outright (_check_missing_blocks — a
# functional non-gap, every read already defensive), these are keys arriving
# for the *first* time, so they're mapped into raw below rather than silently
# widened into this set with no user-facing change.
KNOWN_DATA_KEYS = ALWAYS_PRESENT_BLOCKS | OPTIONAL_DATA_BLOCKS | frozenset(
    {"is_instant_order", "is_shopee_market_order", "has_epod"}
)
KNOWN_RECORD_KEYS = frozenset(
    {
        "tracking_code",
        "tracking_name",
        "description",
        "buyer_description",
        "seller_description",
        "display_flag",
        "display_flag_v2",
        "actual_time",
        "reason_code",
        "reason_desc",
        "issue_type",
        "standard_reason_code",
        "standard_reason_description",
        "epod",
        "delivery_on_hold_times",
        "milestone_code",
        "milestone_name",
        "current_location",
        "next_location",
        "driver_infos",
    }
)

# The `milestone_code` vocabulary mapped so far — five values out of an
# unknown-size set with gaps at 2/3/4/7/9 and no known ceiling. Kept here
# (rather than only as _STATUS_MAP's keys in parcels.py) so the one-shot
# warning can state the known set without re-deriving it.
KNOWN_MILESTONE_CODES = frozenset({1, 5, 6, 8, 10})

# The fine-grained tracking_code vocabulary observed so far. It has grown on
# almost every new capture (9 -> 19 -> 26), so treat it as a sample: log the
# first unrecognised value, never reject it, never map ParcelStatus from it.
KNOWN_TRACKING_CODES = frozenset(
    {
        "A000", "F000", "F004", "F050", "F098", "F100", "F430", "F440", "F441",
        "F445", "F450", "F510", "F515", "F540", "F541", "F580", "F598", "F599",
        "F600", "F650", "F671", "F673", "F677", "F680", "F980", "F999",
    }
)

# Sentinel values mean "no exception"; everything else is real and sampled
# from a single Vietnamese parcel — the whole set is expected to grow.
KNOWN_REASON_CODES = frozenset({"R00", "", "R102", "R105", "R172"})
KNOWN_STANDARD_REASON_CODES = frozenset(
    {"R00", "P99000", "T99000", "D99000", "P02000", "P03002", "D03008"}
)
KNOWN_ISSUE_TYPES = frozenset({2, 3, 99})

# The carrier-computed overall-state field. A cross-check only, never a status
# source — it does not exist at all on the Brazilian shape.
KNOWN_GROUP_NAMES = frozenset({"Delivered", "Pending Pickup", "Return"})
KNOWN_SUBGROUP_NAMES = frozenset({"Delivered", "Pending Pickup", "Returned"})

# Tracked parcels live in the config entry options as a list of
# ``{tracking_code}`` dicts — this carrier has no account or parcel feed, so the
# user enters the codes themselves. Kept as dicts so future per-parcel fields
# slot in without an options migration.
CONF_PARCELS = "parcels"
CONF_TRACKING_CODE = "tracking_code"

# Delivered-parcels retention: keep delivered parcels visible for the last N
# days, or keep only the N most recent — identical across the suite.
CONF_DELIVERED_FILTER_TYPE = "delivered_filter_type"
CONF_DELIVERED_FILTER_AMOUNT = "delivered_filter_amount"
DEFAULT_DELIVERED_FILTER_TYPE = "days"
DEFAULT_DELIVERED_FILTER_AMOUNT = 7

# Dynamic, status-driven polling — unconditional, no user-facing interval
# option. See carrier-research/dynamic-polling.md for the full algorithm and
# the reasoning behind it.
#
# Quiet window: no polling between these local hours except the two anchors
# below, for overnight / end-of-day catch-up.
QUIET_WINDOW_START_HOUR = 0
QUIET_WINDOW_END_HOUR = 6

# Cadence while polling is active (minutes). Hot = at least one tracked,
# not-yet-delivered parcel is out_for_delivery within HOT_LOOKAHEAD_HOURS of
# its planned_from (or has no planned_from at all); mid = anything else still
# in flight. This is a barcode-based coordinator (Section 2.1): when every
# tracked parcel is delivered, or nothing is tracked, polling stops entirely
# instead of falling to the mid tier — see coordinator.py's
# ``_hottest_tier_minutes``.
HOT_INTERVAL_MINUTES = 15
MID_INTERVAL_MINUTES = 45
HOT_LOOKAHEAD_HOURS = 1

# Small, stable per-install offset added to every computed interval so
# different installs don't all hit an anchor or tier boundary at the same
# second. Deterministic (hash of the config entry id), not random.
STAGGER_MINUTES = 7

# Per-parcel status history is opt-in and off by default, identical across the
# suite. Kept off by default even though the timeline arrives in the same
# response and costs no extra request: it is a large attribute.
CONF_INCLUDE_HISTORY = "include_history"
DEFAULT_INCLUDE_HISTORY = False

# Cap each parcel's history to the most recent N events so the attribute stays
# well under HA's ~16 KB state-attribute limit.
HISTORY_MAX_EVENTS = 20
