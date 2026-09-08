from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from tractian_agent.domain.models import Persona, RunCreate, RunResult, RunStatus, Session

PERSONAS = [
    Persona(id="ana", user_id="usr_ana", name="Ana Mantovani", role="Gerente de manutenção", company_id="comp_forja_br", company_name="Forja Brasil"),
    Persona(id="lucas", user_id="usr_lucas", name="Lucas Pereira", role="Mecânico", company_id="comp_aurora", company_name="Cervejaria Aurora"),
    Persona(id="marta", user_id="usr_marta", name="Marta Ribeiro", role="Analista de confiabilidade", company_id="comp_papel_sul", company_name="Papel Sul"),
    Persona(id="helena", user_id="usr_helena", name="Helena Castro", role="Gerente de manutenção", company_id="comp_papel_sul", company_name="Papel Sul"),
    Persona(id="pedro", user_id="usr_pedro", name="Pedro Alves", role="Coordenador", company_id="comp_mineracao_andes", company_name="Mineração Andes"),
    Persona(id="sofia", user_id="usr_sofia", name="Sofia Nunes", role="Analista de confiabilidade", company_id="comp_petro_delta", company_name="Petro Delta"),
    Persona(id="bruno", user_id="usr_bruno", name="Bruno Dias", role="Operador", company_id="comp_acme", company_name="Acme Auto Peças"),
    Persona(id="carla", user_id="usr_carla", name="Carla Mendes", role="Engenheira", company_id="comp_cimento_vale", company_name="Cimento Vale"),
    Persona(id="raul", user_id="usr_raul", name="Raul Souza", role="Eletricista", company_id="comp_texfil", company_name="Texfil"),
    Persona(id="gustavo", user_id="usr_gustavo", name="Gustavo Lima", role="Mecânico", company_id="comp_cimento_vale", company_name="Cimento Vale"),
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (datetime, Path)):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Tipo não serializável: {type(value)!r}")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default, separators=(",", ":"))


class Database:
    """Persistência operacional e snapshots projetados para API/SSE."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self._lock, self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS personas (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    company_id TEXT NOT NULL,
                    company_name TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    persona_id TEXT NOT NULL REFERENCES personas(id),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL UNIQUE,
                    session_id TEXT REFERENCES sessions(id),
                    persona_id TEXT NOT NULL REFERENCES personas(id),
                    user_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    case_id TEXT,
                    message TEXT NOT NULL,
                    additional_context TEXT,
                    investigation_key TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    parent_run_id TEXT,
                    input_hash TEXT,
                    pipeline_signature TEXT,
                    seed TEXT NOT NULL,
                    gate_enabled INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    modality TEXT,
                    decision TEXT,
                    current_stage TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    thread_id TEXT NOT NULL,
                    node TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_checkpoints_run ON checkpoints(run_id, id);
                CREATE TABLE IF NOT EXISTS results (
                    run_id TEXT PRIMARY KEY REFERENCES runs(id),
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            existing_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(runs)")
            }
            migrations = {
                "additional_context": "TEXT",
                "investigation_key": "TEXT",
                "revision": "INTEGER NOT NULL DEFAULT 1",
                "parent_run_id": "TEXT",
                "input_hash": "TEXT",
                "pipeline_signature": "TEXT",
            }
            for column, declaration in migrations.items():
                if column not in existing_columns:
                    connection.execute(f"ALTER TABLE runs ADD COLUMN {column} {declaration}")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_investigation "
                "ON runs(investigation_key, revision DESC)"
            )
            connection.executemany(
                """
                INSERT INTO personas(id,user_id,name,role,company_id,company_name)
                VALUES(:id,:user_id,:name,:role,:company_id,:company_name)
                ON CONFLICT(id) DO UPDATE SET
                    user_id=excluded.user_id,name=excluded.name,role=excluded.role,
                    company_id=excluded.company_id,company_name=excluded.company_name
                """,
                [persona.model_dump() for persona in PERSONAS],
            )

    def list_personas(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM personas ORDER BY name")]

    def get_persona(self, persona_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM personas WHERE id=?", (persona_id,)).fetchone()
            return dict(row) if row else None

    def create_session(self, persona_id: str) -> Session:
        session = Session(id=f"ses_{uuid4().hex[:12]}", persona_id=persona_id)
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO sessions(id,persona_id,created_at) VALUES(?,?,?)",
                (session.id, session.persona_id, session.created_at.isoformat()),
            )
        return session

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            return dict(row) if row else None

    def create_run(
        self,
        request: RunCreate,
        *,
        user_id: str,
        seed: str,
        pipeline_signature: str,
        reuse_ttl_seconds: int,
    ) -> dict[str, Any]:
        run_id = f"run_{uuid4().hex[:12]}"
        thread_id = f"thread_{uuid4().hex}"
        timestamp = _now()
        investigation_key = request.investigation_key or request.case_id
        if not investigation_key:
            raw_key = f"{user_id}|{request.asset_id}|{' '.join(request.message.lower().split())}"
            investigation_key = f"inv_{sha256(raw_key.encode('utf-8')).hexdigest()[:24]}"
        input_payload = {
            "user_id": user_id,
            "asset_id": request.asset_id,
            "case_id": request.case_id,
            "message": request.message.strip(),
            "additional_context": (request.additional_context or "").strip(),
            "seed": seed,
            "gate_enabled": request.gate_enabled,
        }
        input_hash = sha256(dumps(input_payload).encode("utf-8")).hexdigest()
        with self._lock, self.connect() as connection:
            previous = connection.execute(
                "SELECT * FROM runs WHERE investigation_key=? ORDER BY revision DESC LIMIT 1",
                (investigation_key,),
            ).fetchone()
            if previous and previous["input_hash"] == input_hash and previous["pipeline_signature"] == pipeline_signature:
                age = datetime.now(UTC) - datetime.fromisoformat(previous["updated_at"])
                reusable = previous["status"] in {
                    RunStatus.QUEUED.value,
                    RunStatus.RUNNING.value,
                } or (
                    previous["status"] == RunStatus.COMPLETED.value
                    and age.total_seconds() <= reuse_ttl_seconds
                )
                if reusable:
                    value = self._run_row(previous)
                    value["reused"] = True
                    return value
            revision = int(previous["revision"] or 1) + 1 if previous else 1
            parent_run_id = previous["id"] if previous else None
            connection.execute(
                """
                INSERT INTO runs(
                    id,thread_id,session_id,persona_id,user_id,asset_id,case_id,message,
                    additional_context,investigation_key,revision,parent_run_id,input_hash,
                    pipeline_signature,seed,gate_enabled,status,current_stage,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    thread_id,
                    request.session_id,
                    request.persona_id,
                    user_id,
                    request.asset_id,
                    request.case_id,
                    request.message,
                    request.additional_context,
                    investigation_key,
                    revision,
                    parent_run_id,
                    input_hash,
                    pipeline_signature,
                    seed,
                    int(request.gate_enabled),
                    RunStatus.QUEUED.value,
                    "queued",
                    timestamp,
                    timestamp,
                ),
            )
        value = self.get_run(run_id)  # type: ignore[assignment]
        if value:
            value["reused"] = False
        return value  # type: ignore[return-value]

    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        current_stage: str | None = None,
        modality: str | None = None,
        decision: str | None = None,
        error: str | None = None,
    ) -> None:
        values = {
            "status": status,
            "current_stage": current_stage,
            "modality": modality,
            "decision": decision,
            "error": error,
            "updated_at": _now(),
        }
        fields = [f"{key}=?" for key, value in values.items() if value is not None]
        params = [value for value in values.values() if value is not None]
        if not fields:
            return
        with self._lock, self.connect() as connection:
            connection.execute(
                f"UPDATE runs SET {', '.join(fields)} WHERE id=?",
                [*params, run_id],
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            return self._run_row(row) if row else None

    def list_runs(
        self,
        *,
        session_id: str | None = None,
        persona_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id=?")
            params.append(session_id)
        if persona_id:
            clauses.append("persona_id=?")
            params.append(persona_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM runs{where} ORDER BY created_at DESC LIMIT ?",
                params,
            )
            return [self._run_row(row) for row in rows]

    @staticmethod
    def _run_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["gate_enabled"] = bool(value["gate_enabled"])
        value.setdefault("reused", False)
        return value

    def save_checkpoint(self, run_id: str, node: str, state: dict[str, Any]) -> int:
        timestamp = _now()
        with self._lock, self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO checkpoints(run_id,thread_id,node,state_json,created_at) VALUES(?,?,?,?,?)",
                (run_id, state["thread_id"], node, dumps(state), timestamp),
            )
            return int(cursor.lastrowid)

    def list_checkpoints(
        self, run_id: str, *, after_id: int = 0, include_state: bool = True
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM checkpoints WHERE run_id=? AND id>? ORDER BY id",
                (run_id, after_id),
            )
            output = []
            for row in rows:
                value = dict(row)
                if include_state:
                    value["state"] = json.loads(value.pop("state_json"))
                else:
                    value.pop("state_json")
                output.append(value)
            return output

    def save_result(self, result: RunResult) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO results(run_id,result_json,created_at) VALUES(?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET result_json=excluded.result_json,created_at=excluded.created_at
                """,
                (result.run_id, result.model_dump_json(), _now()),
            )

    def get_result(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM results WHERE run_id=?", (run_id,)
            ).fetchone()
            return json.loads(row["result_json"]) if row else None
