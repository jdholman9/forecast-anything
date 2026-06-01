# Unified Claims — Design Note

**Status:** alignment draft. Not committed; pending Jacob confirmation.
**Author:** Sherman (drafting Jacob's vision from a 2026-06-01 voice note).
**Don't build yet.** Iterate on this doc first, then design the schema migration, then write code.

---

## The framing shift

Today the model has three concepts: `Event` (what's being measured), `Forecast` (a prediction), and `Actual` (the truth). The split assumes a clean line between "what was predicted" and "what actually happened." In practice that line is blurry:

- Census housing starts publish a *preliminary* number, then revise it several times over the following years. Which one is "the actual"?
- A model projection and a survey's preliminary estimate are both *claims about a quantity, with uncertainty*. They differ in framing, not in shape.
- The existing `Actual` already supports uncertainty (`margin_of_error`, `distribution_params`) — half-acknowledging that "ground truth" is itself an estimate.

The proposed shift: **collapse `Forecast` and `Actual` into one unified type — a Claim about an event's quantity, with a `kind` flag distinguishing forward-looking predictions from observation-based estimates.** Scoring becomes a self-join: pick a prediction, pick an estimate, compute the rule.

Working name for the unified type: **Claim**. Other candidates: `Measurement`, `Estimate`, `Value`. (Naming is the cheap part — pick later.)

---

## Proposed model

`Event` stays as-is in spirit. Defines a quantity to track ("US housing starts, May 2026"). `resolution_date` stays meaningful (when the quantity becomes observable in the world) but doesn't gate scoring.

`Claim` replaces both `Forecast` and `Actual`:

| Field | Type | Notes |
|---|---|---|
| `id` | int | |
| `event_id` | int → Event | |
| `kind` | enum | `prediction` or `estimate` (see Decision 1) |
| `value` | float | nullable; if null, distribution_type required |
| `distribution_type` | str | nullable; `normal`, `empirical`, etc. |
| `distribution_params` | json | parameters for the distribution |
| `made_at` | datetime | when the claim was made/published |
| `made_by` | str | source — model name, survey, agency, etc. (today's `notes`) |
| `notes` | str | freeform context |

A `Claim` is always a point-or-distribution about an event's quantity. The `kind` field is the only semantic distinction between the two cases.

---

## What scoring looks like

Scoring becomes a self-join. The question shifts from *"what's the actual?"* to *"which estimate are we scoring against?"*

```python
# Score one prediction against one specific estimate
score(prediction_id, against=estimate_id)

# Score all predictions on an event against the latest estimate
leaderboard(event_id, against=Latest("estimate"))

# Other natural references
leaderboard(event_id, against=First("estimate"))         # first print — catches model bias against unrevised data
leaderboard(event_id, against=Specific(claim_id))         # a specific revision
leaderboard(event_id, against=Latest(made_by="Census"))   # last estimate from a specific source
```

New workflows the unification unlocks:

- Score forecasts against first-print Census numbers (catch bias against unrevised data).
- Score forecasts against latest-revision numbers (truth as currently known).
- Score one estimate against another (compare survey methodologies).
- Score forecast vs forecast (model A vs model B, no actual required).

---

## What stays the same

- Distribution types and registry — `Normal`, `Empirical`, etc., all unchanged.
- Scoring rules — CRPS (standard + generalized), Brier. The math doesn't care which side is "actual."
- Event definitions and the `ForecastStore` orchestration surface for events.

## What changes

- `Forecast` and `Actual` tables collapse into `Claim`.
- `submit_forecast(event_id, ...)` and `record_actual(event_id, ...)` consolidate into `submit_claim(event_id, kind=..., ...)`.
- `score_event(event_id)` becomes `score_event(event_id, against=...)` with a default of `Latest("estimate")`.
- Migration of existing data is mechanical: every `Forecast` → `Claim(kind="prediction")`, every `Actual` → `Claim(kind="estimate")`.
- `Event.status` (`open`/`closed`) becomes softer (see "Concerns" below).
- The typer CLI subcommand groups (`event`, `forecast`, `actual`) → `event`, `claim`. Non-trivial CLI rewrite.

---

## Decisions to nail down (your call)

1. **`kind` enum shape.** Just `prediction | estimate`, or do you also want `revision` (explicit revision chains) and/or `final` (a single canonical truth marker)?
   - *My lean:* keep it two-valued. A revision is just an estimate that happens to land later; "final" can be done via `is_canonical` flag or a convention.
2. **Default `against` semantics.** "Latest estimate" means most recent by `made_at`? Or do we want a `superseded_by` chain?
   - *My lean:* by `made_at`. Cheap and right.
3. **The "canonical truth" problem.** Some downstream views (visualizations, leaderboards) want a single value per event. Need a way to nominate one.
   - *Options:* (a) an `is_canonical` flag on `Claim`, (b) "latest estimate by made_at" as the convention, (c) a separate `Event.canonical_claim_id` pointer.
   - *My lean:* convention (b) for now; add an `is_canonical` flag later only if real workflows demand it.
4. **Backwards compatibility.** Keep the old `Forecast` / `Actual` API as a thin shim during migration, or hard cut?
   - *My lean:* hard cut. You're the only user. Migration is a one-time script.
5. **Caching scored values.** Today, when an Actual lands you call `store.score_event()` and the result is computed once. Under the new model, "the answer" shifts whenever a new estimate lands. Do we cache per `(prediction_id, against_id)` pair, or always recompute on demand?
   - *My lean:* always recompute. Scoring is cheap; staleness bugs are not.

---

## Concerns / things to consider

- **Event lifecycle becomes less crisp.** Today an event clearly closes when an Actual lands. With Claims, "when is the event resolved?" becomes a soft question. Probably fine for your use case but worth knowing.
- **The "ground truth" concept doesn't fully go away.** Some workflows need a single canonical value per event. Decision 3 above is where this lives.
- **CLI rewrite is real work.** The 947-line typer CLI assumes the three-noun structure. Non-trivial migration.
- **Phase 0 script unaffected.** Reads "find events ready to score, record the actual, score" — maps cleanly to "find events with predictions but no estimates, submit estimate, score." Path forward stays intact.
- **Forecast-vs-forecast comparisons.** The unification makes this trivially possible. Is that valuable to you, or accidental scope creep? My lean: it's valuable — comparing two models without waiting for actuals is a real research workflow.

---

## On the name

`forecast_anything` is sticky and communicates the gist even when the package handles broader claims. My lean: keep it. Other tries (`estimate_anything`, `claim_anything`, etc.) lose punch. The README can explain the broader scope; the package name doesn't have to.

The only real argument for changing it: if you ever publish or attract collaborators, "forecast" might mislead them. For a personal-or-small-project, keep the sticky name.

---

## What I'd need from you before any code

Confirm or correct each of:

1. Direction is right? Unify `Forecast` + `Actual` into `Claim` with `kind` flag.
2. Decision 1: two-valued `kind` (`prediction | estimate`)?
3. Decision 2: `Latest()` = by `made_at`?
4. Decision 3: "canonical truth" — convention only, no flag yet?
5. Decision 4: hard cut on API, no shim?
6. Decision 5: always recompute scores, no caching?
7. Keep the name `forecast_anything`?
8. Anything I'm missing in the framing.

Once we're aligned, the next step is a schema migration plan + a stub of the new `submit_claim` / `score(against=...)` API — not yet built, just sketched.
