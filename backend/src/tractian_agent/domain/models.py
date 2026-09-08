from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

CanonicalIntent: TypeAlias = Literal[  # noqa: UP040 - mantém enum inline no JSON Schema
    "bearing_procedure",
    "bpfo_definition",
    "break_without_alert",
    "divergent_diagnoses",
    "electrical_or_mechanical",
    "explicit_escalation",
    "model_coverage",
    "open_investigation",
    "poor_signal_quality",
    "possible_false_positive",
    "reprocess",
    "request_retraining",
    "request_specialist",
    "rms_threshold",
    "rms_without_insight",
    "stale_after_maintenance",
    "symptom_without_baseline",
    "update_criticality",
]

SourceTool: TypeAlias = Literal[  # noqa: UP040 - mantém enum inline no JSON Schema
    "analyses",
    "analysis_details",
    "baseline",
    "rms",
    "spectrum",
    "data_quality",
    "model",
    "knowledge",
]

AnalysisStatus: TypeAlias = Literal[  # noqa: UP040 - mantém enum inline no JSON Schema
    "current", "stale", "pending", "inconclusive"
]

ConflictImpact: TypeAlias = Literal[  # noqa: UP040 - mantém enum inline no JSON Schema
    "informational", "blocks_claim", "blocks_action"
]


def utc_now() -> datetime:
    return datetime.now(UTC)


class EnvelopeMode(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INCONCLUSIVE = "inconclusive"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"


class Modality(StrEnum):
    CONTEXTUALIZE = "contextualizar"
    INVESTIGATE = "investigar"
    RECOMMEND = "recomendar"


class Decision(StrEnum):
    ORIENT = "orientar"
    RECOMMEND = "recomendar"
    ACT = "agir"
    ESCALATE = "escalar"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class QueryEnvelope(BaseModel):
    mode: EnvelopeMode
    data: Any = None
    notes: str | None = None


class ToolError(BaseModel):
    kind: Literal["http", "transport", "validation"]
    status_code: int | None = None
    code: str | None = None
    message: str
    retryable: bool = False


class ToolEvent(BaseModel):
    id: str
    name: str
    method: str
    path: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    envelope: QueryEnvelope | None = None
    result: Any = None
    error: ToolError | None = None
    latency_ms: float
    started_at: datetime = Field(default_factory=utc_now)


class Evidence(BaseModel):
    id: str
    claim: str
    source_event_id: str
    source_path: str
    fields: list[str] = Field(default_factory=list)
    mode: EnvelopeMode
    decisive: bool = False


class EvidenceFact(BaseModel):
    """Valor primário auditável projetado de um evento GET ativo."""

    evidence_id: str
    source_event_id: str
    source_path: str
    field: str
    value: Any
    mode: EnvelopeMode
    observation: str | None = None
    observed_at: datetime
    source_timestamp: str | None = None
    source_version: str | None = None


class ConflictRecord(BaseModel):
    topic: str
    sources: list[str]
    resolution: str | None = None
    resolved: bool = False
    rule: str
    impact: ConflictImpact = "blocks_action"


class DecisionRecord(BaseModel):
    stage: str
    decision: str
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class AgentEvent(BaseModel):
    """Registro observável de um agente, sem cadeia de pensamento privada."""

    role: Literal["classifier", "source_selector", "investigator", "judge", "writer"]
    model: str
    status: Literal["completed", "fallback", "failed", "reused"]
    latency_ms: float = 0
    summary: str
    error: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    attempts: int = 0
    token_usage_complete: bool | None = None
    failure_stage: Literal["configuration", "provider", "json", "schema", "policy"] | None = None
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class GateResult(BaseModel):
    gate: Literal["sufficiency"]
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=utc_now)
    enabled: bool = True


class ActionRecommendation(BaseModel):
    """Ação sugerida para decisão humana; nunca é executada pelo agente."""

    kind: Literal[
        "reprocess_analysis",
        "request_specialist",
        "update_asset",
        "request_retraining",
        "escalate_case",
        "collect_more_data",
        "inspect_asset",
    ]
    target_id: str | None = None
    justification: str
    params: dict[str, Any] = Field(default_factory=dict)
    priority: Literal["low", "medium", "high"] = "medium"
    requires_human_approval: bool = True


class InvestigationHypothesis(BaseModel):
    statement: str
    status: Literal["supported", "weakened", "open"]
    evidence_ids: list[str] = Field(default_factory=list)


class InvestigationReport(BaseModel):
    conclusion: str
    evidence_ids: list[str] = Field(default_factory=list)
    hypotheses: list[InvestigationHypothesis] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    needs_human: bool = Field(
        default=False,
        description=(
            "True somente quando não existe resposta segura ao cliente e um engenheiro precisa "
            "formular a resposta. Não representa a aprovação humana de uma ação recomendada."
        ),
    )
    recommendation: ActionRecommendation | None = Field(
        default=None,
        description=(
            "Ação operacional formal recomendada, ou null quando o caso exige apenas uma "
            "explicação/orientação ao cliente."
        ),
    )


# Compatibilidade de desserialização para checkpoints criados antes da troca de nome.
# O contrato e o código novo usam InvestigationReport.
InvestigationDossier = InvestigationReport


class InvestigationPlan(BaseModel):
    tools: list[SourceTool] = Field(default_factory=list, max_length=8)
    required_tools: list[SourceTool] = Field(default_factory=list, max_length=8)
    knowledge_queries: list[str] = Field(default_factory=list, max_length=3)
    # Campo legado aceito na leitura de checkpoints v5/v6.
    knowledge_query: str | None = None
    analysis_status: str | None = None
    focus: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_legacy_query(self) -> InvestigationPlan:
        if self.knowledge_query and not self.knowledge_queries:
            self.knowledge_queries = [self.knowledge_query]
        return self


class NewInvestigationPlan(InvestigationPlan):
    """Contrato estrito para planos novos; o pai ainda lê checkpoints v5/v6/v7."""

    analysis_status: AnalysisStatus | None = None


class SourceAttempt(BaseModel):
    revision: int
    tools: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    result_counts: dict[str, int] = Field(default_factory=dict)
    selected_ids: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    adjustments: list[str] = Field(default_factory=list)


class SourceCandidate(BaseModel):
    id: str
    title: str
    type: str | None = None
    tags: list[str] = Field(default_factory=list)
    snippet: str = ""


class SelectedSource(BaseModel):
    id: str
    reason: str


class SourceSelection(BaseModel):
    selected_sources: list[SelectedSource] = Field(default_factory=list, max_length=8)
    missing_information: list[str] = Field(default_factory=list)


class DraftResponse(BaseModel):
    summary: str
    explanation: list[str]
    next_steps: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ReviewObjection(BaseModel):
    """Objeção semântica do juiz; não é uma instrução de roteamento do grafo."""

    kind: Literal[
        "intent_mismatch",
        "missing_source",
        "unsupported_claim",
        "unsafe_recommendation",
        "decisive_conflict",
        "human_required",
    ]
    detail: str
    claim: str | None = None
    source: SourceTool | None = None
    suggested_intent: CanonicalIntent | None = None


class JudgeAssessment(BaseModel):
    """Parecer consultivo. Somente a política determinística compila a decisão final."""

    objections: list[ReviewObjection] = Field(default_factory=list, max_length=6)
    summary: str


class RuntimeVerdict(BaseModel):
    verdict: Literal[
        "approve",
        "revise_classification",
        "revise_sources",
        "revise_investigation",
        "escalate",
    ]
    intent_aligned: bool = True
    recommendation_supported: bool = True
    suggested_intent: CanonicalIntent | None = None
    missing_sources: list[SourceTool] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    safe: bool
    grounded: bool
    complete: bool
    reasons: list[str] = Field(default_factory=list)
    judge: Literal["deterministic", "llm", "deterministic_fallback"] = "deterministic"
    advisory_objections: list[ReviewObjection] = Field(default_factory=list)
    safe_fallback_required: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_verdict(cls, value: Any) -> Any:
        if isinstance(value, dict):
            normalized = dict(value)
            legacy = normalized.get("verdict")
            if legacy == "rewrite":
                normalized["verdict"] = "revise_investigation"
            elif legacy == "investigate_more":
                normalized["verdict"] = "revise_sources"
            return normalized
        return value

    @model_validator(mode="after")
    def validate_approval(self) -> RuntimeVerdict:
        if self.verdict == "approve" and (
            not self.safe
            or not self.grounded
            or not self.complete
            or not self.intent_aligned
            or not self.recommendation_supported
            or self.missing_sources
            or self.unsupported_claims
        ):
            # Saídas estruturadas inconsistentes não devem derrubar a execução nem liberar
            # a resposta. Normalize-as para a correção mais específica possível.
            if self.missing_sources:
                self.verdict = "revise_sources"
            else:
                self.verdict = "revise_investigation"
            self.reasons = [
                *self.reasons,
                "Approve rejeitado pela política: o parecer não satisfez todos os critérios.",
            ]
        return self


class EscalationPackage(BaseModel):
    reason: str
    ticket: str
    user_id: str
    asset_id: str
    recipient: Literal["maintenance_engineer"] = "maintenance_engineer"
    customer_response_allowed: bool = False
    summary: str
    review_reasons: list[str] = Field(default_factory=list)
    findings: list[InvestigationHypothesis] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    recommendations: list[ActionRecommendation] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    conflicts: list[ConflictRecord] = Field(default_factory=list)
    executed: bool = False


class AgentState(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    run_id: str
    thread_id: str
    session_id: str | None = None
    case_id: str | None = None
    company_id: str | None = None
    asset_id: str
    user_id: str
    seed: str
    gate_enabled: bool = True
    ticket: str
    additional_context: str | None = None
    investigation_key: str | None = None
    revision: int = 1
    parent_run_id: str | None = None
    reused_stages: list[str] = Field(default_factory=list)
    intent: str | None = None
    modality: Modality | None = None
    status: RunStatus = RunStatus.QUEUED
    current_stage: str = "queued"
    user: dict[str, Any] = Field(default_factory=dict)
    asset: dict[str, Any] = Field(default_factory=dict)
    tool_events: list[ToolEvent] = Field(default_factory=list)
    envelopes: dict[str, QueryEnvelope] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    conflicts: list[ConflictRecord] = Field(default_factory=list)
    active_event_ids: list[str] = Field(default_factory=list)
    active_envelopes: dict[str, QueryEnvelope] = Field(default_factory=dict)
    active_evidence_ids: list[str] = Field(default_factory=list)
    active_gaps: list[str] = Field(default_factory=list)
    active_conflicts: list[ConflictRecord] = Field(default_factory=list)
    factual_context: list[EvidenceFact] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    required_evidence: dict[str, list[str]] = Field(default_factory=dict)
    source_plan: InvestigationPlan | None = None
    source_candidates: list[SourceCandidate] = Field(default_factory=list)
    source_selection: SourceSelection | None = None
    source_history: list[SourceAttempt] = Field(default_factory=list)
    plan_adjustments: list[str] = Field(default_factory=list)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    agent_events: list[AgentEvent] = Field(default_factory=list)
    gates: list[GateResult] = Field(default_factory=list)
    review_history: list[RuntimeVerdict] = Field(default_factory=list)
    recommendations: list[ActionRecommendation] = Field(default_factory=list)
    investigation: InvestigationReport | None = None
    draft: DraftResponse | None = None
    runtime_verdict: RuntimeVerdict | None = None
    rewrite_count: int = 0
    reinvestigation_count: int = 0
    review_revision_count: int = 0
    review_feedback: RuntimeVerdict | None = None
    rejected_report: InvestigationReport | None = None
    final_response_valid: bool = False
    final_decision: Decision | None = None
    escalation: EscalationPackage | None = None
    error: str | None = None


class RunMetrics(BaseModel):
    tool_calls: int
    duration_ms: float
    degraded_reads: int
    conflicts: int
    mutations_attempted: int


class RunResult(BaseModel):
    run_id: str
    thread_id: str
    status: RunStatus
    modality: Modality
    decision: Decision
    response: DraftResponse | None = None
    final_response_valid: bool = False
    evidence: list[Evidence]
    factual_context: list[EvidenceFact] = Field(default_factory=list)
    gaps: list[str]
    gates: list[GateResult]
    runtime_verdict: RuntimeVerdict
    actions: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[ActionRecommendation] = Field(default_factory=list)
    investigation: InvestigationReport | None = None
    source_plan: InvestigationPlan | None = None
    source_candidates: list[SourceCandidate] = Field(default_factory=list)
    source_selection: SourceSelection | None = None
    source_history: list[SourceAttempt] = Field(default_factory=list)
    review_history: list[RuntimeVerdict] = Field(default_factory=list)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    agent_events: list[AgentEvent] = Field(default_factory=list)
    escalation: EscalationPackage | None = None
    metrics: RunMetrics
    completed_at: datetime = Field(default_factory=utc_now)


class Persona(BaseModel):
    id: str
    user_id: str
    name: str
    role: str
    company_id: str
    company_name: str


class SessionCreate(BaseModel):
    persona_id: str


class Session(BaseModel):
    id: str
    persona_id: str
    created_at: datetime = Field(default_factory=utc_now)


class RunCreate(BaseModel):
    persona_id: str
    asset_id: str
    message: str = Field(min_length=3, max_length=4000)
    additional_context: str | None = Field(default=None, max_length=8000)
    investigation_key: str | None = Field(default=None, min_length=3, max_length=160)
    session_id: str | None = None
    case_id: str | None = None
    seed: str | None = None
    gate_enabled: bool = True


class RunSummary(BaseModel):
    id: str
    session_id: str | None
    persona_id: str
    user_id: str
    asset_id: str
    case_id: str | None
    message: str
    additional_context: str | None = None
    investigation_key: str | None = None
    revision: int = 1
    parent_run_id: str | None = None
    reused: bool = False
    seed: str
    gate_enabled: bool
    status: RunStatus
    modality: Modality | None = None
    decision: Decision | None = None
    current_stage: str
    error: str | None = None
    created_at: datetime
    updated_at: datetime
