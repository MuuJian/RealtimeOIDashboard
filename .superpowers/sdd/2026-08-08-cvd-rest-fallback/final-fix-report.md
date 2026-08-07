# Final fix report: CVD REST fallback review findings

## Changes

- Clamps synthetic kline event times to the fallback observation time so an
  in-progress candle cannot place the rolling window in the future or reject a
  resumed present-time `aggTrade`.
- Preserves valid rows from mixed REST sweeps while publishing failed symbols
  as exactly `{"cvdStatus": "unavailable"}`, with no numeric CVD fields.
- Replaces stale live history with unavailable state after a total fallback
  failure. Successful universe metadata refreshes retain that source error;
  only an accepted live trade or a populated REST fallback clears it.

## TDD evidence

RED command:

```text
python -m unittest tests.test_cvd_poller.CvdPollerTests.test_in_progress_kline_does_not_block_resumed_live_trade tests.test_cvd_poller.CvdPollerTests.test_invalid_kline_batch_does_not_publish_partial_symbol_cvd tests.test_cvd_poller.CvdPollerTests.test_failed_rest_fallback_hides_older_live_history_as_unavailable tests.test_cvd_poller.CvdPollerTests.test_refresh_universe_does_not_clear_cvd_unavailable_state -v
```

Before implementation, all four regressions failed for their intended reasons:

- resumed live trade: `AssertionError: False is not true`;
- mixed sweep: failed row was numeric zero with `collecting` status;
- failed fallback after live history: error remained `None`;
- universe refresh after unavailable: error was cleared to `None`.

GREEN: the unchanged command passed all four regressions after implementation.
The combined focused domain/poller suite then passed 17 tests:

```text
python -m unittest tests.test_cvd tests.test_cvd_poller -v

----------------------------------------------------------------------
Ran 17 tests in 0.002s

OK
```

## Verification

Full Python suite:

```text
python -m unittest discover -s tests -v

----------------------------------------------------------------------
Ran 245 tests in 3.611s

OK
```

Static asset check:

```text
node realtime_oi_dashboard/scripts/check-static-js.mjs

Checked 38 reachable dashboard JavaScript files and 8 stylesheets.
```

Staged diff validation before commit:

```text
git diff --cached --check
```

Completed with exit code 0 and no findings.

## Commit

`668cc8e Fix CVD fallback unavailable state`

## Concerns

- The full Python suite emits expected simulated signal-scan failure log lines
  before completing successfully.
- The static check initially encountered sandbox `EPERM` while Node resolved
  the parent user directory; the unchanged command passed outside the sandbox.
