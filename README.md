# Resy-Bot

Resy exposes a number of API endpoints for making reservations,
these can be investigated by taking a look at the `api.resy.com`
calls from the network tab. We can have some fun making automated
calls to those endpoints right when reservations become available

## Conversational use (Claude Code)

This repo ships two Claude Code skills that let you set up your account and
make reservations by just talking to Claude Code. They drive `resy_cli.py`
(one JSON object per command on stdout).

- **resy-setup** — connect your Resy account. Walks you through copying your
  `api_key` and session `token` from the browser DevTools Network tab and
  storing them (plus a payment method) in `credentials.json`.
- **resy-reserve** — find, book, or snipe a reservation. Resolves the venue,
  lists open slots, and books the slot closest to your ideal time (or schedules
  a snipe at a reservation "drop" time).

Auth is now **token-based** — no password is needed. You copy a static
frontend `api_key` and an ES256-signed `X-Resy-Auth-Token` session JWT from
the browser; the JWT lasts ~45 days and is re-copied when it expires.

Example commands:

```bash
# Store credentials (add --payment-method-id before booking)
python resy_cli.py setup --api-key "<api_key>" --token "<token>"

# Verify auth and list saved cards
python resy_cli.py check
python resy_cli.py payment-methods

# Find a venue, then list open slots
python resy_cli.py search-venue --query "Carbone"
python resy_cli.py find --venue-id 12345 --day 2026-07-20 --party-size 2

# Book the slot closest to 19:00 now
python resy_cli.py book --venue-id 12345 --day 2026-07-20 --party-size 2 --ideal-time 19:00 --window-hours 1

# Or wait until the 10:00 drop and race to book
python resy_cli.py schedule --venue-id 12345 --day 2026-07-20 --party-size 2 --ideal-time 19:00 --drop-time 10:00
```

## API status (as of 2026)

Verified current in July 2026:

- Endpoints `/4/find`, `/3/details`, and `/3/book` (plus `/3/venuesearch/search`
  and `/2/user`) are the live endpoints used by the bot.
- The booking request now requires a **`Referer`** header (this was previously
  mis-sent as `Referrer` and rejected by Resy).
- Auth is **token-based**: an `Authorization: ResyAPI api_key="..."` header plus
  an ES256-signed `X-Resy-Auth-Token` session JWT. The token expires roughly
  every **45 days** and must be refreshed by re-copying it from the browser.

## Running

### Dependencies

Primary dependencies are pydantic and requests.
pydantic is used for serializing/deserializing requests/responses from Resy.

This project's dependencies are managed by poetry, so (assuming you have poetry installed) you can just install as easily as
`poetry install`.

### Local Configuration

The primary pieces of configuration for local execution are
defined in the `ResyConfig` and `TimedReservationRequest`
pydantic models in `resy_bot/models.py`.


#### ResyConfig

`ResyConfig` specifies credentials for personal Resy accounts.
Users should create a `credentials.json` file formatted as:
```json
{
  "api_key": "<api-key>",
  "token": "<api-token>",
  "payment_method_id": <payment-method>,
  "email": "<email>",
  "password": "<password>"
}
```

These values can be found in requests made in the Network tab.
- `api_key` can be found in the request headers under the
key `Authorization` in the format `ResyAPI api_key="<api-key>"`
- `token` can be found  in the request headers under the
key `X-Resy-Auth-Token`
- `payment_method_id` can be found in the request body to the endpoint
`/3/book`


#### TimedReservationRequest

In order to make a reservation right as it drops, a JSON
`TimedReservationRequest` must be created, see the following example
JSON:

```json
{
"reservation_request": {
  "party_size": 4,
  "venue_id": 12345,
  "window_hours": 1,
  "prefer_early": false,
  "ideal_date": "2023-03-30",
  "days_in_advance": 14,
  "ideal_hour": 19,
  "ideal_minute": 30,
  "preferred_type": "Dining Room"
},
  "expected_drop_hour": "10",
  "expected_drop_minute": "0"
}
```

These fields are mostly determined by the user:
- `party_size` is the number of members in the party
- `venue_id` is another field taken from communication in the
Network tab. This can be found as a URL param in requests to
the `/2/config` endpoint when navigating to the desired restaurant page
- `window_hours` is the number of hours before & after
the ideal hour/minute you are interested in
- `prefer_early` determines whether the earlier slot is selected when
2 time slots equidistant fom ideal hour/minute
- `ideal_date` is the date to search. This should not be provided if `days_in_advance` is used
- `days_in_advance` is the number of days from _now_ that the reservation becomes available. This should not be provided if `ideal_date` is used
- `ideal_hour` defines the hour field of the ideal timeslot
- `ideal_minute` defines the minute field of the ideal timeslot
- `preferred_type` is an optional field defining the type of seating
desired. If provided, Resy-Bot will _only_ search for that seating
type
- `expected_drop_hour` defines the hour field to of datetime
to start searching for slots
- `expected_drop_minute` defines the minute field to of datetime
to start searching for slots


### Command Line Execution

This application can be run from the command line. To do so,
the command should be formatted as

`poetry run python main.py <path/to/credentials.json> <path/to/reservation/request.json>`

From here, the application will wait until the time specified by
`expected_drop_hour` and `expected_drop_minute` to begin searching
for available timeslots.
