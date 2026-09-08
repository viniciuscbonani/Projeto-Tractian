from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Annotated, Any, TypedDict
from uuid import uuid4

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from tractian_agent.agents.llm import LLMExecutionError
from tractian_agent.agents.multiagent import (
    classify_with_llm,
    deterministic_review,
    fallback_report,
    plan_sources_with_llm,
    review_with_llm,
    select_sources_with_llm,
    synthesize_with_llm,
    validate_written_response,
    write_with_llm,
    written_response_is_safe,
    written_response_requires_safe_fallback,
)
from tractian_agent.agents.specialists import (
    collect_source_plan,
    fetch_selected_sources,
)
from tractian_agent.agents.writer import write_response
from tractian_agent.config import Settings
from tractian_agent.domain.models import (
    ActionRecommendation,
    AgentEvent,
    AgentState,
    ConflictRecord,
    Decision,
    DecisionRecord,
    EscalationPackage,
    Evidence,
    GateResult,
    InvestigationPlan,
    InvestigationReport,
    Modality,
    QueryEnvelope,
    RunMetrics,
    RunResult,
    RunStatus,
    RuntimeVerdict,
    SourceAttempt,
    SourceCandidate,
    ToolEvent,
)
from tractian_agent.domain.policies import sufficiency_gate
from tractian_agent.integrations.tractian import IndustrialClient, InstrumentedTools


def _comparable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def merge_sequence(current: list[Any] | None, update: list[Any] | None) -> list[Any]:
    """Accept both deltas and full snapshots without duplicating append-only state."""
    left = list(current or [])
    right = list(update or [])
    if not right:
        return left
    if len(right) >= len(left) and all(
        _comparable(existing) == _comparable(incoming)
        for existing, incoming in zip(left, right, strict=False)
    ):
        return right
    return [*left, *right]


def merge_mapping(
    current: dict[str, Any] | None, update: dict[str, Any] | None
) -> dict[str, Any]:
    return {**(current or {}), **(update or {})}


def merge_recommendations(
    current: list[Any] | None, update: list[Any] | None
) -> list[Any]:
    """Mantém a recomendação mais recente para cada ação e alvo."""
    merged = merge_sequence(current, update)
    unique: dict[tuple[str, str | None], Any] = {}
    for item in merged:
        value = _comparable(item)
        key = (str(value.get("kind", "")), value.get("target_id"))
        unique[key] = item
    return list(unique.values())


_SEQUENCE_STATE_FIELDS = {
    "reused_stages",
    "tool_events",
    "evidence",
    "gaps",
    "conflicts",
    "decisions",
    "agent_events",
    "gates",
    "review_history",
    "source_history",
}
_MAPPING_STATE_FIELDS = {"envelopes"}


def merge_workflow_state(
    current: dict[str, Any], update: dict[str, Any]
) -> dict[str, Any]:
    """Aplica ao snapshot de auditoria os mesmos reducers declarados no grafo."""
    merged = dict(current)
    for key, value in update.items():
        if key in _SEQUENCE_STATE_FIELDS:
            merged[key] = merge_sequence(merged.get(key), value)
        elif key in _MAPPING_STATE_FIELDS:
            merged[key] = merge_mapping(merged.get(key), value)
        else:
            merged[key] = value
    return merged


class WorkflowState(TypedDict, total=False):
    run_id: str
    thread_id: str
    session_id: str | None
    case_id: str | None
    company_id: str | None
    asset_id: str
    user_id: str
    seed: str
    gate_enabled: bool
    ticket: str
    additional_context: str | None
    investigation_key: str | None
    revision: int
    parent_run_id: str | None
    reused_stages: Annotated[list[str], merge_sequence]
    intent: str | None
    modality: str | None
    status: str
    current_stage: str
    user: dict[str, Any]
    asset: dict[str, Any]
    tool_events: Annotated[list[Any], merge_sequence]
    envelopes: Annotated[dict[str, Any], merge_mapping]
    evidence: Annotated[list[Any], merge_sequence]
    gaps: Annotated[list[str], merge_sequence]
    conflicts: Annotated[list[Any], merge_sequence]
    active_event_ids: list[str]
    active_envelopes: dict[str, Any]
    active_evidence_ids: list[str]
    active_gaps: list[str]
    active_conflicts: list[Any]
    factual_context: list[Any]
    hypotheses: list[str]
    required_evidence: dict[str, list[str]]
    source_plan: Any
    source_candidates: list[Any]
    source_selection: Any
    source_history: Annotated[list[Any], merge_sequence]
    plan_adjustments: list[str]
    decisions: Annotated[list[Any], merge_sequence]
    agent_events: Annotated[list[Any], merge_sequence]
    gates: Annotated[list[Any], merge_sequence]
    review_history: Annotated[list[Any], merge_sequence]
    recommendations: list[Any]
    investigation: Any
    draft: Any
    runtime_verdict: Any
    rewrite_count: int
    reinvestigation_count: int
    review_revision_count: int
    review_feedback: Any
    rejected_report: Any
    final_response_valid: bool
    final_decision: str | None
    escalation: Any
    error: str | None


ClientFactory = Callable[[str, str], IndustrialClient]
CheckpointCallback = Callable[[str, dict[str, Any]], Any]

CHECKPOINT_TYPES = [
    ("tractian_agent.domain.models", name)
    for name in (
        "ActionRecommendation",
        "AgentEvent",
        "ConflictRecord",
        "DecisionRecord",
        "DraftResponse",
        "EnvelopeMode",
        "EscalationPackage",
        "Evidence",
        "EvidenceFact",
        "GateResult",
        "InvestigationDossier",
        "InvestigationReport",
        "InvestigationHypothesis",
        "InvestigationPlan",
        "JudgeAssessment",
        "NewInvestigationPlan",
        "QueryEnvelope",
        "RuntimeVerdict",
        "ReviewObjection",
        "SelectedSource",
        "SourceCandidate",
        "SourceAttempt",
        "SourceSelection",
        "ToolError",
        "ToolEvent",
    )
]


class AgentWorkflow:
    def __init__(
        self,
        settings: Settings,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.settings = settings
        self.client_factory = client_factory or (
            lambda user_id, seed: IndustrialClient(
                settings.industrial_api_url,
                user_id=user_id,
                seed=seed,
                timeout=settings.industrial_api_timeout_seconds,
            )
        )
        builder = StateGraph(WorkflowState)
        builder.add_node("context", self._context)
        builder.add_node("classifier", self._classifier)
        builder.add_node("source_plan", self._source_plan)
        builder.add_node("source_collect", self._source_collect)
        builder.add_node("source_select", self._source_select)
        builder.add_node("investigator", self._investigator)
        builder.add_node("sufficiency_gate", self._sufficiency)
        builder.add_node("reviewer", self._reviewer)
        builder.add_node("writer", self._writer)
        builder.add_node("finalize", self._finalize)
        builder.add_edge(START, "context")
        builder.add_edge("context", "classifier")
        builder.add_edge("classifier", "source_plan")
        builder.add_edge("source_plan", "source_collect")
        builder.add_edge("source_collect", "source_select")
        builder.add_edge("source_select", "investigator")
        builder.add_edge("investigator", "sufficiency_gate")
        builder.add_edge("sufficiency_gate", "reviewer")
        builder.add_conditional_edges(
            "reviewer",
            self._route_runtime,
            {
                "classifier": "classifier",
                "source_plan": "source_plan",
                "investigator": "investigator",
                "writer": "writer",
                "finalize": "finalize",
            },
        )
        builder.add_edge("writer", "finalize")
        builder.add_edge("finalize", END)
        self._builder = builder

    @asynccontextmanager
    async def _compiled_graph(self) -> AsyncIterator[Any]:
        path = self.settings.graph_checkpoint_path
        path.parent.mkdir(parents=True, exist_ok=True)
        serializer = JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)
        async with AsyncSqliteSaver.from_conn_string(str(path)) as checkpointer:
            checkpointer.serde = serializer
            await checkpointer.setup()
            yield self._builder.compile(checkpointer=checkpointer)

    async def _context(self, state: WorkflowState) -> dict[str, Any]:
        client = self.client_factory(state["user_id"], state["seed"])
        tools = InstrumentedTools(client)
        events = [ToolEvent.model_validate(item) for item in state.get("tool_events", [])]
        evidence = [Evidence.model_validate(item) for item in state.get("evidence", [])]
        gaps = list(state.get("gaps", []))
        envelopes = {
            key: QueryEnvelope.model_validate(value)
            for key, value in state.get("envelopes", {}).items()
        }
        try:
            user_event = await tools.read(
                "get_current_user",
                "/users/me",
                {"x-user-id": state["user_id"]},
                client.get_user,
            )
            events.append(user_event)
            user = user_event.result or {}
            if user_event.error:
                gaps.append(f"/users/me: {user_event.error.message}")

            asset_event = await tools.read(
                "get_asset",
                f"/assets/{state['asset_id']}",
                {"asset_id": state["asset_id"]},
                lambda: client.get_asset(state["asset_id"]),
            )
            events.append(asset_event)
            asset = asset_event.envelope.data if asset_event.envelope else {}
            if asset_event.envelope:
                envelopes["asset"] = asset_event.envelope
                if asset_event.envelope.mode.value not in {"inconclusive", "unavailable"}:
                    evidence.append(
                        Evidence(
                            id=f"ev_{uuid4().hex[:10]}",
                            claim="Identidade técnica, criticidade e sensores do ativo foram carregados.",
                            source_event_id=asset_event.id,
                            source_path=asset_event.path,
                            fields=["id", "machine_type", "criticality", "points"],
                            mode=asset_event.envelope.mode,
                            decisive=True,
                        )
                    )
            if asset_event.error:
                gaps.append(f"{asset_event.path}: {asset_event.error.message}")
        finally:
            await client.aclose()
        return {
            "user": user,
            "asset": asset,
            "company_id": user.get("company_id") if user else state.get("company_id"),
            "tool_events": events,
            "envelopes": envelopes,
            "evidence": evidence,
            "gaps": gaps,
            "active_event_ids": [item.id for item in events],
            "active_envelopes": envelopes,
            "active_evidence_ids": [item.id for item in evidence],
            "active_gaps": gaps,
            "active_conflicts": [],
            "status": RunStatus.RUNNING.value,
            "current_stage": "context",
        }

    async def _classifier(self, state: WorkflowState) -> dict[str, Any]:
        events = [AgentEvent.model_validate(item) for item in state.get("agent_events", [])]
        review_feedback = state.get("review_feedback")
        should_revise = bool(
            review_feedback
            and RuntimeVerdict.model_validate(review_feedback).verdict == "revise_classification"
        )
        if (
            not should_revise
            and "classifier" in state.get("reused_stages", [])
            and state.get("modality")
            and state.get("intent")
        ):
            modality = Modality(state["modality"])
            intent = str(state["intent"])
            reason = "Classificação reaproveitada da revisão anterior desta investigação."
            events.append(
                AgentEvent(
                    role="classifier",
                    model=self.settings.classifier_model or "offline",
                    status="reused",
                    summary=reason,
                )
            )
        else:
            context_parts = [state.get("additional_context") or ""]
            if should_revise:
                feedback = RuntimeVerdict.model_validate(review_feedback)
                context_parts.append(
                    "O juiz solicitou nova classificação. "
                    f"Intenção sugerida: {feedback.suggested_intent or 'não informada'}. "
                    f"Motivos: {'; '.join(feedback.reasons)}"
                )
            modality, intent, reason, event = await classify_with_llm(
                self.settings,
                state["ticket"],
                "\n".join(value for value in context_parts if value),
            )
            if event.error:
                raise LLMExecutionError(event)
            events.append(event)
        decisions = [DecisionRecord.model_validate(item) for item in state.get("decisions", [])]
        decisions.append(
            DecisionRecord(
                stage="classifier",
                decision=modality.value,
                reason=f"{reason} Intent: {intent}.",
            )
        )
        return {
            "modality": modality.value,
            "intent": intent,
            "decisions": decisions,
            "agent_events": events,
            "current_stage": "classifier",
        }

    async def _source_plan(self, state: WorkflowState) -> dict[str, Any]:
        plan, event = await plan_sources_with_llm(self.settings, dict(state))
        if event.error:
            raise LLMExecutionError(event)
        return {
            "source_plan": plan,
            "source_candidates": [],
            "source_selection": None,
            "required_evidence": {},
            "plan_adjustments": [],
            "investigation": None,
            "hypotheses": [],
            "recommendations": [],
            "draft": None,
            "final_response_valid": False,
            "agent_events": [event],
            "current_stage": "source_plan",
        }

    async def _source_collect(self, state: WorkflowState) -> dict[str, Any]:
        plan = InvestigationPlan.model_validate(state["source_plan"])
        client = self.client_factory(state["user_id"], state["seed"])
        try:
            update = await collect_source_plan(
                dict(state), client, self.settings, plan
            )
        finally:
            await client.aclose()
        return update

    async def _source_select(self, state: WorkflowState) -> dict[str, Any]:
        plan = InvestigationPlan.model_validate(state["source_plan"])
        candidates = [
            SourceCandidate.model_validate(item) for item in state.get("source_candidates", [])
        ]
        selection, event = await select_sources_with_llm(
            self.settings, dict(state), candidates
        )
        if event and event.error:
            raise LLMExecutionError(event)
        client = self.client_factory(state["user_id"], state["seed"])
        try:
            update = await fetch_selected_sources(
                {**dict(state), "source_selection": selection},
                client,
                plan,
                selection,
            )
        finally:
            await client.aclose()
        result: dict[str, Any] = {**update, "source_selection": selection}
        result["source_history"] = [
            SourceAttempt(
                revision=int(state.get("review_revision_count", 0)) + 1,
                tools=list(plan.tools),
                queries=list(plan.knowledge_queries),
                result_counts={"candidates": len(candidates)},
                selected_ids=[item.id for item in selection.selected_sources],
                failures=list(update.get("active_gaps", [])),
                adjustments=list(state.get("plan_adjustments", [])),
            )
        ]
        if event:
            result["agent_events"] = [event]
        return result

    async def _investigator(self, state: WorkflowState) -> dict[str, Any]:
        report, synthesis_event = await synthesize_with_llm(self.settings, dict(state))
        if synthesis_event.error:
            raise LLMExecutionError(synthesis_event)
        recommendations = [report.recommendation] if report.recommendation else []
        return {
            "investigation": report,
            "hypotheses": [item.statement for item in report.hypotheses],
            "recommendations": recommendations,
            "draft": None,
            "final_response_valid": False,
            "agent_events": [synthesis_event],
            "current_stage": "investigator",
        }

    def _route_runtime(self, state: WorkflowState) -> str:
        verdict = RuntimeVerdict.model_validate(state["runtime_verdict"])
        if verdict.verdict == "revise_classification" and verdict.suggested_intent:
            return "classifier"
        if verdict.verdict == "revise_sources" and verdict.missing_sources:
            return "source_plan"
        if verdict.verdict == "revise_investigation" and verdict.unsupported_claims:
            return "investigator"
        if verdict.verdict == "escalate" or state.get("intent") == "explicit_escalation":
            return "finalize"
        return "writer" if verdict.verdict == "approve" else "finalize"

    async def _sufficiency(self, state: WorkflowState) -> dict[str, Any]:
        envelopes = {
            key: QueryEnvelope.model_validate(value)
            for key, value in (state.get("active_envelopes") or state.get("envelopes", {})).items()
        }
        conflicts = [
            ConflictRecord.model_validate(value)
            for value in state.get("active_conflicts", state.get("conflicts", []))
        ]
        gate = sufficiency_gate(
            envelopes,
            state.get("required_evidence", {}),
            conflicts,
            state.get("gate_enabled", True),
        )
        gates = [GateResult.model_validate(item) for item in state.get("gates", [])] + [gate]
        decisions = [DecisionRecord.model_validate(item) for item in state.get("decisions", [])]
        decisions.append(
            DecisionRecord(
                stage="sufficiency_gate",
                decision="pass" if gate.passed else "block",
                reason="; ".join(gate.reasons + gate.missing),
            )
        )
        return {
            "gates": gates,
            "decisions": decisions,
            "current_stage": "sufficiency_gate",
        }

    async def _reviewer(self, state: WorkflowState) -> dict[str, Any]:
        report = InvestigationReport.model_validate(state["investigation"])
        reviewed_verdict, event = await review_with_llm(self.settings, dict(state), report)
        if event.error:
            raise LLMExecutionError(event)
        verdict = reviewed_verdict
        original_report = report
        used_safe_fallback = False
        if reviewed_verdict.safe_fallback_required:
            conservative = fallback_report(dict(state))
            conservative_check = deterministic_review(dict(state), conservative)
            if conservative_check.verdict == "approve":
                report = conservative
                used_safe_fallback = True
                verdict = reviewed_verdict.model_copy(
                    update={
                        "safe_fallback_required": False,
                        "reasons": [
                            *reviewed_verdict.reasons,
                            "A síntese contestada foi substituída por uma resposta local validada.",
                        ],
                    }
                )
                event = event.model_copy(
                    update={
                        "summary": (
                            f"{event.summary} Objeção contida por resposta local conservadora."
                        )
                    }
                )
            else:
                verdict = RuntimeVerdict(
                    verdict="escalate",
                    intent_aligned=conservative_check.intent_aligned,
                    recommendation_supported=conservative_check.recommendation_supported,
                    suggested_intent=conservative_check.suggested_intent,
                    missing_sources=conservative_check.missing_sources,
                    unsupported_claims=conservative_check.unsupported_claims,
                    safe=conservative_check.safe,
                    grounded=conservative_check.grounded,
                    complete=False,
                    reasons=[
                        *reviewed_verdict.reasons,
                        *conservative_check.reasons,
                        "A contingência local também não produziu resposta segura e útil.",
                    ],
                    judge="deterministic_fallback",
                    advisory_objections=reviewed_verdict.advisory_objections,
                )
        revision_verdicts = {
            "revise_classification",
            "revise_sources",
            "revise_investigation",
        }
        revision_count = state.get("review_revision_count", 0)
        if (
            verdict.verdict in revision_verdicts
            and revision_count >= self.settings.max_review_revisions
        ):
            verdict = RuntimeVerdict(
                verdict="escalate",
                intent_aligned=reviewed_verdict.intent_aligned,
                recommendation_supported=reviewed_verdict.recommendation_supported,
                suggested_intent=reviewed_verdict.suggested_intent,
                missing_sources=reviewed_verdict.missing_sources,
                unsupported_claims=reviewed_verdict.unsupported_claims,
                safe=reviewed_verdict.safe,
                grounded=reviewed_verdict.grounded,
                complete=reviewed_verdict.complete,
                reasons=[
                    *reviewed_verdict.reasons,
                    "Limite de uma correção automática atingido.",
                ],
                judge=reviewed_verdict.judge,
            )
        decisions = [DecisionRecord.model_validate(item) for item in state.get("decisions", [])]
        decisions.append(
            DecisionRecord(
                stage="reviewer",
                decision=verdict.verdict,
                reason="; ".join(verdict.reasons),
                evidence_ids=report.evidence_ids,
            )
        )
        return {
            "runtime_verdict": verdict,
            "review_history": [reviewed_verdict],
            "review_revision_count": (
                revision_count + 1
                if reviewed_verdict.verdict in revision_verdicts
                and verdict.verdict != "escalate"
                else revision_count
            ),
            "review_feedback": (
                reviewed_verdict
                if reviewed_verdict.verdict in revision_verdicts
                and verdict.verdict != "escalate"
                else None
            ),
            "rejected_report": (
                original_report
                if reviewed_verdict.verdict in revision_verdicts
                or used_safe_fallback
                else state.get("rejected_report")
            ),
            "investigation": (
                None
                if reviewed_verdict.verdict in revision_verdicts
                and verdict.verdict != "escalate"
                else report
            ),
            "hypotheses": (
                []
                if reviewed_verdict.verdict in revision_verdicts
                and verdict.verdict != "escalate"
                else [item.statement for item in report.hypotheses]
            ),
            "recommendations": (
                []
                if reviewed_verdict.verdict in revision_verdicts
                and verdict.verdict != "escalate"
                else ([report.recommendation] if report.recommendation else [])
            ),
            "draft": None,
            "agent_events": [event],
            "decisions": decisions,
            "current_stage": "reviewer",
        }

    async def _writer(self, state: WorkflowState) -> dict[str, Any]:
        report = InvestigationReport.model_validate(state["investigation"])
        fallback = write_response(dict(state))
        draft, event = await write_with_llm(self.settings, dict(state), report, fallback)
        # O redator não participa da decisão técnica. Se sua saída for inválida, a
        # renderização local já produz uma resposta segura e auditável; somente uma
        # falha sem fallback deve abortar o caso.
        if event.error and event.status != "fallback":
            raise LLMExecutionError(event)
        replaced_by_policy, _ = written_response_requires_safe_fallback(report, draft)
        draft = validate_written_response(dict(state), report, draft, fallback)
        if replaced_by_policy:
            event = event.model_copy(
                update={
                    "status": "fallback",
                    "summary": (
                        "Redação local usada porque a saída do modelo ampliou ou violou "
                        "o relatório aprovado."
                    ),
                    "failure_stage": "policy",
                    "failure_reason": "writer_claim_drift",
                }
            )
        valid = written_response_is_safe(dict(state), report, draft)
        return {
            "draft": draft if valid else None,
            "final_response_valid": valid,
            "agent_events": [event],
            "current_stage": "writer",
        }

    async def _finalize(self, state: WorkflowState) -> dict[str, Any]:
        verdict = RuntimeVerdict.model_validate(state["runtime_verdict"])
        report = InvestigationReport.model_validate(state["investigation"])
        recommendations = [
            ActionRecommendation.model_validate(item) for item in state.get("recommendations", [])
        ]
        if (
            verdict.verdict != "approve"
            or state.get("intent") == "explicit_escalation"
            or not state.get("final_response_valid", False)
        ):
            decision = Decision.ESCALATE
        elif recommendations:
            decision = Decision.RECOMMEND
        else:
            decision = Decision.ORIENT
        escalation = None
        if decision == Decision.ESCALATE:
            review_reasons = list(dict.fromkeys(verdict.reasons))
            open_questions = list(
                dict.fromkeys([*report.unknowns, *state.get("gaps", [])])
            )
            explicit = state.get("intent") == "explicit_escalation"
            reason = (
                "O cliente solicitou explicitamente atendimento humano."
                if explicit
                else "; ".join(verdict.reasons)
                if verdict.verdict != "approve"
                else "A validação final não conseguiu produzir uma resposta pública segura."
            )
            preliminary_findings = [
                item.model_copy(
                    update={
                        "statement": (
                            f"Achado preliminar: {item.statement}"
                            if explicit
                            else f"Achado preliminar/contestado: {item.statement}"
                        ),
                        "status": "open",
                    }
                )
                for item in report.hypotheses
            ]
            escalation = EscalationPackage(
                reason=reason,
                ticket=state["ticket"],
                user_id=state["user_id"],
                asset_id=state["asset_id"],
                summary=(
                    (
                        f"O cliente solicitou encaminhamento à engenharia: {state['ticket']} "
                        "Nenhuma resposta automática foi enviada. O engenheiro responsável "
                        "deve revisar as evidências e conduzir a avaliação humana."
                    )
                    if explicit
                    else (
                        f"O cliente perguntou: {state['ticket']} A análise automática não foi "
                        "liberada porque a revisão encontrou evidência insuficiente ou "
                        "inconsistente. Revise os achados preliminares e formule a resposta "
                        "ao cliente."
                    )
                ),
                review_reasons=review_reasons,
                findings=preliminary_findings,
                open_questions=open_questions,
                recommendations=recommendations,
                evidence=[
                    Evidence.model_validate(item)
                    for item in state.get("evidence", [])
                    if not state.get("active_evidence_ids")
                    or Evidence.model_validate(item).id in state.get("active_evidence_ids", [])
                ],
                gaps=state.get("active_gaps", state.get("gaps", [])),
                conflicts=state.get("active_conflicts", state.get("conflicts", [])),
                executed=False,
            )
        decisions = [DecisionRecord.model_validate(item) for item in state.get("decisions", [])]
        decisions.append(
            DecisionRecord(
                stage="finalize",
                decision=decision.value,
                reason=(
                    "Resposta ao cliente bloqueada; pacote preparado para o engenheiro."
                    if decision == Decision.ESCALATE
                    else "Relatório revisado antes da redação; nenhuma ação foi executada."
                ),
            )
        )
        return {
            "final_decision": decision.value,
            "escalation": escalation,
            "draft": None if decision == Decision.ESCALATE else state.get("draft"),
            "decisions": decisions,
            "status": RunStatus.COMPLETED.value,
            "current_stage": "completed",
        }

    async def run(
        self,
        initial: AgentState,
        checkpoint: CheckpointCallback | None = None,
        *,
        resume: bool = False,
    ) -> tuple[AgentState, RunResult]:
        started = perf_counter()
        config = {"configurable": {"thread_id": initial.thread_id}}
        async with self._compiled_graph() as graph:
            saved = await graph.aget_state(config)
            if resume:
                if not saved.values:
                    raise ValueError(f"Nenhum checkpoint encontrado para {initial.thread_id}.")
                current = dict(saved.values)
                graph_input: dict[str, Any] | None = None
            else:
                if saved.values:
                    await graph.checkpointer.adelete_thread(initial.thread_id)
                current = initial.model_dump(mode="python")
                graph_input = current

            async for update in graph.astream(
                graph_input,
                config=config,
                stream_mode="updates",
                durability="sync",
            ):
                for node, delta in update.items():
                    if isinstance(delta, dict):
                        # `stream_mode=updates` entrega somente o delta do nó. A cópia
                        # de auditoria precisa aplicar os mesmos reducers do estado nativo
                        # para não perder eventos e evidências das etapas anteriores.
                        current = merge_workflow_state(current, delta)
                    if checkpoint:
                        result = checkpoint(node, current)
                        if inspect.isawaitable(result):
                            await result
            persisted = await graph.aget_state(config)
            current = dict(persisted.values)
        final_state = AgentState.model_validate(current)
        events = final_state.tool_events
        metrics = RunMetrics(
            tool_calls=len(events),
            duration_ms=(perf_counter() - started) * 1000,
            degraded_reads=sum(
                1
                for event in events
                if event.envelope and event.envelope.mode.value != "complete"
            ),
            conflicts=len(final_state.conflicts),
            mutations_attempted=sum(1 for event in events if event.method in {"POST", "PATCH"}),
        )
        result = RunResult(
            run_id=final_state.run_id,
            thread_id=final_state.thread_id,
            status=RunStatus.COMPLETED,
            modality=Modality(final_state.modality),
            decision=Decision(final_state.final_decision),
            response=final_state.draft,
            final_response_valid=final_state.final_response_valid,
            evidence=[
                item for item in final_state.evidence
                if not final_state.active_evidence_ids or item.id in final_state.active_evidence_ids
            ],
            factual_context=final_state.factual_context,
            gaps=final_state.active_gaps or final_state.gaps,
            gates=final_state.gates,
            runtime_verdict=final_state.runtime_verdict,
            actions=[],
            recommendations=final_state.recommendations,
            investigation=final_state.investigation,
            source_plan=final_state.source_plan,
            source_candidates=final_state.source_candidates,
            source_selection=final_state.source_selection,
            source_history=final_state.source_history,
            review_history=final_state.review_history,
            decisions=final_state.decisions,
            agent_events=final_state.agent_events,
            escalation=final_state.escalation,
            metrics=metrics,
        )
        return final_state, result

    async def pause_after(
        self,
        initial: AgentState,
        node: str,
        checkpoint: CheckpointCallback | None = None,
    ) -> AgentState:
        """Executa até um nó e deixa o thread pronto para retomada em outro processo."""
        current = initial.model_dump(mode="python")
        config = {"configurable": {"thread_id": initial.thread_id}}
        async with self._compiled_graph() as graph:
            saved = await graph.aget_state(config)
            if saved.values:
                await graph.checkpointer.adelete_thread(initial.thread_id)
            async for update in graph.astream(
                current,
                config=config,
                stream_mode="updates",
                interrupt_after=[node],
                durability="sync",
            ):
                for current_node, delta in update.items():
                    if isinstance(delta, dict):
                        current = merge_workflow_state(current, delta)
                    if checkpoint:
                        result = checkpoint(current_node, current)
                        if inspect.isawaitable(result):
                            await result
            persisted = await graph.aget_state(config)
        return AgentState.model_validate(persisted.values)

    async def checkpoint_history(self, thread_id: str) -> list[dict[str, Any]]:
        """Expõe o histórico nativo para auditoria e testes de retomada."""
        config = {"configurable": {"thread_id": thread_id}}
        history: list[dict[str, Any]] = []
        async with self._compiled_graph() as graph:
            async for snapshot in graph.aget_state_history(config):
                history.append(
                    {
                        "values": dict(snapshot.values),
                        "next": list(snapshot.next),
                        "metadata": dict(snapshot.metadata or {}),
                        "created_at": snapshot.created_at,
                    }
                )
        return history

    async def latest_checkpoint(self, thread_id: str) -> AgentState | None:
        """Recupera o último estado persistido, inclusive depois de falha técnica."""
        config = {"configurable": {"thread_id": thread_id}}
        async with self._compiled_graph() as graph:
            snapshot = await graph.aget_state(config)
        return AgentState.model_validate(snapshot.values) if snapshot.values else None
