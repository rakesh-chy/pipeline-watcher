# pipeline-watcher

A self-hosted SLA monitor for batch data pipelines. Register your jobs, send heartbeats when they run, and `pipeline-watcher` will tell you when one goes stale, when failure rates spike, or when an upstream file stops refreshing - with Slack alerts and a small status page.

Backed by Postgres. Single binary. ~30 seconds from `docker compose up` to a working dashboard.

---

## Why

Most teams' "is this pipeline still working?" answer is buried in three different tools - orchestrator UI, Slack history, a CSV on someone's laptop. This is the smallest thing that turns that into one URL.

It's deliberately not a replacement for Datadog / PagerDuty / a real APM. It's the in-between layer for batch jobs that don't justify any of those, but that you still need to know about when they break.

## What it does

- **Heartbeat ingest** - pipelines POST `{pipeline, status, duration, message}` when they finish a run. Recorded with a server-side timestamp.
- **Freshness probes** - for pipelines that produce an output URL/file, an optional `Last-Modified` probe runs on the schedule.
- **SLA evaluator** - every N seconds, opens an incident when:
  - the last heartbeat is older than the expected interval (`heartbeat_missed`),
  - the failure rate over a configurable window exceeds the threshold (`failure_rate`),
  - the freshness probe reports a stale resource (recorded as a failed heartbeat).
- **Incidents** - auto-deduped while open, auto-resolved when health returns. Each open/resolve emits a Slack message (when configured).
- **Status page** - `/` renders a dark dashboard; `/status` is the JSON version.
- **CLI** - register pipelines, emit heartbeats, run one-off checks, browse incidents.

## Architecture

```
                                 ┌──────────────────┐
   your pipelines  ──heartbeat──>│  FastAPI ingest  │──┐
                                 └──────────────────┘  │
                                                       v
                                           ┌──────────────────────┐
                                           │      Postgres        │
                                           │  pipelines           │
                                           │  heartbeats          │
                                           │  incidents           │
                                           └──────────┬───────────┘
                                                      │
   ┌────────────────────┐    ticks every N seconds    │
   │  APScheduler tick  │────────────────────────────>│
   └────────────────────┘     evaluate_once()         │
                                                      │
                            ┌─────────────────────────┴──────────────┐
                            v                                        v
                ┌──────────────────────┐                  ┌──────────────────┐
                │  Slack alerter       │                  │  Status page     │
                │  (open / resolved)   │                  │  /  /status      │
                └──────────────────────┘                  └──────────────────┘
```

## Five-minute start

```bash
# 1. Start Postgres
docker compose up -d postgres

# 2. Install
pip install -e ".[dev]"

# 3. Init + seed + synthetic heartbeats + first SLA pass
watcher demo

# 4. Status page on http://127.0.0.1:8080
watcher serve
```

You should land on a status page with five pipelines: one healthy, one stale, one failing, one quiet, one freshness-probed.

## Real usage

```bash
# Register a pipeline (single)
watcher register --name orders-etl --interval 3600 --owner data-platform

# Or register many from YAML
watcher register --config examples/pipelines.yaml

# Have your pipeline emit a heartbeat when a run finishes
curl -X POST http://127.0.0.1:8080/heartbeat \
  -H "content-type: application/json" \
  -d '{"pipeline":"orders-etl","status":"success","duration_seconds":42}'

# Or from the CLI (handy in cron / GitHub Actions)
watcher heartbeat orders-etl --status success --duration 42

# Run the evaluator on a schedule
watcher run-scheduler
```

## Config

All settings come from env vars (or a `.env` file in the working directory). Prefix: `WATCHER_`.

| Env var | Default | Notes |
|---|---|---|
| `WATCHER_DATABASE_URL` | `postgresql://watcher:watcher@localhost:5432/watcher` | Required |
| `WATCHER_API_HOST` | `127.0.0.1` | |
| `WATCHER_API_PORT` | `8080` | |
| `WATCHER_CHECK_INTERVAL_SECONDS` | `60` | Evaluator tick rate |
| `WATCHER_ALERTS_ENABLED` | `false` | Set `true` to actually post to Slack |
| `WATCHER_SLACK_WEBHOOK_URL` | - | Required when alerts are on |
| `WATCHER_LOG_LEVEL` | `INFO` | |

See [`.env.example`](.env.example).

## Project layout

```
src/watcher/
  config.py          # Pydantic-settings, env-var driven
  models.py          # Pipeline / Heartbeat / Incident
  storage.py         # Postgres schema + queries (psycopg pool)
  checks.py          # SLA evaluators (heartbeat, failure_rate)
  freshness.py       # Last-Modified probe
  alerter.py         # Slack webhook poster
  runner.py          # evaluate_once() - open/resolve + alert
  scheduler.py       # APScheduler loop
  api.py             # FastAPI app
  cli.py             # Typer CLI
  seed.py            # Demo pipelines + history
  templates/
    status.html      # Jinja status page
tests/               # pytest, real Postgres via docker-compose
.github/workflows/   # CI: postgres service + ruff + pytest
```

## Tests

```bash
docker compose up -d postgres
pytest -v
```

Tests run against a real Postgres (each test gets its own schema, dropped on teardown). If Postgres isn't reachable they skip cleanly. CI uses a Postgres service container.

## Roadmap

- PagerDuty / generic webhook alerter alongside Slack
- Per-pipeline retention policy (default: 90 days of heartbeats)
- Read-only public status page mode
- OpenTelemetry trace export so heartbeats can carry a trace id

## License

MIT - see [LICENSE](LICENSE).
