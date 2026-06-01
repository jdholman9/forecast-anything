# Unified Claims — Design Note

**Status:** alignment draft. Direction confirmed 2026-06-01. Decisions still open.
**Author:** Sherman (drafting Jacob's vision from a 2026-06-01 voice note).
**Don't build yet.** Iterate on this doc first, then design the schema migration, then write code.

---

## Atomic layer scope (the rule that decides what belongs here)

`forecast_anything` is the **atomic layer** for forecasting. Concretely:

| In scope (this layer) | Out of scope (hoster decides) |
|---|---|
| Storing claims about quantities (predictions and estimates, point or distributional) | Whether an event is "resolved" or still open |
| Scoring rules (CRPS, Brier) and proper-scoring-rule math | Which claim counts as canonical truth |
| Self-join scoring: any claim vs any other claim on the same event | When a score "officially" fires for a workflow |
| Distribution registry, extension hooks, queries | Lifecycle automation, notifications, archival policy |

The hoster — whether that's a separate package later, a project script, or a human workflow — decides what "resolution" and "canonical" mean for their use case. This layer just stores claims and computes scores between any two of them on the same event.

This boundary kills any temptation to bake `Event.status = resolved`, `is_canonical` flags, or "the actual" semantics into this layer. Hosters can layer those on top however they want.

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

Scoring is a self-join: pick a claim, score it against another claim on the same event. The atomic layer doesn't pick *which* claim is the reference — the caller does, always.

```python
# Primitive: score claim A against claim B (any two claims on the same event)
score(claim_id, against=other_claim_id)

# Caller picks the reference however they want
ref = store.list_claims(event_id, kind="estimate")[-1].id   # last estimate by made_at
score(prediction_id, against=ref)
```

Optional sugar (helpers that build common references — sugar, not semantics):

```python
score(claim_id, against=Latest("estimate"))             # most recent estimate by made_at
score(claim_id, against=First("estimate"))              # first published estimate
score(claim_id, against=Latest(made_by="Census"))       # most recent from a source
```

These helpers are convenience that wraps a query — they don't encode "canonical truth." A hoster that wants different semantics queries directly.

New workflows the unification unlocks:

- Score forecasts against first-print Census numbers (model bias against unrevised data).
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
- `Event.status` (`open`/`closed`) likely **goes away** — resolution is a hoster concern, not an atomic-layer concern. If it stays it's purely advisory metadata, not used by any internal logic.
- The typer CLI subcommand groups (`event`, `forecast`, `actual`) → `event`, `claim`. Non-trivial CLI rewrite.

---

## Decisions to nail down (your call)

1. **`kind` enum shape.** Just `prediction | estimate`, or do you also want `revision` as an explicit type?
   - *My lean:* keep it two-valued. A revision is just an estimate that happens to land later — `made_at` already captures the ordering.
2. **Sugar helper for "latest" by `made_at`.** Ship `Latest("estimate")` / `First("estimate")` helpers as syntactic sugar in the API, or leave it to the caller to query and pass a `claim_id`?
   - *My lean:* ship the helpers. They're thin wrappers, they make the common case readable, and they don't smuggle in semantics — they just build a reference the caller could have built themselves.
3. **Backwards compatibility.** Keep the old `Forecast` / `Actual` API as a thin shim during migration, or hard cut?
   - *My lean:* hard cut. You're the only user. Migration is a one-time script.
4. **Caching scored values.** Always recompute scores on demand, no cache?
   - *My lean:* yes. Scoring is cheap; staleness is a footgun. The atomic layer shouldn't try to keep cached scores fresh.

*(Decision 3 from the previous draft — "canonical truth nomination" — was deleted. That's a hoster concern, not an atomic-layer concern.)*

---

## Concerns / things to consider

- **Event lifecycle stops being this layer's problem.** Resolution, "open" vs "closed", first-print vs revised — these are hoster concerns now. This layer just stores claims with timestamps and computes scoring between them.
- **CLI rewrite is real work.** The 947-line typer CLI assumes the three-noun structure. Non-trivial migration to `event` + `claim`.
- **Phase 0 script translates cleanly.** "Find events ready to score, record the actual, score" → "find events whose hosting layer flagged them ready, submit estimate, score predictions against it." The atomic layer doesn't need to change here; only the hosting code does.
- **Forecast-vs-forecast comparisons.** The unification makes this trivially possible. Valuable or accidental scope? My lean: valuable — comparing two models without waiting for actuals is a real research workflow, and the atomic layer doesn't have to do anything special to support it. It just falls out.
- **Open question — where does the hosting layer live?** Is the hoster a separate package you have in mind (`forecast_anything_host`, or a "lifecycle" package), or just "the user's project code" that imports `forecast_anything` and decides its own semantics? Worth naming this even if it stays vague — affects what hooks/queries the atomic layer should expose.

---

## On the name

`forecast_anything` is sticky and communicates the gist even when the package handles broader claims. My lean: keep it. Other tries (`estimate_anything`, `claim_anything`, etc.) lose punch. The README can explain the broader scope; the package name doesn't have to.

The only real argument for changing it: if you ever publish or attract collaborators, "forecast" might mislead them. For a personal-or-small-project, keep the sticky name.

---

## What I'd need from you before any code

Direction confirmed 2026-06-01 (atomic layer; resolution is a hoster concern). Still open:

1. Decision 1: two-valued `kind` (`prediction | estimate`)?
2. Decision 2: ship `Latest()` / `First()` sugar helpers?
3. Decision 3: hard cut on API, no `Forecast`/`Actual` shim?
4. Decision 4: always recompute scores, no caching?
5. Keep the name `forecast_anything`?
6. Hosting-layer shape: separate package, or "user's project code"? Even a vague answer affects what hooks the atomic layer exposes.
7. Anything else missing in the framing.

Once we're aligned, next step is a schema migration plan + a stub of the new `submit_claim` / `score(claim_id, against=...)` API — sketched, not built.
