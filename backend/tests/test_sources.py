from __future__ import annotations

import pytest

import tractian_agent.agents.multiagent as multiagent_module
from tractian_agent.agents.multiagent import select_sources_with_llm
from tractian_agent.agents.specialists import (
    InvestigationBuffer,
    _apply_conflict_context,
    _select_analysis_ids,
    collect_source_plan,
    fetch_selected_sources,
    prepare_plan,
)
from tractian_agent.domain.models import (
    AgentEvent,
    EnvelopeMode,
    InvestigationPlan,
    QueryEnvelope,
    SelectedSource,
    SourceCandidate,
    SourceSelection,
    ToolError,
    ToolEvent,
)


class KnowledgeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def search_knowledge(self, query: str) -> QueryEnvelope:
        self.calls.append(("GET", "/knowledge/search"))
        return QueryEnvelope(
            mode=EnvelopeMode.COMPLETE,
            data={
                "results": [
                    {
                        "id": "kb_real_1",
                        "title": "Falhas elétricas",
                        "type": "guidance",
                        "tags": ["eletrica"],
                        "body": "Conteúdo relevante.",
                    },
                    {
                        "id": "kb_real_1",
                        "title": "Falhas elétricas",
                        "body": "Resultado duplicado.",
                    },
                ]
            },
        )

    async def get_knowledge(self, document_id: str) -> QueryEnvelope:
        self.calls.append(("GET", f"/knowledge/{document_id}"))
        return QueryEnvelope(
            mode=EnvelopeMode.COMPLETE,
            data={"id": document_id, "title": "Falhas elétricas", "body": "Conteúdo."},
        )


def candidate(document_id: str) -> SourceCandidate:
    return SourceCandidate(id=document_id, title=f"Documento {document_id}")


@pytest.mark.asyncio
async def test_source_selection_accepts_only_real_unique_candidates(settings, monkeypatch):
    async def fake_structured_call(*args, **kwargs):
        del args, kwargs
        return SourceSelection(
            selected_sources=[
                SelectedSource(id="kb_real_1", reason="Relevante."),
                SelectedSource(id="kb_real_1", reason="Duplicado."),
                SelectedSource(id="kb_inventado", reason="Não existe."),
                SelectedSource(id="kb_real_2", reason="Complementar."),
            ]
        ), AgentEvent(
            role="source_selector",
            model="small-model",
            status="completed",
            summary="Seleção concluída.",
        )

    monkeypatch.setattr(multiagent_module, "structured_call", fake_structured_call)
    selection, _ = await select_sources_with_llm(
        settings.model_copy(update={"max_source_documents": 2}),
        {"ticket": "É elétrico?", "intent": "electrical_or_mechanical"},
        [candidate("kb_real_1"), candidate("kb_real_2")],
    )

    assert [item.id for item in selection.selected_sources] == [
        "kb_real_1",
        "kb_real_2",
    ]
    assert any("kb_inventado" in item for item in selection.missing_information)


@pytest.mark.asyncio
async def test_empty_search_skips_second_model_call(settings, monkeypatch):
    called = False

    async def should_not_run(*args, **kwargs):
        nonlocal called
        del args, kwargs
        called = True
        raise AssertionError("A seleção não deve chamar o modelo sem candidatos.")

    monkeypatch.setattr(multiagent_module, "structured_call", should_not_run)
    selection, event = await select_sources_with_llm(
        settings, {"ticket": "Teste"}, []
    )

    assert selection.selected_sources == []
    assert event is None
    assert called is False


@pytest.mark.asyncio
async def test_provider_failure_is_exposed_by_source_selector(settings, monkeypatch):
    async def failed_call(*args, **kwargs):
        del args, kwargs
        return None, AgentEvent(
            role="source_selector",
            model="small-model",
            status="failed",
            summary="Falha.",
            error="HTTP 503",
        )

    monkeypatch.setattr(multiagent_module, "structured_call", failed_call)
    selection, event = await select_sources_with_llm(
        settings, {"ticket": "Teste"}, [candidate("kb_real_1")]
    )

    assert selection.selected_sources == []
    assert event is not None and event.error == "HTTP 503"


@pytest.mark.asyncio
async def test_offline_selection_ranks_candidate_content_without_known_ids(
    settings, monkeypatch
):
    async def offline_call(*args, **kwargs):
        del args, kwargs
        return None, AgentEvent(
            role="source_selector",
            model="offline",
            status="fallback",
            summary="Modelo não configurado.",
        )

    monkeypatch.setattr(multiagent_module, "structured_call", offline_call)
    selection, _ = await select_sources_with_llm(
        settings.model_copy(update={"max_source_documents": 2}),
        {
            "ticket": "A vibração do motor pode ter origem elétrica?",
            "intent": "electrical_or_mechanical",
            "source_plan": InvestigationPlan(
                tools=["knowledge"],
                required_tools=["knowledge"],
                knowledge_queries=["eletrica"],
            ),
        },
        [
            SourceCandidate(
                id="doc_a",
                title="Troca de rolamento em motor",
                snippet="Isolar eletricamente antes da manutenção.",
            ),
            SourceCandidate(
                id="doc_b",
                title="Falhas elétricas em motores",
                tags=["eletrica", "motor"],
                snippet="Componentes elétricos no espectro.",
            ),
        ],
    )

    assert [item.id for item in selection.selected_sources] == ["doc_b"]


@pytest.mark.asyncio
async def test_collection_and_fetch_use_get_and_reject_unknown_document(settings):
    client = KnowledgeClient()
    plan = InvestigationPlan(
        tools=["knowledge"],
        required_tools=["knowledge"],
        knowledge_queries=["falha elétrica", "falha elétrica"],
    )
    state = {
        "asset_id": "asset_1",
        "intent": "electrical_or_mechanical",
        "ticket": "A origem é elétrica?",
    }
    collected = await collect_source_plan(state, client, settings, plan)

    assert [item.id for item in collected["source_candidates"]] == ["kb_real_1"]
    selection = SourceSelection(
        selected_sources=[
            SelectedSource(id="kb_real_1", reason="Retornado pela busca."),
            SelectedSource(id="kb_inventado", reason="Não retornado."),
        ]
    )
    fetched = await fetch_selected_sources(
        {**state, **collected}, client, plan, selection
    )

    assert all(method == "GET" for method, _ in client.calls)
    assert ("GET", "/knowledge/kb_real_1") in client.calls
    assert ("GET", "/knowledge/kb_inventado") not in client.calls
    assert fetched["envelopes"]["knowledge"].data["id"] == "kb_real_1"
    assert fetched["required_evidence"] == {
        "knowledge:kb_real_1": ["id", "title", "body"]
    }
    assert "knowledge" not in fetched["active_envelopes"]


def test_plan_dependency_and_invalid_status_are_checked_before_get():
    prepared, adjustments = prepare_plan(
        InvestigationPlan(tools=["analysis_details"], required_tools=["analysis_details"]),
        "open_investigation",
    )
    assert prepared.tools[0] == "analyses"
    assert "analyses" in prepared.required_tools
    assert adjustments

    with pytest.raises(ValueError, match="analysis_status"):
        prepare_plan(InvestigationPlan(analysis_status="finished"), "open_investigation")


def test_criticality_action_without_technical_question_does_not_require_diagnosis():
    plan = InvestigationPlan(
        tools=["analyses", "analysis_details", "knowledge"],
        required_tools=["analyses", "analysis_details", "knowledge"],
        knowledge_queries=["criticidade"],
    )

    prepared, adjustments = prepare_plan(
        plan,
        "update_criticality",
        "Mude a criticidade para média após aprovação.",
    )
    technical, _ = prepare_plan(
        plan,
        "update_criticality",
        "A criticidade deveria mudar? Justifique com evidência técnica.",
    )

    assert prepared.tools == []
    assert prepared.required_tools == []
    assert prepared.knowledge_queries == []
    assert prepared.knowledge_query is None
    assert prepared.focus == [
        (
            "Preservar a criticidade solicitada e recomendar a alteração futura, "
            "sempre sujeita à aprovação humana."
        )
    ]
    assert adjustments
    assert technical.tools == plan.tools
    assert technical.required_tools == ["analyses", "analysis_details"]


def test_explicit_escalation_collects_the_minimum_engineering_package():
    prepared, adjustments = prepare_plan(
        InvestigationPlan(
            tools=["analyses", "analysis_details", "baseline", "data_quality"],
            required_tools=["analyses", "analysis_details", "baseline", "data_quality"],
        ),
        "explicit_escalation",
        "Encaminhe esta análise para engenharia.",
    )

    assert prepared.tools == [
        "analyses",
        "analysis_details",
        "baseline",
        "data_quality",
        "rms",
    ]
    assert prepared.required_tools == prepared.tools
    assert any("rms" in item.lower() for item in adjustments)


def test_bearing_procedure_removes_diagnostic_sources_from_plan():
    prepared, adjustments = prepare_plan(
        InvestigationPlan(
            tools=["analyses", "analysis_details", "knowledge", "baseline", "data_quality"],
            required_tools=[
                "analyses",
                "analysis_details",
                "knowledge",
                "baseline",
                "data_quality",
            ],
            knowledge_queries=["procedimento", "torque"],
        ),
        "bearing_procedure",
        "Qual é o procedimento de troca e como validar torque e baseline?",
    )

    assert prepared.tools == ["knowledge", "baseline"]
    assert prepared.required_tools == ["knowledge", "baseline"]
    assert any("Fontes diagnósticas removidas" in item for item in adjustments)


def test_specialist_request_uses_pending_analysis_without_generic_knowledge():
    prepared, adjustments = prepare_plan(
        InvestigationPlan(
            tools=["analyses", "analysis_details", "baseline", "knowledge", "data_quality"],
            required_tools=[
                "analyses",
                "analysis_details",
                "baseline",
                "knowledge",
                "data_quality",
            ],
            knowledge_queries=["compressor"],
            analysis_status="current",
        ),
        "request_specialist",
        "Quero que um especialista veja.",
    )

    assert prepared.tools == ["analyses", "analysis_details", "baseline"]
    assert prepared.required_tools == prepared.tools
    assert prepared.analysis_status is None
    assert prepared.knowledge_queries == []


def test_open_investigation_does_not_require_generic_knowledge():
    prepared, adjustments = prepare_plan(
        InvestigationPlan(
            tools=["analyses", "analysis_details", "baseline", "data_quality", "knowledge"],
            required_tools=[
                "analyses",
                "analysis_details",
                "baseline",
                "data_quality",
                "knowledge",
            ],
            knowledge_queries=["alertas"],
        ),
        "open_investigation",
        "Está tudo normal?",
    )

    assert "knowledge" not in prepared.tools
    assert "knowledge" not in prepared.required_tools
    assert prepared.knowledge_queries == []
    assert any("próprio ativo" in item for item in adjustments)


def test_bpfo_confirmation_requires_analysis_and_detail():
    prepared, adjustments = prepare_plan(
        InvestigationPlan(
            tools=["knowledge", "spectrum"],
            required_tools=["knowledge", "spectrum"],
            knowledge_queries=["BPFO"],
        ),
        "bpfo_definition",
        "Um pico isolado confirma defeito?",
    )

    assert "analyses" in prepared.required_tools
    assert "analysis_details" in prepared.required_tools
    assert any("pico isolado" in item for item in adjustments)


def test_failed_refresh_invalidates_previous_active_value():
    old = ToolEvent(
        id="tool_old",
        name="get_rms",
        method="GET",
        path="/assets/a/rms",
        envelope=QueryEnvelope(mode=EnvelopeMode.COMPLETE, data={"samples": [{"value": 4}]}),
        latency_ms=1,
    )
    buffer = InvestigationBuffer(
        {
            "tool_events": [old],
            "envelopes": {"rms": old.envelope},
            "active_envelopes": {"rms": old.envelope},
            "active_event_ids": [old.id],
        }
    )
    failed = ToolEvent(
        id="tool_new",
        name="get_rms",
        method="GET",
        path="/assets/a/rms",
        error=ToolError(kind="transport", message="timeout", retryable=True),
        latency_ms=2,
    )
    buffer.record(failed, "rms", "RMS consultado", ["samples"], decisive=True)

    output = buffer.output()
    assert output["active_envelopes"]["rms"].mode == EnvelopeMode.UNAVAILABLE
    assert output["active_event_ids"][-1] == "tool_new"


def test_divergent_intent_without_data_does_not_claim_resolved_conflict():
    buffer = InvestigationBuffer({})

    _apply_conflict_context("divergent_diagnoses", buffer)

    assert buffer.active_conflicts == []


def test_analysis_details_are_selected_by_status_then_recency_with_omissions():
    buffer = InvestigationBuffer(
        {
            "active_envelopes": {
                "analyses": QueryEnvelope(
                    mode=EnvelopeMode.COMPLETE,
                    data={
                        "analyses": [
                            {"id": "stale_new", "status": "stale", "created_at": "2026-09-05"},
                            {"id": "current_old", "status": "current", "created_at": "2026-09-01"},
                            {"id": "current_new", "status": "current", "created_at": "2026-09-04"},
                            {"id": "pending", "status": "pending", "created_at": "2026-09-05"},
                        ]
                    },
                )
            }
        }
    )

    selected, omitted = _select_analysis_ids(buffer, 2)

    assert selected == ["pending", "current_new"]
    assert omitted == ["current_old", "stale_new"]


def test_active_fact_projection_keeps_original_value_and_event_link():
    buffer = InvestigationBuffer({})
    event = ToolEvent(
        id="tool_rms",
        name="get_rms",
        method="GET",
        path="/assets/a/rms",
        envelope=QueryEnvelope(
            mode=EnvelopeMode.COMPLETE,
            data={"samples": [{"ts": "2026-01-02", "value": 1.25}], "unit": "mm/s"},
        ),
        latency_ms=1,
    )
    buffer.record(event, "rms", "RMS consultado", ["samples", "unit"], decisive=True)

    facts = buffer.output()["factual_context"]
    assert facts[0].source_event_id == "tool_rms"
    assert facts[0].value[0]["value"] == 1.25
    assert facts[1].value == "mm/s"
