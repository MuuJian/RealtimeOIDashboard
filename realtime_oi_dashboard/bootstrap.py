"""Composition root and process lifecycle for the realtime OI dashboard."""

from __future__ import annotations

from realtime_oi_dashboard.application.background_service import (
    BackgroundPollerService,
)
from realtime_oi_dashboard.application.poller import OIPoller, timestamp
from realtime_oi_dashboard.cli import parse_args
from realtime_oi_dashboard.server import create_dashboard_server


SHUTDOWN_TIMEOUT_SECONDS = 15


def main(argv=None):
    args = parse_args(argv)
    oi_service = create_oi_service(args)
    return run_dashboard(args, oi_service)


def create_oi_service(args):
    poller = OIPoller(
        batch_size=args.oi_batch_size,
        batch_delay=args.oi_batch_delay,
        oi_workers=args.oi_workers,
        oi_history_cache_seconds=args.oi_history_cache_seconds,
        ticker_cache_seconds=args.ticker_cache_seconds,
        funding_cache_seconds=args.funding_cache_seconds,
        market_cap_cache_seconds=args.market_cap_cache_seconds,
        snapshot_save_interval=args.snapshot_save_interval,
    )
    return BackgroundPollerService(
        poller,
        thread_name="oi-poller",
        stopped_message="OI poller stopped",
    )


def run_dashboard(args, oi_service):
    try:
        server = create_dashboard_server(
            args.host,
            args.port,
            oi_state_provider=oi_service,
        )
    except OSError as exc:
        print(f"无法启动面板: {exc}")
        _close_after_start_failure(oi_service)
        return 1

    with server:
        try:
            oi_service.start()
        except Exception as exc:
            print(f"无法启动 OI 轮询线程: {exc}")
            _close_after_start_failure(oi_service)
            return 1

        try:
            log_startup(args)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\nDashboard stopped.")
        finally:
            _stop_oi_service(oi_service)
    return 0


def log_startup(args):
    print(f"Dashboard running at http://{args.host}:{args.port}")
    print("Price uses Binance futures WebSocket in the browser.")
    print(
        f"OI updates {args.oi_batch_size} symbols every "
        f"{args.oi_batch_delay} seconds with {args.oi_workers} workers."
    )


def _close_after_start_failure(service):
    try:
        service.close()
    except Exception as exc:
        print(f"{timestamp()} failed to close OI poller: {exc}")


def _stop_oi_service(service):
    if not service.stop(timeout=SHUTDOWN_TIMEOUT_SECONDS):
        print(
            f"{timestamp()} OI poller did not stop within "
            f"{SHUTDOWN_TIMEOUT_SECONDS} seconds"
        )
        return
    try:
        service.worker.save_state(force=True)
    except Exception as exc:
        print(f"{timestamp()} failed to save final OI cache: {exc}")
