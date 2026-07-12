---
name: resy-setup
description: Set up, connect, or configure a Resy account and credentials for the reservation bot. Use when the user says things like "set up resy", "connect my resy account", "configure resy credentials", "log into resy", or when a booking is attempted but credentials.json is missing or its token has expired.
---

# Resy setup

Help the user obtain and store three credentials the bot needs: an **api_key**, a **token** (session JWT), and a **payment_method_id** (required before booking). Auth is token-based — no password login.

There are two ways to get the api_key and token. **Ask the user which they'd prefer** — default to suggesting **Option A** if they appear to be working on their own machine (a local Claude Code session with a real display), and default to suggesting **Option B** if you're running in a remote/cloud session with no display to show them (there's no way to open a visible browser window for them to log into).

## Option A: automated capture (recommended, run on your own machine)

A script drives a real, visible Chromium browser, watches the network requests it makes, and pulls the `api_key` and `token` out automatically the moment the user logs in and browses to a restaurant page — no manual DevTools digging required. This only works on the user's own machine with a real display; it cannot run inside a remote/cloud session.

```bash
pip install playwright
playwright install chromium
python tools/capture_resy_credentials.py
```

It will open a browser window, print instructions, wait for the user to log in and browse to any restaurant page, then automatically call `resy_cli.py setup` to write `credentials.json`. Pass `--payment-method-id <id>` to set that in the same run, `--credentials <path>` for a non-default path, or `--quiet` to suppress printing the raw api_key/token to the terminal. If it times out or fails, it prints the captured values so you can fall back to running `resy_cli.py setup` yourself, or fall back to Option B below.

## Option B: manual DevTools copy (works anywhere, including remote sessions)

Walk the user through these exact DevTools steps (they do this; you cannot):

1. Log in at **resy.com** in a desktop browser.
2. Open DevTools (**F12** or **Cmd+Opt+I**) → **Network** tab. Filter the request list by `api.resy.com`.
3. Browse to any restaurant page or run a search so requests fire, then click any request to `api.resy.com`.
4. In that request's **Request Headers**, copy two values:
   - **api_key**: from `Authorization: ResyAPI api_key="XXXXX"` — copy only the `XXXXX` part.
   - **token**: the full value of the `X-Resy-Auth-Token` header (a long JWT).

## Save the credentials (skip if you used Option A — it already saved them)

If you used Option B, save the two copied values now (quote both values):

```bash
python resy_cli.py setup --api-key "<api_key>" --token "<token>"
```

Output: `{"status":"saved","path":"credentials.json","has_payment_method":false}`

## Verify auth works

```bash
python resy_cli.py check
```

Expect `{"status":"ok"}`. If it returns `{"error":...}` with an auth failure, the token is wrong or expired — have the user re-copy a fresh `X-Resy-Auth-Token` and re-run `setup`.

## Add a payment method (required to book)

List the user's saved cards, then ask which one to use:

```bash
python resy_cli.py payment-methods
```

Output: `{"payment_methods":[{"id":123,"display":"Visa ...4242"}]}`

Re-run `setup` with the chosen id (include the same api-key and token):

```bash
python resy_cli.py setup --api-key "<api_key>" --token "<token>" --payment-method-id <id>
```

Confirm `has_payment_method` is now `true`.

## Security and maintenance

- `credentials.json` holds secrets. Confirm `.gitignore` covers it (add a `credentials.json` line if it is not already listed) and **never commit it or echo the token/api_key back to the user in full**.
- The token expires roughly every **45 days**. When `check` starts failing with an auth error, the user re-runs `setup` with a freshly copied token; the api_key and payment_method_id usually stay the same.
