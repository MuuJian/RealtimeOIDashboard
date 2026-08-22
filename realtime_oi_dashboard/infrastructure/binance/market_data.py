"""Adapt shared Binance market-data resources."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


FAPI_BASE_URL = "https://fapi.binance.com"
TICKER_24H_URL = f"{FAPI_BASE_URL}/fapi/v1/ticker/24hr"
EXCHANGE_INFO_URL = f"{FAPI_BASE_URL}/fapi/v1/exchangeInfo"


class DirectBinanceMarketData:
    """Load shared Binance resources without adding a cache policy."""

    def __init__(
        self,
        request_json: Callable[..., Any],
        *,
        ticker_attempts: int = 3,
        exchange_info_attempts: int = 3,
    ) -> None:
        if not callable(request_json):
            raise TypeError("request_json must be callable")
        self._request_json = request_json
        self._ticker_attempts = ticker_attempts
        self._exchange_info_attempts = exchange_info_attempts

    def get_tickers(self) -> list:
        return self._request_json(
            TICKER_24H_URL,
            timeout=12,
            attempts=self._ticker_attempts,
        )

    def get_exchange_info(self, *, force_refresh: bool = False) -> dict:
        return self._request_json(
            EXCHANGE_INFO_URL,
            timeout=12,
            attempts=self._exchange_info_attempts,
        )


def resolve_market_data_source(
    *,
    market_data=None,
    legacy_shared_cache=None,
    direct_factory: Callable[[], Any],
    required_methods=("get_tickers", "get_exchange_info"),
):
    """Resolve one explicit market-data source during object construction."""

    if market_data is not None and legacy_shared_cache is not None:
        raise TypeError("pass market_data or shared_rest_cache, not both")
    source = market_data or legacy_shared_cache
    if source is None:
        source = direct_factory()
    for method_name in required_methods:
        if not callable(getattr(source, method_name, None)):
            raise TypeError(
                "market_data is missing required method " + method_name
            )
    return source
