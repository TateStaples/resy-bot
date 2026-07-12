#!/usr/bin/env python
"""Conversational CLI for the Resy reservation bot.

Every command prints EXACTLY ONE JSON object to stdout. Human-readable /
log text goes to stderr only. On any error, a ``{"error": ...}`` object is
printed to stdout and the process exits with status 1.
"""
import argparse
import json
import sys
from datetime import date

from resy_bot.models import (
    ResyConfig,
    ReservationRequest,
    TimedReservationRequest,
    FindRequestBody,
)
from resy_bot.api_access import ResyApiAccess
from resy_bot.manager import ResyManager


DEFAULT_CREDENTIALS_PATH = "credentials.json"


def eprint(*args) -> None:
    """Print human/log text to stderr only."""
    print(*args, file=sys.stderr)


def load_config(path: str) -> ResyConfig:
    """Read the credentials JSON file and return a ResyConfig."""
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"{path} not found — run `resy_cli.py setup` or the "
            "resy-setup skill first"
        )

    return ResyConfig(**data)


def _parse_hh_mm(value: str, field_name: str):
    """Parse a "HH:MM" string into (hour, minute), validating the format."""
    try:
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        raise ValueError(
            f"{field_name} must be in HH:MM (24-hour) format, got {value!r}"
        )
    return hour, minute


def cmd_setup(args) -> dict:
    data = {"api_key": args.api_key, "token": args.token}

    if args.payment_method_id is not None:
        data["payment_method_id"] = args.payment_method_id
    if args.email is not None:
        data["email"] = args.email
    if args.password is not None:
        data["password"] = args.password

    with open(args.credentials, "w") as f:
        json.dump(data, f, indent=2)

    return {
        "status": "saved",
        "path": args.credentials,
        "has_payment_method": "payment_method_id" in data,
    }


def cmd_check(args) -> dict:
    cfg = load_config(args.credentials)
    api = ResyApiAccess.build(cfg)
    api.get_user()
    return {"status": "ok"}


def cmd_payment_methods(args) -> dict:
    cfg = load_config(args.credentials)
    user = ResyApiAccess.build(cfg).get_user()
    pms = user.get("payment_methods", []) or []
    result = [
        {"id": pm.get("id"), "display": pm.get("display") or pm.get("type") or "card"}
        for pm in pms
    ]
    return {"payment_methods": result}


def cmd_search_venue(args) -> dict:
    cfg = load_config(args.credentials)
    venues = ResyApiAccess.build(cfg).search_venues(args.query, per_page=args.limit)
    return {"venues": venues}


def cmd_find(args) -> dict:
    cfg = load_config(args.credentials)
    api = ResyApiAccess.build(cfg)
    body = FindRequestBody(
        venue_id=args.venue_id, party_size=args.party_size, day=args.day
    )

    try:
        slots = api.find_booking_slots(body)
    except IndexError:
        # Resy returned no venues in results
        slots = []

    result = [
        {
            "time": slot.date.start.strftime("%H:%M"),
            "type": slot.config.type,
            "config_token": slot.config.token,
        }
        for slot in slots
    ]
    return {"slots": result}


def _build_reservation_request(args) -> ReservationRequest:
    ideal_hour, ideal_minute = _parse_hh_mm(args.ideal_time, "--ideal-time")
    return ReservationRequest(
        venue_id=args.venue_id,
        party_size=args.party_size,
        ideal_hour=ideal_hour,
        ideal_minute=ideal_minute,
        window_hours=args.window_hours,
        prefer_early=args.prefer_early,
        preferred_type=args.preferred_type,
        ideal_date=date.fromisoformat(args.day),
        days_in_advance=None,
    )


def _require_payment_method(cfg: ResyConfig) -> None:
    if cfg.payment_method_id is None:
        raise ValueError(
            "no payment_method_id configured — run "
            "`setup --payment-method-id <id>` (see `payment-methods`) "
            "before booking"
        )


def cmd_book(args) -> dict:
    cfg = load_config(args.credentials)
    _require_payment_method(cfg)

    request = _build_reservation_request(args)
    manager = ResyManager.build(cfg)
    resy_token = manager.make_reservation(request)
    return {"status": "booked", "resy_token": resy_token}


def cmd_schedule(args) -> dict:
    cfg = load_config(args.credentials)
    _require_payment_method(cfg)

    request = _build_reservation_request(args)
    drop_hour, drop_minute = _parse_hh_mm(args.drop_time, "--drop-time")
    timed_request = TimedReservationRequest(
        reservation_request=request,
        expected_drop_hour=drop_hour,
        expected_drop_minute=drop_minute,
    )

    eprint(f"Waiting until {args.drop_time} to book — this will block until then.")

    manager = ResyManager.build(cfg)
    resy_token = manager.make_reservation_at_opening_time(timed_request)
    return {"status": "booked", "resy_token": resy_token}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resy_cli.py",
        description="Conversational CLI for the Resy reservation bot",
    )
    parser.add_argument(
        "--credentials",
        default=DEFAULT_CREDENTIALS_PATH,
        help="path to the credentials JSON file (default: credentials.json)",
    )

    # Allow --credentials to also appear after the subcommand. SUPPRESS means
    # the subparser only sets the attribute when the flag is actually given,
    # so a value supplied before the subcommand is preserved otherwise.
    creds_parent = argparse.ArgumentParser(add_help=False)
    creds_parent.add_argument(
        "--credentials",
        default=argparse.SUPPRESS,
        help="path to the credentials JSON file (default: credentials.json)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_setup = sub.add_parser(
        "setup", help="save Resy credentials", parents=[creds_parent]
    )
    p_setup.add_argument("--api-key", required=True)
    p_setup.add_argument("--token", required=True)
    p_setup.add_argument("--payment-method-id", type=int, default=None)
    p_setup.add_argument("--email", default=None)
    p_setup.add_argument("--password", default=None)
    p_setup.set_defaults(func=cmd_setup)

    p_check = sub.add_parser(
        "check", help="verify credentials work", parents=[creds_parent]
    )
    p_check.set_defaults(func=cmd_check)

    p_pm = sub.add_parser(
        "payment-methods",
        help="list saved payment methods",
        parents=[creds_parent],
    )
    p_pm.set_defaults(func=cmd_payment_methods)

    p_search = sub.add_parser(
        "search-venue", help="search for venues by name", parents=[creds_parent]
    )
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=5)
    p_search.set_defaults(func=cmd_search_venue)

    p_find = sub.add_parser(
        "find", help="find open booking slots", parents=[creds_parent]
    )
    p_find.add_argument("--venue-id", required=True)
    p_find.add_argument("--day", required=True, help="YYYY-MM-DD")
    p_find.add_argument("--party-size", type=int, required=True)
    p_find.set_defaults(func=cmd_find)

    p_book = sub.add_parser(
        "book", help="book a reservation now", parents=[creds_parent]
    )
    p_book.add_argument("--venue-id", required=True)
    p_book.add_argument("--day", required=True, help="YYYY-MM-DD")
    p_book.add_argument("--party-size", type=int, required=True)
    p_book.add_argument("--ideal-time", required=True, help="HH:MM")
    p_book.add_argument("--window-hours", type=int, default=1)
    p_book.add_argument("--prefer-early", action="store_true")
    p_book.add_argument("--preferred-type", default=None)
    p_book.set_defaults(func=cmd_book)

    p_sched = sub.add_parser(
        "schedule",
        help="wait for a drop time and then book",
        parents=[creds_parent],
    )
    p_sched.add_argument("--venue-id", required=True)
    p_sched.add_argument("--day", required=True, help="YYYY-MM-DD")
    p_sched.add_argument("--party-size", type=int, required=True)
    p_sched.add_argument("--ideal-time", required=True, help="HH:MM")
    p_sched.add_argument("--drop-time", required=True, help="HH:MM")
    p_sched.add_argument("--window-hours", type=int, default=1)
    p_sched.add_argument("--prefer-early", action="store_true")
    p_sched.add_argument("--preferred-type", default=None)
    p_sched.set_defaults(func=cmd_schedule)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = args.func(args)
    except Exception as e:  # noqa: BLE001 - CLI contract: any error -> json + exit 1
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    main()
