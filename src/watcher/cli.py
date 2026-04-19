"""Typer CLI."""

from __future__ import annotations

import logging
import sys
from typing import Annotated

import typer
import uvicorn
import yaml
from rich.console import Console
from rich.table import Table

from watcher.alerter import Alerter
from watcher.config import get_settings
from watcher.models import Heartbeat, IncidentStatus, Pipeline, RunStatus
from watcher.runner import evaluate_once
from watcher.seed import emit_demo_heartbeats, seed_pipelines
from watcher.storage import Storage

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


def _storage() -> Storage:
    return Storage(settings=get_settings())


@app.command()
def init() -> None:
    """Create the Postgres schema."""
    st = _storage()
    try:
        st.init_schema()
        console.print(f"[green]ok[/green] schema ready at [cyan]{st.settings.database_url}[/cyan]")
    finally:
        st.close()


@app.command()
def register(
    config: Annotated[str | None, typer.Option("--config", "-c", help="YAML file of pipelines")] = None,
    name: Annotated[str | None, typer.Option(help="Pipeline name (single mode)")] = None,
    interval: Annotated[int | None, typer.Option(help="Expected interval in seconds")] = None,
    description: Annotated[str | None, typer.Option()] = None,
    owner: Annotated[str | None, typer.Option()] = None,
    freshness_url: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Register one pipeline (flags) or many (--config file.yaml)."""
    st = _storage()
    try:
        if config:
            with open(config) as f:
                data = yaml.safe_load(f) or {}
            entries = data.get("pipelines", [])
            for entry in entries:
                st.upsert_pipeline(Pipeline(**entry))
            console.print(f"[green]ok[/green] registered {len(entries)} pipeline(s)")
            return
        if not name or interval is None:
            console.print("[red]error[/red] provide --config OR --name and --interval")
            raise typer.Exit(2)
        st.upsert_pipeline(
            Pipeline(
                name=name,
                description=description,
                expected_interval_seconds=interval,
                owner=owner,
                freshness_url=freshness_url,
            )
        )
        console.print(f"[green]ok[/green] registered [cyan]{name}[/cyan]")
    finally:
        st.close()


@app.command()
def heartbeat(
    pipeline: str,
    status: Annotated[str, typer.Option(help="success|failed|running")] = "success",
    duration: Annotated[float | None, typer.Option()] = None,
    message: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Emit a heartbeat."""
    st = _storage()
    try:
        if st.get_pipeline(pipeline) is None:
            console.print(f"[red]error[/red] unknown pipeline: {pipeline}")
            raise typer.Exit(2)
        hb_id = st.record_heartbeat(
            Heartbeat(
                pipeline=pipeline,
                status=RunStatus(status),
                duration_seconds=duration,
                message=message,
            )
        )
        console.print(f"[green]ok[/green] heartbeat #{hb_id}")
    finally:
        st.close()


@app.command()
def seed() -> None:
    """Register the bundled demo pipelines."""
    st = _storage()
    try:
        n = seed_pipelines(st)
        console.print(f"[green]ok[/green] seeded {n} pipelines")
    finally:
        st.close()


@app.command()
def demo() -> None:
    """Init schema, seed pipelines, emit synthetic history, run one evaluation pass."""
    st = _storage()
    try:
        st.init_schema()
        seed_pipelines(st)
        n = emit_demo_heartbeats(st)
        console.print(f"[green]ok[/green] wrote {n} synthetic heartbeats")
        summary = evaluate_once(st)
        console.print(
            f"[green]ok[/green] checked {summary.pipelines_checked} pipelines, "
            f"{summary.incidents_opened} opened, {summary.incidents_resolved} resolved"
        )
        console.print("\nRun [bold]watcher status[/bold] or [bold]watcher serve[/bold] to view.")
    finally:
        st.close()


@app.command()
def check() -> None:
    """Run the SLA evaluator once."""
    st = _storage()
    try:
        alerter = Alerter(settings=st.settings)
        summary = evaluate_once(st, alerter=alerter)
        console.print(
            f"checked {summary.pipelines_checked} pipelines, "
            f"{summary.incidents_opened} opened, {summary.incidents_resolved} resolved"
        )
        for r in summary.results:
            marker = "[red]FAIL[/red]" if r.breaching else "[green]ok[/green]"
            console.print(f"  {marker} {r.pipeline} / {r.kind.value} - {r.detail}")
    finally:
        st.close()


@app.command()
def status() -> None:
    """Print pipeline health to the terminal."""
    st = _storage()
    try:
        from watcher.checks import run_checks

        table = Table(title="pipeline-watcher", show_lines=False)
        table.add_column("pipeline", style="cyan")
        table.add_column("owner")
        table.add_column("last")
        table.add_column("checks")

        for p in st.list_pipelines():
            results = run_checks(p, st)
            last = st.last_heartbeat(p.name)
            last_str = last["ts"].strftime("%Y-%m-%d %H:%M") if last else "-"
            check_strs = []
            for r in results:
                mark = "[red]FAIL[/red]" if r.breaching else "[green]ok[/green]"
                check_strs.append(f"{mark} {r.kind.value}")
            table.add_row(p.name, p.owner or "-", last_str, "\n".join(check_strs))
        console.print(table)
    finally:
        st.close()


@app.command()
def incidents(
    open_only: Annotated[bool, typer.Option("--open/--all")] = True,
) -> None:
    """List incidents (open by default)."""
    st = _storage()
    try:
        rows = st.list_incidents(IncidentStatus.OPEN if open_only else None)
        if not rows:
            console.print("[green]no incidents[/green]")
            return
        table = Table(title=f"incidents ({'open' if open_only else 'all'})")
        table.add_column("id")
        table.add_column("pipeline", style="cyan")
        table.add_column("kind")
        table.add_column("severity")
        table.add_column("status")
        table.add_column("opened")
        for i in rows:
            sev_color = "red" if i.severity.value == "critical" else "yellow"
            table.add_row(
                str(i.id),
                i.pipeline,
                i.kind.value,
                f"[{sev_color}]{i.severity.value}[/{sev_color}]",
                i.status.value,
                i.opened_at.strftime("%Y-%m-%d %H:%M"),
            )
        console.print(table)
    finally:
        st.close()


@app.command()
def serve(
    host: Annotated[str | None, typer.Option()] = None,
    port: Annotated[int | None, typer.Option()] = None,
) -> None:
    """Serve the FastAPI status page + heartbeat API."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    uvicorn.run(
        "watcher.api:create_app",
        host=host or settings.api_host,
        port=port or settings.api_port,
        factory=True,
        reload=False,
    )


@app.command()
def run_scheduler() -> None:
    """Run the evaluator loop until Ctrl-C."""
    from watcher.scheduler import run_forever

    logging.basicConfig(level=get_settings().log_level)
    try:
        run_forever()
    except KeyboardInterrupt:
        console.print("\n[yellow]stopped[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    app()
