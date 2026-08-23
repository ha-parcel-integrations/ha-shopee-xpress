"""Tests for the pure parcel-mapping helpers.

These need no Home Assistant instance — the whole point of keeping
``parcels.py`` free of I/O is that the carrier-specific mapping can be tested
as plain functions. Fixtures come from ``payloads.py``, itself a faithful
(redacted) reproduction of the six real captures documented in
``carrier-research/api/shopee-xpress/tracking.md``.
"""
import logging
from datetime import datetime, timedelta, timezone

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shopee_xpress import parcels as parcels_module
from custom_components.shopee_xpress.const import (
    CAPABILITIES,
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DOMAIN,
    HISTORY_MAX_EVENTS,
    KNOWN_CAPABILITIES,
    ParcelStatus,
)
from custom_components.shopee_xpress.parcels import (
    REQUESTED_CODE_KEY,
    _describe_status_text,
    _epoch_seconds_to_iso,
    _tracking_url,
    apply_delivered_filter,
    build_history,
    map_parcel_status,
    normalize_parcel,
    parse_iso,
    resolve_display_number,
    sort_parcels_by_ts,
)

from .payloads import (
    BR_CODE,
    ID_CODE,
    MY_CODE,
    PH_CODE,
    TH_CODE,
    VN_CODE,
    br_data,
    id_data,
    my_data,
    ph_data,
    record,
    th_data,
    vn_data,
)


@pytest.fixture(autouse=True)
def _reset_one_shot_warnings():
    """Every ``_warn_once`` category is a module-level, session-lived set —
    clear it before each test so tests don't depend on execution order."""
    parcels_module._warned.clear()
    yield
    parcels_module._warned.clear()


def _stamped(raw: dict, code: str) -> dict:
    """Return ``raw`` with the coordinator's requested-code stamp applied."""
    return {**raw, REQUESTED_CODE_KEY: code}


# ---------------------------------------------------------------------------
# map_parcel_status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,expected",
    [
        (1, ParcelStatus.REGISTERED),
        (5, ParcelStatus.IN_TRANSIT),
        (6, ParcelStatus.OUT_FOR_DELIVERY),
        (8, ParcelStatus.DELIVERED),
        (10, ParcelStatus.RETURNING),
    ],
)
def test_map_parcel_status_known(code, expected):
    assert map_parcel_status({"milestone_code": code}) == expected


def test_map_parcel_status_missing_record_is_unknown():
    assert map_parcel_status(None) == ParcelStatus.UNKNOWN
    assert map_parcel_status({}) == ParcelStatus.UNKNOWN


def test_map_parcel_status_missing_milestone_code_is_unknown():
    assert map_parcel_status({"tracking_code": "F000"}) == ParcelStatus.UNKNOWN


def test_map_parcel_status_never_produces_problem():
    """Exceptions are not derivable from milestone_code — Option A (§2)."""
    for code in (1, 5, 6, 8, 10):
        assert map_parcel_status({"milestone_code": code}) != ParcelStatus.PROBLEM


def test_unmapped_milestone_code_warns_once_with_context(caplog):
    """Gaps in the known enum ({2,3,4,7,9,...}) report `unknown` plus a
    one-shot warning carrying every field a report needs in one shot."""
    caplog.set_level(logging.WARNING)
    rec = {
        "milestone_code": 7,
        "tracking_code": "F999999",
        "tracking_name": "Mystery",
        "milestone_name": "???",
        "reason_code": "R00",
        "standard_reason_code": None,
    }
    assert map_parcel_status(rec) == ParcelStatus.UNKNOWN
    assert map_parcel_status(rec) == ParcelStatus.UNKNOWN
    assert caplog.text.count("milestone_code=7") == 1
    assert "F999999" in caplog.text
    assert "issues/new" in caplog.text


def test_unmapped_milestone_code_9_also_warns(caplog):
    caplog.set_level(logging.WARNING)
    assert map_parcel_status({"milestone_code": 9}) == ParcelStatus.UNKNOWN
    assert "milestone_code=9" in caplog.text


# ---------------------------------------------------------------------------
# timestamp helpers
# ---------------------------------------------------------------------------


def test_parse_iso_handles_z_naive_and_garbage():
    assert parse_iso("2026-04-29T13:12:42+00:00").tzinfo is not None
    assert parse_iso("2026-04-29T13:12:42").tzinfo == timezone.utc
    assert parse_iso("not-a-date") is None
    assert parse_iso(None) is None


def test_epoch_seconds_to_iso_converts_real_dates():
    # 1770278488 is the Malaysian delivery timestamp — resolves to Feb 2026.
    assert _epoch_seconds_to_iso(1770278488, field="actual_time") == (
        "2026-02-05T08:01:28+00:00"
    )


def test_epoch_seconds_to_iso_none_passthrough():
    assert _epoch_seconds_to_iso(None, field="actual_time") is None


def test_epoch_seconds_to_iso_warns_once_on_implausible_value(caplog):
    caplog.set_level(logging.WARNING)
    assert _epoch_seconds_to_iso(10**20, field="edd_min") is None
    assert _epoch_seconds_to_iso(10**20, field="edd_min") is None
    assert caplog.text.count("edd_min") == 1
    assert "plausible epoch" in caplog.text


def test_epoch_seconds_to_iso_warns_on_non_numeric_value(caplog):
    caplog.set_level(logging.WARNING)
    assert _epoch_seconds_to_iso("not-a-number", field="actual_time") is None
    assert "plausible epoch" in caplog.text


# ---------------------------------------------------------------------------
# _tracking_url
# ---------------------------------------------------------------------------


def test_tracking_url_builds_per_market_deep_link():
    assert _tracking_url("VN", "SPXVN00000000000C") == "https://spx.vn/track?SPXVN00000000000C"


def test_tracking_url_none_without_a_tracking_code():
    assert _tracking_url("MY", None) is None


# ---------------------------------------------------------------------------
# resolve_display_number / _describe_status_text
# ---------------------------------------------------------------------------


def test_resolve_display_number_prefers_spx_tn_parcel_view():
    number, internal = resolve_display_number(my_data())
    assert number == MY_CODE
    assert internal is False


def test_resolve_display_number_falls_back_to_sls_tn_order_view():
    """No order_info at all (the Brazilian shape) — sls_tn, labelled internal."""
    number, internal = resolve_display_number(br_data())
    assert number == BR_CODE  # this capture's sls_tn == the requested value
    assert internal is True


def test_resolve_display_number_nothing_available():
    assert resolve_display_number({}) == (None, True)


def test_describe_status_text_prefers_buyer_description():
    rec = record("F980", "Delivered", 8, "Delivered", 1, description="internal",
                 buyer_description="consumer facing")
    assert _describe_status_text(rec) == "consumer facing"


def test_describe_status_text_falls_back_to_tracking_name():
    rec = {"tracking_code": "F004", "tracking_name": "Courier assigned",
           "description": "", "buyer_description": ""}
    assert _describe_status_text(rec) == "Courier assigned"


def test_describe_status_text_last_resort_is_tracking_code():
    rec = {"tracking_code": "F004", "tracking_name": "", "description": ""}
    assert _describe_status_text(rec) == "F004"


def test_describe_status_text_all_empty_is_none():
    assert _describe_status_text({}) is None


# ---------------------------------------------------------------------------
# build_history — the traps
# ---------------------------------------------------------------------------


def test_build_history_reverses_newest_first_to_oldest_first():
    raw = my_data()
    history = build_history(raw["sls_tracking_info"]["records"])
    assert parse_iso(history[0]["timestamp"]) < parse_iso(history[-1]["timestamp"])
    # F000 (Manifested, milestone 1) is the real oldest event.
    assert history[0]["status"] == ParcelStatus.REGISTERED
    assert history[-1]["status"] == ParcelStatus.DELIVERED


def test_build_history_filters_on_display_flag_not_v2():
    """display_flag_v2 must never gate history — only display_flag does."""
    shown = record("F600", "Out For Delivery", 6, "x", 100, display_flag=1, display_flag_v2=0)
    hidden = record("F441", "Loaded", 5, "x", 200, display_flag=0, display_flag_v2=13)
    history = build_history([hidden, shown])
    assert len(history) == 1
    assert history[0]["raw_status"] == "F600" or history[0]["status"] == ParcelStatus.OUT_FOR_DELIVERY


def test_build_history_status_is_canonical_and_raw_status_is_carrier_text():
    """The bug this suite was rewritten to fix: status/raw_status were swapped."""
    raw = my_data()
    history = build_history(raw["sls_tracking_info"]["records"])
    for entry in history:
        assert isinstance(entry["status"], ParcelStatus)
        if entry["raw_status"] is not None:
            assert not isinstance(entry["raw_status"], ParcelStatus)
            assert isinstance(entry["raw_status"], str)
    delivered_entry = history[-1]
    assert delivered_entry["status"] == ParcelStatus.DELIVERED
    assert delivered_entry["raw_status"] == "Your parcel has been delivered"


def test_build_history_does_not_deduplicate_repeated_tracking_codes_br():
    """F004 repeats three times in the raw records (all display_flag: 0, an
    internal-only event filtered from the display list by design — same
    treatment as any other internal step). F540 repeats twice with
    display_flag: 1 and *does* survive into `history`, undeduplicated —
    that is where "not de-duplicated on tracking_code" is actually
    observable in the filtered output.
    """
    raw = br_data()
    records = raw["sls_tracking_info"]["records"]
    assert sum(1 for r in records if r["tracking_code"] == "F004") == 3

    history = build_history(records)
    left_sorting_center = [e for e in history if e["raw_status"] == "Left Domestic Sorting Center"]
    assert len(left_sorting_center) == 2
    assert len({e["timestamp"] for e in left_sorting_center}) == 2


def test_build_history_keeps_both_philippine_sorting_centre_legs():
    raw = ph_data()
    records = raw["sls_tracking_info"]["records"]
    history = build_history(records)
    line_haul_end = [e for e in history if e["raw_status"] == "Domestic Line Haul End"]
    assert len(line_haul_end) == 2
    assert len({e["timestamp"] for e in line_haul_end}) == 2
    first_mile_hub = [e for e in history if e["raw_status"] == "Enter Domestic First Mile Hub"]
    assert len(first_mile_hub) == 2


def test_build_history_caps_at_20_and_drops_the_oldest_vietnamese_event():
    """21 of VN's 26 records survive the display_flag filter — one more than
    the cap, so the true oldest (`F000 Manifested`) is dropped by design."""
    raw = vn_data()
    records = raw["sls_tracking_info"]["records"]
    filtered = [r for r in records if r.get("display_flag") == 1]
    assert len(filtered) == 21

    history = build_history(records)
    assert len(history) == HISTORY_MAX_EVENTS == 20
    # The dropped event is the oldest (Manifested); the new oldest is the
    # second pickup-reschedule attempt.
    assert history[0]["raw_status"] == (
        "Pickup attempt was unsuccessful :Sender Request Reschedule Pickup"
    )
    assert "Sender is preparing to ship your parcel" not in [
        e["raw_status"] for e in history
    ]


def test_build_history_stable_sort_keeps_ties_in_original_order():
    tied_a = record("F599", "Enter Last Mile Hub", 5, "In transit", 1770000000, description="first")
    tied_b = record("F599", "Enter Last Mile Hub", 5, "In transit", 1770000000, description="second")
    # newest-first input: b then a, tied on actual_time. Reversing to
    # chronological order puts a before b, and the stable sort must keep it
    # that way rather than reordering same-second entries arbitrarily.
    history = build_history([tied_b, tied_a])
    assert [e["raw_status"] for e in history] == ["first", "second"]


def test_build_history_handles_missing_and_malformed():
    assert build_history(None) == []
    assert build_history([{"tracking_code": "F000", "display_flag": 1}]) == []  # no timestamp
    assert build_history(["not-a-dict"]) == []
    assert build_history([{"display_flag": 0, "actual_time": 1}]) == []  # internal only


def test_build_history_caps_to_max_events_param():
    records = [
        record("F599", "x", 5, "In transit", 1770000000 + day, display_flag=1)
        for day in range(25)
    ]
    assert len(build_history(records, max_events=20)) == 20


# ---------------------------------------------------------------------------
# normalize_parcel — the canonical contract
# ---------------------------------------------------------------------------

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
    "status",
    "raw_status",
    "delivered",
    "delivered_at",
    "planned_from",
    "planned_to",
    "pickup",
    "pickup_point",
    "url",
    "weight",
    "dimensions",
    "history",
    "raw",
]


def test_normalize_publishes_exactly_the_canonical_keys():
    """The aggregator and cross-carrier dashboards depend on this key set."""
    parcel = normalize_parcel(_stamped(my_data(), MY_CODE), market="MY")
    assert list(parcel) == CANONICAL_KEYS


def test_capabilities_are_known_values():
    assert CAPABILITIES <= KNOWN_CAPABILITIES


def test_capabilities_match_what_normalize_parcel_actually_returns():
    delivered = normalize_parcel(_stamped(my_data(), MY_CODE), market="MY", include_history=True)
    if "weight" in CAPABILITIES:
        assert delivered["weight"] is not None
    if "dimensions" in CAPABILITIES:
        assert delivered["dimensions"] is not None
    if "delivery_window" in CAPABILITIES:
        # MY is delivered so its own window is suppressed — check a live one.
        active = normalize_parcel(_stamped(id_data(), ID_CODE), market="ID")
        # ID has no edd_info at all; use a market that legitimately carries one.
        th_active = th_data()
        th_active["sls_tracking_info"]["records"][0]["milestone_code"] = 6
        active = normalize_parcel(_stamped(th_active, TH_CODE), market="TH")
        assert active["planned_from"] is not None or active["planned_to"] is not None
    if "pickup_point" in CAPABILITIES:
        assert delivered["pickup_point"] is not None
    if "url" in CAPABILITIES:
        assert delivered["url"] is not None
    if "history" in CAPABILITIES:
        assert delivered["history"] is not None


# --- Malaysia: the reference "everything present" shape --------------------


def test_normalize_malaysia_delivered():
    parcel = normalize_parcel(_stamped(my_data(), MY_CODE), market="MY", include_history=True)
    assert parcel["carrier"] == "Shopee Xpress"
    assert parcel["barcode"] == MY_CODE
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["raw_status"] == "Your parcel has been delivered"
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] == "2026-02-05T08:01:28+00:00"
    # ETA suppressed once delivered, even though edd_info is present.
    assert parcel["planned_from"] is None
    assert parcel["planned_to"] is None
    assert parcel["weight"] is None
    assert parcel["dimensions"] is None
    assert parcel["pickup_point"] is None
    assert parcel["url"] == "https://spx.com.my/track?MY000000000000"
    assert parcel["sender"] is None
    assert parcel["raw"]["resolved_number"] == MY_CODE
    assert parcel["raw"]["resolved_number_is_internal"] is False
    assert parcel["raw"]["market"] == "MY"
    assert len(parcel["history"]) == 7  # 10 records, 3 internal (display_flag 0)


# --- Thailand: sentinel exception values must not warn ---------------------


def test_normalize_thailand_sentinels_do_not_warn(caplog):
    caplog.set_level(logging.WARNING)
    parcel = normalize_parcel(_stamped(th_data(), TH_CODE), market="TH")
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["barcode"] == TH_CODE
    assert "Unrecognised" not in caplog.text


# --- Philippines: full block set, ETA present -------------------------------


def test_normalize_philippines_delivered_with_eta_present_but_suppressed():
    parcel = normalize_parcel(_stamped(ph_data(), PH_CODE), market="PH")
    assert parcel["barcode"] == PH_CODE
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["delivered"] is True
    # edd_info is present in this capture but delivered -> still suppressed.
    assert parcel["planned_from"] is None
    assert parcel["planned_to"] is None


# --- Brazil: the divergent block set — the crash-prevention regression -----


def test_normalize_brazil_survives_missing_order_and_parcel_and_edd_info():
    """Gate B's regression test: must not raise, must still hit the minimum."""
    parcel = normalize_parcel(_stamped(br_data(), BR_CODE), market="BR", include_history=True)
    assert parcel["barcode"] == BR_CODE  # falls back to the requested number
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["delivered"] is True
    assert parcel["planned_from"] is None
    assert parcel["planned_to"] is None
    assert parcel["raw"]["spx_tn"] is None  # order_info absent -> no spx_tn at all
    assert parcel["raw"]["resolved_number"] == BR_CODE
    assert parcel["raw"]["resolved_number_is_internal"] is True
    assert parcel["raw"]["fulfillment_info_deliver_type"] == 1
    assert parcel["raw"]["is_shopee_market_order"] is True


def test_normalize_brazil_still_works_with_order_info_and_edd_info_added():
    """Optional-tolerant, not BR-shaped: adding the blocks back must not break
    anything, proving the defensive reads aren't secretly BR-specific."""
    raw = br_data()
    raw["order_info"] = {
        "sls_tn": "BR000000000000Y",
        "spx_tn": "BR000000000000Y",
        "tracking_code_group_name": "Delivered",
        "tracking_code_subgroup_name": "Delivered",
        "order_id": 1,
        "order_max_update_limit": 10,
    }
    raw["parcel_info"] = {"customer_tracking_no": ""}
    raw["edd_info"] = {"edd_min": 1782400000, "edd_max": 1782410000}
    parcel = normalize_parcel(_stamped(raw, BR_CODE), market="BR")
    assert parcel["barcode"] == "BR000000000000Y"
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["planned_from"] is None  # still suppressed: delivered


def test_normalize_brazil_missing_blocks_logs_nothing(caplog):
    """Regression: the removed `_check_missing_blocks()` must leave no trace —
    no warning, no exception, for a response missing three whole blocks."""
    caplog.set_level(logging.WARNING)
    parcel = normalize_parcel(_stamped(br_data(), BR_CODE), market="BR")
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert "missing" not in caplog.text.lower()
    assert not hasattr(parcels_module, "_check_missing_blocks")


# --- Indonesia: the single-record, not-yet-picked-up shape -----------------


def test_normalize_indonesia_single_record_not_delivered():
    parcel = normalize_parcel(_stamped(id_data(), ID_CODE), market="ID", include_history=True)
    assert parcel["barcode"] == ID_CODE
    assert parcel["status"] == ParcelStatus.REGISTERED
    assert parcel["delivered"] is False
    assert parcel["delivered_at"] is None
    assert parcel["planned_from"] is None  # no edd_info at all, despite order_info present
    assert parcel["planned_to"] is None
    assert len(parcel["history"]) == 1


# --- Vietnam: the returned parcel — the fullest trap coverage --------------


def test_normalize_vietnam_returning_never_delivered():
    parcel = normalize_parcel(_stamped(vn_data(), VN_CODE), market="VN", include_history=True)
    assert parcel["barcode"] == VN_CODE
    assert parcel["status"] == ParcelStatus.RETURNING  # milestone_code 10
    assert parcel["delivered"] is False
    assert parcel["delivered_at"] is None  # finished, but never "delivered"
    assert parcel["planned_from"] is None
    assert parcel["planned_to"] is None


def test_normalize_vietnam_exception_records_omit_keys_without_raising():
    """23 of 26 records omit issue_type/standard_reason_code entirely; must
    not raise on either the ones that carry them or the ones that don't."""
    raw = vn_data()
    without_exception_fields = [
        r for r in raw["sls_tracking_info"]["records"]
        if "issue_type" not in r and "standard_reason_code" not in r
    ]
    assert len(without_exception_fields) == 23
    parcel = normalize_parcel(_stamped(raw, VN_CODE), market="VN")
    assert parcel is not None


def test_normalize_vietnam_f650_maps_to_out_for_delivery_not_problem():
    """Assert §2's decision explicitly, so a later refactor can't silently
    flip it: a failed delivery attempt stays on its happy-path milestone."""
    raw = vn_data()
    f650 = next(r for r in raw["sls_tracking_info"]["records"] if r["tracking_code"] == "F650")
    assert f650["milestone_code"] == 6
    assert map_parcel_status(f650) == ParcelStatus.OUT_FOR_DELIVERY
    assert map_parcel_status(f650) != ParcelStatus.PROBLEM


def test_normalize_vietnam_f050_maps_to_registered_not_problem():
    raw = vn_data()
    for f050 in (r for r in raw["sls_tracking_info"]["records"] if r["tracking_code"] == "F050"):
        assert f050["milestone_code"] == 1
        assert map_parcel_status(f050) == ParcelStatus.REGISTERED


def test_normalize_vietnam_known_exception_vocab_does_not_warn(caplog):
    """R172/R102/R105, D03008/P02000/P03002 and issue_type 2/3 are all in the
    known sets sampled from this very parcel — nothing here should surprise."""
    caplog.set_level(logging.WARNING)
    normalize_parcel(_stamped(vn_data(), VN_CODE), market="VN", include_history=True)
    assert "Unrecognised" not in caplog.text


def test_normalize_vietnam_group_subgroup_differ():
    parcel = normalize_parcel(_stamped(vn_data(), VN_CODE), market="VN")
    assert parcel["raw"]["tracking_code_group_name"] == "Return"
    assert parcel["raw"]["tracking_code_subgroup_name"] == "Returned"


def test_normalize_vietnam_missing_edd_info_logs_nothing(caplog):
    caplog.set_level(logging.WARNING)
    normalize_parcel(_stamped(vn_data(), VN_CODE), market="VN")
    assert "missing" not in caplog.text.lower()


def test_normalize_vietnam_history_preserves_triple_f599_and_both_f050():
    raw = vn_data()
    history = build_history(raw["sls_tracking_info"]["records"])
    last_mile = [e for e in history if e["raw_status"] and "28-NDH Nam Dinh Hub" in e["raw_status"]]
    assert len(last_mile) >= 2  # F599 entries with that hub in their text
    reschedules = [
        e for e in history
        if e["raw_status"] and e["raw_status"].startswith("Pickup attempt was unsuccessful")
    ]
    assert len(reschedules) == 2


# ---------------------------------------------------------------------------
# Warning categories exercised through normalize_parcel
# ---------------------------------------------------------------------------


def test_unrecognised_reason_code_warns_once(caplog):
    caplog.set_level(logging.WARNING)
    raw = my_data()
    raw["sls_tracking_info"]["records"][0]["reason_code"] = "R999"
    normalize_parcel(_stamped(raw, MY_CODE), market="MY")
    normalize_parcel(_stamped(raw, MY_CODE), market="MY")
    assert caplog.text.count("R999") == 1


def test_unrecognised_standard_reason_code_warns_once(caplog):
    caplog.set_level(logging.WARNING)
    raw = my_data()
    raw["sls_tracking_info"]["records"][0]["standard_reason_code"] = "ZZZZZ"
    normalize_parcel(_stamped(raw, MY_CODE), market="MY")
    assert "ZZZZZ" in caplog.text
    assert "does not match" in caplog.text  # also fails the shape check


def test_unrecognised_issue_type_warns_once(caplog):
    caplog.set_level(logging.WARNING)
    raw = my_data()
    raw["sls_tracking_info"]["records"][0]["issue_type"] = 42
    normalize_parcel(_stamped(raw, MY_CODE), market="MY")
    assert "issue_type=42" in caplog.text


def test_standard_reason_code_shape_mismatch_with_issue_type_warns(caplog):
    caplog.set_level(logging.WARNING)
    raw = my_data()
    # Known standard_reason_code value, but paired with a disagreeing
    # issue_type: the phase-decomposition invariant breaks.
    raw["sls_tracking_info"]["records"][0]["standard_reason_code"] = "D03008"
    raw["sls_tracking_info"]["records"][0]["issue_type"] = 2
    normalize_parcel(_stamped(raw, MY_CODE), market="MY")
    assert "does not agree with" in caplog.text


def test_unrecognised_tracking_code_warns_once(caplog):
    caplog.set_level(logging.WARNING)
    raw = my_data()
    raw["sls_tracking_info"]["records"][0]["tracking_code"] = "F123456"
    normalize_parcel(_stamped(raw, MY_CODE), market="MY")
    normalize_parcel(_stamped(raw, MY_CODE), market="MY")
    assert caplog.text.count("F123456") == 1


def test_unrecognised_group_name_warns(caplog):
    caplog.set_level(logging.WARNING)
    raw = my_data()
    raw["order_info"]["tracking_code_group_name"] = "Something New"
    normalize_parcel(_stamped(raw, MY_CODE), market="MY")
    assert "Something New" in caplog.text


def test_unrecognised_subgroup_name_warns(caplog):
    caplog.set_level(logging.WARNING)
    raw = my_data()
    raw["order_info"]["tracking_code_subgroup_name"] = "Something Else"
    normalize_parcel(_stamped(raw, MY_CODE), market="MY")
    assert "Something Else" in caplog.text


def test_delivered_cross_check_mismatch_warns(caplog):
    caplog.set_level(logging.WARNING)
    raw = my_data()
    # Newest milestone says delivered (8), but the carrier's own group name
    # disagrees.
    raw["order_info"]["tracking_code_group_name"] = "Pending Pickup"
    normalize_parcel(_stamped(raw, MY_CODE), market="MY")
    assert "disagrees with" in caplog.text


def test_delivered_cross_check_no_op_when_group_name_absent(caplog):
    """order_info present but without a group name — nothing to cross-check."""
    caplog.set_level(logging.WARNING)
    raw = my_data()
    del raw["order_info"]["tracking_code_group_name"]
    normalize_parcel(_stamped(raw, MY_CODE), market="MY")
    assert "disagrees with" not in caplog.text


def test_delivered_cross_check_no_warning_when_consistent(caplog):
    caplog.set_level(logging.WARNING)
    normalize_parcel(_stamped(my_data(), MY_CODE), market="MY")
    assert "disagrees with" not in caplog.text


def test_payload_shape_warns_on_unexpected_top_level_key(caplog):
    caplog.set_level(logging.WARNING)
    raw = my_data()
    raw["a_brand_new_block"] = {"foo": "bar"}
    normalize_parcel(_stamped(raw, MY_CODE), market="MY")
    assert "a_brand_new_block" in caplog.text


def test_payload_shape_warns_with_list_shaped_unexpected_value(caplog):
    """Covers the list branch of the type-only shape describer."""
    caplog.set_level(logging.WARNING)
    raw = my_data()
    raw["a_new_list_block"] = [1, 2, 3]
    normalize_parcel(_stamped(raw, MY_CODE), market="MY")
    assert "list[3]" in caplog.text


def test_payload_shape_warns_on_unexpected_record_key(caplog):
    caplog.set_level(logging.WARNING)
    raw = my_data()
    raw["sls_tracking_info"]["records"][0]["a_brand_new_field"] = 1
    normalize_parcel(_stamped(raw, MY_CODE), market="MY")
    assert "a_brand_new_field" in caplog.text


def test_payload_shape_no_warning_for_known_shape(caplog):
    caplog.set_level(logging.WARNING)
    normalize_parcel(_stamped(my_data(), MY_CODE), market="MY")
    assert "unrecognised" not in caplog.text.lower()


def test_requested_code_key_itself_never_flagged_as_unexpected(caplog):
    """REQUESTED_CODE_KEY is synthetic (coordinator-added), not a wire field —
    _check_payload_shape must exclude it explicitly."""
    caplog.set_level(logging.WARNING)
    normalize_parcel(_stamped(my_data(), MY_CODE), market="MY")
    assert REQUESTED_CODE_KEY not in caplog.text


# ---------------------------------------------------------------------------
# empty-records edge case
# ---------------------------------------------------------------------------


def test_normalize_empty_records_does_not_raise():
    raw = {"sls_tracking_info": {"records": []}, REQUESTED_CODE_KEY: "X"}
    parcel = normalize_parcel(raw, market="MY")
    assert parcel["status"] == ParcelStatus.UNKNOWN
    assert parcel["barcode"] == "X"
    assert parcel["delivered"] is False


def test_normalize_missing_sls_tracking_info_does_not_raise():
    raw = {REQUESTED_CODE_KEY: "X"}
    parcel = normalize_parcel(raw, market="MY")
    assert parcel["status"] == ParcelStatus.UNKNOWN
    assert parcel["barcode"] == "X"


# ---------------------------------------------------------------------------
# sort_parcels_by_ts
# ---------------------------------------------------------------------------


def test_sort_parcels_ascending_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "planned_from": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "planned_from": None},
        {"barcode": "c", "planned_from": "2026-05-01T10:00:00Z"},
    ]
    ordered = [p["barcode"] for p in sort_parcels_by_ts(parcels, "planned_from")]
    assert ordered == ["c", "a", "b"]


def test_sort_parcels_descending_still_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "delivered_at": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "delivered_at": "nonsense"},
        {"barcode": "c", "delivered_at": "2026-05-01T10:00:00Z"},
    ]
    ordered = [
        p["barcode"]
        for p in sort_parcels_by_ts(parcels, "delivered_at", descending=True)
    ]
    assert ordered == ["a", "c", "b"]


# ---------------------------------------------------------------------------
# apply_delivered_filter
# ---------------------------------------------------------------------------


def _entry(filter_type: str, amount: int) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_DELIVERED_FILTER_TYPE: filter_type,
            CONF_DELIVERED_FILTER_AMOUNT: amount,
        },
    )


def _delivered_pair() -> list[dict]:
    now = datetime.now(timezone.utc)
    return [
        {"barcode": "RECENT", "delivered_at": (now - timedelta(days=1)).isoformat()},
        {"barcode": "OLD", "delivered_at": (now - timedelta(days=30)).isoformat()},
    ]


def test_delivered_filter_by_days():
    kept = apply_delivered_filter(_delivered_pair(), _entry("days", 7))
    assert [p["barcode"] for p in kept] == ["RECENT"]


def test_delivered_filter_by_count():
    parcels = _delivered_pair()
    assert apply_delivered_filter(parcels, _entry("parcels", 1)) == parcels[:1]


def test_delivered_filter_keeps_unparseable_timestamp():
    parcels = [{"barcode": "WEIRD", "delivered_at": "nonsense"}]
    assert apply_delivered_filter(parcels, _entry("days", 7)) == parcels
