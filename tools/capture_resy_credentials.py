#!/usr/bin/env python
"""Capture Resy API credentials by driving a real, visible browser.

WHAT THIS DOES
--------------
Today, connecting this bot to your Resy account means opening browser
DevTools, filtering the Network tab for ``api.resy.com``, and manually
copying two header values (``api_key`` and the ``X-Resy-Auth-Token``
session JWT) out of a request. This script automates that: it opens a
real (headed, visible) Chromium window, watches outgoing network requests
in the background, and grabs those two values itself the moment you log
in and browse to a restaurant page. It then hands them straight to
``resy_cli.py setup`` so ``credentials.json`` gets written for you.

WHERE TO RUN THIS
------------------
Run this on YOUR OWN machine — a laptop or desktop with a real display.
It launches an actual browser window you interact with, so it will NOT
work inside a remote/cloud/headless Claude Code session (there is no
screen to show you, and no way for you to log in). If you're in a remote
session, use the manual DevTools steps in the resy-setup skill instead
(``.claude/skills/resy-setup/SKILL.md``, "Option B").

REQUIREMENTS
------------
    pip install playwright
    playwright install chromium

USAGE
-----
    python tools/capture_resy_credentials.py [--credentials PATH]
                                              [--payment-method-id ID]
                                              [--quiet]

PRIVACY
-------
This script never sends your credentials anywhere except to your own
local ``credentials.json`` (via ``resy_cli.py setup``, run as a
subprocess on your machine). There is no telemetry and no network calls
other than the ones your browser makes to resy.com as you log in
normally.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print(
        "error: the `playwright` package is not installed.\n"
        "Install it on YOUR OWN machine with:\n\n"
        "    pip install playwright\n"
        "    playwright install chromium\n\n"
        "Then re-run: python tools/capture_resy_credentials.py",
        file=sys.stderr,
    )
    sys.exit(1)


RESY_CLI_PATH = Path(__file__).resolve().parent.parent / "resy_cli.py"
DEFAULT_CREDENTIALS_PATH = "credentials.json"
TIMEOUT_SECONDS = 300  # 5 minutes
POLL_INTERVAL_MS = 500

AUTH_HEADER_RE = re.compile(r'ResyAPI api_key="([^"]+)"')


class _Captured:
    """Small mutable holder for values captured across request callbacks."""

    def __init__(self):
        self.api_key = None
        self.token = None

    @property
    def done(self) -> bool:
        return self.api_key is not None and self.token is not None


def _make_request_handler(captured: "_Captured"):
    def handler(request) -> None:
        if captured.done:
            return
        if "api.resy.com" not in request.url:
            return

        # Playwright normalizes header names to lowercase.
        headers = request.headers

        auth_header = headers.get("authorization")
        if auth_header:
            match = AUTH_HEADER_RE.search(auth_header)
            if match:
                captured.api_key = match.group(1)

        token_header = headers.get("x-resy-auth-token")
        if token_header:
            captured.token = token_header

    return handler


def capture_credentials() -> "_Captured":
    """Open a headed browser, watch requests, and return captured creds."""
    captured = _Captured()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        # Register the listener BEFORE navigating so we don't miss anything.
        page.on("request", _make_request_handler(captured))

        page.goto("https://resy.com")

        print(
            "\nA browser window has opened. Please log in to Resy "
            "(email/password or however you normally do), then browse to "
            "any restaurant page so we can capture your session token.\n"
            "This window will close automatically once your credentials "
            "are captured, or you can press Ctrl+C to cancel.\n",
            file=sys.stderr,
        )

        elapsed_ms = 0
        timeout_ms = TIMEOUT_SECONDS * 1000
        while not captured.done and elapsed_ms < timeout_ms:
            page.wait_for_timeout(POLL_INTERVAL_MS)
            elapsed_ms += POLL_INTERVAL_MS

        browser.close()

        if not captured.done:
            print(
                f"error: timed out after {TIMEOUT_SECONDS} seconds without "
                "capturing both the api_key and the session token.\n"
                "Falling back to the manual approach: see the resy-setup "
                "skill's 'Option B: manual DevTools copy' "
                "(.claude/skills/resy-setup/SKILL.md).",
                file=sys.stderr,
            )
            sys.exit(1)

    return captured


def run_resy_cli_setup(
    api_key: str, token: str, credentials_path: str, payment_method_id
) -> bool:
    """Shell out to `resy_cli.py setup`. Returns True on success."""
    cmd = [
        sys.executable,
        str(RESY_CLI_PATH),
        "setup",
        "--api-key",
        api_key,
        "--token",
        token,
        "--credentials",
        credentials_path,
    ]
    if payment_method_id is not None:
        cmd += ["--payment-method-id", str(payment_method_id)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        print(f"error: failed to run resy_cli.py setup: {exc}", file=sys.stderr)
        return False

    if result.returncode != 0:
        print(
            "warning: `resy_cli.py setup` did not succeed:\n"
            f"{result.stdout}\n{result.stderr}",
            file=sys.stderr,
        )
        return False

    print(result.stdout)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Capture Resy api_key and session token via a headed browser, "
            "and write them to credentials.json (run on your own machine)."
        )
    )
    parser.add_argument(
        "--credentials",
        default=DEFAULT_CREDENTIALS_PATH,
        help=f"Path to write credentials.json to (default: {DEFAULT_CREDENTIALS_PATH})",
    )
    parser.add_argument(
        "--payment-method-id",
        type=int,
        default=None,
        help="Optional payment_method_id to store alongside the captured credentials",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print the raw api_key/token to the terminal, even on capture",
    )
    args = parser.parse_args()

    captured = capture_credentials()

    print("Credentials captured.", file=sys.stderr)
    if not args.quiet:
        print(f"  api_key: {captured.api_key}", file=sys.stderr)
        print(f"  token (sensitive, treat like a password): {captured.token}", file=sys.stderr)

    ok = run_resy_cli_setup(
        captured.api_key, captured.token, args.credentials, args.payment_method_id
    )

    if ok:
        print(f"Saved to {args.credentials}.", file=sys.stderr)
    else:
        print(
            "Could not auto-save via resy_cli.py setup. Run it yourself with "
            "the values above:\n\n"
            f"    python resy_cli.py setup --api-key \"<api_key>\" "
            f"--token \"<token>\" --credentials {args.credentials}",
            file=sys.stderr,
        )
        if args.quiet:
            print(
                "(Re-run without --quiet to see the captured api_key/token.)",
                file=sys.stderr,
            )
        sys.exit(1)


if __name__ == "__main__":
    main()
