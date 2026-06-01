"""
Phase 0 — Auto-score newly-published actuals.

Reads an actuals CSV (date, value), finds events in the ForecastStore whose
resolution_date matches a published value, records the actual, scores every
forecast on that event, and prints a leaderboard digest.

Designed to run monthly (manually or via scheduler) once the upstream actuals
pipeline (e.g. `00_fetch_data.py` in mf-permits-forecast) refreshes the CSV.

Defaults assume the mf-permits-forecast project layout; override with flags
for any other domain.

Usage:
    python scripts/score_latest_actuals.py
    python scripts/score_latest_actuals.py --dry-run
    python scripts/score_latest_actuals.py --db /path/to.db --actuals /path/to.csv

CSV format:
    Two columns. First column = date (YYYY-MM-DD); second column = numeric value.
    Header row required. Extra columns are ignored.

Event matching:
    An event is "ready to score" if (a) its resolution_date appears as a date
    in the CSV, (b) it has no actual recorded yet (open status), and (c) it
    has at least one forecast attached.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from forecast_anything import ForecastStore

DEFAULT_SOURCE = "Census MPS (monthly NSA)"


def _find_mf_permits_root() -> Optional[Path]:
    """Locate the mf-permits-forecast project. Checks the side-by-side
    Working/ location first, then the Documents/ root fallback (current
    state per workspace notes — move is pending).
    """
    here = Path(__file__).resolve().parent.parent  # forecast_anything repo root
    candidates = [
        here.parent / "mf-permits-forecast",                # ../mf-permits-forecast
        Path.home() / "Documents" / "mf-permits-forecast",  # absolute fallback
    ]
    for candidate in candidates:
        if (candidate / "mf_permits_forecasts.db").exists():
            return candidate
    return None


_MF_PERMITS_ROOT = _find_mf_permits_root()
DEFAULT_DB = (
    _MF_PERMITS_ROOT / "mf_permits_forecasts.db" if _MF_PERMITS_ROOT else None
)
DEFAULT_ACTUALS = (
    _MF_PERMITS_ROOT / "data" / "processed" / "mf_permits_monthly.csv"
    if _MF_PERMITS_ROOT else None
)


@dataclass
class ScoredEvent:
    event_id: int
    title: str
    resolution_date: str
    actual: float
    leaderboard: list[dict]  # rows from store.score_event(event_id)


def load_actuals(path: Path) -> dict[str, float]:
    """Read the CSV; return {date_str: value}. First two columns only."""
    actuals: dict[str, float] = {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            next(reader)  # skip header
        except StopIteration:
            return actuals
        for row in reader:
            if len(row) < 2:
                continue
            date_str, value_str = row[0].strip(), row[1].strip()
            if not date_str or not value_str:
                continue
            try:
                actuals[date_str] = float(value_str)
            except ValueError:
                continue
    return actuals


def find_ready_events(store: ForecastStore, actuals: dict[str, float]) -> list[tuple]:
    """Return [(event, value)] for events ready to be scored."""
    ready: list[tuple] = []
    for event in store.list_events(status="open"):
        if event.resolution_date in actuals:
            forecasts = store.get_forecasts(event.id)
            if forecasts:
                ready.append((event, actuals[event.resolution_date]))
    return ready


def score_event(
    store: ForecastStore,
    event,
    actual: float,
    source: str,
    *,
    dry_run: bool,
) -> Optional[ScoredEvent]:
    if dry_run:
        return None

    store.record_actual(
        event.id,
        value=actual,
        source=source,
        reported_at=event.resolution_date,
    )
    leaderboard = store.score_event(event.id)
    return ScoredEvent(
        event_id=event.id,
        title=event.title,
        resolution_date=event.resolution_date,
        actual=actual,
        leaderboard=leaderboard,
    )


def print_digest(scored: list[ScoredEvent]) -> None:
    if not scored:
        print("No events scored.")
        return

    for sev in scored:
        print(f"\n== {sev.title}")
        print(f"   resolution: {sev.resolution_date}    actual: {sev.actual:.2f}")
        print()
        rows = sorted(sev.leaderboard, key=lambda r: r.get("score", float("inf")))
        rank_width = max(len(str(len(rows))), 2)
        name_width = max((len(r.get("notes") or "(unnamed)") for r in rows), default=10)
        for i, row in enumerate(rows, start=1):
            name = row.get("notes") or "(unnamed)"
            score = row.get("score")
            score_str = f"CRPS={score:.3f}" if score is not None else "CRPS=n/a"
            marker = "  <- best" if i == 1 else ""
            print(f"   {i:>{rank_width}}. {name:<{name_width}}   {score_str}{marker}")


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"ForecastStore DB (default: {DEFAULT_DB if DEFAULT_DB else 'auto-detect; not found'})",
    )
    p.add_argument(
        "--actuals",
        type=Path,
        default=DEFAULT_ACTUALS,
        help=f"Actuals CSV (default: {DEFAULT_ACTUALS if DEFAULT_ACTUALS else 'auto-detect; not found'})",
    )
    p.add_argument("--source", default=DEFAULT_SOURCE, help=f"Source label for recorded actuals (default: {DEFAULT_SOURCE!r})")
    p.add_argument("--dry-run", action="store_true", help="Show what would be scored without writing to the DB")
    args = p.parse_args(argv)

    if args.db is None:
        print(
            "error: mf-permits-forecast project not auto-located; pass --db <path>",
            file=sys.stderr,
        )
        return 1
    if args.actuals is None:
        print(
            "error: actuals CSV not auto-located; pass --actuals <path>",
            file=sys.stderr,
        )
        return 1
    if not args.db.exists():
        print(f"error: DB not found at {args.db}", file=sys.stderr)
        return 1
    if not args.actuals.exists():
        print(f"error: actuals CSV not found at {args.actuals}", file=sys.stderr)
        return 1

    actuals = load_actuals(args.actuals)
    if not actuals:
        print(f"error: no rows parsed from {args.actuals}", file=sys.stderr)
        return 1

    print(f"loaded {len(actuals)} actuals from {args.actuals.name}")
    print(f"DB: {args.db}")

    store = ForecastStore(str(args.db))
    ready = find_ready_events(store, actuals)

    if not ready:
        print("\nNo events ready to score -- every open event either has no matching")
        print("actual published yet, or already has an actual recorded.")
        return 0

    print(f"\n{len(ready)} event(s) ready to score" + (" [DRY RUN]" if args.dry_run else ""))

    scored: list[ScoredEvent] = []
    for event, actual in ready:
        if args.dry_run:
            print(f"  would record actual={actual:.2f} for event {event.id}: {event.title}")
            continue
        result = score_event(store, event, actual, args.source, dry_run=False)
        if result:
            scored.append(result)

    if not args.dry_run:
        print_digest(scored)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
