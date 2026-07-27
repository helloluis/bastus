"""FastAPI control-plane app: run CRUD, live WebSocket streaming, pause/abort,
and static hosting of the web UI.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from bastus.db import repo
from bastus.db.session import get_database
from bastus.engine.report import narrative_summary
from bastus.models.run import RunConfig
from bastus.models.taxonomy import CATEGORIES
from bastus.web.broadcaster import Broadcaster
from bastus.web.manager import RunManager
from bastus.web.provision import SERVER_CHANNEL, ServerManager
from bastus.web.schemas import CreateRunRequest

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = get_database()
    await db.create_all()
    await repo.fail_orphaned_runs(db)  # a restart kills in-flight run tasks; don't leave them "running"
    app.state.db = db
    app.state.broadcaster = Broadcaster()
    app.state.server_mgr = ServerManager(app.state.broadcaster)
    app.state.manager = RunManager(db, app.state.broadcaster, app.state.server_mgr)
    await app.state.server_mgr.reconcile()  # re-attach to a pod that survived a restart
    yield
    await db.dispose()


app = FastAPI(title="BASTUS", lifespan=lifespan)


def _serialize_run(row) -> dict:
    return {
        "run_id": row.id,
        "label": row.label,
        "state": row.state,
        "config": row.config,
        "total_goals": row.total_goals,
        "total_breaks": row.total_breaks,
        "error": row.error,
        "created_at": row.created_at,
        "finished_at": row.finished_at,
    }


@app.get("/api/categories")
async def categories() -> list[dict]:
    return [
        {"code": c.code, "name": c.name, "description": c.description,
         "text_refusal_only": c.text_refusal_only}
        for c in CATEGORIES
    ]


@app.get("/api/server")
async def server_status() -> dict:
    return app.state.server_mgr.status.as_dict()


@app.post("/api/server/provision")
async def provision_server() -> dict:
    ok = await app.state.server_mgr.provision()
    if not ok:
        raise HTTPException(status_code=409, detail="server already provisioning or ready")
    return {"ok": True}


@app.post("/api/server/destroy")
async def destroy_server() -> dict:
    if app.state.manager.has_active_runs:
        raise HTTPException(
            status_code=409,
            detail="Cannot destroy the server while a run is in progress — abort or wait for it to finish.",
        )
    ok = await app.state.server_mgr.destroy()
    if not ok:
        raise HTTPException(status_code=409, detail="no pod to destroy")
    return {"ok": True}


@app.websocket("/api/server/stream")
async def server_stream(ws: WebSocket) -> None:
    await ws.accept()
    broadcaster: Broadcaster = ws.app.state.broadcaster
    queue = broadcaster.subscribe(SERVER_CHANNEL)
    try:
        await ws.send_json({"type": "server_state", "data": ws.app.state.server_mgr.status.as_dict()})
        while True:
            msg = await queue.get()
            await ws.send_json(msg)
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.unsubscribe(SERVER_CHANNEL, queue)


@app.post("/api/runs")
async def create_run(req: CreateRunRequest) -> dict:
    # Live runs need the attacker pod; mock runs are offline and don't.
    if not req.mock and not app.state.server_mgr.is_ready:
        raise HTTPException(status_code=409, detail="Provision the RunPod server before launching a live run.")
    try:
        config = RunConfig(
            label=req.label,
            enabled_categories=req.enabled_categories,
            num_tests=req.num_tests,
            beam_width=req.beam_width,
            branching_factor=req.branching_factor,
            max_turns=req.max_turns,
            break_threshold=req.break_threshold,
            multimodal=req.multimodal,
            mock=req.mock,
        )
    except Exception as exc:  # invalid category, etc.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    run_id = await app.state.manager.start(config)
    return {"run_id": run_id}


@app.get("/api/runs")
async def list_runs() -> list[dict]:
    rows = await repo.list_runs(app.state.db)
    return [_serialize_run(r) for r in rows]


@app.get("/api/runs/{run_id}")
async def get_run(run_id: int) -> dict:
    row = await repo.get_run(app.state.db, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    goals = await repo.get_goals(app.state.db, run_id)
    per_cat: dict[str, dict] = {}
    for g in goals:
        s = per_cat.setdefault(g.category, {"tested": 0, "broken": 0, "best_harm": 0.0})
        s["tested"] += 1
        s["broken"] += int(g.broken)
        s["best_harm"] = max(s["best_harm"], g.best_harm)
    for s in per_cat.values():
        s["asr"] = s["broken"] / s["tested"] if s["tested"] else 0.0
    turns = await repo.get_turns(app.state.db, run_id)
    verdict_counts: dict[str, int] = {}
    for t in turns:
        verdict_counts[t.verdict] = verdict_counts.get(t.verdict, 0) + 1
    detail = _serialize_run(row)
    detail["goals"] = [
        {"goal_key": g.goal_key, "category": g.category, "objective": g.objective,
         "broken": g.broken, "best_harm": g.best_harm, "seed_image_ref": g.seed_image_ref}
        for g in goals
    ]
    detail["per_category"] = per_cat
    detail["verdict_counts"] = verdict_counts
    detail["summary_text"] = narrative_summary(
        per_cat, state=row.state, error_turns=verdict_counts.get("error", 0)
    )
    return detail


@app.get("/api/runs/{run_id}/turns")
async def get_turns(run_id: int) -> list[dict]:
    turns = await repo.get_turns(app.state.db, run_id)
    return [
        {"goal_key": t.goal_key, "branch_id": t.branch_id, "depth": t.depth,
         "attacker": t.attacker_text, "target": t.target_text, "verdict": t.verdict,
         "harm": t.harm, "category": t.category, "created_at": t.created_at}
        for t in turns
    ]


@app.post("/api/runs/{run_id}/pause")
async def pause_run(run_id: int) -> dict:
    ok = await app.state.manager.pause(run_id)
    if not ok:
        raise HTTPException(status_code=409, detail="run not active")
    return {"ok": True}


@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: int) -> dict:
    ok = await app.state.manager.resume(run_id)
    if not ok:
        raise HTTPException(status_code=409, detail="run not active")
    return {"ok": True}


@app.post("/api/runs/{run_id}/abort")
async def abort_run(run_id: int) -> dict:
    ok = app.state.manager.abort(run_id)
    if not ok:
        raise HTTPException(status_code=409, detail="run not active")
    return {"ok": True}


@app.websocket("/api/runs/{run_id}/stream")
async def stream(ws: WebSocket, run_id: int) -> None:
    await ws.accept()
    broadcaster: Broadcaster = ws.app.state.broadcaster
    queue = broadcaster.subscribe(run_id)
    try:
        row = await repo.get_run(ws.app.state.db, run_id)
        if row is not None:
            await ws.send_json({"type": "snapshot",
                                "data": {"run_id": row.id, "state": row.state}})
        while True:
            msg = await queue.get()
            await ws.send_json(msg)
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.unsubscribe(run_id, queue)


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
