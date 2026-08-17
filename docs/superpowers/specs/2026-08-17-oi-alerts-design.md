# OI Alerts Design

**Date:** 2026-08-17

## Goal

Add an `OI Alerts` dashboard tab that monitors the current total USD open-interest value for every active Binance USDT perpetual contract. It generates actionable display signals and Telegram notifications when a token crosses configured global OI thresholds. The first release is notification-only: it never submits exchange orders.

## Product Rules

- Monitor all active Binance USDT perpetual contracts.
- Use each token's current total OI value in USD, not OI accumulated across a time window.
- Default thresholds are 75M, 100M, and 150M USD; users can edit the three global values in the tab. Values must be positive and strictly increasing.
- A rising cross of 75M creates a `Long entry` signal; 100M creates `Add position`; 150M creates `High OI alert`.
- A threshold sends at most one notification until OI falls below that threshold. For example, a token that reaches 120M, falls to 90M, then rises above 100M sends a new 100M alert.
- On first observation, service restart, or a configuration save, current values establish a baseline. Existing values above a threshold do not generate historical or catch-up alerts.
- Alerts are signals only. No Binance trading API keys, order placement, leverage, or position management are in scope.

## Architecture

`OIPoller` already collects and stores the current OI value for each symbol. After each successful symbol update is applied, an `AlertEngine` consumes the latest OI value and evaluates the configured thresholds.

```text
Binance OI update
  -> OIPoller applies latest row
  -> AlertEngine evaluates crossing state
  -> persistent event/state store
  -> asynchronous Telegram delivery queue
  -> OI Alerts API and dashboard tab
```

The `AlertEngine` has one responsibility: compare a current OI value against persisted per-symbol threshold state and emit an alert event only for valid upward crossings. The Telegram notifier is separate and receives events through a bounded background queue, so network latency never blocks dashboard polling.

Persist the editable settings, per-symbol threshold state, and recent alert events in a project data file using atomic replacement. State survives restarts and prevents duplicate notifications. Retain the newest 50 events for the UI.

## Telegram Integration

Telegram credentials remain server-only:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

The browser never receives either value. The notifier uses Telegram's HTTPS `sendMessage` endpoint. When credentials are absent, the engine still records and displays signals, while API status reports `not configured`.

Delivery failures mark the associated event as `failed`, record the reason and last attempted timestamp, and retry a finite number of times with backoff. The tab shows the final delivery state. A test-message API validates the configured bot and chat without waiting for a threshold crossing.

## Dashboard Experience

The new `OI Alerts` tab contains:

1. A master enable/disable control, Telegram delivery status, and a `Send test message` action.
2. Global threshold inputs in millions of USD, defaulting to 75, 100, and 150, plus their mapped labels: `Long entry`, `Add position`, and `High OI alert`.
3. A live table of tokens currently above at least one threshold, including symbol, current total OI, highest active threshold, and last trigger time.
4. A recent-events table with timestamp, symbol, OI value, threshold, signal label, and Telegram delivery result.

Saving valid configuration applies it immediately and baselines all observed symbols; it produces no catch-up notifications. Invalid configuration returns a validation error and leaves the previous settings intact.

## API Surface

- `GET /api/oi-alerts`: current configuration, Telegram status, active alert rows, and recent events.
- `PUT /api/oi-alerts/config`: validate and persist global enablement and thresholds, then baseline observed symbols.
- `POST /api/oi-alerts/test-message`: enqueue one Telegram test message when credentials are configured.

All API input is validated on the server. Responses never expose Telegram credentials.

## Error Handling

- Alert evaluation ignores incomplete, stale, non-finite, or invalid OI values.
- A Telegram failure does not fail an OI polling batch.
- File loading failures are surfaced in alert status; a valid default configuration is used without sending unbaselined alerts.
- Atomic file writes prevent partial configuration/state files on interruption.

## Tests

Add focused backend and frontend coverage for:

- upward crossings at 75M, 100M, and 150M;
- no duplicate alert while a threshold remains exceeded;
- re-alert after falling below then re-crossing;
- restart and configuration-save baselining without catch-up alerts;
- threshold validation and safe persistence;
- Telegram successful delivery, missing credentials, retryable failure, and final failure;
- API credential redaction, test-message behavior, and tab rendering of status, active rows, and recent events.

## Setup Documentation

Update the README with instructions to create a bot through BotFather, send it `/start` (or add it to the target group), determine the chat ID, configure the two environment variables, and use the dashboard test-message action.
