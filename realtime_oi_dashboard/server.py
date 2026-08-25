"""HTTP transport for the realtime OI dashboard."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from realtime_oi_dashboard.application.background_service import (
    BackgroundServiceStopped,
)
from realtime_oi_dashboard.application.oi.poller import timestamp
from realtime_oi_dashboard.domain.oi_alerts.model import validate_alert_config
from realtime_oi_dashboard.web import DashboardRequestHandler
from realtime_oi_dashboard.profile import DashboardProfile, resolve_profile


ROOT_DIR = Path(__file__).resolve().parent
INDEX_FILE = ROOT_DIR / "index.html"
STATIC_DIR = ROOT_DIR / "static"
MAX_JSON_BODY_BYTES = 64 * 1024
SAFE_ALERT_LOAD_ERROR = "Saved OI alert state could not be loaded; defaults are active"


class DashboardHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address,
        request_handler_class,
        *,
        oi_state_provider,
        signal_scan_state_provider=None,
        oi_alert_provider=None,
        profile: DashboardProfile | None = None,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.oi_state_provider = oi_state_provider
        self.signal_scan_state_provider = signal_scan_state_provider
        self.oi_alert_provider = oi_alert_provider
        self.profile = profile or resolve_profile(None)

    def handle_error(self, request, client_address) -> None:
        _, error, _ = sys.exc_info()
        if isinstance(error, ConnectionError):
            return
        super().handle_error(request, client_address)


class DashboardHandler(DashboardRequestHandler):
    index_file = INDEX_FILE
    static_dir = STATIC_DIR

    def do_GET(self) -> None:
        self.serve_request()

    def do_HEAD(self) -> None:
        self.serve_request()

    def do_POST(self) -> None:
        self.serve_mutation()

    def do_PUT(self) -> None:
        self.serve_mutation()

    def serve_request(self) -> None:
        try:
            parsed = urlparse(self.path)
        except ValueError:
            self.send_error(400, "Invalid request target")
            return
        if parsed.path == "/livez":
            self.send_json({"status": "ok"})
            return
        if parsed.path == "/readyz":
            self.send_readiness()
            return
        if parsed.path == "/runtime-config.js":
            self.send_runtime_config()
            return
        if self.send_dashboard_asset(parsed.path):
            return
        if parsed.path == "/api/oi":
            self.send_oi_state()
            return
        if parsed.path == "/api/signal-scan":
            if not self.feature_enabled("signal_scan_enabled"):
                self.send_error(404)
                return
            self.send_signal_scan_state()
            return
        if parsed.path == "/api/oi-alerts":
            if not self.feature_enabled("oi_alerts_enabled"):
                self.send_error(404)
                return
            self.send_oi_alert_state()
            return
        self.send_error(404)

    def serve_mutation(self) -> None:
        try:
            parsed = urlparse(self.path)
        except ValueError:
            self.send_json({"error": "Invalid request target"}, status=400)
            return
        if parsed.path not in {
            "/api/oi-alerts/config",
            "/api/oi-alerts/test-message",
        }:
            self.send_error(404)
            return
        if not self.feature_enabled("oi_alerts_enabled"):
            self.send_error(404)
            return
        try:
            payload = self.read_json_body()
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return

        if parsed.path == "/api/oi-alerts/config" and self.command == "PUT":
            self.update_oi_alert_config(payload)
            return
        if parsed.path == "/api/oi-alerts/test-message" and self.command == "POST":
            self.send_oi_alert_test_message()
            return
        self.send_error(404)

    def read_json_body(self) -> dict:
        content_type = self.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            raise ValueError("Content-Type must be application/json")
        raw_length = self.headers.get("Content-Length")
        try:
            content_length = int(raw_length)
        except (TypeError, ValueError):
            raise ValueError("Content-Length is required") from None
        if content_length < 0 or content_length > MAX_JSON_BODY_BYTES:
            raise ValueError("JSON request body exceeds 64 KiB")
        body = self.rfile.read(content_length)
        if len(body) != content_length:
            raise ValueError("Incomplete JSON request body")
        try:
            payload = json.loads(
                body.decode("utf-8"), parse_constant=_reject_json_constant
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise ValueError("Malformed JSON request body") from None
        if not isinstance(payload, dict):
            raise ValueError("JSON request body must be an object")
        return payload

    def send_oi_state(self):
        provider = getattr(self.server, "oi_state_provider", None)
        if provider is None:
            self.send_json({"error": "OI poller unavailable"}, status=503)
            return
        try:
            self.send_json(provider.get_state())
        except BackgroundServiceStopped as exc:
            self.send_json({"error": str(exc)}, status=503)
        except Exception as exc:
            print(f"{timestamp()} failed to serve OI state: {exc}")
            self.send_json({"error": "OI state unavailable"}, status=503)

    def feature_enabled(self, attribute: str) -> bool:
        profile = getattr(self.server, "profile", resolve_profile(None))
        return bool(getattr(profile, attribute, False))

    def send_runtime_config(self) -> None:
        profile = getattr(self.server, "profile", resolve_profile(None))
        config = json.dumps(profile.public_config(), separators=(",", ":"))
        body = (
            "globalThis.__REALTIME_OI_DASHBOARD_CONFIG__=" + config + ";"
            "document.documentElement.dataset.dashboardProfile="
            f"{json.dumps(profile.name)};"
        ).encode("utf-8")
        self._send_body(
            body,
            content_type="application/javascript; charset=utf-8",
            cache_control="no-store",
        )

    def send_signal_scan_state(self):
        provider = getattr(self.server, "signal_scan_state_provider", None)
        if provider is None:
            self.send_json({"error": "Signal scan poller unavailable"}, status=503)
            return
        try:
            state = provider.get_state()
            self.send_json(
                _enrich_signal_scan_state(
                    state,
                    getattr(self.server, "oi_state_provider", None),
                )
            )
        except BackgroundServiceStopped as exc:
            self.send_json({"error": str(exc)}, status=503)
        except Exception as exc:
            print(f"{timestamp()} failed to serve signal scan state: {exc}")
            self.send_json({"error": "Signal scan state unavailable"}, status=503)

    def send_oi_alert_state(self) -> None:
        provider = self.oi_alert_provider()
        if provider is None:
            return
        try:
            self.send_json(_public_alert_state(provider.get_alert_state()))
        except BackgroundServiceStopped:
            self.send_json({"error": "OI alert provider unavailable"}, status=503)
        except Exception as exc:
            print(f"{timestamp()} failed to serve OI alert state: {exc}")
            self.send_json({"error": "OI alert state unavailable"}, status=503)

    def update_oi_alert_config(self, payload: dict) -> None:
        try:
            config = validate_alert_config(
                payload.get("enabled"),
                payload.get("thresholds"),
                scale_alerts_enabled=payload.get("scale_alerts_enabled", True),
                change_window_minutes=payload.get("change_window_minutes", 15),
                min_oi_change_percent=payload.get("min_oi_change_percent", 3.0),
                min_price_change_percent=payload.get("min_price_change_percent", 0.5),
                require_cvd_confirmation=payload.get("require_cvd_confirmation", False),
                cooldown_minutes=payload.get("cooldown_minutes", 30),
                symbols=payload.get("symbols", ()),
            )
            for field in ("enabled", "scale_alerts_enabled", "require_cvd_confirmation"):
                if field in payload and not isinstance(payload.get(field), bool):
                    raise ValueError(f"{field} must be a boolean")
            sanitized_payload = {
                "enabled": config.enabled,
                "thresholds": list(config.thresholds),
                "scale_alerts_enabled": config.scale_alerts_enabled,
                "change_window_minutes": config.change_window_minutes,
                "min_oi_change_percent": config.min_oi_change_percent,
                "min_price_change_percent": config.min_price_change_percent,
                "require_cvd_confirmation": config.require_cvd_confirmation,
                "cooldown_minutes": config.cooldown_minutes,
                "symbols": list(config.symbols),
            }
        except (TypeError, ValueError, OverflowError):
            self.send_json({"error": "Invalid alert configuration"}, status=400)
            return

        provider = self.oi_alert_provider()
        if provider is None:
            return
        try:
            self.send_json(
                _public_alert_state(provider.update_alert_config(sanitized_payload))
            )
        except BackgroundServiceStopped:
            self.send_json({"error": "OI alert provider unavailable"}, status=503)
        except (TypeError, ValueError, OverflowError):
            self.send_json({"error": "Invalid alert configuration"}, status=400)
        except Exception as exc:
            print(f"{timestamp()} failed to update OI alert configuration: {exc}")
            self.send_json({"error": "OI alert configuration unavailable"}, status=503)

    def send_oi_alert_test_message(self) -> None:
        provider = self.oi_alert_provider()
        if provider is None:
            return
        try:
            result = provider.send_alert_test_message()
            self.send_json(_public_alert_test_result(result))
        except BackgroundServiceStopped:
            self.send_json({"error": "OI alert provider unavailable"}, status=503)
        except Exception as exc:
            print(f"{timestamp()} failed to queue OI alert test message: {exc}")
            self.send_json({"error": "OI alert test message unavailable"}, status=503)

    def oi_alert_provider(self):
        provider = getattr(self.server, "oi_alert_provider", None)
        if provider is None:
            self.send_json({"error": "OI alert provider unavailable"}, status=503)
            return None
        return provider

    def send_readiness(self) -> None:
        oi_state, oi_summary = _oi_readiness(
            getattr(self.server, "oi_state_provider", None)
        )
        ready = oi_state is not None
        payload = {
            "status": "ready" if ready else "not_ready",
            "components": {"oi": oi_summary},
        }
        profile = getattr(self.server, "profile", resolve_profile(None))
        if profile.signal_scan_enabled:
            payload["components"]["signalScan"] = _signal_scan_readiness(
                getattr(self.server, "signal_scan_state_provider", None)
            )
        if profile.cvd_enabled:
            payload["components"]["cvd"] = _cvd_readiness(oi_state)
        self.send_json(payload, status=200 if ready else 503)


def _oi_readiness(provider):
    if provider is None:
        return None, {"status": "unavailable", "rows": 0}
    try:
        state = provider.get_state()
    except BackgroundServiceStopped:
        return None, {"status": "stopped", "rows": 0}
    except Exception:
        return None, {"status": "error", "rows": 0}

    if not isinstance(state, dict):
        return None, {"status": "invalid", "rows": 0}
    rows = state.get("rows")
    if not isinstance(rows, list):
        return None, {"status": "invalid", "rows": 0}
    row_count = sum(
        isinstance(row, dict)
        and isinstance(row.get("symbol"), str)
        and bool(row["symbol"])
        for row in rows
    )
    if row_count == 0:
        return None, {"status": "warming", "rows": 0}
    component_status = "degraded" if state.get("error") else "ready"
    return state, {"status": component_status, "rows": row_count}


def _enrich_signal_scan_state(state: object, oi_provider) -> dict:
    if not isinstance(state, dict):
        raise ValueError("signal scan state is invalid")
    try:
        features = oi_provider.get_signal_features() if oi_provider is not None else {}
    except Exception:
        features = {}
    if not isinstance(features, dict):
        features = {}
    enriched = dict(state)
    for group_name in ("bulls", "bears", "spikes"):
        rows = state.get(group_name)
        if not isinstance(rows, list):
            continue
        enriched[group_name] = [
            _enrich_signal_row(row, features.get(row.get("symbol")), group_name)
            if isinstance(row, dict)
            else row
            for row in rows
        ]
    enriched["feature_window_minutes"] = _feature_window(features)
    return enriched


def _enrich_signal_row(row: dict, feature: object, group_name: str) -> dict:
    feature = feature if isinstance(feature, Mapping) else {}
    oi_change = _finite_or_none(feature.get("oi_change_percent"))
    price_change = _finite_or_none(feature.get("price_change_percent"))
    cvd_ratio = _finite_or_none(feature.get("cvd_ratio"))
    funding = _finite_or_none(feature.get("funding_rate_percent"))
    direction = {
        "bulls": "多頭趨勢",
        "bears": "空頭趨勢",
        "spikes": "波動突增",
    }.get(group_name, "市場訊號")
    context = []
    if oi_change is not None:
        context.append(f"OI {oi_change:+.2f}%")
    if cvd_ratio is not None:
        context.append(f"CVD {cvd_ratio:+.1%}")
    if context:
        reason = f"{direction}；" + "，".join(context)
    else:
        reason = f"{direction}；OI 窗口預熱中"
    return {
        **row,
        "oiChangePercent": oi_change,
        "oiValueChangePercent": _finite_or_none(
            feature.get("oi_value_change_percent")
        ),
        "windowPriceChangePercent": price_change,
        "currentOiValue": _finite_or_none(feature.get("current_oi_value")),
        "cvd15mRatio": cvd_ratio,
        "cvdDirection": feature.get("cvd_direction")
        if isinstance(feature.get("cvd_direction"), str)
        else None,
        "fundingRatePercent": funding,
        "oiUpdatedAt": feature.get("exchange_timestamp_ms")
        if isinstance(feature.get("exchange_timestamp_ms"), int)
        else None,
        "signalReason": reason,
    }


def _feature_window(features: Mapping) -> int | None:
    for feature in features.values():
        if isinstance(feature, Mapping):
            value = feature.get("window_minutes")
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None


def _finite_or_none(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    from math import isfinite

    parsed = float(value)
    return parsed if isfinite(parsed) else None


def _signal_scan_readiness(provider) -> dict:
    if provider is None:
        return {"status": "unavailable", "signals": 0}
    try:
        state = provider.get_state()
    except BackgroundServiceStopped:
        return {"status": "stopped", "signals": 0}
    except Exception:
        return {"status": "error", "signals": 0}

    if not isinstance(state, dict):
        return {"status": "invalid", "signals": 0}
    groups = [state.get(name) for name in ("bulls", "bears", "spikes")]
    if not all(isinstance(group, list) for group in groups):
        return {"status": "invalid", "signals": 0}
    signal_count = sum(
        isinstance(signal, dict)
        for group in groups
        for signal in group
    )
    if state.get("error") or state.get("partial"):
        status = "degraded"
    elif state.get("saved_at") is None:
        status = "warming"
    else:
        status = "ready"
    return {"status": status, "signals": signal_count}


def _cvd_readiness(oi_state) -> dict:
    if not isinstance(oi_state, dict):
        return {"status": "unavailable", "health": "unavailable"}
    meta = oi_state.get("cvd_meta")
    if not isinstance(meta, dict):
        return {"status": "unavailable", "health": "unavailable"}
    health = meta.get("serviceHealth")
    if health == "live":
        status = "ready"
    elif health == "warming":
        status = "warming"
    elif health in {"partial", "stale"}:
        status = "degraded"
    else:
        health = "unavailable"
        status = "unavailable"
    return {"status": status, "health": health}


def _public_alert_state(state: object) -> dict:
    if not isinstance(state, Mapping):
        raise ValueError("alert state is invalid")
    config = state.get("config")
    if not isinstance(config, Mapping):
        raise ValueError("alert configuration is invalid")
    validated_config = validate_alert_config(
        config.get("enabled"),
        config.get("thresholds"),
        scale_alerts_enabled=config.get("scale_alerts_enabled", True),
        change_window_minutes=config.get("change_window_minutes", 15),
        min_oi_change_percent=config.get("min_oi_change_percent", 3.0),
        min_price_change_percent=config.get("min_price_change_percent", 0.5),
        require_cvd_confirmation=config.get("require_cvd_confirmation", False),
        cooldown_minutes=config.get("cooldown_minutes", 30),
        symbols=config.get("symbols", ()),
    )
    return {
        "schema_version": 2,
        "config": {
            "enabled": validated_config.enabled,
            "thresholds": list(validated_config.thresholds),
            "scale_alerts_enabled": validated_config.scale_alerts_enabled,
            "change_window_minutes": validated_config.change_window_minutes,
            "min_oi_change_percent": validated_config.min_oi_change_percent,
            "min_price_change_percent": validated_config.min_price_change_percent,
            "require_cvd_confirmation": validated_config.require_cvd_confirmation,
            "cooldown_minutes": validated_config.cooldown_minutes,
            "symbols": list(validated_config.symbols),
        },
        "telegram": _public_telegram_status(state.get("notifier")),
        "storage": _public_alert_storage_status(state.get("storage")),
        "active": _public_alert_records(
            state.get("active"),
            (
                "symbol",
                "event_type",
                "oi_value",
                "threshold",
                "signal",
                "oi_change_percent",
                "price_change_percent",
                "explanation",
                "as_of",
            ),
        ),
        "events": _public_alert_events(state.get("events")),
    }


def _public_alert_test_result(result: object) -> dict:
    if not isinstance(result, Mapping) or not isinstance(result.get("queued"), bool):
        raise ValueError("alert test result is invalid")
    return {
        "queued": result["queued"],
        "telegram": _public_telegram_status(result.get("notifier")),
    }


def _public_telegram_status(status: object) -> dict:
    if not isinstance(status, Mapping) or not isinstance(status.get("status"), str):
        raise ValueError("Telegram status is invalid")
    last_error = status.get("last_error")
    last_attempt_at = status.get("last_attempt_at")
    if last_error is not None and not isinstance(last_error, str):
        raise ValueError("Telegram status is invalid")
    if last_attempt_at is not None and not isinstance(last_attempt_at, str):
        raise ValueError("Telegram status is invalid")
    return {
        "status": status["status"],
        "last_error": last_error,
        "last_attempt_at": last_attempt_at,
    }


def _public_alert_storage_status(status: object) -> dict:
    if not isinstance(status, Mapping) or status.get("status") not in {
        "ok",
        "load_error",
    }:
        raise ValueError("alert storage status is invalid")
    last_error = status.get("last_error")
    if last_error is not None and not isinstance(last_error, str):
        raise ValueError("alert storage status is invalid")
    if status["status"] == "load_error" and not last_error:
        raise ValueError("alert storage status is invalid")
    return {
        "status": status["status"],
        "last_error": SAFE_ALERT_LOAD_ERROR if status["status"] == "load_error" else None,
    }


def _public_alert_events(records: object) -> list[dict]:
    public_records = _public_alert_records(
        records,
        (
            "symbol",
            "event_id",
            "event_type",
            "oi_value",
            "threshold",
            "signal",
            "oi_change_percent",
            "price_change_percent",
            "explanation",
            "exchange_timestamp_ms",
            "triggered_at",
            "delivery_status",
            "failure_reason",
            "last_attempt_at",
        ),
    )
    for record in public_records:
        if record["delivery_status"] != "failed":
            record["failure_reason"] = None
            continue
        if record["failure_reason"] not in {
            "Telegram delivery failed",
            "delivery queue is full",
        }:
            record["failure_reason"] = "Telegram delivery failed"
        if not isinstance(record["last_attempt_at"], str) or not record[
            "last_attempt_at"
        ].strip():
            raise ValueError("failed alert event diagnostics are invalid")
    return public_records


def _public_alert_records(records: object, fields: tuple[str, ...]) -> list[dict]:
    if not isinstance(records, list):
        raise ValueError("alert records are invalid")
    public_records = []
    for record in records:
        if not isinstance(record, Mapping) or any(
            field not in record for field in fields
        ):
            raise ValueError("alert record is invalid")
        public_records.append({field: record[field] for field in fields})
    return public_records


def _reject_json_constant(value: str):
    raise ValueError(f"Invalid JSON constant: {value}")


def create_dashboard_server(
    host,
    port,
    *,
    oi_state_provider,
    signal_scan_state_provider=None,
    oi_alert_provider=None,
    profile=None,
):
    return DashboardHTTPServer(
        (host, port),
        DashboardHandler,
        oi_state_provider=oi_state_provider,
        signal_scan_state_provider=signal_scan_state_provider,
        oi_alert_provider=oi_alert_provider,
        profile=profile,
    )
