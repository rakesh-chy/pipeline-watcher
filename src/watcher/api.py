"""FastAPI app: heartbeat ingest + JSON + HTML status."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib import resources

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from watcher.checks import run_checks
from watcher.config import Settings, get_settings
from watcher.models import Heartbeat, IncidentStatus, Pipeline
from watcher.storage import Storage


def _templates_env() -> Environment:
    templates_dir = resources.files("watcher").joinpath("templates")
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["humanize_age"] = _humanize_age
    return env


def _humanize_age(ts: datetime | None) -> str:
    if ts is None:
        return "never"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    delta = (datetime.now(UTC) - ts).total_seconds()
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def create_app(storage: Storage | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    storage = storage or Storage(settings=settings)
    templates = _templates_env()

    app = FastAPI(title="pipeline-watcher", version="0.1.0")

    def get_storage() -> Storage:
        return storage

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.post("/heartbeat", status_code=202)
    def post_heartbeat(hb: Heartbeat, st: Storage = Depends(get_storage)) -> dict:
        if st.get_pipeline(hb.pipeline) is None:
            raise HTTPException(status_code=404, detail=f"unknown pipeline: {hb.pipeline}")
        hb_id = st.record_heartbeat(hb)
        return {"id": hb_id}

    @app.post("/pipelines", status_code=201)
    def upsert_pipeline(p: Pipeline, st: Storage = Depends(get_storage)) -> dict:
        st.upsert_pipeline(p)
        return {"name": p.name}

    @app.get("/pipelines")
    def list_pipelines(st: Storage = Depends(get_storage)) -> list[dict]:
        return [p.model_dump() for p in st.list_pipelines()]

    @app.get("/status")
    def status_json(st: Storage = Depends(get_storage)) -> dict:
        pipelines = st.list_pipelines()
        out = []
        for p in pipelines:
            results = run_checks(p, st)
            last = st.last_heartbeat(p.name)
            out.append(
                {
                    "pipeline": p.name,
                    "owner": p.owner,
                    "last_heartbeat_ts": last["ts"].isoformat() if last else None,
                    "last_status": last["status"] if last else None,
                    "checks": [
                        {
                            "kind": r.kind.value,
                            "breaching": r.breaching,
                            "severity": r.severity.value,
                            "detail": r.detail,
                        }
                        for r in results
                    ],
                }
            )
        open_incidents = st.list_incidents(IncidentStatus.OPEN)
        return {"pipelines": out, "open_incidents": len(open_incidents)}

    @app.get("/", response_class=HTMLResponse)
    def status_page(request: Request, st: Storage = Depends(get_storage)) -> str:
        pipelines = st.list_pipelines()
        rows = []
        for p in pipelines:
            results = run_checks(p, st)
            last = st.last_heartbeat(p.name)
            healthy = not any(r.breaching for r in results)
            rows.append(
                {
                    "pipeline": p,
                    "last": last,
                    "results": results,
                    "healthy": healthy,
                }
            )
        open_incidents = st.list_incidents(IncidentStatus.OPEN)
        tpl = templates.get_template("status.html")
        return tpl.render(
            rows=rows,
            open_incidents=open_incidents,
            now=datetime.now(UTC),
        )

    return app
