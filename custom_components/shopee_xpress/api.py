"""Shopee Xpress public tracking API client.

One keyless GET per parcel, keyed on a query parameter that resolves against
several identifier namespaces at once (tracking code, order id, and a
merchant-supplied free-text reference) — see the tracking-code handling in
``config_flow.py`` for what that means for user input. The host and
``language_code`` are per-market, both supplied by the caller.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import TRACKING_API_URL

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

    def __init__(self, session: aiohttp.ClientSession, *, host: str, language_code: str) -> None:
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
