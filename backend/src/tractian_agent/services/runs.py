from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from tractian_agent.agents.llm import LLMExecutionError
from tractian_agent.config import Settings
from tractian_agent.domain.models import AgentState, RunCreate, RunStatus
from tractian_agent.graph import AgentWorkflow
from tractian_agent.integrations.tractian import IndustrialClient
from tractian_agent.persistence import Database


class RunService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        workflow: AgentWorkflow | None = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.workflow = workflow or AgentWorkflow(settings)
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def create(self, request: RunCreate) -> dict[str, Any]:
        persona = self.database.get_persona(request.persona_id)
        if not persona:
            raise ValueError("Persona não encontrada.")
        if request.session_id:
            session = self.database.get_session(request.session_id)
            if not session or session["persona_id"] != request.persona_id:
                raise ValueError("Sessão não pertence à persona informada.")
        seed = request.seed or self.settings.default_seed
        return self.database.create_run(
            request,
            user_id=persona["user_id"],
            seed=seed,
            pipeline_signature=self.settings.pipeline_signature,
            reuse_ttl_seconds=self.settings.result_reuse_ttl_seconds,
        )

    def start(self, run_id: str) -> None:
        task = asyncio.create_task(self.execute(run_id), name=f"agent:{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))

    async def execute(self, run_id: str) -> None:
        run = self.database.get_run(run_id)
        if not run:
            raise ValueError("Execução não encontrada.")
        parent = self.database.get_run(run["parent_run_id"]) if run.get("parent_run_id") else None
        can_reuse_classifier = bool(
            parent
            and parent.get("message") == run.get("message")
            and (parent.get("additional_context") or "") == (run.get("additional_context") or "")
            and parent.get("user_id") == run.get("user_id")
            and parent.get("asset_id") == run.get("asset_id")
            and parent.get("pipeline_signature") == run.get("pipeline_signature")
            and parent.get("modality")
        )
        initial = AgentState(
            run_id=run["id"],
            thread_id=run["thread_id"],
            session_id=run["session_id"],
            case_id=run["case_id"],
            asset_id=run["asset_id"],
            user_id=run["user_id"],
            seed=run["seed"],
            gate_enabled=run["gate_enabled"],
            ticket=run["message"],
            additional_context=run.get("additional_context"),
            investigation_key=run.get("investigation_key"),
            revision=int(run.get("revision") or 1),
            parent_run_id=run.get("parent_run_id"),
            reused_stages=["classifier"] if can_reuse_classifier else [],
            modality=parent.get("modality") if can_reuse_classifier and parent else None,
            intent=(
                self._classifier_intent(parent["id"])
                if can_reuse_classifier and parent
                else None
            ),
        )
        self.database.update_run(run_id, status=RunStatus.RUNNING.value, current_stage="starting")

        def checkpoint(node: str, state: dict[str, Any]) -> None:
            if node in {
                "classifier",
                "source_plan",
                "source_collect",
                "source_select",
                "investigator",
                "sufficiency_gate",
                "reviewer",
                "writer",
                "finalize",
            }:
                self.database.save_checkpoint(run_id, node, state)
            self.database.update_run(
                run_id,
                status=str(state.get("status", RunStatus.RUNNING.value)),
                current_stage=str(state.get("current_stage", node)),
                modality=str(state["modality"]) if state.get("modality") else None,
                decision=str(state["final_decision"]) if state.get("final_decision") else None,
            )

        try:
            native_history = await self.workflow.checkpoint_history(initial.thread_id)
            _, result = await self.workflow.run(
                initial,
                checkpoint,
                resume=bool(native_history),
            )
            self.database.save_result(result)
            self.database.update_run(
                run_id,
                status=RunStatus.COMPLETED.value,
                current_stage="completed",
                modality=result.modality.value,
                decision=result.decision.value,
            )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self.database.update_run(
                run_id,
                status=RunStatus.FAILED.value,
                current_stage="failed",
                error=message,
            )
            persisted = self.database.list_checkpoints(run_id)
            failed_state = (
                dict(persisted[-1]["state"])
                if persisted
                else initial.model_dump(mode="json")
            )
            if isinstance(exc, LLMExecutionError):
                agent_events = list(failed_state.get("agent_events", []))
                agent_events.append(exc.event.model_dump(mode="json"))
                failed_state["agent_events"] = agent_events
            failed_state.update(
                {"status": "failed", "current_stage": "failed", "error": message}
            )
            self.database.save_checkpoint(run_id, "failed", failed_state)
            raise

    def _classifier_intent(self, run_id: str) -> str | None:
        for checkpoint in reversed(self.database.list_checkpoints(run_id)):
            state = checkpoint.get("state", {})
            if state.get("intent"):
                return str(state["intent"])
        return None

    async def list_assets(self, persona_id: str) -> list[dict[str, Any]]:
        persona = self.database.get_persona(persona_id)
        if not persona:
            raise ValueError("Persona não encontrada.")
        async with IndustrialClient(
            self.settings.industrial_api_url,
            user_id=persona["user_id"],
            seed=self.settings.default_seed,
            timeout=self.settings.industrial_api_timeout_seconds,
        ) as client:
            envelope = await client.list_assets(persona["company_id"])
        data = envelope.data if isinstance(envelope.data, dict) else {}
        return data.get("assets", [])

    def demo_cases(self) -> list[dict[str, Any]]:
        repository_root = Path(__file__).resolve().parents[4]
        path = self.settings.demo_cases_path or (
            repository_root / "api-tractian" / "agent-input" / "cases.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))
