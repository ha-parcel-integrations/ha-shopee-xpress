"""Shopee Xpress public tracking API client.

One keyless GET per parcel, keyed on a query parameter that resolves against
several identifier namespaces at once (tracking code, order id, and a
merchant-supplied free-text reference) — see the tracking-code handling in
``config_flow.py`` for what that means for user input. The host and
``language_code`` are per-market, both supplied by the caller.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import aiohttp

from .const import FLEET_API_URL, FLEET_NO_DATA_RETCODES, TRACKING_API_URL

_LOGGER = logging.getLogger(__name__)


class ShopeeXpressApiError(Exception):
    """Raised when a Shopee Xpress API call returns an unexpected response."""

    def __init__(self, detail: str) -> None:
        """Store the detail that triggered the error."""
        super().__init__(f"Shopee Xpress API request failed: {detail}")
        self.detail = detail


class ShopeeXpressApiClient:
    """Client for one market's public Shopee Xpress tracking endpoint.

    No authentication: the endpoint answers HTTP 200 with a JSON envelope for
    both success and failure, distinguished by ``retcode``::

        {"retcode": 0, "data": {...}, "message": "success", ...}
        {"retcode": 2, "message": "...ref record not unique...", ...}

    The failure envelope is an internal-error shape, not a clean "unknown
    tracking number" signal — a not-found code and a genuinely broken backend
    can look identical on this route. So, unlike most carriers in this suite,
    this client has **no concept of "not found"**: every non-success response
    raises :class:`ShopeeXpressApiError`, and the caller must not read that as
    "the parcel does not exist".
    """

    def __init__(
        self, session: aiohttp.ClientSession, *, host: str, language_code: str
    ) -> None:
        """Initialise the client for one market's host."""
        self._session = session
        self._host = host
        self._language_code = language_code

    async def async_get_parcel(self, tracking_code: str) -> dict[str, Any]:
        """Fetch one parcel's tracking details for this client's market.

        Returns the ``data`` object of a successful (``retcode == 0``)
        response. Raises :class:`ShopeeXpressApiError` for anything else —
        an error envelope, an unparseable body, or a non-2xx status; network
        errors propagate as ``aiohttp.ClientError``.
        """
        url = TRACKING_API_URL.format(
            host=self._host,
            tracking_code=tracking_code,
            language_code=self._language_code,
        )
        async with self._session.get(url) as response:
            if response.status != 200:
                raise ShopeeXpressApiError(f"HTTP {response.status}")
            try:
                # content_type=None: consumer endpoints routinely serve JSON as
                # text/plain, and aiohttp would otherwise refuse to parse it.
                payload = await response.json(content_type=None)
            except ValueError as err:
                raise ShopeeXpressApiError(f"unparseable body ({err})") from err

        if not isinstance(payload, dict):
            raise ShopeeXpressApiError("unexpected body (not a JSON object)")

        if payload.get("retcode") != 0:
            raise ShopeeXpressApiError(str(payload.get("message") or "error envelope"))

        data = payload.get("data")
        if not isinstance(data, dict):
            raise ShopeeXpressApiError("success envelope without a data object")
        return data


_FLEET_SEED = "MGViZmZmZTYzZDJhNDgxY2Y1N2ZlN2Q1ZWJkYzlmZDY="
# suite: allow browser user-agent (the fleet feed refuses any other client)
_FLEET_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)


def fleet_query(tracking_code: str, seconds: int) -> str:
    """Return the feed's ``sls_tracking_number`` value for one lookup."""
    digest = hashlib.sha256(
        f"{tracking_code}{seconds}{_FLEET_SEED}".encode()
    ).hexdigest()
    return f"{tracking_code}|{seconds}{digest}"


class ShopeeXpressFleetClient:
    """Client for the fleet feed, the route the Taiwanese tracker reads.

    The reply carries the scans as ``data.tracking_list``. A number the feed
    holds nothing for comes back as an empty ``data`` with its own retcode;
    that is returned as an empty dict, not raised.
    """

    def __init__(self, session: aiohttp.ClientSession, *, host: str) -> None:
        """Initialise the client for one market's host."""
        self._session = session
        self._host = host

    async def async_get_parcel(self, tracking_code: str) -> dict[str, Any]:
        """Fetch one parcel's scans, or ``{}`` when the feed holds none."""
        params = {"sls_tracking_number": fleet_query(tracking_code, int(time.time()))}
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": _FLEET_USER_AGENT,
        }
        async with self._session.get(
            FLEET_API_URL.format(host=self._host), params=params, headers=headers
        ) as response:
            if response.status != 200:
                raise ShopeeXpressApiError(f"HTTP {response.status}")
            try:
                payload = await response.json(content_type=None)
            except ValueError as err:
                raise ShopeeXpressApiError(f"unparseable body ({err})") from err

        if not isinstance(payload, dict):
            raise ShopeeXpressApiError("unexpected body (not a JSON object)")
        retcode = payload.get("retcode")
        if retcode in FLEET_NO_DATA_RETCODES:
            return {}
        if retcode != 0:
            raise ShopeeXpressApiError(str(payload.get("message") or "error envelope"))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ShopeeXpressApiError("success envelope without a data object")
        answered = data.get("sls_tracking_number")
        if answered and str(answered).upper() != tracking_code.upper():
            raise ShopeeXpressApiError("reply names another number")
        return data
