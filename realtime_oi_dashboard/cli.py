"""Command-line configuration for the realtime OI dashboard."""

from __future__ import annotations

import argparse
import os
from math import isfinite

from realtime_oi_dashboard.infrastructure.market_cap_client import (
    DEFAULT_MARKET_CAP_REFRESH_SECONDS,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8777


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def port_number(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if not isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if not isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be 0 or greater")
    return parsed


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Realtime price + batched OI dashboard")
    platform_port = os.environ.get("PORT")
    default_host = os.environ.get("HOST") or (
        "0.0.0.0" if platform_port else DEFAULT_HOST
    )
    parser.add_argument("--host", default=default_host)
    parser.add_argument(
        "--port",
        type=port_number,
        default=platform_port or DEFAULT_PORT,
    )
    parser.add_argument(
        "--oi-batch-size",
        type=positive_int,
        default=25,
        help="symbols per batch",
    )
    parser.add_argument(
        "--oi-batch-delay",
        type=positive_float,
        default=1.0,
        help="seconds between batches",
    )
    parser.add_argument(
        "--oi-workers",
        type=positive_int,
        default=3,
        help="parallel OI requests",
    )
    parser.add_argument(
        "--ticker-cache-seconds",
        type=non_negative_float,
        default=10,
        help="seconds to cache futures 24h ticker; 0 disables the cache",
    )
    parser.add_argument(
        "--funding-cache-seconds",
        type=non_negative_float,
        default=3600,
        help="fallback funding-rate cache duration; 0 disables the cache",
    )
    parser.add_argument(
        "--market-cap-refresh-seconds",
        "--market-cap-cache-seconds",
        dest="market_cap_cache_seconds",
        type=non_negative_float,
        default=DEFAULT_MARKET_CAP_REFRESH_SECONDS,
        help=(
            "seconds between background CoinGecko refresh rounds; "
            "0 uses only the minimum per-page interval"
        ),
    )
    parser.add_argument(
        "--snapshot-save-interval",
        type=non_negative_float,
        default=10,
        help="seconds between atomic cache writes; 0 writes every batch",
    )
    return parser.parse_args(argv)
