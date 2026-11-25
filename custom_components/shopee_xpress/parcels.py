"""Canonical parcel shape, status mapping and list helpers.

Everything in this module is a **pure function** — no I/O, no Home Assistant
objects beyond the config entry's options. That keeps the carrier-specific
mapping apart from the coordinator, and makes it unit-testable without HA.

Two things drive most of what is unusual here, relative to a typical carrier
in this suite:

* Three of the five ``data`` blocks a response can carry are absent on some
  markets — not empty, genuinely missing keys — so every read below is
  ``.get()``-ed, and the canonical minimum (barcode, status, delivered) is
  built only from the one block that is always present.
* Exceptions never show up in ``milestone_code`` — a refused delivery and a
  failed pickup both keep their ordinary happy-path milestone. ``status`` is
  therefore a pure function of ``milestone_code`` alone; the exception is
  still visible through ``raw_status`` and ``raw``. Overriding it there would
  mean triggering ``problem`` off a vocabulary sampled from a single parcel,
  which risks more false positives than it fixes.

The status vocabulary is not fully known — five of an unknown number of
``milestone_code`` values, two reason vocabularies sampled from one parcel.
Every place that matters logs the first unrecognised value once, via
:func:`_warn_once`, rather than guessing or crashing.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta, tzinfo
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    FLEET_MARKETS,
    FLEET_TRACKING_URL,
    HISTORY_MAX_EVENTS,
    KNOWN_DATA_KEYS,
    KNOWN_GROUP_NAMES,
    KNOWN_ISSUE_TYPES,
    KNOWN_MILESTONE_CODES,
    KNOWN_REASON_CODES,
    KNOWN_RECORD_KEYS,
    KNOWN_STANDARD_REASON_CODES,
    KNOWN_SUBGROUP_NAMES,
    KNOWN_TRACKING_CODES,
    MARKETS,
    TRACKING_URL,
    ParcelStatus,
)

_LOGGER = logging.getLogger(__name__)

# Where the coordinator stashes the tracking code a fetch was made for, on the
# raw ``data`` dict before it reaches normalize_parcel(). Leading underscore
# keeps it clearly apart from anything the wire could ever send — every real
# field name in this payload is a plain identifier.
REQUESTED_CODE_KEY = "_requested_tracking_code"

# Where users report a status we do not map yet. Rewritten by the bootstrap
# script; it must point at the carrier's own repo so the log line is
# copy-pasteable straight into a new issue.
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-shopee-xpress/issues/new"
    "?template=unrecognised_status.yml"
)

# The mapping key is milestone_code, a small integer — chosen over any text
# field because language_code is honoured inconsistently (Thai comes back in
# Thai, Malay comes back in English), so a substring test on the description
# fields would be a market-dependent guess. `10` covers the whole return leg,
# in progress and terminal alike; only the finer tracking_code `F999`
# distinguishes "coming back" from "back with the sender", which the
# canonical enum has no slot for.
_STATUS_MAP: dict[int, ParcelStatus] = {
    1: ParcelStatus.REGISTERED,
    5: ParcelStatus.IN_TRANSIT,
    6: ParcelStatus.OUT_FOR_DELIVERY,
    8: ParcelStatus.DELIVERED,
    10: ParcelStatus.RETURNING,
}

# Every surprise this module can log, keyed so the same surprise never logs
# twice in one HA session. One flat set (rather than one per category) keeps
# this simple; keys are namespaced with a category prefix to avoid collisions.
_warned: set[str] = set()


def _warn_once(key: str, message: str, *args: Any) -> None:
    """Log ``message`` once per session, with a copy-paste issue link."""
    if key in _warned:
        return
    _warned.add(key)
    message += "\n  Please report it — open an issue with this line: %s"
    _LOGGER.warning(
        message,
        *args,
        NEW_ISSUE_URL,
    )


def map_parcel_status(record: dict[str, Any] | None) -> ParcelStatus:
    """Map the newest event record to a canonical :class:`ParcelStatus`.

    An empty history (never observed, but not ruled out either) reports
    ``unknown`` silently; an out-of-vocabulary ``milestone_code`` reports
    ``unknown`` with a one-shot warning that carries every field a report
    needs to close the gap in one shot.
    """
    if not record:
        return ParcelStatus.UNKNOWN
    code = record.get("milestone_code")
    if code is None:
        return ParcelStatus.UNKNOWN
    mapped = _STATUS_MAP.get(code)
    if mapped is not None:
        return mapped
    _warn_once(
        f"milestone_code:{code}",
        "Unrecognised Shopee Xpress milestone_code=%r (known: %s). "
        "tracking_code=%r tracking_name=%r milestone_name=%r reason_code=%r "
        "standard_reason_code=%r → reported as 'unknown'.",
        code,
        sorted(KNOWN_MILESTONE_CODES),
        record.get("tracking_code"),
        record.get("tracking_name"),
        record.get("milestone_name"),
        record.get("reason_code"),
        record.get("standard_reason_code"),
    )
    return ParcelStatus.UNKNOWN


# <phase letter><zero-padded issue_type><3-digit reason>, e.g. "D03008". The
# one confirmed exception is the bare "R00" sentinel, checked separately.
_STANDARD_REASON_SHAPE_RE = re.compile(r"^([PTD])(\d{2})(\d{3})$")


def _check_reason_vocabulary(record: dict[str, Any]) -> None:
    """Warn once on any exception-field value outside the sampled vocabulary.

    Sampled from a single Vietnamese parcel — every value outside the known
    sets is real information, not noise, so each one is worth exactly one log
    line rather than being swallowed.
    """
    reason_code = record.get("reason_code")
    if reason_code is not None and reason_code not in KNOWN_REASON_CODES:
        _warn_once(
            f"reason_code:{reason_code}",
            "Unrecognised Shopee Xpress reason_code=%r (known: %s).",
            reason_code,
            sorted(KNOWN_REASON_CODES),
        )

    standard_code = record.get("standard_reason_code")
    if standard_code is not None and standard_code not in KNOWN_STANDARD_REASON_CODES:
        _warn_once(
            f"standard_reason_code:{standard_code}",
            "Unrecognised Shopee Xpress standard_reason_code=%r (known: %s).",
            standard_code,
            sorted(KNOWN_STANDARD_REASON_CODES),
        )

    issue_type = record.get("issue_type")
    if issue_type is not None and issue_type not in KNOWN_ISSUE_TYPES:
        _warn_once(
            f"issue_type:{issue_type}",
            "Unrecognised Shopee Xpress issue_type=%r (known: %s).",
            issue_type,
            sorted(KNOWN_ISSUE_TYPES),
        )

    # Shape/consistency check, independent of the vocabulary check above: even
    # a *known* standard_reason_code is worth flagging if the decomposition
    # that has held 6/6 times so far stops holding.
    if isinstance(standard_code, str) and standard_code != "R00":
        match = _STANDARD_REASON_SHAPE_RE.match(standard_code)
        if match is None:
            _warn_once(
                f"standard_reason_shape:{standard_code}",
                "Shopee Xpress standard_reason_code=%r does not match the "
                "<phase><issue_type><reason> shape or the 'R00' sentinel.",
                standard_code,
            )
        elif issue_type is not None and int(match.group(2)) != issue_type:
            _warn_once(
                f"standard_reason_mismatch:{standard_code}:{issue_type}",
                "Shopee Xpress standard_reason_code=%r does not agree with "
                "issue_type=%r on this record — the decomposition may not "
                "hold any more.",
                standard_code,
                issue_type,
            )


def _check_tracking_code(tracking_code: Any) -> None:
    """Warn once on a tracking_code outside the sampled vocabulary.

    Never used to map ParcelStatus or to key/de-duplicate anything — it has
    grown on nearly every capture (9 -> 19 -> 26 values) and is not unique
    within one parcel's history.
    """
    if isinstance(tracking_code, str) and tracking_code not in KNOWN_TRACKING_CODES:
        _warn_once(
            f"tracking_code:{tracking_code}",
            "Unrecognised Shopee Xpress tracking_code=%r.",
            tracking_code,
        )


def _check_group_names(order_info: dict[str, Any]) -> None:
    """Warn once on a carrier-computed overall-state value we have not seen."""
    if not order_info:
        return
    group = order_info.get("tracking_code_group_name")
    if group is not None and group not in KNOWN_GROUP_NAMES:
        _warn_once(
            f"group_name:{group}",
            "Unrecognised Shopee Xpress tracking_code_group_name=%r (known: %s).",
            group,
            sorted(KNOWN_GROUP_NAMES),
        )
    subgroup = order_info.get("tracking_code_subgroup_name")
    if subgroup is not None and subgroup not in KNOWN_SUBGROUP_NAMES:
        _warn_once(
            f"subgroup_name:{subgroup}",
            "Unrecognised Shopee Xpress tracking_code_subgroup_name=%r (known: %s).",
            subgroup,
            sorted(KNOWN_SUBGROUP_NAMES),
        )


def _check_delivered_cross_check(delivered: bool, order_info: dict[str, Any]) -> None:
    """Log once when the milestone-derived delivered flag disagrees.

    Compared against the carrier's own ``tracking_code_group_name`` — a
    cross-check only, never a precondition: it is absent on some markets and
    its vocabulary is not fully known either.
    """
    if not order_info:
        return
    group = order_info.get("tracking_code_group_name")
    if group is None:
        return
    group_says_delivered = group == "Delivered"
    if group_says_delivered != delivered:
        _warn_once(
            f"delivered_mismatch:{delivered}:{group}",
            "Shopee Xpress milestone-derived delivered=%s disagrees with "
            "tracking_code_group_name=%r.",
            delivered,
            group,
        )


def _describe_shape(value: Any) -> str:
    """Return ``type`` for a leaf, or the sorted key list for a dict.

    No values, so this is always safe to paste into a public issue.
    """
    if isinstance(value, dict):
        return f"object with keys {sorted(value)}"
    if isinstance(value, list):
        return f"list[{len(value)}]"
    return type(value).__name__


def _check_payload_shape(raw: dict[str, Any], newest_record: dict[str, Any]) -> None:
    """Log once per unrecognised top-level or record-level key.

    A key we have never seen is worth more as a map than as a complaint —
    this is what would tell us a market ships a sixth ``data`` block, or a
    record grows a field none of the six captures had.
    """
    unexpected_top = sorted(set(raw) - KNOWN_DATA_KEYS - {REQUESTED_CODE_KEY})
    if unexpected_top:
        _warn_once(
            f"shape:data:{unexpected_top}",
            "Shopee Xpress response carries unrecognised top-level key(s): %s.",
            {key: _describe_shape(raw[key]) for key in unexpected_top},
        )
    unexpected_record = sorted(set(newest_record) - KNOWN_RECORD_KEYS)
    if unexpected_record:
        _warn_once(
            f"shape:record:{unexpected_record}",
            "Shopee Xpress event record carries unrecognised key(s): %s.",
            {key: _describe_shape(newest_record[key]) for key in unexpected_record},
        )


# Plausible epoch-seconds bounds (2000-01-01 .. 2100-01-01). Every capture to
# date resolves to 2025/2026; this is deliberately generous rather than tight.
_MIN_PLAUSIBLE_EPOCH = 946_684_800
_MAX_PLAUSIBLE_EPOCH = 4_102_444_800


def _epoch_seconds_to_iso(value: Any, *, field: str) -> str | None:
    """Return an ISO 8601 string for an epoch-**seconds** field, or ``None``.

    Every timestamp in this payload (``actual_time``, ``edd_min``,
    ``edd_max``) is epoch seconds, confirmed by every capture resolving to a
    real 2025/2026 date — this carrier does not use epoch milliseconds.
    """
    if value is None:
        return None
    if not isinstance(value, (int, float)) or not (
        _MIN_PLAUSIBLE_EPOCH <= value <= _MAX_PLAUSIBLE_EPOCH
    ):
        _warn_once(
            f"timestamp:{field}:{value}",
            "Shopee Xpress %s=%r does not look like a plausible epoch-seconds "
            "timestamp.",
            field,
            value,
        )
        if not isinstance(value, (int, float)):
            return None
    try:
        return datetime.fromtimestamp(value, tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware datetime, or ``None`` on failure."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def resolve_display_number(raw: dict[str, Any]) -> tuple[str | None, bool]:
    """Return the number to show the user, and whether it is the internal one.

    ``order_info.spx_tn`` when present (the "parcel view"); otherwise
    ``sls_tracking_info.sls_tn`` (the "order view", reached by an order id or
    an ``sls_tn`` lookup) — always present, but is SPX's own internal number,
    not the one printed on a shipping label. Surfacing whichever one the
    response actually resolved to is the visibility obligation this carrier's
    lookup needs: the same query parameter also matches merchant-supplied free
    text, so a short or mistyped input can return a stranger's parcel, and
    this is how a mismatch becomes visible without the integration having to
    decide the input was wrong.
    """
    order_info = raw.get("order_info") or {}
    spx_tn = order_info.get("spx_tn") or None
    if spx_tn:
        return spx_tn, False
    sls_tn = (raw.get("sls_tracking_info") or {}).get("sls_tn") or None
    return sls_tn, True


def _describe_status_text(record: dict[str, Any]) -> str | None:
    """Return the carrier's own human-readable status text for one record.

    Preference order: the consumer-facing description, the internal one, the
    milestone's English label, and only as a last resort the bare
    ``tracking_code`` — a fine-grained internal code like ``"F004"`` is not a
    readable status on its own, but it beats returning nothing when a record
    somehow carries none of the three text fields.
    """
    return (
        record.get("buyer_description")
        or record.get("description")
        or record.get("tracking_name")
        or record.get("tracking_code")
        or None
    )


def build_history(
    records: list[Any] | None, *, max_events: int = HISTORY_MAX_EVENTS
) -> list[dict]:
    """Build the canonical ``history`` list from SPX's ``records[]``.

    ``records`` arrives newest-first; the canonical shape is oldest-first, so
    it is reversed here. Filtered to ``display_flag == 1`` — records with
    ``display_flag: 0`` are internal steps with empty description fields, and
    would otherwise show up as blank rows. Never filtered on
    ``display_flag_v2``, whose vocabulary is undocumented. Not de-duplicated
    on ``tracking_code``, which repeats within a single history (a hub can be
    entered twice, a driver can be (re)assigned more than once) — de-duping on
    it would silently delete real legs of the journey. Sorted stably on
    ``actual_time`` so two records that tie to the second keep their original
    (chronological) relative order.

    ``status`` is each record's own canonical :class:`ParcelStatus`, derived
    the same way as the top-level one (from that record's ``milestone_code``,
    via :func:`map_parcel_status`) — not the carrier's free text, which is
    ``raw_status`` instead.
    """
    chronological = list(reversed(records or []))
    entries: list[tuple[datetime, dict]] = []
    for record in chronological:
        if not isinstance(record, dict) or record.get("display_flag") != 1:
            continue
        timestamp = _epoch_seconds_to_iso(
            record.get("actual_time"), field="actual_time"
        )
        if timestamp is None:
            continue
        parsed = parse_iso(timestamp)
        entries.append(
            (
                parsed or datetime.min.replace(tzinfo=UTC),
                {
                    "timestamp": timestamp,
                    "status": map_parcel_status(record),
                    "raw_status": _describe_status_text(record),
                },
            )
        )
    entries.sort(key=lambda item: item[0])
    ordered = [entry for _, entry in entries]
    return ordered[-max_events:]


def _tracking_url(market: str, tracking_code: str | None) -> str | None:
    """Construct the consumer tracking deep-link for a parcel.

    Same host as the API host for ``market``, a different path — see
    :data:`~.const.TRACKING_URL`.
    """
    if not tracking_code:
        return None
    if market in FLEET_MARKETS:
        return FLEET_TRACKING_URL.format(
            host=FLEET_MARKETS[market], tracking_code=tracking_code
        )
    host, _language_code = MARKETS[market]
    return TRACKING_URL.format(host=host, tracking_code=tracking_code)


# The fleet feed's own stage codes. Taiwan's network (SP_*, DOP_*) and the
# hub codes the same feed carries elsewhere (FMHub_*, LMHub_*, SOC_*).
_FLEET_STATUS_MAP: dict[str, ParcelStatus] = {
    "Created": ParcelStatus.REGISTERED,
    "DOP_Received": ParcelStatus.IN_TRANSIT,
    "FMHub_Pickup_Done": ParcelStatus.IN_TRANSIT,
    "FMHub_Received": ParcelStatus.IN_TRANSIT,
    "FMHub_LHTransporting": ParcelStatus.IN_TRANSIT,
    "SP_LHTransporting": ParcelStatus.IN_TRANSIT,
    "SOC_LHUnloading": ParcelStatus.IN_TRANSIT,
    "SOC_LHUnloaded": ParcelStatus.IN_TRANSIT,
    "SOC_Received": ParcelStatus.IN_TRANSIT,
    "SOC_LHTransporting": ParcelStatus.IN_TRANSIT,
    "LMHub_LHUnloading": ParcelStatus.IN_TRANSIT,
    "LMHub_LHUnloaded": ParcelStatus.IN_TRANSIT,
    "LMHub_Received": ParcelStatus.IN_TRANSIT,
    "SP_HD_Received": ParcelStatus.IN_TRANSIT,
    "Delivering": ParcelStatus.OUT_FOR_DELIVERY,
    "SP_Ready_Collection": ParcelStatus.AT_PICKUP_POINT,
    "SP_Collection_Collected": ParcelStatus.DELIVERED,
    "Delivered": ParcelStatus.DELIVERED,
}


def map_fleet_status(code: Any) -> ParcelStatus | None:
    """Map one fleet stage code, warning once for one not in the map."""
    if not code:
        return None
    mapped = _FLEET_STATUS_MAP.get(str(code))
    if mapped is None:
        _warn_once(
            f"fleet_status:{code}",
            "Unrecognised Shopee Xpress fleet status=%r, reported as the newest "
            "status we do recognise.",
            code,
        )
    return mapped


def _fleet_events(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the feed's scans oldest-first, dropping exact repeats."""
    events: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for event in raw.get("tracking_list") or []:
        if not isinstance(event, dict):
            continue
        key = (event.get("timestamp"), event.get("status"))
        if key in seen:
            continue
        seen.add(key)
        events.append(event)
    events.sort(key=_fleet_sort_key)
    return events


def _fleet_sort_key(event: dict[str, Any]) -> float:
    value = event.get("timestamp")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _moment(value: Any, zone: tzinfo) -> tuple[datetime, bool, str] | None:
    """Return ``(aware datetime, date_only, text)`` for a carrier time, or ``None``.

    A naive time or a bare date gets ``zone``; an aware time keeps its offset
    and, when it came in as a string, its own spelling.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        moment = datetime.combine(value, time.min, tzinfo=zone)
        return moment, True, moment.isoformat()
    elif isinstance(value, str) and value:
        try:
            if len(value) == 10:
                moment = datetime.combine(
                    date.fromisoformat(value), time.min, tzinfo=zone
                )
                return moment, True, moment.isoformat()
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo:
            return parsed, False, value
    else:
        return None
    moment = parsed if parsed.tzinfo else parsed.replace(tzinfo=zone)
    return moment, False, moment.isoformat()


def _end_of_day(moment: datetime, zone: tzinfo) -> datetime:
    local = moment.astimezone(zone)
    return datetime.combine(local.date(), time(23, 59, 59), tzinfo=zone)


# Single-zone markets only; Indonesia and Brazil span several zones and use
# Home Assistant's zone, like an unknown market.
_MARKET_ZONES = {
    "MY": "Asia/Kuala_Lumpur",
    "PH": "Asia/Manila",
    "TH": "Asia/Bangkok",
    "VN": "Asia/Ho_Chi_Minh",
    "SG": "Asia/Singapore",
    "TW": "Asia/Taipei",
}


def _market_zone(market: str) -> tzinfo:
    name = _MARKET_ZONES.get(market)
    return ZoneInfo(name) if name else dt_util.get_default_time_zone()


def planned_window(
    start: Any, end: Any, *, zone: tzinfo
) -> tuple[str | None, str | None]:
    """Return ``(planned_from, planned_to)`` in the canonical window shape.

    ``start`` and ``end`` are ISO strings, dates or datetimes, or ``None``; an
    epoch number must be converted first (see ``to_iso_timestamp``). A window
    keeps both ends. One moment with a time ends at ``23:59:59`` the same local
    day; a date covers ``00:00:00`` to ``23:59:59``; two dates run from the
    first day's start to the last day's end. Equal values are one moment,
    reversed values are swapped, and ``planned_to`` is never set without
    ``planned_from``. ``zone`` is the carrier's own zone: it dates naive times
    and bare dates and decides which day a moment ends on, so a ``Z`` moment
    still ends on the carrier's local day. When nothing is left of that day
    after the moment, there is no ``planned_to``.
    """
    first = _moment(start, zone)
    last = _moment(end, zone)
    if first is None:
        first, last = last, None
    if first is None:
        return None, None

    def closing(moment: tuple[datetime, bool, str]) -> datetime:
        return _end_of_day(moment[0], zone) if moment[1] else moment[0]

    if last is not None and closing(last) < first[0]:
        first, last = last, first
    if last is not None and closing(last) == first[0]:
        last = None

    if last is None:
        end_of_day = _end_of_day(first[0], zone)
        return first[2], end_of_day.isoformat() if end_of_day > first[0] else None
    return first[2], closing(last).isoformat() if last[1] else last[2]


_NO_WINDOW_STATUSES = frozenset(
    {ParcelStatus.AT_PICKUP_POINT, ParcelStatus.RETURNING, ParcelStatus.DELIVERED}
)


def planned_for_status(
    status: ParcelStatus, planned_from: str | None, planned_to: str | None
) -> tuple[str | None, str | None]:
    """Empty the delivery window once the parcel is at its destination or done."""
    if status in _NO_WINDOW_STATUSES:
        return None, None
    return planned_from, planned_to


def is_pickup(
    route_flag: bool | None,
    status: ParcelStatus,
    event_statuses: Iterable[ParcelStatus | None] = (),
) -> bool:
    """Whether the delivery route ends at a pickup point.

    The carrier's own route flag wins; otherwise the parcel having reached
    ``AT_PICKUP_POINT`` at any point counts, so the value survives collection.
    """
    if route_flag:
        return True
    return status is ParcelStatus.AT_PICKUP_POINT or any(
        event is ParcelStatus.AT_PICKUP_POINT for event in event_statuses
    )


def _normalize_fleet_parcel(
    raw: dict[str, Any], *, market: str, include_history: bool
) -> dict:
    """Normalise a fleet-feed reply (``data``, or ``{}`` when it holds nothing)."""
    requested_code = raw.get(REQUESTED_CODE_KEY)
    events = _fleet_events(raw)
    statuses = [map_fleet_status(event.get("status")) for event in events]

    status = ParcelStatus.UNKNOWN
    status_event: dict[str, Any] = {}
    current = map_fleet_status(raw.get("current_status"))
    if current is not None:
        status = current
        status_event = next(
            (
                e
                for e in reversed(events)
                if e.get("status") == raw.get("current_status")
            ),
            events[-1] if events else {},
        )
    else:
        for event, mapped in zip(reversed(events), reversed(statuses), strict=True):
            if mapped is not None:
                status, status_event = mapped, event
                break
    newest = events[-1] if events else {}
    delivered = status is ParcelStatus.DELIVERED

    history = [
        {
            "timestamp": _epoch_seconds_to_iso(
                event.get("timestamp"), field="timestamp"
            ),
            "status": mapped,
            "raw_status": event.get("message") or event.get("status"),
        }
        for event, mapped in zip(events, statuses, strict=True)
    ][-HISTORY_MAX_EVENTS:]

    # The fleet feed carries no delivery estimate.
    planned_from = planned_to = None

    barcode = raw.get("sls_tracking_number") or requested_code
    data = {key: value for key, value in raw.items() if key != REQUESTED_CODE_KEY}
    return {
        "carrier": "Shopee Xpress",
        "barcode": barcode,
        "sender": None,
        "receiver": raw.get("recipient_name") or None,
        "contents": None,
        "status": status,
        "raw_status": newest.get("message") or raw.get("current_status") or None,
        "delivered": delivered,
        "delivered_at": (
            _epoch_seconds_to_iso(status_event.get("timestamp"), field="timestamp")
            if delivered
            else None
        ),
        "planned_from": planned_from,
        "planned_to": planned_to,
        "pickup": is_pickup(None, status, statuses),
        "pickup_point": None,
        "url": _tracking_url(market, barcode),
        "weight": None,
        "dimensions": None,
        "history": history if include_history else None,
        "raw": {**data, "market": market},
    }


def normalize_parcel(
    raw: dict[str, Any], *, market: str, include_history: bool = False
) -> dict:
    """Return a carrier-agnostic parcel dict with the full payload under ``raw``.

    ``raw`` is the API response's ``data`` object, with
    :data:`REQUESTED_CODE_KEY` set by the coordinator to the tracking code the
    fetch was made for. Only ``sls_tracking_info`` is present in every market;
    every other block is read with ``.get()`` and a default, in every market,
    regardless of which one this hub is bound to — the block set does not
    split cleanly along market lines (it depends on which identifier
    namespace the lookup resolved against instead). ``base_info`` and the top-level
    ``has_epod`` boolean are the newest members of that optional set — first
    seen in production, never in the six original captures, so both are
    carried through unbranched rather than assigned any inferred meaning.
    """
    if market in FLEET_MARKETS:
        return _normalize_fleet_parcel(
            raw, market=market, include_history=include_history
        )
    order_info = raw.get("order_info") or {}
    sls_tracking_info = raw.get("sls_tracking_info") or {}
    edd_info = raw.get("edd_info") or {}
    requested_code = raw.get(REQUESTED_CODE_KEY)

    records = sls_tracking_info.get("records") or []
    newest = records[0] if records and isinstance(records[0], dict) else {}
    for record in records:
        if isinstance(record, dict):
            _check_reason_vocabulary(record)
            _check_tracking_code(record.get("tracking_code"))

    _check_payload_shape(raw, newest)
    _check_group_names(order_info)

    status = map_parcel_status(newest)
    delivered = status is ParcelStatus.DELIVERED
    _check_delivered_cross_check(delivered, order_info)

    spx_tn = order_info.get("spx_tn") or None
    barcode = spx_tn or requested_code
    resolved_number, resolved_is_internal = resolve_display_number(raw)

    planned_from, planned_to = planned_for_status(
        status,
        *planned_window(
            _epoch_seconds_to_iso(edd_info.get("edd_min"), field="edd_min"),
            _epoch_seconds_to_iso(edd_info.get("edd_max"), field="edd_max"),
            zone=_market_zone(market),
        ),
    )
    pickup = is_pickup(
        None,
        status,
        (map_parcel_status(record) for record in records if isinstance(record, dict)),
    )

    receiver = sls_tracking_info.get("receiver_name") or None

    return {
        "carrier": "Shopee Xpress",
        "barcode": barcode,
        "sender": None,
        "receiver": receiver,
        "contents": None,
        "status": status,
        "raw_status": _describe_status_text(newest),
        "delivered": delivered,
        "delivered_at": (
            _epoch_seconds_to_iso(newest.get("actual_time"), field="actual_time")
            if delivered
            else None
        ),
        "planned_from": planned_from,
        "planned_to": planned_to,
        "pickup": pickup,
        "pickup_point": None,
        "url": _tracking_url(market, barcode),
        "weight": None,
        "dimensions": None,
        "history": build_history(records) if include_history else None,
        "raw": {
            **{k: v for k, v in raw.items() if k != REQUESTED_CODE_KEY},
            "resolved_number": resolved_number,
            "resolved_number_is_internal": resolved_is_internal,
            "market": market,
        },
    }


def sort_parcels_by_ts(
    parcels: list[dict], key_field: str, *, descending: bool = False
) -> list[dict]:
    """Return normalised parcels sorted by the ISO timestamp at ``key_field``.

    The suite's sort contract: incoming/outgoing ascending on ``planned_from``,
    delivered descending on ``delivered_at``. Parcels whose value is missing or
    unparseable always sort to the end, regardless of ``descending``.
    """
    with_ts: list[tuple[datetime, dict]] = []
    without_ts: list[dict] = []
    for parcel in parcels:
        parsed = parse_iso(parcel.get(key_field))
        if parsed is None:
            without_ts.append(parcel)
        else:
            with_ts.append((parsed, parcel))
    with_ts.sort(key=lambda item: item[0], reverse=descending)
    return [parcel for _, parcel in with_ts] + without_ts


def apply_delivered_filter(parcels: list[dict], entry: ConfigEntry) -> list[dict]:
    """Trim the delivered list per the entry's retention option.

    ``parcels`` must already be sorted newest-first. ``days`` keeps deliveries
    from the last N days (an unparseable ``delivered_at`` is kept rather than
    silently dropped); the ``parcels`` type keeps the N most recent. Parcels
    stay *tracked* either way — this only controls what the delivered sensor
    shows.
    """
    options = entry.options
    filter_type = options.get(CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE)
    amount = int(
        options.get(CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT)
    )
    if filter_type == "days":
        cutoff = datetime.now(UTC) - timedelta(days=amount)
        return [
            parcel
            for parcel in parcels
            if (parsed := parse_iso(parcel.get("delivered_at"))) is None
            or parsed >= cutoff
        ]
    return parcels[:amount]
