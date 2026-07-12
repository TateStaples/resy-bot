# Resy Booking Latency Study — Plan & Model

**Status:** design / pre-registration. Nothing here has been measured yet — the numbers in
§4 and the Appendix are *priors to be validated*, flagged as such. The purpose of this
document is to define exactly what we will measure and how we will decide whether the
current simple Python bot is fast enough, or whether lower-latency engineering is justified.

---

## 1. The core question

We win a contested slot **iff our booking commit reaches Resy before the slot is taken by
someone else (or by us hitting the drop)**. So the whole problem reduces to comparing two
random variables:

- **L** — our bot's end-to-end latency: time from the true "drop instant" *t₀* until our
  `POST /3/book` is accepted. *We control this.*
- **T** — the slot's **survival time**: time from *t₀* until the specific slot we want is
  grabbed by the competitive field. *We do not control this; we must measure it.*

> **Win probability:**  `P(win) = P(L < T)`.

Everything below is machinery to (a) estimate the distribution of **T** as a function of the
variables the user named — reservation time, restaurant quality, day of week — and (b)
estimate our own **L** across deployment options, then (c) combine them into a go/no-go
decision on optimizing the code.

---

## 2. What the competitive field looks like (research findings)

Evidence gathered July 2026 (sources at the bottom):

- **Drops are per-venue rolling windows, not universal midnight.** Each restaurant releases
  the day that enters its booking window at *its own* fixed time. Verified examples:
  Carbone — **10:00 AM ET, 10–30 days out**; Tatiana — **12:00 PM ET, ~20–27 days out**;
  The Four Horsemen — **7:00 AM ET, 29 days out**. Most hot venues drop 9–10 AM ET.
  ⇒ *t₀ is knowable per venue but has its own jitter (see §9).*
- **Aggregate sellout is 10–30 s; the single hottest slot is sub-second.** Reporting
  consistently says prime weekend inventory "vanishes within 10–30 seconds" (Tatiana <30 s;
  Carbone prime Fri/Sat 7–9 PM <10 s). That 10–30 s is the time for *all* prime tables to go;
  the *one* most-contested slot (e.g. Sat 7:30 PM for 2) is decided among bots much faster.
  ⇒ **T is heavily right-skewed and strongly covariate-dependent — exactly what we must model.**
- **The field is automated and sophisticated.** A resale/scalping ecosystem
  (Appointment Trader ≈ $7M GMV, ~50k users end-2024) runs bots against Resy/OpenTable.
  Resy data: presumed bots/brokers have **4× the no-show rate** and **2× late-cancels**.
  NY has banned reservation *resale* (Restaurant Reservation Anti-Piracy Law). ⇒ we are
  racing purpose-built software, not humans, for Tier-S venues.
- **Historically little hard rate-limiting, but active behavioral bot-detection.** A 2022
  reverse-engineering write-up found no obvious rate limits; Resy now runs detection models
  on booking patterns and deactivates flagged accounts. ⇒ our measurement harness must stay
  read-only and gentle (§9), and aggressive optimization has an account-risk cost.
- **Cancellations cause re-drops.** Slots reappear when others cancel (bots over-book then
  dump). ⇒ a *second* opportunity distribution exists; a patient bot gets **K > 1** shots
  (§10). This materially changes the economics and must be modeled separately.

---

## 3. The two distributions we must measure

| | **L — our latency** | **T — slot survival** |
|---|---|---|
| Owner | us (controllable) | the field (observational) |
| How measured | instrument our own request path (§7 Phase 0) | high-frequency polling of `/4/find` around drops (§7 Phase 1) |
| Censoring | none (we time our own calls) | yes — left/interval (gone before first poll) + right (still there at end) |
| Output | density `f_L(l)` per deploy target | survival curve `S_T(t | covariates)` per stratum |

---

## 4. Our latency budget — decomposed from the actual code

The current critical path (`resy_bot/manager.py::make_reservation`) after a slot is detected is
**three serial HTTP round-trips**:

1. `GET /4/find`  → detect the slot (`find_booking_slots`)
2. `GET /3/details` → exchange config token for `book_token` (`get_booking_token`)
3. `POST /3/book` → commit (`book_slot`)

Plus the drop-detection loop: `make_reservation_at_opening_time` busy-waits (no sleep) until
`t₀`, then `make_reservation_with_retries` calls `make_reservation` up to `N_RETRIES` times
**with no back-off** (note: `SECONDS_TO_WAIT_BETWEEN_RETRIES` is defined but not actually used
in the retry loop — the loop hammers as fast as Python allows). So our latency is:

```
L ≈ clock_error(t₀)                     # how far off our fired-clock is from true drop
  + detect_gap                          # ≤ one find-RTT once the slot is live
  + RTT_find + RTT_details + RTT_book    # 3 serial round-trips
  + per_call_overhead (Python/requests/TLS; Session keep-alive amortizes handshake)
```

**Priors to validate (NOT measured yet):**

| Deployment | RTT to Resy | 3 serial RTTs + overhead | Plausible L (p50) |
|---|---|---|---|
| Home broadband, warm process | ~40–120 ms | ~200–500 ms | **~0.3–0.8 s** |
| VPS in AWS us-east-1 (near Resy), warm, keep-alive | ~10–40 ms | ~60–180 ms | **~0.15–0.4 s** |

Read against §2 (single hot slot decided sub-second; 2nd-tier slots survive 1–30 s), this is
the whole tension: **plausibly good enough for Tier-A and re-drops, marginal-to-losing for the
single hottest Tier-S slot.** The study exists to replace "plausibly" with a measured
`P(win)`.

---

## 5. The statistical model

### 5.1 Survival analysis for T
Because T is censored (some slots are gone before our first poll; some never sell within the
observation window), we use survival methods rather than plain regression:

- **Nonparametric — Kaplan–Meier** `Ŝ(t)` per stratum; **log-rank** tests between strata
  (e.g. Fri-prime vs Tue-early). Handles right-censoring directly; left/interval censoring
  handled with a Turnbull estimator or by treating "gone at first poll" as an event in
  `(0, first_poll]`.
- **Semiparametric — Cox proportional hazards**, `h(t|x) = h₀(t)·exp(βᵀx)`. The `exp(β)` are
  **hazard ratios**: how much each covariate multiplies the "grab rate." This is the primary
  inferential model for *which variables matter and by how much*.
- **Parametric AFT (Weibull / log-logistic)** for a closed-form `S_T(t)` we can integrate in
  §5.3 and extrapolate into the sub-poll-interval region we can't observe directly.

### 5.2 Microfoundation (why these families fit)
Model the field as **C competitors**, each independently succeeding at rate `r`. The first
success is `T = min` of `C` exponentials `→ Exp(Λ)` with contention `Λ = C·r`. That gives
`S_T(t) = exp(−Λ t)`, i.e. an exponential (Weibull with shape k=1). Hype/day/daypart enter
through `Λ(x) = exp(βᵀx)` — the same log-linear link as Cox/Poisson. Weibull's shape `k`
lets the grab rate accelerate or decay over the first seconds (we expect `k>1`: a feeding
frenzy at t₀ that thins out). **This is the model to fit and report.**

### 5.3 The deliverable: a win-probability surface
Combine the two distributions:

```
P(win | x, deploy) = P(L < T) = ∫₀^∞ f_L(l) · S_T(l | x) dl
```

With `L` from Phase 0 and `S_T` from Phase 1, we produce **win-probability curves vs. our
latency budget, per restaurant tier × day × daypart**. Example shape of the answer (numbers
illustrative until measured):

> "Tier-S, Sat 7:30 PM, party 2: `Λ̂` ⇒ median T ≈ 0.4 s. Home bot (L p50 ≈ 0.6 s) ⇒
> P(win) ≈ 15%. us-east-1 bot (L p50 ≈ 0.25 s) ⇒ P(win) ≈ 55%. Tier-A same slot: median
> T ≈ 8 s ⇒ P(win) ≈ 95% from either. ⇒ optimize only for Tier-S."

### 5.4 Over-a-season probability (re-drops)
A patient bot gets `K` independent-ish shots (initial drop + cancellation re-drops, §2/§10):
`P(get it eventually) = 1 − (1 − p)^K`. Estimating the re-drop rate is a Phase-1 by-product
(count reappearances per venue-week) and can flip a per-attempt "loss" into a seasonal "win."

---

## 6. Variables & experimental design

**Response:** `T` = seconds from `t₀` until the target slot is taken (event), with censoring flags.

**Primary covariates (the user's variables + the obvious confounders):**

| Covariate | Levels / encoding | Hypothesis |
|---|---|---|
| **Restaurant demand tier ("quality/hype")** | S (Carbone/Tatiana/4 Charles-class), A (hot, non-insane), B (bookable) — or a continuous *demand index* (see below) | dominant driver of `Λ` |
| **Day of week of the reservation** | Fri/Sat vs Sun–Thu (or 7 levels) | Fri/Sat sharply higher `Λ` |
| **Daypart / reservation time** | prime (7:00–8:30 PM), shoulder (6–7, 8:30–9:30), off (≤5:30, ≥9:30), lunch | prime >> off |
| **Party size** | 2, 3–4, 5+ | 2-tops scarcest at top venues |
| **Lead time / booking window** | days-ahead the slot is for | interacts with tier |
| **Drop time-of-day** | the venue's own release hour | 10 AM workday drops vs off-hours differ |

**Demand index (to avoid hand-labeled "quality"):** derive a continuous hype score per venue
from observable proxies — historical time-to-sellout (bootstrapped from pilot data), size of
the Resy "Notify" list if exposed, media-mention count, seat count (smaller = scarcer). Use it
both as a Cox covariate and to define tiers for reporting.

**Panel:** ~12–20 venues spanning all three tiers, each observed across many daily drops so
that day-of-week and daypart vary *within* venue (venue as a random effect / stratified
baseline hazard to absorb venue-specific `h₀`).

---

## 7. Measurement methodology (phased)

### Phase 0 — Characterize **our own** latency `L` (cheap, low-risk, do first)
- Add stage timestamps to the request path (wrap `requests` via an HTTP hook or a small
  `perf_counter()` shim around each call in `api_access.py`): DNS, TCP connect, TLS, request
  sent, TTFB, body received, parse. Record per-stage for `find`, `details`, `book`.
- Measure **cold vs warm** (fresh process/Session vs pre-warmed keep-alive pool).
- Run from each candidate deployment: **home broadband, us-east-1 VPS, us-east-1 Lambda**,
  ≥ 500 samples each, across the day (Resy load varies).
- Measure **clock error**: NTP-sync the host; separately estimate Resy's own `t₀` jitter by
  timestamping the first appearance of new inventory across many real drops (Phase 1 feeds this).
- **Output:** empirical `f_L` per deployment + a stage-level breakdown that tells us *where*
  the milliseconds go (which optimizations in §10 would actually pay off). This phase uses
  only read-only `find` plus, optionally, book+immediate-cancel on Tier-B venues to time a
  *real* `POST /3/book` (§9 caveat).

### Phase 1 — Observe the field's survival `T` (observational, weeks)
- **Drop-tracker harness** (new `latency_probe.py`, reusing `ResyApiAccess.find_booking_slots`):
  for each venue in the panel, starting ~2 s before its known `t₀`, poll `/4/find` for the
  target day at a fixed cadence and log, per `config_token`: `first_seen`, `last_seen`,
  party_size, slot time, and whether it was already gone at first poll.
- **Cadence trade-off:** faster polling → finer `T` resolution near `t₀` but higher
  detection/rate risk. Start at **250–500 ms**, jittered, read-only, capped attempts per venue.
  We are deliberately characterizing the **0.25–30 s regime** — precisely where a *simple*
  bot competes. Sub-250 ms dynamics are inferred by the Weibull extrapolation (§5.2), not
  polled, to stay under the radar.
- Per slot: `T = last_seen − t₀` (event) or censor flags. Aggregate to survival curves.
- **By-product:** cancellation **re-drop** events (a token reappearing after disappearing)
  → the `K`-shots model in §5.4.

### Phase 2 — Fit, combine, decide
- Fit KM + Cox + Weibull-AFT (§5). Report hazard ratios, per-stratum `S_T`, and the
  `P(win)` surface (§5.3). Validate PH assumption (Schoenfeld residuals); if violated, use
  stratified Cox or AFT.

### Phase 3 (optional) — Live end-to-end calibration
- On **Tier-B** (easy) venues where losing is cheap, run the *actual* bot to book (then cancel
  promptly and courteously) to measure the gap between "observed available in `/find`" and
  "successfully committed via `/book`" — the thing passive polling can't see.

---

## 8. Sample size & power
- Target: estimate each stratum's **median survival within ±20% at 95% CI**, and detect a
  2× hazard ratio between strata at 80% power.
- Rule of thumb for survival: precision/power is driven by **number of events**, not rows.
  Budget **≥ 30–50 observed events per stratum**; with ~6 reporting strata and censoring,
  plan for a few hundred observed drops. A 15-venue panel × daily drops reaches this in
  **~3–4 weeks**. Pilot the first week to get variance estimates and refine.

---

## 9. Threats to validity (and mitigations)
- **Bot detection / account risk.** Keep Phase 1 read-only, jittered, capped; use a
  dedicated account; never hammer `book`. Treat aggressive optimization (§10) as carrying an
  account-ban cost, not just an engineering cost.
- **Clock / drop jitter.** Restaurants don't drop at exactly `HH:00:00.000`; `t₀` itself is a
  random variable. NTP-sync our host and *estimate* `t₀` from first-inventory-appearance
  rather than assuming the nominal time. This jitter actually *helps* us (widens the field's
  effective start spread).
- **Passive observation ≠ bookable.** A token visible in `/find` may already be locked by a
  competitor's in-flight `book`. Phase 3 calibrates this optimism gap; until then, treat
  Phase-1 `S_T` as an **upper bound** on our opportunity.
- **Inventory heterogeneity.** 2 tables vs 20 changes survival independent of hype. Record
  observed slot count per venue-day and include as a covariate/offset.
- **Survivorship & left-censoring.** Slots gone before first poll are the *most* contested and
  the most informative — do not drop them; encode as interval events `(0, t_firstpoll]`.
- **Non-stationarity.** Hype shifts week to week (reviews, awards). Use venue random effects
  and keep the panel window short enough to treat `Λ` as locally stationary.

---

## 10. Decision framework (go / no-go) + optimization backlog

**Decision rule (pre-registered):** pick the target venue set and an acceptable seasonal
success rate (proposed: **≥ 70% of genuine attempts land the reservation within a season**,
counting re-drops). Then:

- If the **simple bot** (current code, best cheap deployment = warm process in us-east-1)
  clears the threshold on the target set → **ship as-is**; do not add complexity.
- If it clears it for Tier-A/B but not Tier-S → **ship, and scope Tier-S optimizations only**.
- If it misses broadly → **execute the optimization backlog**, re-measuring `L` after each
  step (Phase 0 is repeatable) until `P(win)` clears or returns diminish.

**Optimization backlog, ranked by expected ms saved ÷ effort** (each maps to a measurable
piece of §4's `L`):

1. **Collapse round-trips.** We pay **3 serial RTTs**. Investigate whether `/3/details` is
   strictly required or whether `book_token`/config token can be pre-fetched or reused —
   removing one RTT is a ~⅓ latency cut for near-zero code. *(Highest leverage.)*
2. **Deploy in AWS us-east-1**, warm, HTTP keep-alive / connection pre-pool + HTTP/2. Pure ops,
   large RTT win vs home.
3. **Actually use / tune the retry cadence** and add a **clock-sync + speculative pre-fire**
   (start firing a few ms before nominal `t₀`, absorb misses via the retry loop).
4. **Concurrency:** fire attempts at several acceptable slots / party sizes in parallel
   (async) instead of the current serial select-then-book, so we're not single-threaded on the
   one slot.
5. **Rewrite the hot path** (Go/Rust, async I/O) only if 1–4 are insufficient — highest effort,
   and only the `find→details→book` critical section needs it.
6. **Multiple sessions/accounts in parallel** — *explicitly deprioritized:* high detection/ban
   risk and edges toward the scalping behavior Resy penalizes (§11).

---

## 11. Responsible-use note
This bot is intended for booking tables **for oneself**. New York law bans commercial
*resale* of reservations, and Resy actively detects and deactivates bot/broker accounts
(4× no-show data). The optimizations above should stay within personal use: don't mass-book,
don't hold inventory you won't use, cancel early if plans change. Latency work that requires
many accounts or over-booking is out of scope on both legal and ethical grounds.

---

## 12. Concrete next steps
1. **Phase 0 harness** — add stage timing to `api_access.py`; produce `f_L` for home vs
   us-east-1. *(~1 day; no Resy risk.)*
2. **`latency_probe.py`** — drop-tracker over a seed panel of 3–4 venues (one per tier) for a
   pilot week; validate the pipeline and get variance estimates.
3. Expand the panel, run Phases 1–2 for ~3–4 weeks, publish the `P(win)` surface.
4. Apply the §10 decision rule.

*(I can scaffold the Phase 0 timer and the `latency_probe.py` tracker next — say the word.)*

---

### Sources
- [How Resy Drops Work — Restaurants for Kings](https://restaurantsforkings.com/blog/resy-prime-time-strategy-2026)
- [NYC Resy Release Times — ReservationFinder](https://www.reservationfinder.io/guides/nyc-resy-release-times)
- [Toughest reservations in NYC — Time Out](https://www.timeout.com/newyork/news/these-are-the-most-impossible-restaurant-reservations-in-nyc-right-nowand-here-is-how-people-are-actually-getting-them-042326)
- [Dinner at Tatiana is 'impossible' — Gothamist](https://gothamist.com/arts-entertainment/dinner-reservations-at-tatiana-are-impossible-to-get-so-i-spent-a-month-trying)
- [Reservations selling for hundreds — NBC News](https://www.nbcnews.com/news/us-news/reservations-top-new-york-city-restaurants-are-selling-hundreds-dollar-rcna151702)
- [NY banned reservation resales; Appointment Trader tests the law — Columbia News Service](https://columbianewsservice.com/2025/07/28/new-york-banned-reservation-resales-now-appointment-trader-is-testing-the-law-with-ai/)
- [Reservation resale scalpers — Marketplace](https://www.marketplace.org/story/2024/05/20/restaurant-reservation-resale-dining-scalpers)
- [Resy Security Center (bot detection)](https://resy.com/security-center)
- [Reversing Resy's API — jonluca (no rate limiting, 2022)](https://jonluca.substack.com/p/resy-api)
- [Bot getting beat out — Alkaar/resy-booking-bot issue #41](https://github.com/Alkaar/resy-booking-bot/issues/41)
