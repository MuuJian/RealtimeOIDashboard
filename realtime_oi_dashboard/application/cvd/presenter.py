"""Build the public CVD state without controlling service lifecycle."""

from __future__ import annotations

from realtime_oi_dashboard.application.cvd.shard_allocator import (
    desired_shard_count,
)


class CvdPresenter:
    def __init__(
        self,
        store,
        universe,
        backfill,
        read_shards,
        *,
        now_ms,
        target_symbols_per_shard: int,
    ) -> None:
        self._store = store
        self._universe = universe
        self._backfill = backfill
        self._read_shards = read_shards
        self._now_ms = now_ms
        self._target_symbols_per_shard = target_symbols_per_shard

    def build(self, *, top_error=None, snapshot_error=None) -> dict:
        rows = self._store.published()
        active_symbols = self._store.active_symbols()
        if not rows and active_symbols:
            rows = dict(self._store.publish(now_ms=self._now_ms()))

        metrics = [shard.metrics() for shard in self._read_shards()]
        health_counts = _health_counts(rows.values())
        connected = sum(bool(item["connected"]) for item in metrics)
        diagnostic = (
            top_error or self._universe.last_error or self._backfill.last_error
        )
        return {
            "rows": rows,
            "tracked_symbols": sorted(active_symbols),
            "error": diagnostic,
            "cvd_meta": {
                "serviceHealth": _service_health(
                    health_counts,
                    connected,
                    len(metrics),
                ),
                "universeSymbols": len(active_symbols),
                "desiredShards": max(
                    len(metrics),
                    desired_shard_count(
                        len(active_symbols),
                        target_symbols_per_shard=(
                            self._target_symbols_per_shard
                        ),
                    ),
                ),
                "activeShards": len(metrics),
                "connectedShards": connected,
                "incomingMessagesPerSecond": sum(
                    item["messagesPerSecond"] for item in metrics
                ),
                "processingLagMs": max(
                    (item["processingLagMs"] for item in metrics),
                    default=0.0,
                ),
                "backfillQueueSize": self._backfill.queue_size,
                "healthCounts": health_counts,
                "snapshotError": snapshot_error,
            },
        }


def _health_counts(rows) -> dict[str, int]:
    counts = {
        "warming": 0,
        "live": 0,
        "stale": 0,
        "partial": 0,
        "unavailable": 0,
    }
    for row in rows:
        health = row.get("cvdHealth", "unavailable")
        counts[health] = counts.get(health, 0) + 1
    return counts


def _service_health(health_counts, connected_shards, active_shards):
    if not active_shards:
        return "unavailable"
    if not connected_shards:
        return "stale"
    if connected_shards < active_shards:
        return "partial"
    if any(
        health_counts.get(health, 0)
        for health in ("stale", "partial", "unavailable")
    ):
        return "partial"
    if health_counts.get("warming", 0):
        return "warming"
    if health_counts.get("live", 0):
        return "live"
    return "warming"
