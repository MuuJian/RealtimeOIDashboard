"""Composition root and process lifecycle for the realtime OI dashboard."""

from __future__ import annotations

from realtime_oi_dashboard.application.background_service import (
    BackgroundPollerService,
)
from realtime_oi_dashboard.application.poller import OIPoller, timestamp
from realtime_oi_dashboard.application.signal_scan import SignalScanPoller
from realtime_oi_dashboard.cli import parse_args
from realtime_oi_dashboard.infrastructure.binance_rest_cache import (
    BinanceRestCache,
)
from realtime_oi_dashboard.server import create_dashboard_server


SHUTDOWN_TIMEOUT_SECONDS = 15


def main(argv=None):
    args = parse_args(argv)
    shared_rest_cache = create_shared_rest_cache(args)
    cvd_service = None
    if getattr(args, "cvd_enabled", True):
        try:
            cvd_service = create_cvd_service(
                args,
                shared_rest_cache=shared_rest_cache,
            )
        except Exception as exc:
            print(f"{timestamp()} CVD unavailable; continuing with OI dashboard: {exc}")
    try:
        oi_service = create_oi_service(
            args,
            cvd_state_provider=cvd_service,
            shared_rest_cache=shared_rest_cache,
        )
    except BaseException:
        _close_shared_rest_cache(shared_rest_cache)
        raise
    try:
        signal_scan_service = create_signal_scan_service(
            args,
            shared_rest_cache=shared_rest_cache,
        )
    except Exception as exc:
        print(
            f"{timestamp()} signal scan unavailable; "
            f"continuing with the OI dashboard: {exc}"
        )
        signal_scan_service = None
    return run_dashboard(
        args,
        oi_service,
        signal_scan_service,
        cvd_service,
        shared_rest_cache,
    )


def create_shared_rest_cache(args):
    return BinanceRestCache(
        ticker_cache_seconds=getattr(args, "ticker_cache_seconds", 10),
    )


def create_oi_service(
    args,
    *,
    cvd_state_provider=None,
    shared_rest_cache=None,
):
    poller = OIPoller(
        batch_size=args.oi_batch_size,
        batch_delay=args.oi_batch_delay,
        oi_workers=args.oi_workers,
        ticker_cache_seconds=args.ticker_cache_seconds,
        funding_cache_seconds=args.funding_cache_seconds,
        market_cap_cache_seconds=args.market_cap_cache_seconds,
        snapshot_save_interval=args.snapshot_save_interval,
        cvd_state_provider=cvd_state_provider,
        shared_rest_cache=shared_rest_cache,
    )
    return BackgroundPollerService(
        poller,
        thread_name="oi-poller",
        stopped_message="OI poller stopped",
    )


def create_cvd_service(args, *, shared_rest_cache=None):
    from realtime_oi_dashboard.application.cvd import CvdPoller

    poller = CvdPoller(
        shared_rest_cache=shared_rest_cache,
        universe_refresh_seconds=getattr(
            args, "cvd_universe_refresh_seconds", 900
        ),
        target_symbols_per_shard=getattr(
            args, "cvd_target_symbols_per_shard", 150
        ),
        target_messages_per_second_per_shard=getattr(
            args, "cvd_target_messages_per_second_per_shard", 600
        ),
        max_processing_lag_ms=getattr(args, "cvd_max_processing_lag_ms", 500),
        scale_out_confirm_seconds=getattr(
            args, "cvd_scale_out_confirm_seconds", 30
        ),
        backfill_requests_per_second=getattr(
            args, "cvd_backfill_requests_per_second", 4
        ),
        backfill_workers=getattr(args, "cvd_backfill_workers", 2),
        persist_enabled=getattr(args, "cvd_persist_enabled", True),
        persist_minutes=getattr(args, "cvd_persist_minutes", 20),
        persist_interval_seconds=getattr(
            args, "cvd_persist_interval_seconds", 300
        ),
        snapshot_path=getattr(args, "cvd_snapshot_path", None),
        connection_rotate_seconds=getattr(
            args, "cvd_connection_rotate_seconds", 85_800
        ),
    )
    return BackgroundPollerService(
        poller,
        thread_name="cvd-poller",
        stopped_message="CVD poller stopped",
    )


def create_signal_scan_service(args, *, shared_rest_cache=None):
    poller = SignalScanPoller(
        interval_seconds=args.signal_scan_interval,
        shared_rest_cache=shared_rest_cache,
    )
    return BackgroundPollerService(
        poller,
        thread_name="signal-scan-poller",
        stopped_message="Signal scan poller stopped",
    )


def run_dashboard(
    args,
    oi_service,
    signal_scan_service,
    cvd_service=None,
    shared_rest_cache=None,
):
    try:
        server = create_dashboard_server(
            args.host,
            args.port,
            oi_state_provider=oi_service,
            signal_scan_state_provider=signal_scan_service,
        )
    except OSError as exc:
        print(f"無法啟動面板: {exc}")
        _close_after_start_failure(oi_service, "OI poller")
        _close_after_start_failure(signal_scan_service, "signal scan poller")
        _close_after_start_failure(cvd_service, "CVD poller")
        _close_shared_rest_cache(shared_rest_cache)
        return 1

    with server:
        try:
            oi_service.start()
        except Exception as exc:
            print(f"無法啟動 OI 輪詢線程: {exc}")
            _close_after_start_failure(oi_service, "OI poller")
            _close_after_start_failure(signal_scan_service, "signal scan poller")
            _close_after_start_failure(cvd_service, "CVD poller")
            _close_shared_rest_cache(shared_rest_cache)
            return 1

        cvd_started = _start_optional_cvd(cvd_service)
        signal_scan_started = _start_optional_signal_scan(
            server,
            signal_scan_service,
        )

        try:
            log_startup(args)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\nDashboard stopped.")
        finally:
            _stop_shared_rest_cache(shared_rest_cache)
            _stop_oi_service(oi_service)
            if signal_scan_started:
                _stop_signal_scan_service(signal_scan_service)
            if cvd_started:
                _stop_cvd_service(cvd_service)
            _close_shared_rest_cache(shared_rest_cache)
    return 0


def _start_optional_signal_scan(server, signal_scan_service):
    if signal_scan_service is None:
        return False
    try:
        signal_scan_service.start()
    except Exception as exc:
        print(
            f"{timestamp()} signal scan unavailable; "
            f"continuing with the OI dashboard: {exc}"
        )
        _close_after_start_failure(signal_scan_service, "signal scan poller")
        server.signal_scan_state_provider = None
        return False
    return True


def _start_optional_cvd(cvd_service):
    if cvd_service is None:
        return False
    try:
        cvd_service.start()
    except Exception as exc:
        print(f"{timestamp()} CVD unavailable; continuing with OI dashboard: {exc}")
        _close_after_start_failure(cvd_service, "CVD poller")
        return False
    return True


def log_startup(args):
    print(f"Dashboard running at http://{args.host}:{args.port}")
    print("Price uses Binance futures WebSocket in the browser.")
    print(
        f"OI updates {args.oi_batch_size} symbols every "
        f"{args.oi_batch_delay} seconds with {args.oi_workers} workers."
    )


def _close_after_start_failure(service, label):
    if service is None:
        return
    try:
        service.close()
    except Exception as exc:
        print(f"{timestamp()} failed to close {label}: {exc}")


def _close_shared_rest_cache(cache):
    if cache is None:
        return
    try:
        cache.close()
    except Exception as exc:
        print(f"{timestamp()} failed to close shared Binance REST cache: {exc}")


def _stop_shared_rest_cache(cache):
    if cache is None:
        return
    try:
        cache.stop()
    except Exception as exc:
        print(f"{timestamp()} failed to stop shared Binance REST cache: {exc}")


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


def _stop_signal_scan_service(service):
    if not service.stop(timeout=SHUTDOWN_TIMEOUT_SECONDS):
        print(
            f"{timestamp()} signal scan poller did not stop within "
            f"{SHUTDOWN_TIMEOUT_SECONDS} seconds"
        )


def _stop_cvd_service(service):
    if not service.stop(timeout=SHUTDOWN_TIMEOUT_SECONDS):
        print(
            f"{timestamp()} CVD poller did not stop within "
            f"{SHUTDOWN_TIMEOUT_SECONDS} seconds"
        )
