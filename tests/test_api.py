"""Tests for the Shopee Xpress API client.

No "not found" branch here on purpose: the real failure envelope
(``retcode != 0``) is an internal-error shape indistinguishable from a
genuinely broken backend, so every non-success response raises — the client
has no concept of "this code does not exist".
"""
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.shopee_xpress.api import (
    ShopeeXpressApiClient,
    ShopeeXpressApiError,
)

from .payloads import MY_CODE, envelope, error_envelope, my_data


def _session_returning(status: int, body: object = None) -> MagicMock:
    response = AsyncMock()
    response.status = status
    if isinstance(body, str):
        response.json = AsyncMock(side_effect=json.JSONDecodeError("x", body, 0))
    else:
        response.json = AsyncMock(return_value=body)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=ctx)
    return session


def _client(session) -> ShopeeXpressApiClient:
    return ShopeeXpressApiClient(session, host="spx.com.my", language_code="ms")


async def test_get_parcel_returns_data_on_success():
    session = _session_returning(200, envelope(my_data()))
    client = _client(session)

    data = await client.async_get_parcel(MY_CODE)

    assert data["order_info"]["spx_tn"] == MY_CODE
    # the tracking code, host and language_code all end up in the URL
    url = session.get.call_args[0][0]
    assert MY_CODE in url
    assert "spx.com.my" in url
    assert "language_code=ms" in url


async def test_get_parcel_raises_on_error_envelope():
    """The internal-error shape (retcode != 0) is not a "not found" signal."""
    client = _client(_session_returning(200, error_envelope("ref record not unique")))
    with pytest.raises(ShopeeXpressApiError) as err:
        await client.async_get_parcel(MY_CODE)
    assert "ref record not unique" in str(err.value)


async def test_get_parcel_raises_on_error_envelope_without_message():
    client = _client(_session_returning(200, {"retcode": 2}))
    with pytest.raises(ShopeeXpressApiError):
        await client.async_get_parcel(MY_CODE)


async def test_get_parcel_raises_on_success_envelope_without_data():
    """A `retcode: 0` body that somehow has no `data` object is still a bug
    to surface, not something to paper over as a normal empty result."""
    client = _client(_session_returning(200, {"retcode": 0, "message": "success"}))
    with pytest.raises(ShopeeXpressApiError):
        await client.async_get_parcel(MY_CODE)


async def test_get_parcel_raises_on_success_envelope_with_non_dict_data():
    client = _client(_session_returning(200, {"retcode": 0, "data": "oops"}))
    with pytest.raises(ShopeeXpressApiError):
        await client.async_get_parcel(MY_CODE)


async def test_get_parcel_raises_on_non_200_status():
    client = _client(_session_returning(500, {}))
    with pytest.raises(ShopeeXpressApiError) as err:
        await client.async_get_parcel(MY_CODE)
    assert "500" in str(err.value)


async def test_get_parcel_raises_on_unparseable_body():
    client = _client(_session_returning(200, "not json"))
    with pytest.raises(ShopeeXpressApiError):
        await client.async_get_parcel(MY_CODE)


async def test_get_parcel_raises_on_non_object_body():
    client = _client(_session_returning(200, ["not", "a", "dict"]))
    with pytest.raises(ShopeeXpressApiError):
        await client.async_get_parcel(MY_CODE)


async def test_get_parcel_propagates_network_error():
    """ClientError is left alone — DataUpdateCoordinator already wraps it."""
    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))
    client = _client(session)
    with pytest.raises(aiohttp.ClientError):
        await client.async_get_parcel(MY_CODE)


async def test_get_parcel_uses_this_clients_market_for_every_call():
    """Host/language_code are fixed per client instance, not per call."""
    session = _session_returning(200, envelope(my_data()))
    client = ShopeeXpressApiClient(session, host="spx.co.th", language_code="th")
    await client.async_get_parcel("TH000000000000")
    url = session.get.call_args[0][0]
    assert "spx.co.th" in url
    assert "language_code=th" in url
