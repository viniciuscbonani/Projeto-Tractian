from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from tractian_agent.config import Settings, get_settings
from tractian_agent.domain.models import RunCreate, SessionCreate
from tractian_agent.persistence import Database
from tractian_agent.services import RunService


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    service: RunService | None = None,
) -> FastAPI:
    config = settings or get_settings()
    db = database or Database(config.app_database_path)
    runs = service or RunService(config, db)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db.initialize()
        yield

    application = FastAPI(
        title="TRACTIAN Agent API",
        version="0.1.0",
        description=(
            "API própria para análises internas, revisões, histórico e auditoria. "
            "Personas são demonstração e não equivalem a autenticação."
        ),
        lifespan=lifespan,
    )
    application.state.settings = config
    application.state.database = db
    application.state.run_service = runs
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_db(request: Request) -> Database:
        return request.app.state.database

    def get_runs(request: Request) -> RunService:
        return request.app.state.run_service

    @application.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/personas", tags=["client"])
    async def personas(database_: Database = Depends(get_db)) -> list[dict[str, Any]]:
        return database_.list_personas()

    @application.get("/api/personas/{persona_id}/assets", tags=["client"])
    async def assets(
        persona_id: str, run_service: RunService = Depends(get_runs)
    ) -> list[dict[str, Any]]:
        try:
            return await run_service.list_assets(persona_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    @application.get("/api/demo-cases", tags=["client"])
    async def demo_cases(run_service: RunService = Depends(get_runs)) -> list[dict[str, Any]]:
        return run_service.demo_cases()

    @application.post("/api/sessions", status_code=201, tags=["client"])
    async def create_session(
        body: SessionCreate, database_: Database = Depends(get_db)
    ) -> dict[str, Any]:
        if not database_.get_persona(body.persona_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona não encontrada.")
        return database_.create_session(body.persona_id).model_dump(mode="json")

    @application.post("/api/runs", status_code=202, tags=["client"])
    async def create_run(
        body: RunCreate,
        run_service: RunService = Depends(get_runs),
        wait: bool = Query(False, description="Uso de CLI/testes; a UI usa execução assíncrona."),
    ) -> dict[str, Any]:
        try:
            run = run_service.create(body)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        if run.get("reused"):
            return run
        if wait:
            await run_service.execute(run["id"])
            return run_service.database.get_run(run["id"]) or run
        run_service.start(run["id"])
        return run

    @application.get("/api/runs/{run_id}", tags=["client"])
    async def get_run(run_id: str, database_: Database = Depends(get_db)) -> dict[str, Any]:
        run = database_.get_run(run_id)
        if not run:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Execução não encontrada.")
        return run

    @application.get("/api/runs/{run_id}/result", tags=["client"])
    async def get_result(
        run_id: str, database_: Database = Depends(get_db)
    ) -> dict[str, Any]:
        if not database_.get_run(run_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Execução não encontrada.")
        result = database_.get_result(run_id)
        if not result:
            raise HTTPException(status.HTTP_409_CONFLICT, "Resultado ainda não está disponível.")
        return result

    @application.get("/api/personas/{persona_id}/history", tags=["client"])
    async def persona_history(
        persona_id: str, database_: Database = Depends(get_db)
    ) -> list[dict[str, Any]]:
        return database_.list_runs(persona_id=persona_id)

    @application.get("/api/sessions/{session_id}/history", tags=["client"])
    async def session_history(
        session_id: str, database_: Database = Depends(get_db)
    ) -> list[dict[str, Any]]:
        return database_.list_runs(session_id=session_id)

    @application.get("/api/runs/{run_id}/events", tags=["client"])
    async def progress_events(
        run_id: str, request: Request, database_: Database = Depends(get_db)
    ) -> StreamingResponse:
        if not database_.get_run(run_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Execução não encontrada.")

        async def stream():
            cursor = 0
            while not await request.is_disconnected():
                for checkpoint in database_.list_checkpoints(
                    run_id, after_id=cursor, include_state=True
                ):
                    cursor = checkpoint["id"]
                    yield f"id: {cursor}\nevent: progress\ndata: {json.dumps(checkpoint, ensure_ascii=False)}\n\n"
                run = database_.get_run(run_id)
                if run and run["status"] in {"completed", "failed"}:
                    yield f"event: done\ndata: {json.dumps(run, ensure_ascii=False)}\n\n"
                    break
                yield ": keep-alive\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @application.get("/api/admin/runs", tags=["admin"])
    async def admin_runs(
        database_: Database = Depends(get_db), limit: int = Query(100, ge=1, le=500)
    ) -> list[dict[str, Any]]:
        return database_.list_runs(limit=limit)

    @application.get("/api/admin/runs/{run_id}/checkpoints", tags=["admin"])
    async def checkpoints(
        run_id: str, database_: Database = Depends(get_db)
    ) -> list[dict[str, Any]]:
        if not database_.get_run(run_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Execução não encontrada.")
        return database_.list_checkpoints(run_id)

    @application.get("/api/admin/benchmarks/latest", tags=["admin"])
    async def latest_benchmark() -> dict[str, Any]:
        repository_root = Path(__file__).resolve().parents[4]
        report = config.benchmark_report_path
        if not report.is_absolute():
            report = repository_root / report
        if not report.exists():
            return {
                "status": "not_run",
                "message": f"Relatório configurado não encontrado: {report.name}.",
            }
        return json.loads(report.read_text(encoding="utf-8"))

    return application


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "tractian_agent.api.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )
