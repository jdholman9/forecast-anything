"""Command-line interface for forecast-anything."""

from __future__ import annotations

import json
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from forecast_anything import ForecastStore
from forecast_anything.distributions import DISTRIBUTION_REGISTRY
from forecast_anything.models import Event

__version__ = "0.1.0"

console = Console()

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="forecast-anything",
    help=(
        "[bold]forecast-anything[/bold] — Personal forecasting tracker.\n\n"
        "Track predictions, record outcomes, and score your accuracy with\n"
        "proper scoring rules (CRPS for numeric, Brier score for binary).\n\n"
        "Set [bold]FORECAST_DB[/bold] env var or use [bold]--db[/bold] to choose a database file."
    ),
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)

event_app = typer.Typer(
    help="Create and manage forecast events.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
forecast_app = typer.Typer(
    help="Submit forecasts for events.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
actual_app = typer.Typer(
    help="Record actual outcomes for events.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(event_app, name="event")
app.add_typer(forecast_app, name="forecast")
app.add_typer(actual_app, name="actual")

_state: dict = {"db": "forecasts.db"}


@app.callback()
def _global_options(
    version: Optional[bool] = typer.Option(
        None, "--version", "-V", is_eager=True, help="Show version and exit."
    ),
    db: str = typer.Option(
        "forecasts.db",
        "--db",
        envvar="FORECAST_DB",
        help="Path to the SQLite database file.",
        show_default=True,
    ),
) -> None:
    """Personal forecasting tracker with proper scoring rules."""
    if version:
        console.print(f"[bold]forecast-anything[/bold] v{__version__}")
        raise typer.Exit()
    _state["db"] = db


def _store() -> ForecastStore:
    return ForecastStore(_state["db"])


# ---------------------------------------------------------------------------
# Distribution parameter helpers
# ---------------------------------------------------------------------------

_DIST_PARAM_KEYS: dict[str, list[str]] = {
    "normal": ["mean", "std"],
    "lognormal": ["mu", "sigma"],
    "uniform": ["low", "high"],
    "beta": ["alpha", "beta"],
    "gamma": ["shape", "scale"],
    "exponential": ["rate"],
    "poisson": ["mu"],
    "student_t": ["df", "loc", "scale"],
    "triangular": ["low", "mode", "high"],
    "empirical": ["samples"],
}

_DIST_DEFAULTS: dict[str, dict] = {
    "student_t": {"loc": 0.0, "scale": 1.0},
}

_DIST_HINTS: dict[str, dict[str, str]] = {
    "normal": {"mean": "mean", "std": "std deviation (>0)"},
    "lognormal": {"mu": "log-space mean", "sigma": "log-space std deviation (>0)"},
    "uniform": {"low": "minimum value", "high": "maximum value (>low)"},
    "beta": {"alpha": "alpha shape (>0)", "beta": "beta shape (>0)"},
    "gamma": {"shape": "shape parameter (>0)", "scale": "scale parameter (>0)"},
    "exponential": {"rate": "rate λ (>0; mean = 1/λ)"},
    "poisson": {"mu": "mean rate λ (>0)"},
    "student_t": {"df": "degrees of freedom (>0)", "loc": "location (default 0)", "scale": "scale (>0, default 1)"},
    "triangular": {"low": "minimum value", "mode": "most likely value", "high": "maximum value"},
    "empirical": {"samples": "observed values (comma-separated numbers)"},
}


def _prompt_dist_params(dist_name: str) -> dict:
    """Interactively prompt for distribution parameters."""
    keys = _DIST_PARAM_KEYS.get(dist_name, [])
    defaults = _DIST_DEFAULTS.get(dist_name, {})
    hints = _DIST_HINTS.get(dist_name, {})
    params: dict = {}

    console.print(f"\n  [dim]Parameters for [bold]{dist_name}[/bold] distribution:[/dim]")

    for key in keys:
        hint = hints.get(key, key)
        default = defaults.get(key)
        label = f"    {key} [{hint}]"

        if key == "samples":
            raw = typer.prompt(label)
            try:
                params[key] = [float(x.strip()) for x in raw.split(",") if x.strip()]
            except ValueError:
                _err("samples must be comma-separated numbers.")
                raise typer.Exit(1)
        elif default is not None:
            raw = typer.prompt(label, default=str(default))
            try:
                params[key] = float(raw)
            except (ValueError, TypeError):
                _err(f"{key} must be a number.")
                raise typer.Exit(1)
        else:
            raw = typer.prompt(label)
            try:
                params[key] = float(raw)
            except (ValueError, TypeError):
                _err(f"{key} must be a number.")
                raise typer.Exit(1)

    return params


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_EVENT_TYPE_STYLE = {
    "numeric": "[blue]numeric[/blue]",
    "categorical": "[magenta]categorical[/magenta]",
    "binary": "[cyan]binary[/cyan]",
}

_STATUS_STYLE = {
    "open": "[yellow]open[/yellow]",
    "resolved": "[green]resolved[/green]",
    "cancelled": "[dim]cancelled[/dim]",
}


def _fmt_type(event_type: str) -> str:
    return _EVENT_TYPE_STYLE.get(event_type, event_type)


def _fmt_status(status: str) -> str:
    return _STATUS_STYLE.get(status, status)


def _fmt_score(score: float | None, metric: str) -> str:
    if score is None:
        return "[dim]—[/dim]"
    formatted = f"{score:.4f}"
    if metric == "brier":
        # Brier is 0–1; color by absolute quality
        if score < 0.05:
            return f"[green]{formatted}[/green]"
        elif score < 0.20:
            return f"[yellow]{formatted}[/yellow]"
        else:
            return f"[red]{formatted}[/red]"
    # CRPS scale is domain-dependent — no color heuristic
    return formatted


def _err(msg: str) -> None:
    console.print(f"[red]Error:[/red] {msg}")


# ---------------------------------------------------------------------------
# event commands
# ---------------------------------------------------------------------------

@event_app.command("create")
def event_create(
    title: Optional[str] = typer.Option(None, "--title", "-t", help="Event title."),
    event_type: Optional[str] = typer.Option(
        None, "--type", "-T",
        help="Event type: [bold]numeric[/bold], [bold]categorical[/bold], or [bold]binary[/bold].",
    ),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Optional description."),
    categories: Optional[str] = typer.Option(
        None, "--categories", "-c",
        help="Comma-separated categories (categorical events only).",
    ),
    resolution_date: Optional[str] = typer.Option(
        None, "--resolution-date", "-r",
        help="Expected resolution date (e.g. '2026-12-31').",
    ),
) -> None:
    """
    Create a new forecast event.

    Events can be [bold]numeric[/bold] (predict a number), [bold]categorical[/bold]
    (predict which category wins), or [bold]binary[/bold] (predict yes/no).

    Any option left out will be prompted interactively.
    """
    if title is None:
        title = typer.prompt("Event title")

    if event_type is None:
        console.print("  [dim]Types: numeric, categorical, binary[/dim]")
        event_type = typer.prompt("  Event type", default="numeric")

    event_type = event_type.lower().strip()
    if event_type not in ("numeric", "categorical", "binary"):
        _err(f"Invalid type {event_type!r}. Choose: numeric, categorical, binary.")
        raise typer.Exit(1)

    cats_list: list[str] | None = None
    if event_type == "categorical":
        if categories is None:
            categories = typer.prompt("  Categories (comma-separated, at least 2)")
        cats_list = [c.strip() for c in categories.split(",") if c.strip()]
        if len(cats_list) < 2:
            _err("Categorical events require at least 2 categories.")
            raise typer.Exit(1)

    if description is None:
        raw = typer.prompt("  Description", default="")
        description = raw.strip() or None

    if resolution_date is None:
        raw = typer.prompt("  Resolution date (optional)", default="")
        resolution_date = raw.strip() or None

    try:
        store = _store()
        event = store.create_event(
            title=title,
            event_type=event_type,
            description=description,
            categories=cats_list,
            resolution_date=resolution_date,
        )
    except Exception as exc:
        _err(str(exc))
        raise typer.Exit(1)

    lines = [f"[bold]{event.title}[/bold]", f"[dim]Type:[/dim]  {event.event_type}"]
    if event.categories:
        lines.append(f"[dim]Cats:[/dim]  {', '.join(event.categories)}")
    if event.description:
        lines.append(f"[dim]Desc:[/dim]  {event.description}")
    if event.resolution_date:
        lines.append(f"[dim]Date:[/dim]  {event.resolution_date}")

    console.print()
    console.print(Panel(
        "\n".join(lines),
        title=f"[green]Created[/green] — Event [bold]#{event.id}[/bold]",
        border_style="green",
    ))


# ---------------------------------------------------------------------------
# forecast commands
# ---------------------------------------------------------------------------

@forecast_app.command("submit")
def forecast_submit(
    event_id: int = typer.Option(..., "--event-id", "-e", help="ID of the event to forecast."),
    forecast_type: Optional[str] = typer.Option(
        None, "--type", "-t",
        help=(
            "Forecast type: point, binary, categorical, or a distribution name "
            "(normal, lognormal, uniform, beta, gamma, exponential, poisson, "
            "student_t, triangular, empirical)."
        ),
    ),
    params: Optional[str] = typer.Option(
        None, "--params", "-p",
        help='Distribution params as JSON, e.g. \'{"mean": 5, "std": 1}\'.',
    ),
    value: Optional[float] = typer.Option(
        None, "--value", "-v",
        help="Numeric value (point forecast) or probability 0–1 (binary forecast).",
    ),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Optional notes, e.g. model name."),
) -> None:
    """
    Submit a forecast for an event.

    For [bold]numeric[/bold] events: choose a distribution (normal, triangular, empirical, …)
    or a [bold]point[/bold] estimate. Pass [bold]--params[/bold] as JSON or enter interactively.

    For [bold]binary[/bold] events: provide a probability (0.0–1.0).

    For [bold]categorical[/bold] events: provide a probability for each category (must sum to 1.0).

    Examples:
      forecast submit -e 1 --type normal --params '{"mean": 42, "std": 3}'
      forecast submit -e 2 --type binary --value 0.75
      forecast submit -e 3 --type point --value 1250 --notes "My model"
    """
    try:
        store = _store()
        event = store.get_event(event_id)
    except ValueError as exc:
        _err(str(exc))
        raise typer.Exit(1)

    console.print(
        f"\n[dim]Event #[/dim][bold]{event.id}[/bold][dim]:[/dim] "
        f"{event.title} [dim]({event.event_type})[/dim]"
    )

    if forecast_type is None:
        if event.event_type == "binary":
            forecast_type = "binary"
        elif event.event_type == "categorical":
            forecast_type = "categorical"
        else:
            dist_list = ", ".join(["point"] + list(DISTRIBUTION_REGISTRY.keys()))
            console.print(f"  [dim]Available types:[/dim] {dist_list}")
            forecast_type = typer.prompt("  Forecast type", default="normal")

    forecast_type = forecast_type.lower().strip()
    kwargs: dict = {"notes": notes}

    if forecast_type == "point":
        if value is None:
            value = typer.prompt("  Point value", type=float)
        kwargs["point"] = value

    elif forecast_type == "binary":
        if value is None:
            value = typer.prompt("  Probability (0.0 – 1.0)", type=float)
        kwargs["binary"] = value

    elif forecast_type == "categorical":
        cats = event.categories or []
        if not cats:
            _err("This event has no categories defined.")
            raise typer.Exit(1)
        if params:
            try:
                probs = json.loads(params)
            except json.JSONDecodeError:
                _err("--params must be valid JSON.")
                raise typer.Exit(1)
        else:
            console.print(f"  [dim]Categories:[/dim] {', '.join(cats)}")
            console.print("  [dim]Enter probability for each (must sum to 1.0):[/dim]")
            probs: dict[str, float] = {}
            for cat in cats:
                probs[cat] = typer.prompt(f"    P({cat})", type=float)
        kwargs["categorical"] = probs

    elif forecast_type in DISTRIBUTION_REGISTRY:
        if params:
            try:
                dist_params = json.loads(params)
            except json.JSONDecodeError:
                _err("--params must be valid JSON.")
                raise typer.Exit(1)
        else:
            dist_params = _prompt_dist_params(forecast_type)
        kwargs[forecast_type] = dist_params

    else:
        _err(f"Unknown forecast type: {forecast_type!r}")
        valid = ["point", "binary", "categorical"] + list(DISTRIBUTION_REGISTRY.keys())
        console.print(f"  [dim]Valid types:[/dim] {', '.join(valid)}")
        raise typer.Exit(1)

    try:
        forecast = store.submit_forecast(event_id=event_id, **kwargs)
    except Exception as exc:
        _err(str(exc))
        raise typer.Exit(1)

    val_str = json.dumps(forecast.value)
    if len(val_str) > 80:
        val_str = val_str[:77] + "…"

    lines = [
        f"[dim]Event:[/dim]  #{event_id} {event.title}",
        f"[dim]Type:[/dim]   {forecast.forecast_type}",
        f"[dim]Value:[/dim]  {val_str}",
    ]
    if forecast.notes:
        lines.append(f"[dim]Notes:[/dim]  {forecast.notes}")

    console.print()
    console.print(Panel(
        "\n".join(lines),
        title=f"[green]Forecast Submitted[/green] — ID [bold]#{forecast.id}[/bold]",
        border_style="green",
    ))


# ---------------------------------------------------------------------------
# actual commands
# ---------------------------------------------------------------------------

@actual_app.command("record")
def actual_record(
    event_id: int = typer.Option(..., "--event-id", "-e", help="ID of the event."),
    value: Optional[float] = typer.Option(None, "--value", "-v", help="Numeric outcome value."),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Categorical outcome value."),
    outcome: Optional[bool] = typer.Option(None, "--outcome", "-o", help="Binary outcome (true/false)."),
    moe: Optional[float] = typer.Option(
        None, "--moe", help="Margin of error (numeric events, used to build a Normal uncertainty distribution)."
    ),
    confidence: Optional[float] = typer.Option(
        None, "--confidence", help="Confidence level for --moe (e.g. 0.90). Defaults to 0.90."
    ),
    dist_type: Optional[str] = typer.Option(
        None, "--dist-type",
        help="Distribution type for a distributional actual (e.g. normal, empirical).",
    ),
    dist_params: Optional[str] = typer.Option(
        None, "--dist-params",
        help="Distribution params as JSON (used with --dist-type).",
    ),
    source: Optional[str] = typer.Option(
        None, "--source", "-s", help="Data source (e.g. 'BLS CPS', 'Census ACS')."
    ),
    reported_at: Optional[str] = typer.Option(
        None, "--reported-at", help="When the actual was reported (ISO 8601 or free-form)."
    ),
) -> None:
    """
    Record the actual outcome for an event.

    For [bold]numeric[/bold] events, you can record a precise value, add uncertainty via
    [bold]--moe[/bold] (margin of error), or supply a full distribution with
    [bold]--dist-type[/bold] and [bold]--dist-params[/bold].

    Recording an actual marks the event [bold]resolved[/bold] and enables scoring.

    Examples:
      actual record -e 1 --value 42500
      actual record -e 1 --value 42500 --moe 1200 --confidence 0.90 --source "BLS"
      actual record -e 2 --outcome true
      actual record -e 3 --category "Option A"
    """
    try:
        store = _store()
        event = store.get_event(event_id)
    except ValueError as exc:
        _err(str(exc))
        raise typer.Exit(1)

    console.print(
        f"\n[dim]Event #[/dim][bold]{event.id}[/bold][dim]:[/dim] "
        f"{event.title} [dim]({event.event_type})[/dim]"
    )

    if event.event_type == "numeric" and value is None:
        value = typer.prompt("  Actual value", type=float)
        if moe is None and dist_type is None:
            if typer.confirm("  Add margin of error?", default=False):
                moe = typer.prompt("  Margin of error", type=float)
                if confidence is None:
                    confidence = typer.prompt("  Confidence level (e.g. 0.90)", default="0.90", type=float)

    elif event.event_type == "categorical" and category is None:
        cats = event.categories or []
        if cats:
            console.print(f"  [dim]Categories:[/dim] {', '.join(cats)}")
        category = typer.prompt("  Actual category")

    elif event.event_type == "binary" and outcome is None:
        raw = typer.prompt("  Outcome [true/false]").lower().strip()
        if raw in ("true", "yes", "1", "y"):
            outcome = True
        elif raw in ("false", "no", "0", "n"):
            outcome = False
        else:
            _err("Invalid outcome. Use true/yes/false/no.")
            raise typer.Exit(1)

    dist_params_dict: dict | None = None
    if dist_params:
        try:
            dist_params_dict = json.loads(dist_params)
        except json.JSONDecodeError:
            _err("--dist-params must be valid JSON.")
            raise typer.Exit(1)

    try:
        store.record_actual(
            event_id=event_id,
            value=value,
            category_value=category,
            binary_outcome=outcome,
            margin_of_error=moe,
            confidence_level=confidence,
            distribution_type=dist_type,
            distribution_params=dist_params_dict,
            source=source,
            reported_at=reported_at,
        )
    except Exception as exc:
        _err(str(exc))
        raise typer.Exit(1)

    if event.event_type == "numeric":
        outcome_display = str(value)
        if moe:
            cl_pct = f"{(confidence or 0.90) * 100:.0f}%"
            outcome_display += f" ± {moe} ({cl_pct} CI)"
        elif dist_type:
            outcome_display += f" (distribution: {dist_type})"
    elif event.event_type == "categorical":
        outcome_display = category or "—"
    else:
        outcome_display = "[green]True ✓[/green]" if outcome else "[red]False ✗[/red]"

    lines = [
        f"[dim]Event:[/dim]   #{event_id} {event.title}",
        f"[dim]Outcome:[/dim] [bold]{outcome_display}[/bold]",
    ]
    if source:
        lines.append(f"[dim]Source:[/dim]  {source}")
    if reported_at:
        lines.append(f"[dim]Reported:[/dim] {reported_at}")

    console.print()
    console.print(Panel(
        "\n".join(lines),
        title="[green]Actual Recorded[/green] — Event is now [bold]resolved[/bold]",
        border_style="green",
    ))


# ---------------------------------------------------------------------------
# list command
# ---------------------------------------------------------------------------

@app.command("list")
def list_events(
    status: Optional[str] = typer.Option(
        None, "--status", "-s",
        help="Filter by status: [bold]open[/bold], [bold]resolved[/bold], [bold]cancelled[/bold].",
    ),
    scores: bool = typer.Option(
        False, "--scores", help="Compute and show average scores for resolved events."
    ),
) -> None:
    """
    List all events with their status and forecast counts.

    Use [bold]--status open[/bold] to see only events still awaiting resolution.
    Use [bold]--scores[/bold] to also show accuracy scores (computes scoring for each resolved event).
    """
    try:
        store = _store()
        filter_status = status if status != "all" else None
        events = store.list_events(status=filter_status)
    except Exception as exc:
        _err(str(exc))
        raise typer.Exit(1)

    if not events:
        console.print("[dim]No events found.[/dim]")
        return

    title = "Forecast Events"
    if status:
        title += f" ({status})"
    title += f" — {len(events)} total"

    table = Table(title=title, box=box.ROUNDED, header_style="bold cyan", border_style="dim")
    table.add_column("ID", justify="right", width=4, style="bold")
    table.add_column("Title", min_width=28, max_width=50, no_wrap=True)
    table.add_column("Type", width=12)
    table.add_column("Status", width=10)
    table.add_column("Forecasts", justify="right", width=10)
    table.add_column("Resolution", width=13)
    if scores:
        table.add_column("Avg Score", justify="right", width=10)
        table.add_column("Metric", width=6)

    for event in events:
        forecasts = store.get_forecasts(event.id)
        row: list = [
            str(event.id),
            event.title,
            _fmt_type(event.event_type),
            _fmt_status(event.status),
            str(len(forecasts)),
            event.resolution_date or "[dim]—[/dim]",
        ]

        if scores:
            if event.status == "resolved":
                score_rows = store.score_event(event.id)
                if score_rows:
                    valid = [r["score"] for r in score_rows if r["score"] is not None]
                    if valid:
                        avg = sum(valid) / len(valid)
                        metric = score_rows[0]["metric"]
                        row += [_fmt_score(avg, metric), f"[dim]{metric}[/dim]"]
                    else:
                        row += ["[dim]—[/dim]", ""]
                else:
                    row += ["[dim]—[/dim]", ""]
            else:
                row += ["[dim]—[/dim]", ""]

        table.add_row(*row)

    console.print()
    console.print(table)


# ---------------------------------------------------------------------------
# score command
# ---------------------------------------------------------------------------

@app.command("score")
def score_cmd(
    event_id: Optional[int] = typer.Option(
        None, "--event-id", "-e",
        help="Score a specific event. Omit to see all resolved events summarized.",
    ),
) -> None:
    """
    Show accuracy scores for forecasts.

    With [bold]--event-id[/bold]: ranked breakdown of every forecast for that event,
    showing which model or approach performed best.

    Without [bold]--event-id[/bold]: summary table of all resolved events with
    best and average scores.

    Lower scores are always better (CRPS and Brier score are both negatively-oriented).
    """
    try:
        store = _store()
    except Exception as exc:
        _err(str(exc))
        raise typer.Exit(1)

    if event_id is not None:
        _score_single_event(store, event_id)
    else:
        _score_all_events(store)


def _score_single_event(store: ForecastStore, event_id: int) -> None:
    try:
        event = store.get_event(event_id)
        rows = store.score_event(event_id)
    except ValueError as exc:
        _err(str(exc))
        raise typer.Exit(1)

    if rows is None:
        console.print(f"\n[yellow]Event #{event_id} has no actual recorded yet.[/yellow]")
        console.print(
            f"[dim]Record the outcome with:[/dim] "
            f"[bold]actual record --event-id {event_id}[/bold]"
        )
        return

    metric = rows[0]["metric"] if rows else "—"

    table = Table(
        title=f"#{event.id}: {event.title}",
        caption=f"Metric: [bold]{metric}[/bold] — lower is better",
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("Rank", width=6, justify="right")
    table.add_column("ID", width=6, justify="right")
    table.add_column("Type", width=14)
    table.add_column("Notes / Model", min_width=22)
    table.add_column("Score", justify="right", width=10)

    n = len(rows)
    for rank, row in enumerate(rows, 1):
        if rank == 1:
            rank_text = Text(f"  #{rank}", style="green bold")
        elif rank == n and n > 1:
            rank_text = Text(f"  #{rank}", style="red dim")
        else:
            rank_text = Text(f"  #{rank}")

        table.add_row(
            rank_text,
            str(row["forecast_id"]),
            row["forecast_type"],
            row["notes"] or "[dim]—[/dim]",
            _fmt_score(row["score"], metric),
        )

    console.print()
    console.print(table)


def _score_all_events(store: ForecastStore) -> None:
    events = store.list_events(status="resolved")
    if not events:
        console.print("[dim]No resolved events to score yet.[/dim]")
        return

    table = Table(
        title=f"Scores — All Resolved Events ({len(events)})",
        caption="Lower is better for both CRPS and Brier score",
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("ID", width=4, justify="right", style="bold")
    table.add_column("Title", min_width=28, max_width=44, no_wrap=True)
    table.add_column("Type", width=12)
    table.add_column("Forecasts", justify="right", width=10)
    table.add_column("Best", justify="right", width=9)
    table.add_column("Avg", justify="right", width=9)
    table.add_column("Metric", width=6)

    for event in events:
        rows = store.score_event(event.id)
        if not rows:
            continue
        metric = rows[0]["metric"]
        valid = [r["score"] for r in rows if r["score"] is not None]
        if not valid:
            continue
        table.add_row(
            str(event.id),
            event.title,
            _fmt_type(event.event_type),
            str(len(rows)),
            _fmt_score(min(valid), metric),
            _fmt_score(sum(valid) / len(valid), metric),
            f"[dim]{metric}[/dim]",
        )

    console.print()
    console.print(table)


# ---------------------------------------------------------------------------
# dashboard command
# ---------------------------------------------------------------------------

@app.command("dashboard")
def dashboard() -> None:
    """
    Show a summary of forecasting performance and calibration.

    Displays aggregate statistics, per-model breakdowns (grouped by the
    [bold]notes[/bold] field on each forecast), and a list of open events
    still awaiting resolution.
    """
    try:
        store = _store()
        all_events = store.list_events()
    except Exception as exc:
        _err(str(exc))
        raise typer.Exit(1)

    resolved = [e for e in all_events if e.status == "resolved"]
    open_events = [e for e in all_events if e.status == "open"]
    cancelled = [e for e in all_events if e.status == "cancelled"]

    console.print()
    console.rule("[bold]Forecast Dashboard[/bold]")
    console.print()

    summary = (
        f"[bold]{len(all_events)}[/bold] events   "
        f"[yellow]{len(open_events)} open[/yellow]   "
        f"[green]{len(resolved)} resolved[/green]"
        + (f"   [dim]{len(cancelled)} cancelled[/dim]" if cancelled else "")
    )
    console.print(Panel(summary, border_style="dim", padding=(0, 2)))
    console.print()

    if not resolved:
        console.print("[dim]No resolved events yet — keep forecasting and record some outcomes![/dim]")
        console.print()
        _print_open_events(store, open_events)
        return

    # Collect all scores
    crps_scores: list[float] = []
    brier_scores: list[float] = []
    model_crps: dict[str, list[float]] = {}
    model_brier: dict[str, list[float]] = {}

    for event in resolved:
        rows = store.score_event(event.id)
        if not rows:
            continue
        for row in rows:
            if row["score"] is None:
                continue
            model = row["notes"] or "unnamed"
            if row["metric"] == "crps":
                crps_scores.append(row["score"])
                model_crps.setdefault(model, []).append(row["score"])
            else:
                brier_scores.append(row["score"])
                model_brier.setdefault(model, []).append(row["score"])

    # Overall stats panel
    numeric_resolved = [e for e in resolved if e.event_type == "numeric"]
    binary_resolved = [e for e in resolved if e.event_type == "binary"]
    total_forecasts = sum(len(store.get_forecasts(e.id)) for e in all_events)

    stats_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 3))
    stats_table.add_column("Metric", style="dim")
    stats_table.add_column("Value")

    if crps_scores:
        avg_crps = sum(crps_scores) / len(crps_scores)
        stats_table.add_row(
            f"Numeric events  ({len(numeric_resolved)} resolved, {len(crps_scores)} forecasts)",
            f"avg CRPS [bold]{avg_crps:.4f}[/bold]   best {min(crps_scores):.4f}   worst {max(crps_scores):.4f}",
        )

    if brier_scores:
        avg_brier = sum(brier_scores) / len(brier_scores)
        brier_col = "green" if avg_brier < 0.05 else "yellow" if avg_brier < 0.20 else "red"
        stats_table.add_row(
            f"Binary events   ({len(binary_resolved)} resolved, {len(brier_scores)} forecasts)",
            f"avg Brier [{brier_col}][bold]{avg_brier:.4f}[/bold][/{brier_col}]   best {min(brier_scores):.4f}   worst {max(brier_scores):.4f}",
        )

    stats_table.add_row("Total forecasts submitted", str(total_forecasts))

    console.print(Panel(
        stats_table,
        title="[bold]Overall Performance[/bold]",
        border_style="cyan",
        padding=(0, 1),
    ))
    console.print()

    # Per-model breakdown
    all_models = set(model_crps) | set(model_brier)
    show_models = len(all_models) > 1 or (len(all_models) == 1 and "unnamed" not in all_models)
    if show_models:
        if model_crps:
            _print_model_table(model_crps, "crps", "Numeric Model Performance (lower CRPS is better)")
            console.print()
        if model_brier:
            _print_model_table(model_brier, "brier", "Binary Model Performance (lower Brier is better)")
            console.print()

    _print_open_events(store, open_events)


def _print_model_table(model_scores: dict[str, list[float]], metric: str, title: str) -> None:
    table = Table(title=title, box=box.ROUNDED, header_style="bold cyan", border_style="dim")
    table.add_column("Model / Notes", min_width=22)
    table.add_column("Forecasts", justify="right", width=10)
    table.add_column("Avg Score", justify="right", width=10)
    table.add_column("Best Score", justify="right", width=10)

    sorted_models = sorted(model_scores.items(), key=lambda x: sum(x[1]) / len(x[1]))
    for i, (model, s_list) in enumerate(sorted_models):
        avg = sum(s_list) / len(s_list)
        best = min(s_list)
        label = f"[green]{model}[/green]" if (i == 0 and len(sorted_models) > 1) else model
        table.add_row(label, str(len(s_list)), _fmt_score(avg, metric), _fmt_score(best, metric))

    console.print(table)


def _print_open_events(store: ForecastStore, open_events: list[Event]) -> None:
    if not open_events:
        return

    table = Table(
        title=f"Open Events — Awaiting Resolution ({len(open_events)})",
        box=box.SIMPLE_HEAD,
        header_style="bold yellow",
        border_style="dim",
    )
    table.add_column("ID", width=4, justify="right", style="bold")
    table.add_column("Title", min_width=30, no_wrap=True)
    table.add_column("Type", width=12)
    table.add_column("Forecasts", justify="right", width=10)
    table.add_column("Resolution", width=12)

    for event in open_events[:15]:
        forecasts = store.get_forecasts(event.id)
        table.add_row(
            str(event.id),
            event.title,
            _fmt_type(event.event_type),
            str(len(forecasts)),
            event.resolution_date or "[dim]—[/dim]",
        )

    if len(open_events) > 15:
        table.add_row("[dim]…[/dim]", f"[dim]+{len(open_events) - 15} more[/dim]", "", "", "")

    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app()


if __name__ == "__main__":
    main()
