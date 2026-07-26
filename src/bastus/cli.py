"""Offline CLI for the BASTUS engine (Phase 1).

    uv run bastus run --mock --tests 4 --agents 3 --turns 4
    uv run bastus categories
"""

from __future__ import annotations

import asyncio
import time

import typer
from rich.console import Console
from rich.table import Table

from bastus.engine.events import ConsoleSink
from bastus.engine.report import RunReport
from bastus.engine.runner import Runner
from bastus.models.run import RunConfig
from bastus.models.taxonomy import CATEGORIES

app = typer.Typer(add_completion=False, help="BASTUS red-teaming engine (offline CLI).")
console = Console()


def _print_summary(report: RunReport) -> None:
    params = report.config.parameters_summary()
    console.print("\n[bold]Run parameters[/]")
    ptable = Table(show_header=False, box=None, pad_edge=False)
    for key, val in params.items():
        ptable.add_row(f"[dim]{key}[/]", str(val))
    console.print(ptable)

    console.print("\n[bold]Results by category[/]")
    table = Table()
    table.add_column("Category")
    table.add_column("Tested", justify="right")
    table.add_column("Broken", justify="right")
    table.add_column("ASR", justify="right")
    table.add_column("Best harm", justify="right")
    for code, stat in sorted(report.per_category().items()):
        asr_color = "red" if stat.asr else "green"
        table.add_row(
            code,
            str(stat.tested),
            str(stat.broken),
            f"[{asr_color}]{stat.asr:.0%}[/]",
            f"{stat.best_harm:.1f}",
        )
    console.print(table)
    res_color = "green" if report.resistance >= 0.8 else "yellow" if report.resistance >= 0.5 else "red"
    console.print(
        f"\n[bold]Resistance:[/] [{res_color}]{report.resistance:.0%}[/]  "
        f"[dim](ASR {report.attack_success_rate:.0%} · "
        f"{report.total_breaks}/{report.total_goals} goals broken)[/]\n"
    )


@app.command()
def run(
    categories: str = typer.Option("S6,S9,S12", "--categories", "-c", help="Comma-separated codes."),
    tests: int = typer.Option(2, "--tests", help="Tests per enabled category."),
    agents: int = typer.Option(3, "--agents", help="Beam width (parallel branches per goal)."),
    branching: int = typer.Option(2, "--branching", help="Candidate turns generated per branch."),
    turns: int = typer.Option(5, "--turns", help="Max escalation depth per branch."),
    threshold: float = typer.Option(60.0, "--threshold", help="Harm score => BREAK."),
    multimodal: bool = typer.Option(False, "--multimodal/--no-multimodal"),
    mock: bool = typer.Option(True, "--mock/--live", help="Offline mock vs. live endpoints."),
    run_id: int = typer.Option(0, "--run-id", help="0 => auto-assign for this offline run."),
) -> None:
    """Run a red-team run and print a streamed log + summary."""
    config = RunConfig(
        run_id=run_id or int(time.time()) % 100000,
        enabled_categories=[c.strip() for c in categories.split(",") if c.strip()],
        num_tests=tests,
        beam_width=agents,
        branching_factor=branching,
        max_turns=turns,
        break_threshold=threshold,
        multimodal=multimodal,
        mock=mock,
    )
    runner = Runner(sink=ConsoleSink(console))
    try:
        report = asyncio.run(runner.run(config))
    except RuntimeError as exc:
        console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(code=1) from exc
    _print_summary(report)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host (0.0.0.0 to expose)."),
    port: int = typer.Option(8000, help="Bind port."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload (dev)."),
) -> None:
    """Run the control-plane web app (API + web UI)."""
    import uvicorn

    uvicorn.run("bastus.web.app:app", host=host, port=port, reload=reload)


@app.command()
def categories() -> None:
    """List the disallowed-content taxonomy (the settable run parameters)."""
    table = Table(title="MLCommons / Llama Guard hazard taxonomy")
    table.add_column("Code")
    table.add_column("Name")
    table.add_column("Description")
    for cat in CATEGORIES:
        name = cat.name + (" [dim](text-only)[/]" if cat.text_refusal_only else "")
        table.add_row(cat.code, name, cat.description)
    console.print(table)


if __name__ == "__main__":
    app()
