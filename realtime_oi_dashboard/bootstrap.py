"""Composition root and process lifecycle for the realtime OI dashboard."""

from __future__ import annotations

from realtime_oi_dashboard.application.background_service import (
    BackgroundPollerService,
)
from realtime_oi_dashboard.application.oi.poller import OIPoller, timestamp
from realtime_oi_dashboard.cli import parse_args
from realtime_oi_dashboard.server import create_dashboard_server
from realtime_oi_dashboard.shared.runtime.services import ServiceGroup


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
    services = ServiceGroup(oi=("OI poller", oi_service))
    try:
        server = create_dashboard_server(
            args.host,
            args.port,
            oi_state_provider=oi_service,
        )
    except OSError as exc:
        print(f"無法啟動面板: {exc}")
        _report_close_failures(services.close_all())
        return 1

    with server:
        try:
            services.start("oi")
        except Exception as exc:
            print(f"無法啟動 OI 輪詢線程: {exc}")
            _report_close_failures(services.close_all())
            return 1

        try:
            log_startup(args)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\nDashboard stopped.")
        finally:
            if _stop_service(services, "oi"):
                _save_final_oi_state(oi_service)
    return 0


def log_startup(args):
    print(f"Dashboard running at http://{args.host}:{args.port}")
    print("Price uses Binance futures WebSocket in the browser.")
    print(
        f"OI updates {args.oi_batch_size} symbols every "
        f"{args.oi_batch_delay} seconds with {args.oi_workers} workers."
    )


def _close_after_start_failure(service, label):
    _report_close_failures(
        ServiceGroup(target=(label, service)).close_all()
    )


def _report_close_failures(failures):
    for failure in failures:
        print(
            f"{timestamp()} failed to close {failure.label}: "
            f"{failure.error}"
        )


def _stop_service(services, key):
    result = services.stop(key, timeout=SHUTDOWN_TIMEOUT_SECONDS)
    if result.error is not None:
        print(f"{timestamp()} failed to stop {result.label}: {result.error}")
        return False
    if not result.stopped:
        print(
            f"{timestamp()} {result.label} did not stop within "
            f"{SHUTDOWN_TIMEOUT_SECONDS} seconds"
        )
        return False
    return True


def _save_final_oi_state(service):
    try:
        service.worker.save_state(force=True)
    except Exception as exc:
        print(f"{timestamp()} failed to save final OI cache: {exc}")


def _stop_oi_service(service):
    services = ServiceGroup(oi=("OI poller", service))
    if _stop_service(services, "oi"):
        _save_final_oi_state(service)
