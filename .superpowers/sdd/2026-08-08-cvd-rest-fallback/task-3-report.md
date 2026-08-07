# Task 3 report: CVD documentation and verification

## Files

- `README.md`: documents the preferred live Binance `aggTrade` source, the
  30-second silence failover, the approximate fifteen one-minute kline
  taker-buy/taker-sell quote-volume calculation, and the dual-source
  unavailable condition. It retains that CVD does not filter or reorder rows.
- `.superpowers/sdd/2026-08-08-cvd-rest-fallback/task-3-brief.md`: records
  completed documentation and verification steps.
- `.superpowers/sdd/2026-08-08-cvd-rest-fallback/progress.md`: records Task 3
  progress.
- `.superpowers/sdd/2026-08-08-cvd-rest-fallback/task-3-report.md`: this
  report.

## Exact verification outputs

Command:

```text
python -m unittest discover -s tests -v
```

Final output:

```text
----------------------------------------------------------------------
Ran 242 tests in 3.326s

OK
```

Command:

```text
node realtime_oi_dashboard/scripts/check-static-js.mjs
```

Output:

```text
Checked 38 reachable dashboard JavaScript files and 8 stylesheets.
```

## Commit

`Document CVD REST fallback behavior` (the final hash is reported after the
commit).

## Concerns

- The Python suite emits expected simulated signal-scan failure log lines
  before completing successfully.
- The static JavaScript check required sandbox escalation because Node could
  not `lstat` the parent user directory within the sandbox; it passed when
  rerun unchanged outside it.
