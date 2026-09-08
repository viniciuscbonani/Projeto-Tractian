from __future__ import annotations

import unicodedata
from typing import Any
from uuid import uuid4

from tractian_agent.config import Settings
from tractian_agent.domain.models import (
    ConflictRecord,
    DecisionRecord,
    EnvelopeMode,
    Evidence,
    EvidenceFact,
    InvestigationPlan,
    Modality,
    QueryEnvelope,
    SourceCandidate,
    SourceSelection,
    ToolEvent,
)
from tractian_agent.domain.policies import resolve_conflict
from tractian_agent.integrations.tractian import IndustrialClient, InstrumentedTools


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in value if not unicodedata.combining(char))


def classify_ticket(ticket: str) -> tuple[Modality, str]:
    """Contingência explícita quando o classificador LLM não está disponível."""
    text = normalize(ticket)
    if any(
        term in text
        for term in (
            "procedimento",
            "bpfo",
            "tabela fixa",
            "limiar",
            "alarme rms",
            "valor de alarme",
        )
    ):
        intent = (
            "bearing_procedure"
            if "procedimento" in text
            else "bpfo_definition"
            if "bpfo" in text
            else "rms_threshold"
        )
        return Modality.CONTEXTUALIZE, intent
    recommendation_terms = (
        "reprocessa",
        "encaminha",
        "quero que um especialista",
        "muda a criticidade",
        "mudar a criticidade",
        "alterar a criticidade",
        "treina de novo",
    )
    if any(term in text for term in recommendation_terms):
        if "reprocess" in text:
            intent = "reprocess"
        elif "especialista" in text:
            intent = "request_specialist"
        elif "criticidade" in text:
            intent = "update_criticality"
        elif "treina" in text:
            intent = "request_retraining"
        else:
            intent = "explicit_escalation"
        return Modality.RECOMMEND, intent
    if "quebrou" in text and "aviso" in text:
        intent = "break_without_alert"
    elif "rms" in text and ("subindo" in text or "diagnostico" in text):
        intent = "rms_without_insight"
    elif "desbalanceamento" in text and "lisa" in text:
        intent = "possible_false_positive"
    elif "eletric" in text:
        intent = "electrical_or_mechanical"
    elif "em quem" in text or "base solta" in text:
        intent = "divergent_diagnoses"
    elif "desatualizado" in text or "troquei o rolamento" in text:
        intent = "stale_after_maintenance"
    elif "qualidade" in text or "confiar no insight" in text:
        intent = "poor_signal_quality"
    elif "modelo" in text and any(
        term in text for term in ("atende", "corrente continua", "cobre", "cobertura")
    ):
        intent = "model_coverage"
    elif "lubrifica" in text and "baseline" in text:
        intent = "symptom_without_baseline"
    else:
        intent = "open_investigation"
    return Modality.INVESTIGATE, intent


class InvestigationBuffer:
    def __init__(self, state: dict[str, Any], *, reset_sources: bool = False) -> None:
        self.events = [ToolEvent.model_validate(item) for item in state.get("tool_events", [])]
        self.envelopes = {
            key: QueryEnvelope.model_validate(value)
            for key, value in state.get("envelopes", {}).items()
        }
        self.evidence = [Evidence.model_validate(item) for item in state.get("evidence", [])]
        self.gaps = list(state.get("gaps", []))
        self.conflicts = [
            ConflictRecord.model_validate(item) for item in state.get("conflicts", [])
        ]
        self.decisions = [
            DecisionRecord.model_validate(item) for item in state.get("decisions", [])
        ]
        current_envelopes = state.get("active_envelopes") or state.get("envelopes", {})
        current_event_ids = list(state.get("active_event_ids", []))
        current_evidence_ids = list(state.get("active_evidence_ids", []))
        if reset_sources:
            self.active_envelopes = {
                key: QueryEnvelope.model_validate(value)
                for key, value in current_envelopes.items()
                if key == "asset"
            }
            asset_events = {
                item.source_event_id for item in self.evidence if item.source_path.startswith("/assets/")
                and item.source_path.count("/") == 2
            }
            self.active_event_ids = (
                [value for value in current_event_ids if value in asset_events]
                if current_event_ids
                else list(asset_events)
            )
            self.active_evidence_ids = [
                item.id for item in self.evidence if item.source_event_id in asset_events
            ]
            self.active_gaps: list[str] = []
            self.active_conflicts: list[ConflictRecord] = []
        else:
            self.active_envelopes = {
                key: QueryEnvelope.model_validate(value)
                for key, value in current_envelopes.items()
            }
            self.active_event_ids = current_event_ids
            self.active_evidence_ids = current_evidence_ids or [item.id for item in self.evidence]
            self.active_gaps = list(state.get("active_gaps", state.get("gaps", [])))
            self.active_conflicts = [
                ConflictRecord.model_validate(item)
                for item in state.get("active_conflicts", state.get("conflicts", []))
            ]

    def record(
        self,
        event: ToolEvent,
        key: str,
        claim: str,
        fields: list[str],
        *,
        decisive: bool = False,
    ) -> None:
        self.events.append(event)
        self.active_event_ids.append(event.id)
        if event.error:
            gap = f"{event.path}: {event.error.kind}: {event.error.message}"
            self.gaps.append(gap)
            self.active_gaps.append(gap)
            unavailable = QueryEnvelope(mode=EnvelopeMode.UNAVAILABLE, notes=gap)
            self.envelopes[key] = unavailable
            self.active_envelopes[key] = unavailable
            return
        if event.envelope is None:
            return
        self.envelopes[key] = event.envelope
        self.active_envelopes[key] = event.envelope
        if event.envelope.mode in {EnvelopeMode.INCONCLUSIVE, EnvelopeMode.UNAVAILABLE}:
            gap = f"{event.path}: {event.envelope.notes or event.envelope.mode.value}"
            self.gaps.append(gap)
            self.active_gaps.append(gap)
            return
        evidence = Evidence(
            id=f"ev_{uuid4().hex[:10]}",
            claim=claim,
            source_event_id=event.id,
            source_path=event.path,
            fields=fields,
            mode=event.envelope.mode,
            decisive=decisive,
        )
        self.evidence.append(evidence)
        self.active_evidence_ids.append(evidence.id)
        if event.envelope.mode == EnvelopeMode.PARTIAL:
            gap = f"{event.path}: {event.envelope.notes or 'retorno parcial'}"
            self.gaps.append(gap)
            self.active_gaps.append(gap)

    def output(self) -> dict[str, Any]:
        return {
            "tool_events": self.events,
            "envelopes": self.envelopes,
            "evidence": self.evidence,
            "gaps": list(dict.fromkeys(self.gaps)),
            "conflicts": self.conflicts,
            "decisions": self.decisions,
            "active_event_ids": list(dict.fromkeys(self.active_event_ids)),
            "active_envelopes": self.active_envelopes,
            "active_evidence_ids": list(dict.fromkeys(self.active_evidence_ids)),
            "active_gaps": list(dict.fromkeys(self.active_gaps)),
            "active_conflicts": self.active_conflicts,
            "factual_context": project_active_facts(
                self.events,
                self.evidence,
                self.active_event_ids,
                self.active_evidence_ids,
            ),
        }


def _read_field(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


def project_active_facts(
    events: list[ToolEvent],
    evidence: list[Evidence],
    active_event_ids: list[str],
    active_evidence_ids: list[str],
) -> list[EvidenceFact]:
    """Projeta valores de GET ativos sem usar o claim como substituto do dado original."""
    event_by_id = {item.id: item for item in events if item.id in active_event_ids}
    facts: list[EvidenceFact] = []
    for item in evidence:
        if item.id not in active_evidence_ids:
            continue
        event = event_by_id.get(item.source_event_id)
        if not event or not event.envelope:
            continue
        payload = event.envelope.data
        source_timestamp = None
        source_version = None
        if isinstance(payload, dict):
            source_timestamp = next(
                (str(payload[key]) for key in ("measured_at", "timestamp", "created_at") if payload.get(key)),
                None,
            )
            source_version = next(
                (str(payload[key]) for key in ("model_version", "version") if payload.get(key)),
                None,
            )
        for field in item.fields:
            facts.append(
                EvidenceFact(
                    evidence_id=item.id,
                    source_event_id=item.source_event_id,
                    source_path=item.source_path,
                    field=field,
                    value=_read_field(payload, field),
                    mode=item.mode,
                    observation=event.envelope.notes,
                    observed_at=event.started_at,
                    source_timestamp=source_timestamp,
                    source_version=source_version,
                )
            )
    return facts


async def _read(
    buffer: InvestigationBuffer,
    tools: InstrumentedTools,
    *,
    name: str,
    path: str,
    args: dict[str, Any],
    operation: Any,
    key: str,
    claim: str,
    fields: list[str],
) -> ToolEvent:
    event = await tools.read(name, path, args, operation)
    buffer.record(event, key, claim, fields, decisive=True)
    return event


def _analysis_ids(buffer: InvestigationBuffer) -> list[str]:
    envelope = buffer.active_envelopes.get("analyses")
    data = envelope.data if envelope and isinstance(envelope.data, dict) else {}
    return [row["id"] for row in data.get("analyses", []) if row.get("id")]


def _select_analysis_ids(
    buffer: InvestigationBuffer, limit: int
) -> tuple[list[str], list[str]]:
    """Prioriza estados úteis e recência, preservando os IDs omitidos para auditoria."""
    envelope = buffer.active_envelopes.get("analyses")
    data = envelope.data if envelope and isinstance(envelope.data, dict) else {}
    rows = [
        row
        for row in data.get("analyses", [])
        if isinstance(row, dict) and row.get("id")
    ]
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    priority = {"pending": 0, "delayed": 1, "inconclusive": 2, "current": 3, "stale": 4}
    rows.sort(key=lambda row: priority.get(str(row.get("status")), 5))
    ids = [str(row["id"]) for row in rows]
    safe_limit = max(1, limit)
    return ids[:safe_limit], ids[safe_limit:]


async def _list_analyses(
    buffer: InvestigationBuffer,
    tools: InstrumentedTools,
    client: IndustrialClient,
    asset_id: str,
    status: str | None = None,
) -> None:
    suffix = f"?status={status}" if status else ""
    await _read(
        buffer,
        tools,
        name="list_analyses",
        path=f"/assets/{asset_id}/analyses{suffix}",
        args={"asset_id": asset_id, **({"status": status} if status else {})},
        operation=lambda: client.list_analyses(asset_id, status),
        key="analyses",
        claim="Análises do ativo e seus estados foram consultados.",
        fields=["analyses"],
    )


async def _analysis_details(
    buffer: InvestigationBuffer,
    tools: InstrumentedTools,
    client: IndustrialClient,
    limit: int,
) -> list[str]:
    selected_ids, omitted_ids = _select_analysis_ids(buffer, limit)
    for analysis_id in selected_ids:
        await _read(
            buffer,
            tools,
            name="get_analysis",
            path=f"/analyses/{analysis_id}",
            args={"analysis_id": analysis_id},
            operation=lambda value=analysis_id: client.get_analysis(value),
            key=f"analysis:{analysis_id}",
            claim=f"Detalhes da análise {analysis_id} foram verificados.",
            fields=["type", "status", "confidence", "detection_mode", "limitations"],
        )
    return omitted_ids


async def _baseline(
    buffer: InvestigationBuffer, tools: InstrumentedTools, client: IndustrialClient, asset_id: str
) -> None:
    await _read(
        buffer,
        tools,
        name="get_baseline",
        path=f"/assets/{asset_id}/baseline",
        args={"asset_id": asset_id},
        operation=lambda: client.get_baseline(asset_id),
        key="baseline",
        claim="Estado e aplicabilidade do baseline foram verificados.",
        fields=["state", "detection_mode", "learnable", "features"],
    )


async def _rms(
    buffer: InvestigationBuffer, tools: InstrumentedTools, client: IndustrialClient, asset_id: str
) -> None:
    await _read(
        buffer,
        tools,
        name="get_rms",
        path=f"/assets/{asset_id}/rms",
        args={"asset_id": asset_id},
        operation=lambda: client.get_rms(asset_id),
        key="rms",
        claim="Série RMS, referência e limiar do ativo foram consultados.",
        fields=["samples", "baseline_reference", "alarm_threshold"],
    )


async def _spectrum(
    buffer: InvestigationBuffer, tools: InstrumentedTools, client: IndustrialClient, asset_id: str
) -> None:
    await _read(
        buffer,
        tools,
        name="get_spectrum",
        path=f"/assets/{asset_id}/spectrum",
        args={"asset_id": asset_id},
        operation=lambda: client.get_spectrum(asset_id),
        key="spectrum",
        claim="Picos e bandas ausentes do espectro foram verificados.",
        fields=["peaks", "bands_missing"],
    )


async def _quality(
    buffer: InvestigationBuffer, tools: InstrumentedTools, client: IndustrialClient, asset_id: str
) -> None:
    await _read(
        buffer,
        tools,
        name="get_data_quality",
        path=f"/assets/{asset_id}/data-quality",
        args={"asset_id": asset_id},
        operation=lambda: client.get_data_quality(asset_id),
        key="data_quality",
        claim="Completude, frescor e relação sinal-ruído foram verificadas.",
        fields=["completeness", "snr_db", "staleness_flag"],
    )


async def _model(
    buffer: InvestigationBuffer, tools: InstrumentedTools, client: IndustrialClient, model_id: str
) -> None:
    await _read(
        buffer,
        tools,
        name="get_model",
        path=f"/models/{model_id}",
        args={"model_id": model_id},
        operation=lambda: client.get_model(model_id),
        key="model",
        claim="Cobertura, requisitos e processamento do modelo foram verificados.",
        fields=["coverage", "requirements", "processing_state"],
    )


def _record_search_event(
    buffer: InvestigationBuffer, event: ToolEvent, key: str
) -> dict[str, Any]:
    """Registra a busca para auditoria sem torná-la evidência técnica decisiva."""
    buffer.events.append(event)
    buffer.active_event_ids.append(event.id)
    if event.error:
        gap = f"{event.path}: {event.error.kind}: {event.error.message}"
        buffer.gaps.append(gap)
        buffer.active_gaps.append(gap)
        unavailable = QueryEnvelope(mode=EnvelopeMode.UNAVAILABLE, notes=gap)
        buffer.envelopes[key] = unavailable
        buffer.active_envelopes[key] = unavailable
        return {}
    if event.envelope is None:
        return {}
    buffer.envelopes[key] = event.envelope
    buffer.active_envelopes[key] = event.envelope
    if event.envelope.mode in {EnvelopeMode.INCONCLUSIVE, EnvelopeMode.UNAVAILABLE}:
        gap = f"{event.path}: {event.envelope.notes or event.envelope.mode.value}"
        buffer.gaps.append(gap)
        buffer.active_gaps.append(gap)
        return {}
    if event.envelope.mode == EnvelopeMode.PARTIAL:
        gap = f"{event.path}: {event.envelope.notes or 'retorno parcial'}"
        buffer.gaps.append(gap)
        buffer.active_gaps.append(gap)
    return event.envelope.data if isinstance(event.envelope.data, dict) else {}


async def _search_knowledge_candidates(
    buffer: InvestigationBuffer,
    tools: InstrumentedTools,
    client: IndustrialClient,
    queries: list[str],
) -> list[SourceCandidate]:
    candidates: dict[str, SourceCandidate] = {}
    unique_queries = list(dict.fromkeys(normalize(query).strip() for query in queries if query.strip()))
    for index, query in enumerate(unique_queries):
        event = await tools.read(
            "search_knowledge",
            "/knowledge/search",
            {"q": query},
            lambda value=query: client.search_knowledge(value),
        )
        data = _record_search_event(buffer, event, f"knowledge_search:{index}")
        if event.envelope and not event.error and not data.get("results"):
            gap = f"/knowledge/search?q={query}: zero resultados; ausência não comprovada"
            buffer.gaps.append(gap)
            buffer.active_gaps.append(gap)
        for row in data.get("results", []):
            if not isinstance(row, dict) or not row.get("id"):
                continue
            document_id = str(row["id"])
            if document_id in candidates:
                continue
            raw_tags = row.get("tags", [])
            tags = [str(value) for value in raw_tags] if isinstance(raw_tags, list) else []
            body = str(row.get("body") or "")
            candidates[document_id] = SourceCandidate(
                id=document_id,
                title=str(row.get("title") or document_id),
                type=str(row["type"]) if row.get("type") else None,
                tags=tags,
                snippet=body[:280],
            )
    return list(candidates.values())


_REQUIRED_FIELDS: dict[str, list[str]] = {
    "analyses": ["analyses"],
    "baseline": ["state"],
    "rms": ["samples"],
    "spectrum": ["peaks"],
    "data_quality": ["completeness", "snr_db"],
    "model": ["coverage"],
    "knowledge": ["body"],
}

_MINIMUM_TOOLS: dict[str, list[str]] = {
    "bearing_procedure": ["knowledge", "baseline"],
    "bpfo_definition": ["knowledge", "spectrum"],
    "rms_threshold": ["baseline", "rms"],
    "rms_without_insight": ["rms", "baseline", "analyses", "model"],
    "possible_false_positive": ["analyses", "analysis_details", "baseline", "spectrum"],
    "divergent_diagnoses": ["analyses", "analysis_details", "spectrum"],
    "stale_after_maintenance": ["analyses", "analysis_details", "baseline"],
    "poor_signal_quality": ["analysis_details", "data_quality", "model"],
    "model_coverage": ["model"],
    "symptom_without_baseline": ["analyses", "analysis_details", "baseline"],
    "explicit_escalation": [
        "analyses",
        "analysis_details",
        "baseline",
        "data_quality",
        "rms",
    ],
}


def prepare_plan(
    plan: InvestigationPlan,
    intent: str,
    ticket: str = "",
    additional_context: str = "",
) -> tuple[InvestigationPlan, list[str]]:
    """Aplica dependências e mínimos pequenos, registrando cada ajuste auditável."""
    if plan.analysis_status not in {None, "current", "stale", "pending", "inconclusive"}:
        raise ValueError(f"analysis_status não suportado: {plan.analysis_status!r}")
    tools = list(dict.fromkeys(plan.tools))
    required = list(dict.fromkeys(plan.required_tools))
    analysis_status = plan.analysis_status
    adjustments: list[str] = []
    request_text = normalize(f"{ticket} {additional_context}")
    asks_technical_basis = any(
        term in request_text
        for term in (
            "por que",
            "justific",
            "evidenc",
            "tecnic",
            "devo",
            "deveria",
            "adequad",
            "corret",
            "faz sentido",
        )
    )
    if intent == "update_criticality" and request_text and not asks_technical_basis:
        tools = []
        required = []
        knowledge_queries: list[str] = []
        focus = [
            (
                "Preservar a criticidade solicitada e recomendar a alteração futura, "
                "sempre sujeita à aprovação humana."
            )
        ]
        adjustments.append(
            "Pedido de alteração sem pergunta de justificativa técnica: o ativo já carregado "
            "basta para formular recomendação futura sujeita a aprovação."
        )
    elif intent == "bearing_procedure":
        allowed = {"knowledge", "baseline"}
        removed = [source for source in tools if source not in allowed]
        tools = [source for source in tools if source in allowed]
        required = [source for source in required if source in allowed]
        knowledge_queries = plan.knowledge_queries
        focus = plan.focus
        if removed:
            adjustments.append(
                "Fontes diagnósticas removidas: o pedido requer documento de procedimento e "
                "baseline, não uma nova avaliação da condição da máquina."
            )
    elif intent == "request_specialist":
        allowed = {"analyses", "analysis_details", "baseline"}
        removed = [source for source in tools if source not in allowed]
        tools = [source for source in tools if source in allowed]
        required = [source for source in required if source in allowed]
        knowledge_queries = []
        focus = plan.focus
        analysis_status = None
        if removed:
            adjustments.append(
                "Fontes não decisivas removidas: o encaminhamento usa a análise pendente, seus "
                "detalhes e o baseline."
            )
    elif intent == "open_investigation":
        allowed = {
            "analyses",
            "analysis_details",
            "baseline",
            "rms",
            "spectrum",
            "data_quality",
        }
        removed = [source for source in tools if source not in allowed]
        tools = [source for source in tools if source in allowed]
        required = [source for source in required if source in allowed]
        knowledge_queries = []
        focus = plan.focus
        if removed:
            adjustments.append(
                "Conhecimento genérico removido: a condição atual deve ser respondida pelos "
                "dados observados do próprio ativo."
            )
    elif intent == "bpfo_definition" and any(
        term in request_text for term in ("confirma", "confirmar", "defeito", "pico")
    ):
        knowledge_queries = plan.knowledge_queries
        focus = plan.focus
        for source in ("analyses", "analysis_details"):
            if source not in tools:
                tools.append(source)
                adjustments.append(
                    f"Fonte adicionada para avaliar se o pico isolado confirma defeito: {source}."
                )
            if source not in required:
                required.append(source)
    else:
        knowledge_queries = plan.knowledge_queries
        focus = plan.focus
    for source in _MINIMUM_TOOLS.get(intent, []):
        if source not in tools:
            tools.append(source)
            adjustments.append(f"Fonte mínima condicional adicionada: {source} ({intent}).")
        if source not in required:
            required.append(source)
            adjustments.append(f"Fonte marcada como decisiva pela política: {source} ({intent}).")
    for dependent in ("analysis_details", "model"):
        if dependent in tools and "analyses" not in tools:
            tools.insert(0, "analyses")
            adjustments.append(f"Dependência adicionada: analyses antes de {dependent}.")
    if "analysis_details" in required and "analyses" not in required:
        required.append("analyses")
        adjustments.append("Dependência decisiva adicionada: analyses para analysis_details.")
    if "knowledge" in tools and not plan.knowledge_queries:
        adjustments.append("Knowledge sem consulta: recuperação ficará explicitamente indisponível.")
    mentions_docs = any(
        term in request_text
        for term in ("manual", "procediment", "document", "definicao", "criterio")
    )
    if not mentions_docs and "knowledge" in required:
        required.remove("knowledge")
        adjustments.append("Busca de conhecimento tornada opcional pois a solicitação não cita documentos técnicos.")
    return plan.model_copy(
        update={
            "tools": tools,
            "required_tools": required,
            "knowledge_queries": knowledge_queries,
            "knowledge_query": None if not knowledge_queries else plan.knowledge_query,
            "focus": focus,
            "analysis_status": analysis_status,
        }
    ), adjustments


def _required_for_plan(
    plan: InvestigationPlan, buffer: InvestigationBuffer, intent: str
) -> dict[str, list[str]]:
    required: dict[str, list[str]] = {}
    for source in plan.required_tools:
        if source == "analysis_details":
            analysis_ids = [
                key.removeprefix("analysis:")
                for key in buffer.active_envelopes
                if key.startswith("analysis:")
            ]
            if analysis_ids:
                for analysis_id in analysis_ids:
                    required[f"analysis:{analysis_id}"] = ["id", "status", "type"]
            else:
                required["analyses"] = ["analyses.0.id"]
            continue
        if source == "knowledge":
            document_keys = sorted(
                key for key in buffer.active_envelopes if key.startswith("knowledge:")
            )
            if document_keys:
                for key in document_keys:
                    required[key] = ["id", "title", "body"]
            else:
                required["knowledge"] = ["body"]
            continue
        fields = _REQUIRED_FIELDS.get(source)
        if fields:
            required[source] = fields
    if intent in {"rms_threshold", "rms_without_insight"} and "rms" in required:
        required["rms"] = ["samples.0.value", "unit", "alarm_threshold"]
    return required


def _apply_conflict_context(intent: str, buffer: InvestigationBuffer) -> None:
    if intent == "electrical_or_mechanical":
        spectrum = buffer.active_envelopes.get("spectrum")
        data = spectrum.data if spectrum and isinstance(spectrum.data, dict) else {}
        if any("2x" in str(value).lower() for value in data.get("bands_missing", [])):
            gap = "A banda de 2x da frequência de linha está ausente; a origem elétrica não pode ser confirmada."
            buffer.gaps.append(gap)
            buffer.active_gaps.append(gap)
    if intent in {"possible_false_positive", "divergent_diagnoses"}:
        analyses = buffer.active_envelopes.get("analyses")
        rows = analyses.data.get("analyses", []) if analyses and isinstance(analyses.data, dict) else []
        diagnoses = list(dict.fromkeys(str(row.get("type")) for row in rows if row.get("type")))
        if len(diagnoses) > 1:
            conflict = resolve_conflict(
                "diagnósticos divergentes",
                diagnoses,
                same_instant=True,
                dedicated_source=None,
                technical_support=None,
                impact=(
                    "informational"
                    if intent == "divergent_diagnoses"
                    else "blocks_claim"
                ),
            )
            buffer.conflicts.append(conflict)
            buffer.active_conflicts.append(conflict)


def _model_ids(buffer: InvestigationBuffer, settings: Settings) -> list[str]:
    versions: list[str] = []
    analyses = buffer.active_envelopes.get("analyses")
    if analyses and isinstance(analyses.data, dict):
        versions.extend(
            str(row["model_version"])
            for row in analyses.data.get("analyses", [])
            if row.get("model_version")
        )
    for key, envelope in buffer.active_envelopes.items():
        if key.startswith("analysis:") and isinstance(envelope.data, dict) and envelope.data.get("model_version"):
            versions.append(str(envelope.data["model_version"]))
    return list(
        dict.fromkeys(settings.model_version_map[version] for version in versions if version in settings.model_version_map)
    )


async def collect_source_plan(
    state: dict[str, Any],
    client: IndustrialClient,
    settings: Settings,
    plan: InvestigationPlan,
) -> dict[str, Any]:
    """Executa o plano de leitura e devolve candidatos, sem escolher documentos."""
    plan, adjustments = prepare_plan(
        plan,
        str(state.get("intent") or "open_investigation"),
        str(state.get("ticket") or ""),
        str(state.get("additional_context") or ""),
    )
    buffer = InvestigationBuffer(state, reset_sources=True)
    tools = InstrumentedTools(client)
    asset_id = state["asset_id"]
    intent = str(state.get("intent") or "open_investigation")
    selected = set(plan.tools)

    if "analyses" in selected:
        await _list_analyses(buffer, tools, client, asset_id, plan.analysis_status)
    if "analysis_details" in selected:
        if "analyses" not in buffer.envelopes:
            await _list_analyses(buffer, tools, client, asset_id, plan.analysis_status)
        omitted_ids = await _analysis_details(
            buffer, tools, client, settings.max_analysis_details
        )
        if omitted_ids:
            omission = (
                f"Detalhes limitados a {settings.max_analysis_details} análises por estado e "
                f"recência; não revisados: {', '.join(omitted_ids)}."
            )
            adjustments.append(omission)
            buffer.gaps.append(omission)
            buffer.active_gaps.append(omission)
    if "baseline" in selected:
        await _baseline(buffer, tools, client, asset_id)
    if "rms" in selected:
        await _rms(buffer, tools, client, asset_id)
    if "spectrum" in selected:
        await _spectrum(buffer, tools, client, asset_id)
    if "data_quality" in selected:
        await _quality(buffer, tools, client, asset_id)
    if "model" in selected:
        model_ids = _model_ids(buffer, settings)
        if not model_ids:
            gap = "Não foi possível vincular as análises do ativo a um model_id conhecido."
            buffer.gaps.append(gap)
            buffer.active_gaps.append(gap)
            unavailable = QueryEnvelope(mode=EnvelopeMode.UNAVAILABLE, notes=gap)
            buffer.envelopes["model"] = unavailable
            buffer.active_envelopes["model"] = unavailable
        for model_id in model_ids:
            await _model(buffer, tools, client, model_id)
            latest = buffer.active_envelopes.get("model")
            if latest:
                buffer.active_envelopes[f"model:{model_id}"] = latest
    candidates: list[SourceCandidate] = []
    if "knowledge" in selected:
        queries = plan.knowledge_queries or (
            [plan.knowledge_query] if plan.knowledge_query else []
        )
        if not queries:
            gap = "O plano exigiu conhecimento, mas não forneceu consulta de busca."
            buffer.gaps.append(gap)
            buffer.active_gaps.append(gap)
        candidates = await _search_knowledge_candidates(
            buffer,
            tools,
            client,
            queries[: settings.max_source_queries],
        )

    _apply_conflict_context(intent, buffer)

    output = buffer.output()
    output.update(
        source_plan=plan,
        source_candidates=candidates,
        required_evidence=_required_for_plan(plan, buffer, intent),
        plan_adjustments=adjustments,
        current_stage="source_collect",
    )
    return output


async def fetch_selected_sources(
    state: dict[str, Any],
    client: IndustrialClient,
    plan: InvestigationPlan,
    selection: SourceSelection,
) -> dict[str, Any]:
    """Obtém apenas documentos previamente retornados e escolhidos pelo agente."""
    buffer = InvestigationBuffer(state)
    tools = InstrumentedTools(client)
    allowed = {
        SourceCandidate.model_validate(item).id for item in state.get("source_candidates", [])
    }
    fetched = 0
    for selected in selection.selected_sources:
        if selected.id not in allowed:
            gap = f"Documento {selected.id} descartado: ID não retornado pela API."
            buffer.gaps.append(gap)
            buffer.active_gaps.append(gap)
            continue
        event = await _read(
            buffer,
            tools,
            name="get_knowledge",
            path=f"/knowledge/{selected.id}",
            args={"document_id": selected.id},
            operation=lambda value=selected.id: client.get_knowledge(value),
            key=f"knowledge:{selected.id}",
            claim=f"Documento {selected.id} foi recuperado integralmente.",
            fields=["title", "body"],
        )
        if event.envelope and not event.error:
            # Alias apenas histórico para leitores v5/v6/v7; a visão ativa usa knowledge:<id>.
            buffer.envelopes["knowledge"] = event.envelope
            fetched += 1

    buffer.gaps.extend(selection.missing_information)
    if "knowledge" in plan.required_tools and fetched == 0:
        buffer.envelopes["knowledge"] = QueryEnvelope(
            mode=EnvelopeMode.UNAVAILABLE,
            notes="Nenhum documento candidato relevante foi selecionado.",
        )
        buffer.active_envelopes["knowledge"] = buffer.envelopes["knowledge"]
        gap = "Nenhuma fonte de conhecimento decisiva foi recuperada."
        buffer.gaps.append(gap)
        buffer.active_gaps.append(gap)

    output = buffer.output()
    output.update(
        required_evidence=_required_for_plan(plan, buffer, str(state.get("intent") or "open_investigation")),
        current_stage="source_select",
    )
    return output
