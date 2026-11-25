"""The parcel contract's checks, run over every normalised sample."""

from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.util import dt as dt_util
import pytest

from custom_components.shopee_xpress.const import ParcelStatus
from custom_components.shopee_xpress.parcels import (
    REQUESTED_CODE_KEY,
    normalize_parcel,
    parse_iso,
)

from .payloads import (
    BR_CODE,
    MY_CODE,
    TH_CODE,
    TW_CODE,
    VN_CODE,
    br_data,
    fleet_event,
    my_data,
    th_data,
    tw_data,
    tw_ready_data,
    vn_data,
)

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
    "contents",
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

# 2099-05-01 10:00:00 and 12:00:00 UTC, epoch seconds.
_FUTURE_MIN = 4_081_000_000
_FUTURE_MAX = _FUTURE_MIN + 7200


def _stamped(raw: dict, code: str) -> dict:
    return {**raw, REQUESTED_CODE_KEY: code}


def _active_order_view(edd_min, edd_max) -> dict:
    """Malaysia's order view, with the newest record out for delivery."""
    raw = my_data()
    records = raw["sls_tracking_info"]["records"]
    records[0] = {**records[0], "milestone_code": 6}
    raw["edd_info"] = {"edd_min": edd_min, "edd_max": edd_max}
    return raw


def _collected_fleet() -> dict:
    """Waiting at the store, then collected: the newest scan is the collection."""
    data = tw_ready_data()
    data["current_status"] = "Delivered"
    data["tracking_list"] = [
        fleet_event("Delivered", 1791400000, "collected"),
        *data["tracking_list"],
    ]
    return data


def _returning_order_view() -> dict:
    raw = my_data()
    records = raw["sls_tracking_info"]["records"]
    records[0] = {**records[0], "milestone_code": 10}
    return raw


SAMPLES = {
    "my_delivered": lambda: normalize_parcel(
        _stamped(my_data(), MY_CODE), market="MY", include_history=True
    ),
    "th_delivered": lambda: normalize_parcel(_stamped(th_data(), TH_CODE), market="TH"),
    "br_delivered": lambda: normalize_parcel(_stamped(br_data(), BR_CODE), market="BR"),
    "vn_returning": lambda: normalize_parcel(_stamped(vn_data(), VN_CODE), market="VN"),
    "my_active_window": lambda: normalize_parcel(
        _stamped(_active_order_view(_FUTURE_MIN, _FUTURE_MAX), MY_CODE), market="MY"
    ),
    "my_active_moment": lambda: normalize_parcel(
        _stamped(_active_order_view(_FUTURE_MIN, None), MY_CODE), market="MY"
    ),
    "my_returning": lambda: normalize_parcel(
        _stamped(_returning_order_view(), MY_CODE), market="MY"
    ),
    "tw_delivered": lambda: normalize_parcel(_stamped(tw_data(), TW_CODE), market="TW"),
    "tw_at_pickup": lambda: normalize_parcel(
        _stamped(tw_ready_data(), TW_CODE), market="TW", include_history=True
    ),
    "tw_collected": lambda: normalize_parcel(
        _stamped(_collected_fleet(), TW_CODE), market="TW"
    ),
    "tw_empty": lambda: normalize_parcel(_stamped({}, TW_CODE), market="TW"),
}


@pytest.fixture(params=SAMPLES)
def parcel(request) -> dict:
    return SAMPLES[request.param]()


def test_keys_and_order(parcel):
    assert list(parcel) == CANONICAL_KEYS


def test_delivered_follows_status(parcel):
    assert parcel["delivered"] is (parcel["status"] is ParcelStatus.DELIVERED)


def test_delivered_at_only_when_delivered(parcel):
    if not parcel["delivered"]:
        assert parcel["delivered_at"] is None


def test_planned_window_is_ordered_and_anchored(parcel):
    if parcel["planned_to"] is not None:
        assert parcel["planned_from"] is not None
        assert parse_iso(parcel["planned_to"]) > parse_iso(parcel["planned_from"])


def test_planned_is_empty_when_the_parcel_is_done_or_waiting(parcel):
    if parcel["status"] in (
        ParcelStatus.DELIVERED,
        ParcelStatus.AT_PICKUP_POINT,
        ParcelStatus.RETURNING,
    ):
        assert parcel["planned_from"] is None
        assert parcel["planned_to"] is None


def test_pickup_is_a_bool_and_the_point_needs_it(parcel):
    assert isinstance(parcel["pickup"], bool)
    if not parcel["pickup"]:
        assert parcel["pickup_point"] is None


def test_a_collected_pickup_parcel_stays_pickup():
    parcel = SAMPLES["tw_collected"]()
    assert parcel["status"] is ParcelStatus.DELIVERED
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] is not None
    assert parcel["pickup"] is True


def test_a_home_delivery_is_not_pickup():
    assert SAMPLES["tw_delivered"]()["pickup"] is False
    assert SAMPLES["my_delivered"]()["pickup"] is False


def test_waiting_at_the_store_is_pickup_without_planned_window():
    parcel = SAMPLES["tw_at_pickup"]()
    assert parcel["status"] is ParcelStatus.AT_PICKUP_POINT
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] is None


def test_a_return_is_not_delivered_even_when_finished():
    parcel = SAMPLES["vn_returning"]()
    assert parcel["status"] is ParcelStatus.RETURNING
    assert parcel["delivered"] is False
    assert parcel["delivered_at"] is None


def test_a_window_keeps_both_ends():
    parcel = SAMPLES["my_active_window"]()
    assert parse_iso(parcel["planned_from"]) == datetime.fromtimestamp(
        _FUTURE_MIN, tz=dt_util.UTC
    )
    assert parse_iso(parcel["planned_to"]) == datetime.fromtimestamp(
        _FUTURE_MAX, tz=dt_util.UTC
    )


def test_a_moment_ends_at_the_end_of_that_day():
    parcel = SAMPLES["my_active_moment"]()
    zone = ZoneInfo("Asia/Kuala_Lumpur")
    start = parse_iso(parcel["planned_from"]).astimezone(zone)
    end = parse_iso(parcel["planned_to"]).astimezone(zone)
    assert (end.hour, end.minute, end.second, end.microsecond) == (23, 59, 59, 0)
    assert end.date() == start.date()


@pytest.mark.parametrize(
    ("market", "builder", "code", "zone_name", "offset"),
    [
        ("MY", my_data, MY_CODE, "Asia/Kuala_Lumpur", "+08:00"),
        ("TH", th_data, TH_CODE, "Asia/Bangkok", "+07:00"),
        ("VN", vn_data, VN_CODE, "Asia/Ho_Chi_Minh", "+07:00"),
    ],
)
def test_the_window_ends_on_the_markets_own_day(
    market, builder, code, zone_name, offset
):
    """20:00 UTC is already the next day in these markets, not in Home Assistant's."""
    previous = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(dt_util.get_time_zone("America/Los_Angeles"))
    try:
        raw = builder()
        records = raw["sls_tracking_info"]["records"]
        records[0] = {**records[0], "milestone_code": 6}
        raw["edd_info"] = {"edd_min": 4081089600, "edd_max": None}
        parcel = normalize_parcel(_stamped(raw, code), market=market)
    finally:
        dt_util.set_default_time_zone(previous)
    assert parcel["planned_to"] == f"2099-04-29T23:59:59{offset}"


def test_a_multi_zone_market_uses_home_assistants_zone():
    previous = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(dt_util.get_time_zone("America/Los_Angeles"))
    try:
        raw = br_data()
        records = raw["sls_tracking_info"]["records"]
        records[0] = {**records[0], "milestone_code": 6}
        raw["edd_info"] = {"edd_min": 4081089600, "edd_max": None}
        parcel = normalize_parcel(_stamped(raw, BR_CODE), market="BR")
    finally:
        dt_util.set_default_time_zone(previous)
    assert parcel["planned_to"] == "2099-04-28T23:59:59-07:00"
