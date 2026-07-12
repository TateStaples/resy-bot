---
name: resy-reserve
description: Find, book, snipe, or schedule a Resy restaurant reservation. Use when the user says things like "book a table on resy", "get me a reservation", "snipe a resy reservation", "check resy availability", or "schedule a booking when reservations drop".
---

# Resy reserve

Find and book restaurant reservations via `resy_cli.py`. Every command prints one JSON object; parse it. On failure it prints `{"error":"..."}` and exits non-zero.

## 0. Preconditions

- Ensure `credentials.json` exists. If not, tell the user to run the **resy-setup** skill first.
- If a booking is requested but no `payment_method_id` is configured (`has_payment_method:false`), prompt the user to add one via `payment-methods` + `setup` (see resy-setup).

## 1. Gather details (ask only for what's missing)

- Restaurant name
- Date (`YYYY-MM-DD`)
- Party size
- Ideal time (`HH:MM`, 24-hour)
- Flexibility: window hours before/after ideal (default `1`)
- Book the **best current slot now**, or **schedule a snipe** at a reservation "drop" time?

## 2. Resolve the venue id

```bash
python resy_cli.py search-venue --query "<name>"
```

Output: `{"venues":[{"id":123,"name":"...","location":"..."}]}`. If multiple venues come back, show the list (name + location) and **confirm which one** with the user before proceeding.

## 3. See available slots

```bash
python resy_cli.py find --venue-id <id> --day <YYYY-MM-DD> --party-size <n>
```

Output: `{"slots":[{"time":"19:00","type":"Dining Room","config_token":"..."}]}`. Summarize the available times (and seating types) to the user.

## 4. Book now

```bash
python resy_cli.py book --venue-id <id> --day <YYYY-MM-DD> --party-size <n> --ideal-time <HH:MM> [--window-hours <h>] [--prefer-early] [--preferred-type "<type>"]
```

Books the open slot closest to `--ideal-time`. Output: `{"status":"booked","resy_token":"...","slot":{"time":"...","type":"..."}}`. Report the confirmed time, type, and `resy_token`. On `{"error":...}`, explain it (e.g. no matching slots; expired token → re-run **resy-setup**).

## 5. Schedule a snipe

For reservations that open at a known drop time today:

```bash
python resy_cli.py schedule --venue-id <id> --day <YYYY-MM-DD> --party-size <n> --ideal-time <HH:MM> --drop-time <HH:MM> [--window-hours <h>] [--prefer-early] [--preferred-type "<type>"]
```

`--drop-time` is today, 24-hour `HH:MM`. This **blocks until the drop time**, then races to book with rapid retries. Tell the user the process must stay running until it finishes. Output: `{"status":"booked","resy_token":"..."}`.

## Guardrails (always follow)

- **Always confirm the exact venue, date, time, and party size with the user before running `book` or `schedule`.** Booking is a real, often non-refundable action that may incur cancellation fees.
- **Never book without explicit user confirmation of the final details.**
