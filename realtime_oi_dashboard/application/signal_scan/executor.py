"""Bounded concurrent execution for per-symbol signal classification."""

from __future__ import annotations

import threading
from collections.abc import Callable

from realtime_oi_dashboard.domain.errors import PollingStopped


class _Task:
    def __init__(self, index: int, symbol: str) -> None:
        self.index = index
        self.symbol = symbol
        self.thread = None
        self.done = threading.Event()
        self.entry = None
        self.error = None


class SignalScanExecutor:
    """Classify a bounded window while preserving input order."""

    def __init__(
        self,
        stop_event,
        record_error: Callable[[str, Exception], None],
        release_worker: Callable[[], None],
        *,
        workers: int,
        poll_seconds: float,
        wait_for_workers_on_stop: bool,
    ) -> None:
        self._stop_event = stop_event
        self._record_error = record_error
        self._release_worker = release_worker
        self._workers = workers
        self._poll_seconds = poll_seconds
        self._wait_for_workers_on_stop = wait_for_workers_on_stop

    def map(
        self,
        rows: list[dict],
        *,
        symbol_for: Callable[[object], str | None],
        classify: Callable[[dict], dict | None],
    ) -> list[dict]:
        self._raise_if_stopped()
        indexed_rows = list(enumerate(rows))
        valid_rows = []
        for index, row in indexed_rows:
            symbol = symbol_for(row)
            if symbol is not None:
                valid_rows.append((index, row, symbol))
        if not valid_rows:
            return []

        results = {}
        tasks = []
        next_index = 0
        wait_for_workers = True
        worker_count = min(self._workers, len(valid_rows))

        def submit_available() -> None:
            nonlocal next_index
            while len(tasks) < worker_count and next_index < len(valid_rows):
                self._raise_if_stopped()
                index, row, symbol = valid_rows[next_index]
                next_index += 1
                task = _Task(index, symbol)
                task.thread = threading.Thread(
                    target=self._run_task,
                    args=(task, row, classify),
                    name=f"signal-kline-{symbol}",
                    daemon=not self._wait_for_workers_on_stop,
                )
                try:
                    task.thread.start()
                except BaseException as exc:
                    if isinstance(exc, (KeyboardInterrupt, SystemExit, PollingStopped)):
                        raise
                    self._record_error(symbol, exc)
                    continue
                tasks.append(task)

        try:
            submit_available()
            while tasks:
                self._raise_if_stopped()
                completed = [task for task in tasks if task.done.is_set()]
                if not completed:
                    if self._stop_event.wait(self._poll_seconds):
                        raise PollingStopped
                    continue
                for task in completed:
                    tasks.remove(task)
                    task.thread.join()
                    if task.error is not None:
                        if isinstance(task.error, PollingStopped):
                            raise task.error
                        if not isinstance(task.error, Exception):
                            raise task.error
                        self._record_error(task.symbol, task.error)
                    elif task.entry is not None:
                        results[task.index] = task.entry
                submit_available()
        except BaseException:
            wait_for_workers = (
                self._wait_for_workers_on_stop or not self._stop_event.is_set()
            )
            raise
        finally:
            if wait_for_workers:
                for task in tasks:
                    task.thread.join()

        return [
            results[index]
            for index, _row in indexed_rows
            if index in results
        ]

    def _run_task(self, task: _Task, row: dict, classify) -> None:
        try:
            task.entry = classify(row)
        except BaseException as exc:
            task.error = exc
        finally:
            try:
                self._release_worker()
            except BaseException as exc:
                if task.error is None:
                    task.error = exc
            task.done.set()

    def _raise_if_stopped(self) -> None:
        if self._stop_event.is_set():
            raise PollingStopped
