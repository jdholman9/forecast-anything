# Roadmap

Design notes on where this goes beyond Phase 1. The framework is currently a clean storage + scoring layer; everything below is about closing the loop between *making* a forecast and *learning* from it.

---

## Phase 0 (now): the personal feedback loop

The system already does everything needed to be useful for a single user — me, right now. The smallest possible loop that closes:

1. mf-permits forecasts are loaded into `mf_permits_forecasts.db` (32 monthly events × 6 models = 192 forecasts).
2. When a monthly actual prints, record it via `store.record_actual(...)`.
3. Auto-score all 6 models against the actual.
4. Get a one-line readout: *who was closest, who was overconfident, who was biased high/low.*

**This is the entire point of the system.** Everything in later phases is leverage on top of this loop running.

**Status — initial loop:** `scripts/score_latest_actuals.py` is in place. Reads the mf-permits actuals CSV, matches dates to events, records any new actuals, scores the forecasts, and prints a ranked CRPS leaderboard per event. Runs as a no-op today (no published actuals overlap the forecast window yet — first match will land around end of June 2026 when May 2026 NSA permits publish). Verified end-to-end with a temp actual.

**Still on the Phase 0 wish list:**
- Week-over-week leaderboard delta (requires persisting prior-run scores; can land once there's >1 month of real actuals to compare).
- Calibration call ("too tight / too wide / biased") via empirical-vs-forecast quantile coverage on each scored event.
- Auto-run via Windows scheduled task or cron once monthly, after the upstream `00_fetch_data.py` refreshes the actuals CSV.

---

## Phase 2: distribution elicitation

The friction point. Asking anyone — including yourself when you're tired — to specify `mean=6.5, std=0.15` doesn't happen. Most forecasts will never get logged because the data entry is too painful.

**Triangular is already the right primitive** for human input: low / best guess / high. The library supports it. What's missing is the elicitation UX around it.

Lowest-friction inputs, in order:

1. **Triangular** (`low`, `mode`, `high`). One sentence: "my best guess is X, but it could be as low as Y or as high as Z." Already supported.
2. **Percentile elicitation** ("what's your 10/50/90?") that fits a distribution behind the scenes — typically a smooth interpolation or a fitted normal/lognormal. This is what Tetlock's IARPA forecasters used. The forecaster doesn't pick a distribution family; the system does.
3. **Anchor + spread** ("around X, plus or minus Y") → maps to normal with `mean=X`, `std=Y/2`.
4. **Skeptic prompt:** after the forecaster gives 10/50/90, ask *"what would have to be true for the actual to be outside your 10–90 range?"* Forces calibration. If they can't name a scenario, the range is too wide. If they name three plausible scenarios, the range is too narrow.

**None of this needs new math** — it's a thin elicitation layer over the existing `Distribution` registry. Could live as a small interactive CLI (`forecast_anything elicit <event_id>`) or as a function (`store.elicit_forecast(event_id, method="percentiles")`) that walks the user through prompts.

**Open question:** does elicitation belong in this package, or in a separate `forecast_anything_cli` / `forecast_anything_ux` package? Probably the latter — keeps the core engine pure, lets the UX iterate without API churn.

---

## Phase 3: opinionated metrics & scoring per domain

"Anything" in the name is aspirational. In practice, frameworks get used when there's a curated event set so the user doesn't have to invent one. The activation energy of "what should I even forecast?" is the real blocker.

The move (if/when this goes beyond me):

1. **Pick one domain first.** Housing, given the day job. Don't try to be universal up front; niches win.
2. **Define ~15 canonical recurring events.** Examples:
   - 30-year fixed mortgage rate (Freddie Mac PMMS) — weekly
   - Total housing starts (Census/HUD) — monthly
   - Median new home sale price — monthly
   - MoM single-family permit change — monthly
   - MoM multifamily permit change — monthly
   - CPI shelter component MoM — monthly
   - Existing home sales annualized — monthly
   - … etc.
3. **Let the event declare its scoring convention.** Add a `scoring_basis` field to `Event` (or similar). Defaults by event type:
   - "30-year mortgage rate" → level-CRPS in pp (additive errors are what matter; 6.5% vs 6.3% is a 0.2pp miss, not a "3% relative miss")
   - "Housing starts" → log-CRPS (multiplicative; missing 1.4M vs 1.3M is the same proportional miss as 1.4M vs 1.3M would be at a different absolute level)
   - "GDP growth rate" → level-CRPS (already a growth rate; don't double-log it)
   - "Population" → log-CRPS

The forecaster shouldn't have to think about which kind of error matters. That's a domain question, not a forecaster question — the framework should pick a sensible default and let it be overridden per event.

**Implementation sketch:**

```python
class Event:
    scoring_basis: Literal["level", "log", "growth"] = "level"

def crps(forecast, actual, *, basis="level"):
    if basis == "level":
        return _crps_level(forecast, actual)
    elif basis == "log":
        return _crps_level(_log_transform(forecast), math.log(actual))
    elif basis == "growth":
        # forecast and actual are already growth rates → level
        return _crps_level(forecast, actual)
```

---

## Phase 4: community / shared events

Only worth thinking about if there's external pull (which there may never be — and that's fine). The shape would be:

- A canonical event catalogue, versioned (so "Total housing starts, May 2026" has a stable ID anyone can forecast against)
- Public forecasts submitted by anyone, scored when the actual lands
- Per-domain leaderboards
- Calibration plots over time (the Tetlock chart — does this forecaster's 70% bin actually resolve true 70% of the time?)

This is "GMetaculus for housing." Not a goal — just naming what the building blocks could become.

---

## What I'm explicitly *not* doing

- A web UI in the core package. Frontend is a separate concern (per CLAUDE.md design principles).
- Ad hoc metrics (MAPE, MAE, etc.). Proper scoring rules only.
- Aggregating multiple forecasts into a "consensus" — that's a downstream consumer concern, not a framework concern. Provide the primitives, let callers compose.
- Real-time pricing / market integration. Out of scope unless a specific use case shows up.

---

## Order of operations

If energy gets put back into this project, the right order is:

1. **Phase 0** — the auto-scoring digest for mf-permits. One script. Pays off immediately and proves the framework's worth to its only current user.
2. **Phase 2** — elicitation UX, but only when there's a second domain to forecast (so it's getting used, not theorized about).
3. **Phase 3** — domain curation + per-event scoring basis. Only if Phase 2 reveals real friction around "which CRPS variant should I use."
4. **Phase 4** — community, only if external interest materializes.

Phase 0 is small enough to do in an evening. Everything after waits for signal.
