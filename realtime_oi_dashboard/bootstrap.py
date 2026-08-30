"""Composition root and process lifecycle for the realtime OI dashboard."""

from __future__ import annotations

from dataclasses import replace

from realtime_oi_dashboard.application.background_service import (
    BackgroundPollerService,
)
from realtime_oi_dashboard.application.oi.poller import DATA_DIR, OIPoller, timestamp
from realtime_oi_dashboard.cli import parse_args
from realtime_oi_dashboard.infrastructure.binance.rest_cache import (
    BinanceRestCache,
)
from realtime_oi_dashboard.server import create_dashboard_server
from realtime_oi_dashboard.profile import resolve_profile
from realtime_oi_dashboard.shared.runtime.services import ServiceGroup


SHUTDOWN_TIMEOUT_SECONDS = 15
_DEFAULT_ALERT_SERVICE = object()


def main(argv=None):
    args = parse_args(argv)
    profile = resolve_profile(getattr(args, "profile", None))
    if not getattr(args, "cvd_enabled", True):
        profile = replace(profile, cvd_enabled=False)
    shared_rest_cache = create_shared_rest_cache()
    cvd_service = None
    if profile.cvd_enabled:
        try:
            cvd_service = create_cvd_service(
                args,
                shared_rest_cache=shared_rest_cache,
            )
        except Exception as exc:
            print(f"{timestamp()} CVD unavailable; continuing with OI dashboard: {exc}")
    alert_service = None
    try:
        alert_service = create_oi_alert_service() if profile.oi_alerts_enabled else None
        oi_service = create_oi_service(
            args,
            cvd_state_provider=cvd_service,
            shared_rest_cache=shared_rest_cache,
            alert_service=alert_service,
        )
    except BaseException:
        _report_close_failures(
            ServiceGroup(
                alerts=("OI alert service", alert_service),
                cvd=("CVD poller", cvd_service),
            ).close_all()
        )
        _close_shared_rest_cache(shared_rest_cache)
        raise
    signal_scan_service = None
    if profile.signal_scan_enabled:
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
    return run_dashboard(
        args,
        oi_service,
        signal_scan_service,
        cvd_service,
        shared_rest_cache,
        profile=profile,
    )


def create_shared_rest_cache():
    return BinanceRestCache()


def create_oi_service(
    args,
    *,
    cvd_state_provider=None,
    shared_rest_cache=None,
    alert_service=_DEFAULT_ALERT_SERVICE,
):
    if alert_service is _DEFAULT_ALERT_SERVICE:
        alert_service = create_oi_alert_service()
    poller = OIPoller(
        batch_size=args.oi_batch_size,
        batch_delay=args.oi_batch_delay,
        oi_workers=args.oi_workers,
        funding_cache_seconds=args.funding_cache_seconds,
        market_cap_cache_seconds=args.market_cap_cache_seconds,
        cvd_state_provider=cvd_state_provider,
        shared_rest_cache=shared_rest_cache,
        alert_service=alert_service,
    )
    return BackgroundPollerService(
        poller,
        thread_name="oi-poller",
        stopped_message="OI poller stopped",
    )


def create_oi_alert_service():
    """Build alert delivery from server-side environment configuration only."""
    from realtime_oi_dashboard.application.oi_alerts.service import OiAlertService
    from realtime_oi_dashboard.infrastructure.storage.oi_alerts import (
        AlertStateRepository,
    )

    return OiAlertService(AlertStateRepository(DATA_DIR / "oi-alerts.json"))


def create_cvd_service(args, *, shared_rest_cache=None):
    from realtime_oi_dashboard.application.cvd.poller import CvdPoller

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
    from realtime_oi_dashboard.application.signal_scan.poller import SignalScanPoller

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
    profile=None,
):
    profile = profile or resolve_profile(getattr(args, "profile", None))
    services = ServiceGroup(
        oi=("OI poller", oi_service),
        signal_scan=("signal scan poller", signal_scan_service),
        cvd=("CVD poller", cvd_service),
    )
    try:
        server = create_dashboard_server(
            args.host,
            args.port,
            oi_state_provider=oi_service,
            signal_scan_state_provider=signal_scan_service,
            oi_alert_provider=oi_service,
            profile=profile,
        )
    except OSError as exc:
        print(f"無法啟動面板: {exc}")
        _report_close_failures(services.close_all())
        _close_shared_rest_cache(shared_rest_cache)
        return 1

    with server:
        try:
            services.start("oi")
        except Exception as exc:
            print(f"無法啟動 OI 輪詢線程: {exc}")
            _report_close_failures(services.close_all())
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
            _stop_service(services, "oi")
            if signal_scan_started:
                _stop_service(services, "signal_scan")
            if cvd_started:
                _stop_service(services, "cvd")
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


def _report_close_failures(failures):
    for failure in failures:
        print(
            f"{timestamp()} failed to close {failure.label}: "
            f"{failure.error}"
        )


def _close_after_start_failure(service, label):
    services = ServiceGroup(target=(label, service))
    _report_close_failures(services.close_all())


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


def _stop_service(services, key):
    result = services.stop(key, timeout=SHUTDOWN_TIMEOUT_SECONDS)
    if result is None:
        return False
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


def _stop_oi_service(service):
    services = ServiceGroup(oi=("OI poller", service))
    _stop_service(services, "oi")


def _stop_signal_scan_service(service):
    _stop_service(
        ServiceGroup(signal_scan=("signal scan poller", service)),
        "signal_scan",
    )


def _stop_cvd_service(service):
    _stop_service(ServiceGroup(cvd=("CVD poller", service)), "cvd")
