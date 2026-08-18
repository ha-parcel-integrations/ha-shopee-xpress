"""Real (redacted) Shopee Xpress API payloads shared by the test modules.

Six captures — one per supported market — reproduced from
``carrier-research/api/shopee-xpress/tracking.md`` (the private research
repo's own redacted transcription of real device traffic; nothing here was
invented). Values that identify a person, an address, an order or a specific
device are already masked in that source and stay masked here (``"0"``,
``"<city>"``-style placeholders, empty coordinates). Structure, key names,
milestone/tracking codes and the relationships between them (which record is
newest, which fields repeat, which blocks are absent) are real.

Each ``*_data()`` function returns the API response's ``data`` object — what
:class:`~custom_components.shopee_xpress.api.ShopeeXpressApiClient.async_get_parcel`
returns on success, and what ``normalize_parcel()`` takes as ``raw``. Kept in
one module rather than inline in each test so a payload-shape correction only
has one place to happen.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# tracking codes as a user would have entered them (== the captured `spx_tn`
# in every market except Brazil, whose capture was made with a value
# byte-identical to that body's `sls_tn` — see tracking.md).
# ---------------------------------------------------------------------------

MY_CODE = "MY000000000000"
TH_CODE = "TH000000000000"
PH_CODE = "SPEPH000000000000"
BR_CODE = "BR000000000000Y"
ID_CODE = "SPXID000000000000"
VN_CODE = "SPXVN00000000000C"

_EMPTY_LOCATION: dict[str, str] = {
    "location_name": "",
    "location_type_name": "",
    "lng": "",
    "lat": "",
    "full_address": "",
}


def envelope(data: dict) -> dict:
    """Wrap a ``data`` object in the real success envelope (``retcode: 0``)."""
    return {"retcode": 0, "data": data, "message": "success", "detail": "", "debug": ""}


def error_envelope(message: str = "internal error") -> dict:
    """The real failure envelope — no ``data`` key at all, an ambiguous shape
    that cannot be told apart from a genuinely broken backend (see api.py)."""
    return {
        "retcode": 2,
        "message": f"retcode:-2023002, message:{message}",
        "detail": "Oops, an unexpected error has occurred",
        "debug": "",
    }


def record(
    tracking_code: str,
    tracking_name: str,
    milestone_code: int,
    milestone_name: str,
    actual_time: int,
    *,
    display_flag: int = 1,
    description: str = "",
    buyer_description: str | None = None,
    seller_description: str | None = None,
    reason_code: str = "R00",
    reason_desc: str = "R00",
    issue_type: int | None = None,
    standard_reason_code: str | None = None,
    standard_reason_description: str | None = None,
    current_location: dict | None = None,
    next_location: dict | None = None,
    display_flag_v2: int = 13,
    hold_times: bool = True,
) -> dict[str, Any]:
    """Build one ``sls_tracking_info.records[]`` entry.

    ``issue_type`` / ``standard_reason_code`` / ``standard_reason_description``
    are only added when explicitly passed — omitting them (the default)
    reproduces the real "these keys are absent on a clean record" shape,
    which the Vietnamese capture proves happens *within* one body, not only
    across markets. ``hold_times=False`` reproduces the Brazilian capture's
    other trap: no ``delivery_on_hold_times`` key on any record there.
    """
    entry: dict[str, Any] = {
        "tracking_code": tracking_code,
        "tracking_name": tracking_name,
        "description": description,
        "buyer_description": buyer_description if buyer_description is not None else description,
        "seller_description": seller_description if seller_description is not None else description,
        "display_flag": display_flag,
        "display_flag_v2": display_flag_v2,
        "actual_time": actual_time,
        "reason_code": reason_code,
        "reason_desc": reason_desc,
        "epod": "",
        "milestone_code": milestone_code,
        "milestone_name": milestone_name,
        "current_location": current_location or _EMPTY_LOCATION,
        "next_location": next_location or _EMPTY_LOCATION,
    }
    if hold_times:
        entry["delivery_on_hold_times"] = 0
    if issue_type is not None:
        entry["issue_type"] = issue_type
    if standard_reason_code is not None:
        entry["standard_reason_code"] = standard_reason_code
    if standard_reason_description is not None:
        entry["standard_reason_description"] = standard_reason_description
    return entry


def _location(name: str) -> dict[str, str]:
    return {"location_name": name, "location_type_name": "", "lng": "1", "lat": "1", "full_address": "x"}


# ---------------------------------------------------------------------------
# Malaysia — spx.com.my — delivered, full block set (pattern A).
# `F440` repeats (positions 5 and 9): the non-uniqueness trap, confirmed in
# a second market alongside Brazil's `F004` and the Philippines' sorting legs.
# ---------------------------------------------------------------------------


def my_data(code: str = MY_CODE) -> dict:
    """A delivered Malaysian parcel — the reference "everything present" shape."""
    return {
        "parcel_info": {"customer_tracking_no": "0000000000"},
        "order_info": {
            "sls_tn": "MY000000000000R",
            "spx_tn": code,
            "tracking_code_group_name": "Delivered",
            "tracking_code_subgroup_name": "Delivered",
            "order_id": 0,
            "order_max_update_limit": 10,
        },
        "sls_tracking_info": {
            "sls_tn": "MY000000000000R",
            "client_order_id": "0",
            "receiver_name": "",
            "receiver_type_name": "",
            "records": [
                record("F980", "Delivered", 8, "Delivered", 1770278488,
                       description="Your parcel has been delivered"),
                record("F600", "Out For Delivery", 6, "Out for delivery", 1770273420,
                       description="Your parcel is being delivered by courier"),
                record("F598", "Delivery Driver Assigned", 5, "In transit", 1770262887,
                       display_flag=0),
                record("F599", "Enter Last Mile Hub", 5, "In transit", 1770262190,
                       description="Your parcel has been received by delivery hub",
                       current_location=_location("Nilai Hub")),
                record("F440", "Enter Domestic First Mile Hub", 5, "In transit", 1770222086,
                       description="Parcel transported to MKZ sorting centre"),
                record("F450", "Left Domestic First Mile Hub", 5, "In transit", 1770213527,
                       next_location=_location("MKZ sorting centre")),
                record("F441", "Loaded to Truck in First Mile Hub", 5, "In transit", 1770212975,
                       display_flag=0),
                record("F445", "Packed in First Mile Hub", 5, "In transit", 1770211446,
                       display_flag=0),
                record("F440", "Enter Domestic First Mile Hub", 5, "In transit", 1770209065,
                       description="Your parcel has been received by pickup hub",
                       current_location=_location("BPT First Mile Hub")),
                record("F000", "Manifested", 1, "Preparing to ship", 1770104618,
                       description="Sender is preparing to ship your parcel",
                       reason_code="", reason_desc=""),
            ],
        },
        "is_instant_order": False,
        "is_shopee_market_order": False,
        "edd_info": {"edd_min": 1770313289, "edd_max": 1770411958},
    }


# ---------------------------------------------------------------------------
# Thailand — spx.co.th — delivered, full block set (pattern A). Confirms the
# same milestone_code vocabulary in a second market and exercises the
# sentinel exception values (issue_type 99, the *99000 standard_reason_codes)
# that must NOT trigger an unrecognised-vocabulary warning.
# ---------------------------------------------------------------------------


def th_data(code: str = TH_CODE) -> dict:
    """A delivered Thai parcel, carrying the sentinel (no-exception) reason codes."""
    return {
        "parcel_info": {"customer_tracking_no": ""},
        "order_info": {
            "sls_tn": "TH0000000000000",
            "spx_tn": code,
            "tracking_code_group_name": "Delivered",
            "tracking_code_subgroup_name": "Delivered",
            "order_id": 0,
            "order_max_update_limit": 10,
        },
        "sls_tracking_info": {
            "sls_tn": "TH0000000000000",
            "client_order_id": "0",
            "receiver_name": "",
            "receiver_type_name": "",
            "records": [
                record("F980", "Delivered", 8, "Delivered", 1770278600,
                       description="พัสดุของคุณถูกจัดส่งแล้ว",
                       issue_type=99, standard_reason_code="D99000"),
                record("F600", "Out For Delivery", 6, "Out for delivery", 1770273500,
                       issue_type=99, standard_reason_code="T99000"),
                record("F000", "Manifested", 1, "Preparing to ship", 1770104700,
                       reason_code="", reason_desc="",
                       issue_type=99, standard_reason_code="P99000"),
            ],
        },
        "is_instant_order": False,
        "is_shopee_market_order": False,
        "edd_info": {"edd_min": 1770313300, "edd_max": 1770411900},
    }


# ---------------------------------------------------------------------------
# Philippines — spx.ph — delivered, full block set (pattern A), 23 records.
# `F440` repeats, and `F510`/`F515`/`F540`/`F541`/`F580` each repeat across
# two sorting-centre legs — the build plan's own regression fixture for "do
# not de-duplicate history on tracking_code".
# ---------------------------------------------------------------------------


def ph_data(code: str = PH_CODE) -> dict:
    """A delivered Philippine parcel with two distinct sorting-centre legs."""
    return {
        "parcel_info": {"customer_tracking_no": ""},
        "order_info": {
            "sls_tn": "PH0000000000000",
            "spx_tn": code,
            "tracking_code_group_name": "Delivered",
            "tracking_code_subgroup_name": "Delivered",
            "order_id": 0,
            "order_max_update_limit": 10,
        },
        "sls_tracking_info": {
            "sls_tn": "PH0000000000000",
            "client_order_id": "0",
            "receiver_name": "",
            "receiver_type_name": "",
            "records": [
                record("F980", "Delivered", 8, "Delivered", 1778401745,
                       description="Parcel has been delivered",
                       buyer_description="Parcel has been delivered",
                       seller_description="Parcel has been delivered to buyer"),
                record("F600", "Out For Delivery", 6, "Out for delivery", 1778373344,
                       description="Parcel is out for delivery"),
                record("F598", "Delivery Driver Assigned", 5, "In transit", 1778373343,
                       description="Delivery driver has been assigned"),
                record("F599", "Enter Last Mile Hub", 5, "In transit", 1778367806,
                       current_location=_location("Amang Rodriguez Hub")),
                record("F580", "Domestic Line Haul End", 5, "In transit", 1778364516),
                record("F540", "Left Domestic Sorting Center", 5, "In transit", 1778359216),
                record("F541", "Loaded to Truck in Sorting Centre", 5, "In transit", 1778359191),
                record("F515", "Packed in Domestic Sorting Centre", 5, "In transit", 1778342242,
                       display_flag=0),
                record("F510", "Enter Domestic Sorting Center", 5, "In transit", 1778342107,
                       current_location=_location("SOC 6")),
                record("F580", "Domestic Line Haul End", 5, "In transit", 1778340477),
                record("F540", "Left Domestic Sorting Center", 5, "In transit", 1778336021),
                record("F541", "Loaded to Truck in Sorting Centre", 5, "In transit", 1778336020),
                record("F515", "Packed in Domestic Sorting Centre", 5, "In transit", 1778334233,
                       display_flag=0),
                record("F510", "Enter Domestic Sorting Center", 5, "In transit", 1778334125,
                       current_location=_location("MFM Guiguinto")),
                record("F440", "Enter Domestic First Mile Hub", 5, "In transit", 1778331866),
                record("F450", "Left Domestic First Mile Hub", 5, "In transit", 1778327852),
                record("F441", "Loaded to Truck in First Mile Hub", 5, "In transit", 1778327844),
                record("F445", "Packed in First Mile Hub", 5, "In transit", 1778326233,
                       display_flag=0),
                record("F440", "Enter Domestic First Mile Hub", 5, "In transit", 1778326198,
                       current_location=_location("Baliuag Hub")),
                record("F430", "Arrived at First Mile Hub", 5, "In transit", 1778325574),
                record("F100", "Pickup From Domestic Seller", 5, "In transit", 1778318509,
                       next_location=_location("SPX Service Point")),
                record("F098", "Dropoff Done By Domestic Seller", 5, "In transit", 1778317485,
                       current_location=_location("SPX Service Point")),
                record("F000", "Manifested", 1, "Preparing to ship", 1778312976,
                       description="Sender is preparing to ship your parcel",
                       reason_code="", reason_desc=""),
            ],
        },
        "is_instant_order": False,
        "is_shopee_market_order": False,
        "edd_info": {"edd_min": 1778399012, "edd_max": 1778481990},
    }


# ---------------------------------------------------------------------------
# Brazil — spx.com.br — delivered, the divergent shape (pattern B): no
# order_info / parcel_info / edd_info, `fulfillment_info` present,
# `is_shopee_market_order: true`. `F004` repeats three times and no record
# carries `delivery_on_hold_times` at all — the block-set and record-shape
# fixture Gate B's regression test is built on.
# ---------------------------------------------------------------------------


def br_data(code: str = BR_CODE) -> dict:
    """A delivered Brazilian parcel — no order_info/parcel_info/edd_info."""
    return {
        "fulfillment_info": {"deliver_type": 1},
        "sls_tracking_info": {
            "sls_tn": code,  # captured with an sls_tn-shaped input; see module docstring
            "client_order_id": "0000000000000000000",
            "receiver_name": "",
            "receiver_type_name": "",
            "records": [
                record("F980", "Delivered", 8, "Delivered", 1782403700,
                       description="Seu pacote foi entregue a [RECIPIENT NAME] [Receptionist]",
                       reason_desc="", display_flag_v2=13, hold_times=False),
                record("F600", "Out For Delivery", 6, "Out for delivery", 1782377168,
                       display_flag_v2=12, hold_times=False),
                record("F599", "Enter Last Mile Hub", 5, "In transit", 1782362574,
                       display_flag=0, reason_code="", reason_desc="R00",
                       current_location=_location("<city> - MG"), display_flag_v2=9,
                       hold_times=False),
                record("F540", "Left Domestic Sorting Center", 5, "In transit", 1782319361,
                       next_location=_location("<city> - MG"), display_flag_v2=13,
                       hold_times=False),
                record("F541", "Loaded to Truck in Sorting Centre", 5, "In transit", 1782319359,
                       display_flag=0, display_flag_v2=0, hold_times=False),
                record("F515", "Packed in Domestic Sorting Centre", 5, "In transit", 1782296673,
                       current_location=_location("<city> - MG"), next_location=_location("<city> - MG"),
                       display_flag_v2=13, hold_times=False),
                record("F510", "Enter Domestic Sorting Center", 5, "In transit", 1782294163,
                       current_location=_location("<city> - MG"), next_location=_location("<city> - MG"),
                       display_flag_v2=13, hold_times=False),
                record("F540", "Left Domestic Sorting Center", 5, "In transit", 1782197429,
                       display_flag_v2=13, hold_times=False),
                record("F541", "Loaded to Truck in Sorting Centre", 5, "In transit", 1782197428,
                       display_flag=0, display_flag_v2=0, hold_times=False),
                record("F515", "Packed in Domestic Sorting Centre", 5, "In transit", 1782158981,
                       display_flag_v2=13, hold_times=False),
                record("F510", "Enter Domestic Sorting Center", 5, "In transit", 1782152725,
                       display_flag_v2=13, hold_times=False),
                record("F100", "Pickup From Domestic Seller", 5, "In transit", 1782144848,
                       display_flag_v2=12, hold_times=False),
                record("F004", "Courier assigned", 1, "Preparing to ship", 1782136787,
                       display_flag=0, description="Parcel assigned to Driver",
                       display_flag_v2=1, hold_times=False),
                record("F004", "Courier assigned", 1, "Preparing to ship", 1782132221,
                       display_flag=0, description="Parcel assigned to Driver",
                       display_flag_v2=1, hold_times=False),
                record("F004", "Courier assigned", 1, "Preparing to ship", 1782130929,
                       display_flag=0, description="Parcel assigned to Driver",
                       display_flag_v2=1, hold_times=False),
                record("F000", "Manifested", 1, "Preparing to ship", 1782124787,
                       description="Sender is preparing to ship your parcel",
                       reason_code="", reason_desc="", display_flag_v2=12, hold_times=False),
                record("A000", "SLSTN Created", 1, "Preparing to ship", 1782124785,
                       display_flag=0, reason_code="", reason_desc="", display_flag_v2=0,
                       hold_times=False),
            ],
        },
        "is_instant_order": False,
        "is_shopee_market_order": True,
    }


# ---------------------------------------------------------------------------
# Indonesia — spx.co.id — not yet picked up: the only single-record capture,
# `edd_info` absent (pattern C, alongside Vietnam).
# ---------------------------------------------------------------------------


def id_data(code: str = ID_CODE) -> dict:
    """An Indonesian parcel that has not been collected yet — one record."""
    return {
        "parcel_info": {"customer_tracking_no": "INIDQ0000000000000-000"},
        "order_info": {
            "sls_tn": "ID000000000000M",
            "spx_tn": code,
            "tracking_code_group_name": "Pending Pickup",
            "tracking_code_subgroup_name": "Pending Pickup",
            "order_id": 0,
            "order_max_update_limit": 3,
        },
        "sls_tracking_info": {
            "sls_tn": "ID000000000000M",
            "client_order_id": "0",
            "receiver_name": "",
            "receiver_type_name": "",
            "records": [
                record("F000", "Manifested", 1, "Preparing to ship", 1787044898,
                       description="Sender is preparing to ship your parcel",
                       reason_code="", reason_desc=""),
            ],
        },
        "is_instant_order": False,
        "is_shopee_market_order": False,
    }


# ---------------------------------------------------------------------------
# Vietnam — spx.vn — refused by the recipient and returned to sender, 26
# records (the fullest history captured). Supplies `milestone_code: 10`, the
# only populated exception vocabulary, and both `F650`/`F050` failures that
# keep an ordinary happy-path milestone despite carrying a real reason code.
# ---------------------------------------------------------------------------


def vn_data(code: str = VN_CODE) -> dict:
    """A Vietnamese parcel refused by the recipient and returned to sender."""
    return {
        "parcel_info": {"customer_tracking_no": "REDACTED"},
        "order_info": {
            "sls_tn": "VN000000000000U",
            "spx_tn": code,
            "tracking_code_group_name": "Return",
            "tracking_code_subgroup_name": "Returned",
            "order_id": 0,
            "order_max_update_limit": 3,
        },
        "sls_tracking_info": {
            "sls_tn": "VN000000000000U",
            "client_order_id": "0",
            "receiver_name": "",
            "receiver_type_name": "",
            "records": [
                record("F999", "Returned to Sender", 10, "Delivery Unsuccessful", 1766734378,
                       description="Parcel has been returned to sender",
                       current_location=_location("20-HNI Long Bien 3 Hub"), display_flag_v2=5),
                record("F680", "Return Attempt Started", 10, "Delivery Unsuccessful", 1766728630,
                       description="Parcel is out for delivery to sender",
                       current_location=_location("20-HNI Long Bien 3 Hub"), display_flag_v2=5),
                record("F673", "RTS delivery driver assigned", 10, "Delivery Unsuccessful", 1766694697,
                       description="Delivery driver has been assigned in 20-HNI Long Bien 3 Hub",
                       current_location=_location("20-HNI Long Bien 3 Hub"), display_flag_v2=13),
                record("F677", "RTS Line Haul Transportation", 10, "Delivery Unsuccessful", 1766687316,
                       description="Parcel has departed from station ::BN A Mega SOC",
                       current_location=_location("BN A Mega SOC"), display_flag_v2=5),
                record("F671", "Enter RTS Sorting Centre", 10, "Delivery Unsuccessful", 1766672026,
                       description="Parcel has arrived at station ::BN A Mega SOC",
                       current_location=_location("BN A Mega SOC"), display_flag_v2=5),
                record("F677", "RTS Line Haul Transportation", 10, "Delivery Unsuccessful", 1766662445,
                       description="Parcel has departed from station ::28-NDH Nam Dinh Hub",
                       current_location=_location("28-NDH Nam Dinh Hub"), display_flag_v2=5),
                record("F671", "Enter RTS Sorting Centre", 10, "Delivery Unsuccessful", 1766573106,
                       description="Parcel has arrived at station ::28-NDH Nam Dinh Hub",
                       current_location=_location("28-NDH Nam Dinh Hub"), display_flag_v2=5),
                record("F599", "Enter Last Mile Hub", 5, "In transit", 1766573105,
                       description="Parcel has arrived at station 28-NDH Nam Dinh Hub",
                       current_location=_location("28-NDH Nam Dinh Hub"), display_flag_v2=13),
                record("F599", "Enter Last Mile Hub", 5, "In transit", 1766547542,
                       description="Parcel has arrived at station 28-NDH Nam Dinh Hub",
                       current_location=_location("28-NDH Nam Dinh Hub"), display_flag_v2=13),
                record("F650", "Delivery Attempt Failed", 6, "Out for delivery", 1766547541,
                       description="Delivery attempt was unsuccessful :Rejected By Recipient",
                       reason_code="R172", reason_desc="Người nhận từ chối nhận hàng",
                       issue_type=3, standard_reason_code="D03008",
                       standard_reason_description="Rejected By Recipient", display_flag_v2=5),
                record("F600", "Out For Delivery", 6, "Out for delivery", 1766541531,
                       display_flag_v2=13),
                record("F599", "Enter Last Mile Hub", 5, "In transit", 1766537887,
                       description="Parcel has arrived at station 28-NDH Nam Dinh Hub",
                       current_location=_location("28-NDH Nam Dinh Hub"), display_flag_v2=13),
                record("F580", "Domestic Line Haul End", 5, "In transit", 1766535735,
                       display_flag=0,
                       description="System reminder: Not in use, no need edit yet.",
                       buyer_description="System reminder: Not in use, no need edit yet.",
                       display_flag_v2=1),
                record("F540", "Left Domestic Sorting Center", 5, "In transit", 1766520211,
                       description="Parcel has departed from station",
                       next_location=_location("28-NDH Nam Dinh Hub"), display_flag_v2=5),
                record("F541", "Loaded to Truck in Sorting Centre", 5, "In transit", 1766520156,
                       display_flag=0, display_flag_v2=1),
                record("F515", "Packed in Domestic Sorting Centre", 5, "In transit", 1766491008,
                       display_flag=0, display_flag_v2=1),
                record("F510", "Enter Domestic Sorting Center", 5, "In transit", 1766490703,
                       description="Parcel has arrived at station :BN B Mega SOC",
                       current_location=_location("BN B Mega SOC"), display_flag_v2=13),
                record("F440", "Enter Domestic First Mile Hub", 5, "In transit", 1766489975,
                       display_flag_v2=13),
                record("F450", "Left Domestic First Mile Hub", 5, "In transit", 1766485248,
                       next_location=_location("BN B Mega SOC"), display_flag_v2=5),
                record("F441", "Loaded to Truck in First Mile Hub", 5, "In transit", 1766485177,
                       display_flag=0, display_flag_v2=1),
                record("F445", "Packed in First Mile Hub", 5, "In transit", 1766483682,
                       display_flag=0, display_flag_v2=1),
                record("F440", "Enter Domestic First Mile Hub", 5, "In transit", 1766483590,
                       description="Parcel has arrived at station:20-HNI Long Bien 3 Hub",
                       current_location=_location("20-HNI Long Bien 3 Hub"),
                       next_location=_location("BN B Mega SOC"), display_flag_v2=13),
                record("F100", "Pickup From Domestic Seller", 5, "In transit", 1766481413,
                       description="Parcel has been picked up by courier",
                       next_location=_location("20-HNI Long Bien 3 Hub"), display_flag_v2=13),
                record("F050", "Reschedule Pickup", 1, "Preparing to ship", 1766411988,
                       description="Pickup attempt was unsuccessful :Not contactable",
                       reason_code="R102", reason_desc="Không liên hệ được người gửi",
                       issue_type=2, standard_reason_code="P02000",
                       standard_reason_description="Not contactable", display_flag_v2=13),
                record("F050", "Reschedule Pickup", 1, "Preparing to ship", 1766235589,
                       description="Pickup attempt was unsuccessful :Sender Request Reschedule Pickup",
                       reason_code="R105", reason_desc="Người gửi hẹn lại ngày lấy",
                       issue_type=3, standard_reason_code="P03002",
                       standard_reason_description="Sender Request Reschedule Pickup",
                       display_flag_v2=13),
                record("F000", "Manifested", 1, "Preparing to ship", 1766200668,
                       description="Sender is preparing to ship your parcel",
                       reason_code="", reason_desc=""),
            ],
        },
        "is_instant_order": False,
        "is_shopee_market_order": False,
    }
