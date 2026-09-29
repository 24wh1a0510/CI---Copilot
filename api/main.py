"""FastAPI application — Memory-First Competitive Intelligence Copilot.

All endpoints are served at /api/. WebSocket live updates at /ws/.
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import (
    BackgroundTasks,
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from config.settings import settings
from logging_.audit_logger import AuditLogger, AUDIT_DIR
from memory.hindsight_store import HindsightStore
from models.memory_schemas import (
    BriefingRequest,
    CompetitorEvent,
    CompetitorMemoryProfile,
    MemoryStats,
    Prediction,
    RunStatus,
    StrategyEvolution,
)

RESULTS_DIR = Path("data/briefing_results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Shared store instance (initialized in lifespan)
_store: HindsightStore | None = None

# Run registry
_runs: dict[str, dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared resources at startup."""
    global _store
    _store = HindsightStore(base_path=settings.hindsight_memory_path)
    yield
    # Cleanup (nothing needed for file-based store)


app = FastAPI(
    title="CI Copilot API",
    description="Memory-First Competitive Intelligence Copilot",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── WebSocket Connection Manager ──────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}  # run_id -> connections
        self._global: list[WebSocket] = []  # global audit stream

    async def connect(self, websocket: WebSocket, run_id: str | None = None):
        await websocket.accept()
        if run_id:
            self._connections.setdefault(run_id, []).append(websocket)
        else:
            self._global.append(websocket)

    def disconnect(self, websocket: WebSocket, run_id: str | None = None):
        if run_id and run_id in self._connections:
            self._connections[run_id] = [
                ws for ws in self._connections[run_id] if ws != websocket
            ]
        if websocket in self._global:
            self._global.remove(websocket)

    async def broadcast_run(self, run_id: str, data: dict):
        """Send event to all connections for a specific run."""
        connections = self._connections.get(run_id, [])
        dead = []
        for ws in connections:
            try:
                await ws.send_text(json.dumps(data, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, run_id)

    async def broadcast_global(self, data: dict):
        """Send event to all global audit connections."""
        dead = []
        for ws in self._global:
            try:
                await ws.send_text(json.dumps(data, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


# ── Helper Functions ──────────────────────────────────────────────────────────

def get_store() -> HindsightStore:
    if _store is None:
        raise HTTPException(status_code=503, detail="Memory store not initialized")
    return _store


def load_briefing_result(briefing_id: str) -> dict | None:
    path = RESULTS_DIR / f"{briefing_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_briefing_history() -> list[dict]:
    history_file = Path("data/briefing_history.json")
    if not history_file.exists():
        return []
    try:
        data = json.loads(history_file.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    store = get_store()
    stats = store.get_stats()
    return {
        "status": "ok",
        "version": "2.0.0",
        "memory_stats": stats.model_dump(),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── Run Management ────────────────────────────────────────────────────────────

@app.post("/api/runs/start")
async def start_run(request: BriefingRequest, background_tasks: BackgroundTasks):
    """Start a new CI briefing run in the background."""
    import uuid
    run_id = uuid.uuid4().hex[:12]

    run_status = RunStatus(
        run_id=run_id,
        status="queued",
        progress=0,
        current_agent="",
        started_at=datetime.utcnow(),
    )
    _runs[run_id] = {
        "status": run_status.model_dump(mode="json"),
        "result": None,
    }

    background_tasks.add_task(
        _run_briefing_background,
        run_id=run_id,
        request=request,
    )

    return {"run_id": run_id, "status": "queued"}


@app.get("/api/runs/{run_id}/status")
async def get_run_status(run_id: str) -> RunStatus:
    if run_id not in _runs:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return RunStatus.model_validate(_runs[run_id]["status"])


@app.get("/api/runs/{run_id}/result")
async def get_run_result(run_id: str):
    if run_id not in _runs:
        # Try loading from disk
        result = load_briefing_result(run_id)
        if result:
            return result
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    run_data = _runs[run_id]
    status_dict = run_data.get("status", {})
    if status_dict.get("status") not in ("completed", "completed_with_partial_failures", "stopped_at_limit"):
        raise HTTPException(status_code=202, detail=f"Run {run_id} is still {status_dict.get('status')}")

    # Return from disk
    result = load_briefing_result(run_id)
    if result:
        return result
    raise HTTPException(status_code=404, detail="Briefing result not found on disk")


@app.get("/api/runs")
async def list_runs():
    runs = []
    for run_id, data in _runs.items():
        runs.append(data["status"])
    return sorted(runs, key=lambda r: r.get("started_at", ""), reverse=True)[:20]


# ── Memory API ────────────────────────────────────────────────────────────────

@app.get("/api/memory/stats")
async def get_memory_stats() -> MemoryStats:
    return get_store().get_stats()


@app.get("/api/memory/events")
async def get_memory_events(
    competitor: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    days: Optional[int] = Query(default=None),
) -> list[CompetitorEvent]:
    return get_store().get_events(competitor=competitor, event_type=event_type, limit=limit, days=days)


@app.get("/api/memory/profiles")
async def get_memory_profiles() -> list[CompetitorMemoryProfile]:
    return get_store().get_all_profiles()


@app.get("/api/memory/profiles/{competitor}")
async def get_memory_profile(competitor: str) -> CompetitorMemoryProfile:
    profile = get_store().get_memory_profile(competitor)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile for {competitor}")
    return profile


@app.get("/api/memory/timeline")
async def get_memory_timeline(
    competitor: Optional[str] = Query(default=None),
    days: int = Query(default=180, ge=1, le=730),
) -> list[CompetitorEvent]:
    return get_store().get_timeline(competitor=competitor, days=days)


@app.get("/api/memory/strategy/{competitor}")
async def get_strategy_evolution(competitor: str) -> StrategyEvolution:
    strat = get_store().get_strategy_evolution(competitor)
    if not strat:
        raise HTTPException(status_code=404, detail=f"No strategy data for {competitor}")
    return strat


@app.get("/api/memory/strategies")
async def get_all_strategies() -> list[StrategyEvolution]:
    return get_store().get_all_strategies()


@app.get("/api/memory/predictions")
async def get_predictions(
    competitor: Optional[str] = Query(default=None),
) -> list[Prediction]:
    return get_store().get_predictions(competitor=competitor)


@app.post("/api/memory/seed")
async def seed_demo_data():
    """Re-seed demo data if memory is empty."""
    store = get_store()
    stats_before = store.get_stats()
    if stats_before.total_events == 0:
        store._seed_demo_data()
        stats_after = store.get_stats()
        return {"seeded": True, "events_added": stats_after.total_events}
    return {"seeded": False, "message": f"Memory already has {stats_before.total_events} events"}


@app.delete("/api/memory/reset")
async def reset_memory():
    """Clear all memory (development use only)."""
    get_store().clear_all()
    return {"cleared": True, "message": "All Hindsight memory has been cleared"}


# ── Audit Logs ────────────────────────────────────────────────────────────────

@app.get("/api/audit/logs")
async def get_audit_logs(
    run_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    if run_id:
        events = AuditLogger.load(run_id)
        return events[-limit:]

    # Return from most recent log files
    log_files = sorted(AUDIT_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    all_events = []
    for lf in log_files[:5]:
        try:
            with open(lf, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        all_events.append(json.loads(line))
        except Exception:
            pass
    all_events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return all_events[:limit]


@app.get("/api/audit/logs/stream/{run_id}")
async def stream_audit_logs(run_id: str):
    """Server-Sent Events stream of audit log for a specific run."""
    async def event_generator():
        log_path = AUDIT_DIR / f"{run_id}.jsonl"
        last_pos = 0
        # Initial flush of existing events
        if log_path.exists():
            with open(log_path, encoding="utf-8") as f:
                content = f.read()
                last_pos = len(content.encode())
                for line in content.splitlines():
                    if line.strip():
                        yield f"data: {line}\n\n"

        # Poll for new events
        for _ in range(300):  # max 5 minutes
            await asyncio.sleep(1)
            if not log_path.exists():
                continue
            try:
                with open(log_path, "rb") as f:
                    f.seek(last_pos)
                    new_content = f.read()
                    if new_content:
                        last_pos += len(new_content)
                        for line in new_content.decode().splitlines():
                            if line.strip():
                                yield f"data: {line}\n\n"
            except Exception:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Briefings ─────────────────────────────────────────────────────────────────

@app.get("/api/briefings")
async def list_briefings():
    """List all briefings from disk results + history file."""
    briefings = []

    # From disk results
    for path in sorted(RESULTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            briefings.append({
                "id": path.stem,
                "topic": data.get("topic", ""),
                "competitors": data.get("competitors", []),
                "status": data.get("metadata", {}).get("status", "completed"),
                "started_at": data.get("metadata", {}).get("started_at", ""),
                "finished_at": data.get("metadata", {}).get("finished_at", ""),
            })
        except Exception:
            pass

    return briefings


@app.get("/api/briefings/{briefing_id}")
async def get_briefing(briefing_id: str):
    result = load_briefing_result(briefing_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Briefing {briefing_id} not found")
    return result


@app.get("/api/briefings/{briefing_id}/export/markdown")
async def export_briefing_markdown(briefing_id: str):
    result = load_briefing_result(briefing_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Briefing {briefing_id} not found")
    markdown = result.get("markdown", result.get("executive_summary", "No content"))
    return StreamingResponse(
        iter([markdown]),
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename=briefing_{briefing_id}.md"},
    )


@app.get("/api/briefings/{briefing_id}/export/pdf")
async def export_briefing_pdf(briefing_id: str):
    result = load_briefing_result(briefing_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Briefing {briefing_id} not found")

    try:
        from api.pdf_exporter import generate_pdf_bytes
        pdf_bytes = generate_pdf_bytes(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=briefing_{briefing_id}.pdf"},
    )


# ── WebSockets ────────────────────────────────────────────────────────────────

@app.websocket("/ws/runs/{run_id}")
async def websocket_run(websocket: WebSocket, run_id: str):
    await manager.connect(websocket, run_id)
    try:
        # Send current status immediately
        if run_id in _runs:
            await websocket.send_text(json.dumps({
                "event": "status",
                "data": _runs[run_id]["status"],
            }, default=str))
        while True:
            await asyncio.sleep(1)
            if run_id in _runs:
                status = _runs[run_id]["status"]
                if status.get("status") in ("completed", "failed"):
                    await websocket.send_text(json.dumps({
                        "event": "run_complete" if status.get("status") == "completed" else "run_failed",
                        "data": status,
                    }, default=str))
                    break
    except WebSocketDisconnect:
        manager.disconnect(websocket, run_id)


@app.websocket("/ws/audit")
async def websocket_audit(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(10)  # Keep alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ── Background Run Task ───────────────────────────────────────────────────────

async def _run_briefing_background(run_id: str, request: BriefingRequest) -> None:
    """Execute a briefing run asynchronously, broadcasting progress via WebSocket."""

    def update_status(progress: int, current_agent: str, status: str = "running"):
        _runs[run_id]["status"].update({
            "status": status,
            "progress": progress,
            "current_agent": current_agent,
        })

    # Capture the running event loop BEFORE entering the executor thread
    main_loop = asyncio.get_running_loop()

    def _schedule(coro):
        """Thread-safe way to schedule a coroutine on the main event loop."""
        asyncio.run_coroutine_threadsafe(coro, main_loop)

    def on_agent_progress(agent: str, message: str):
        """Called by crew.run_briefing when an agent makes progress — runs in executor thread."""
        agent_progress = {
            "Discovery": 10,
            "Research": 25,
            "Memory": 40,
            "Analyst": 55,
            "Strategy": 68,
            "Prediction": 80,
            "Writer": 92,
            "Supervisor": 5,
        }
        progress = 5
        for key, pct in agent_progress.items():
            if key.lower() in agent.lower():
                progress = pct
                break

        update_status(progress, agent)
        _schedule(manager.broadcast_run(run_id, {
            "event": "agent_progress",
            "data": {
                "run_id": run_id,
                "agent": agent,
                "message": message,
                "progress": progress,
                "timestamp": datetime.utcnow().isoformat(),
            },
        }))
        _schedule(manager.broadcast_global({
            "event": "audit_event",
            "data": {
                "run_id": run_id,
                "agent": agent,
                "message": message,
                "timestamp": datetime.utcnow().isoformat(),
                "event_type": "decision",
            },
        }))

    update_status(0, "", "running")
    await manager.broadcast_run(run_id, {"event": "run_started", "data": {"run_id": run_id}})

    try:
        # Run in executor to avoid blocking the event loop.
        # get_running_loop() is correct here — we ARE inside an async function.
        loop = asyncio.get_running_loop()
        from crew import run_briefing

        briefing = await loop.run_in_executor(
            None,
            lambda: run_briefing(
                topic=request.topic,
                competitors=request.competitors or [],
                on_progress=on_agent_progress,
            ),
        )

        _runs[run_id]["status"].update({
            "status": "completed",
            "progress": 100,
            "current_agent": "Writer",
            "finished_at": datetime.utcnow().isoformat(),
            "briefing_id": briefing.metadata.run_id,
        })
        _runs[run_id]["result"] = briefing.model_dump(mode="json")

        await manager.broadcast_run(run_id, {
            "event": "run_complete",
            "data": {
                "run_id": run_id,
                "briefing_id": briefing.metadata.run_id,
                "topic": briefing.topic,
                "status": "completed",
            },
        })

    except Exception as e:
        _runs[run_id]["status"].update({
            "status": "failed",
            "progress": 0,
            "current_agent": "",
            "finished_at": datetime.utcnow().isoformat(),
            "error": str(e),
        })
        await manager.broadcast_run(run_id, {
            "event": "run_failed",
            "data": {"run_id": run_id, "error": str(e)},
        })
