"""Runtime feature profiles for the dashboard."""

from __future__ import annotations

from dataclasses import dataclass


FULL_PROFILE = "full"
STABLE_PROFILE = "stable"
PROFILE_NAMES = (FULL_PROFILE, STABLE_PROFILE)


@dataclass(frozen=True, slots=True)
class DashboardProfile:
    name: str
    cvd_enabled: bool
    signal_scan_enabled: bool
    oi_alerts_enabled: bool

    def public_config(self) -> dict:
        return {
            "profile": self.name,
            "features": {
                "oi": True,
                "cvd": self.cvd_enabled,
                "signalScan": self.signal_scan_enabled,
                "oiAlerts": self.oi_alerts_enabled,
            },
        }


PROFILES = {
    FULL_PROFILE: DashboardProfile(
        name=FULL_PROFILE,
        cvd_enabled=True,
        signal_scan_enabled=True,
        oi_alerts_enabled=True,
    ),
    STABLE_PROFILE: DashboardProfile(
        name=STABLE_PROFILE,
        cvd_enabled=False,
        signal_scan_enabled=False,
        oi_alerts_enabled=False,
    ),
}


def resolve_profile(name: str | None) -> DashboardProfile:
    try:
        return PROFILES[name or FULL_PROFILE]
    except KeyError:
        raise ValueError(f"Unknown dashboard profile: {name}") from None
