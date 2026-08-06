"""Thread and executor lifecycle for the dashboard polling service."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from realtime_oi_dashboard.domain.errors import PollingStopped


class DashboardRuntime:
    """Run polling and market-cap refresh workers until cancellation."""

    def __init__(
        self,
        update_once,
        refresh_market_caps,
        active_symbols_provider,
        handle_batch_error,
        close,
        stop_event,
        *,
        batch_delay: float,
        workers: int,
        log=print,
        timestamp=lambda: "",
    ) -> None:
        self.update_once = update_once
        self.refresh_market_caps = refresh_market_caps
        self.active_symbols_provider = active_symbols_provider
        self.handle_batch_error = handle_batch_error
        self.close = close
        self.stop_event = stop_event
        self.batch_delay = batch_delay
        self.workers = workers
        self.log = log
        self.timestamp = timestamp

    def run_forever(self) -> None:
        executor = None
        market_cap_thread = None
        try:
            if self.stop_event.is_set():
                return
            market_cap_thread = threading.Thread(
                target=self.refresh_market_caps,
                args=(self.active_symbols_provider,),
                name="market-cap-refresher",
                daemon=True,
            )
            market_cap_thread.start()
            if self.workers > 1:
                executor = ThreadPoolExecutor(
                    max_workers=self.workers,
                    thread_name_prefix="oi-worker",
                )
            while not self.stop_event.is_set():
                try:
                    self.update_once(executor=executor)
                except PollingStopped:
                    break
                except Exception as exc:
                    if self.stop_event.is_set():
                        break
                    self.handle_batch_error(exc)

                self.stop_event.wait(self.batch_delay)
        finally:
            try:
                if executor is not None:
                    executor.shutdown(wait=True, cancel_futures=True)
            finally:
                if market_cap_thread is not None:
                    market_cap_thread.join(timeout=5)
                    if market_cap_thread.is_alive():
                        self.log(
                            f"{self.timestamp()} market-cap refresher did not "
                            "stop within 5 seconds"
                        )
                self._close_after_polling()

    def _close_after_polling(self) -> None:
        try:
            self.close()
        except Exception as exc:
            self.log(
                f"{self.timestamp()} failed to close OI poller: {exc}"
            )
