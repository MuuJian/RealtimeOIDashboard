"""Command-line configuration for the realtime OI dashboard."""

from __future__ import annotations

import argparse
import os
from math import isfinite

from realtime_oi_dashboard.infrastructure.coingecko.client import (
    DEFAULT_MARKET_CAP_REFRESH_SECONDS,
)
from realtime_oi_dashboard.profile import FULL_PROFILE, PROFILE_NAMES


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


def profile_name(value: str) -> str:
    if value not in PROFILE_NAMES:
        choices = ", ".join(PROFILE_NAMES)
        raise argparse.ArgumentTypeError(f"must be one of: {choices}")
    return value


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Realtime price + batched OI dashboard")
    platform_port = os.environ.get("PORT")
    default_host = os.environ.get("HOST") or (
        "0.0.0.0" if platform_port else DEFAULT_HOST
    )
    parser.add_argument("--host", default=default_host)
    parser.add_argument(
        "--profile",
        type=profile_name,
        choices=PROFILE_NAMES,
        default=os.environ.get("DASHBOARD_PROFILE", FULL_PROFILE),
        help="runtime feature profile (full or stable)",
    )
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
        "--signal-scan-interval",
        type=positive_float,
        default=60,
        help="seconds between signal-scan (trend/volatility) refreshes",
    )
    parser.add_argument(
        "--disable-cvd",
        dest="cvd_enabled",
        action="store_false",
        default=True,
        help="disable the backend all-symbol CVD service",
    )
    parser.add_argument(
        "--cvd-universe-refresh-seconds",
        type=positive_float,
        default=900,
        help="seconds between shared exchangeInfo universe checks",
    )
    parser.add_argument(
        "--cvd-target-symbols-per-shard",
        type=positive_int,
        default=150,
        help="soft symbol capacity for each dynamically created CVD shard",
    )
    parser.add_argument(
        "--cvd-target-messages-per-second-per-shard",
        type=positive_float,
        default=600,
        help="sustained message-rate target for CVD scale-out",
    )
    parser.add_argument(
        "--cvd-max-processing-lag-ms",
        type=positive_float,
        default=500,
        help="sustained CVD processing-lag threshold for scale-out",
    )
    parser.add_argument(
        "--cvd-scale-out-confirm-seconds",
        type=positive_float,
        default=30,
        help="seconds an overload must persist before adding a CVD shard",
    )
    parser.add_argument(
        "--cvd-backfill-requests-per-second",
        type=positive_float,
        default=4,
        help="global CVD missing-minute repair request rate",
    )
    parser.add_argument(
        "--cvd-backfill-workers",
        type=positive_int,
        default=2,
        help="bounded workers for CVD missing-minute repair",
    )
    parser.add_argument(
        "--disable-cvd-persist",
        dest="cvd_persist_enabled",
        action="store_false",
        default=True,
        help="disable restart-safe CVD JSON snapshots",
    )
    parser.add_argument(
        "--cvd-persist-minutes",
        type=positive_int,
        default=20,
        help="number of recent CVD minute buckets kept in JSON",
    )
    parser.add_argument(
        "--cvd-persist-interval-seconds",
        type=positive_float,
        default=300,
        help="seconds between atomic CVD JSON snapshots",
    )
    parser.add_argument(
        "--cvd-snapshot-path",
        default=None,
        help="optional path for the CVD JSON snapshot",
    )
    parser.add_argument(
        "--cvd-connection-rotate-seconds",
        type=positive_float,
        default=85_800,
        help="seconds before a smooth CVD shard connection rotation",
    )
    return parser.parse_args(argv)
