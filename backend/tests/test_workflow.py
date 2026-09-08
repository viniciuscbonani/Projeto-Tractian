from __future__ import annotations

import json
from pathlib import Path

import pytest

import tractian_agent.graph.workflow as workflow_module
from tractian_agent.agents.specialists import classify_ticket
from tractian_agent.domain.models import (
    ActionRecommendation,
    AgentEvent,
    AgentState,
    DraftResponse,
    EnvelopeMode,
    InvestigationHypothesis,
    InvestigationReport,
    QueryEnvelope,
    RuntimeVerdict,
)
from tractian_agent.graph import AgentWorkflow
from tractian_agent.graph.workflow import (
    merge_mapping,
    merge_recommendations,
    merge_sequence,
    merge_workflow_state,
)

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "api-tractian" / "agent-input" / "cases.json").read_text())


def test_audit_snapshot_applies_the_same_append_reducers_as_the_graph():
    current = {
        "agent_events": [{"role": "classifier"}],
        "envelopes": {"asset": {"mode": "complete"}},
    }
    merged = merge_workflow_state(
        current,
        {
            "agent_events": [{"role": "investigator"}],
            "envelopes": {"rms": {"mode": "complete"}},
            "current_stage": "investigator",
        },
    )

    assert [item["role"] for item in merged["agent_events"]] == [
        "classifier",
        "investigator",
    ]
    assert set(merged["envelopes"]) == {"asset", "rms"}
    assert merged["current_stage"] == "investigator"


@pytest.mark.asyncio
async def test_complete_graph_with_in_process_async_client(settings):
    class AsyncClient:
        async def aclose(self):
            return None

        async def get_user(self):
            return {"id": "usr", "company_id": "company"}

        async def get_asset(self, asset_id):
            return QueryEnvelope(
                mode=EnvelopeMode.COMPLETE,
                data={"id": asset_id, "machine_type": "compressor", "criticality": "high", "points": []},
            )

        async def list_analyses(self, asset_id, status=None):
            del asset_id, status
            return QueryEnvelope(
                mode=EnvelopeMode.COMPLETE,
                data={
                    "analyses": [
                        {"id": "an_dynamic", "status": "pending", "type": "bearing_fault", "model_version": "3.2.1"}
                    ]
                },
            )

        async def get_baseline(self, asset_id):
            del asset_id
            return QueryEnvelope(mode=EnvelopeMode.COMPLETE, data={"state": "established"})

        async def get_rms(self, asset_id):
            del asset_id
            return QueryEnvelope(
                mode=EnvelopeMode.COMPLETE,
                data={
                    "samples": [{"ts": "2026-09-05T00:00:00Z", "value": 6.0}],
                    "unit": "mm/s",
                    "alarm_threshold": 5.0,
                },
            )

        async def get_data_quality(self, asset_id):
            del asset_id
            return QueryEnvelope(
                mode=EnvelopeMode.COMPLETE,
                data={"completeness": 1.0, "snr_db": 20.0, "staleness_flag": False},
            )

        async def get_model(self, model_id):
            return QueryEnvelope(
                mode=EnvelopeMode.COMPLETE,
                data={"id": model_id, "coverage": ["bearing_fault"], "processing_state": "delayed"},
            )

    graph = AgentWorkflow(settings, client_factory=lambda *_: AsyncClient())
    initial = AgentState(
        run_id="run_async",
        thread_id="thread_async",
        asset_id="asset_dynamic",
        user_id="usr",
        seed="complete",
        ticket="O RMS está subindo e não recebi insight.",
    )

    final, result = await graph.run(initial)

    assert final.current_stage == "completed"
    assert result.decision.value == "recomendar"
    assert result.final_response_valid is True
    assert result.factual_context
    assert all(event.method == "GET" for event in final.tool_events)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[case["ticket_id"] for case in CASES])
async def test_all_17_cases_follow_the_five_agent_flow_without_mutations(workflow, case):
    checkpoints: list[str] = []
    state = AgentState(
        run_id=f"test_{case['id']}",
        thread_id=f"thread_{case['id']}",
        case_id=case["id"],
        company_id=case["company_id"],
        asset_id=case["asset_id"],
        user_id=case["user_id"],
        seed="complete",
        gate_enabled=True,
        ticket=case["message"],
    )

    final, result = await workflow.run(state, lambda node, _: checkpoints.append(node))

    assert result.status.value == "completed"
    assert result.runtime_verdict.verdict in {"approve", "escalate"}
    assert checkpoints[-1] == "finalize"
    assert "sufficiency_gate" in checkpoints
    assert "reviewer" in checkpoints
    if result.decision.value == "escalar":
        assert "writer" not in checkpoints
        assert result.response is None
        assert result.escalation is not None
        assert result.escalation.customer_response_allowed is False
        assert {event.role for event in result.agent_events} == {
            "classifier",
            "source_selector",
            "investigator",
            "judge",
        }
    else:
        assert checkpoints.index("reviewer") < checkpoints.index("writer")
        assert result.response is not None
        assert {event.role for event in result.agent_events} == {
            "classifier",
            "source_selector",
            "investigator",
            "judge",
            "writer",
        }
    assert result.actions == []
    assert result.metrics.mutations_attempted == 0
    assert all(event.method == "GET" for event in final.tool_events)
    assert all(item.requires_human_approval for item in result.recommendations)


@pytest.mark.asyncio
async def test_gate_blocks_unsupported_electrical_conclusion(workflow):
    case = next(item for item in CASES if item["ticket_id"] == "TKT-INV-07")
    state = AgentState(
        run_id="test_gate",
        thread_id="thread_gate",
        case_id=case["id"],
        asset_id=case["asset_id"],
        user_id=case["user_id"],
        seed="complete",
        gate_enabled=True,
        ticket=case["message"],
    )

    _, result = await workflow.run(state)

    assert result.response is not None
    assert "não é possível" in result.response.summary.lower()
    assert result.decision.value in {"orientar", "escalar"}
    assert result.metrics.mutations_attempted == 0


@pytest.mark.asyncio
async def test_electrical_question_selects_relevant_source_without_exact_title(workflow):
    case = next(item for item in CASES if item["ticket_id"] == "TKT-INV-07")
    state = AgentState(
        run_id="test_electrical_source",
        thread_id="thread_electrical_source",
        case_id=case["id"],
        asset_id=case["asset_id"],
        user_id=case["user_id"],
        seed="complete",
        gate_enabled=True,
        ticket=case["message"],
    )

    _, result = await workflow.run(state)

    assert result.source_plan is not None
    assert result.source_plan.knowledge_queries == ["eletrica"]
    assert result.source_selection is not None
    assert [item.id for item in result.source_selection.selected_sources] == [
        "kb_guid_003"
    ]
    assert result.source_plan.knowledge_queries[0] != "Falhas elétricas em motores"


@pytest.mark.asyncio
async def test_bpfo_fallback_answers_the_question_instead_of_listing_tool_calls(workflow):
    case = next(item for item in CASES if item["ticket_id"] == "TKT-CTX-02")
    state = AgentState(
        run_id="test_bpfo_answer",
        thread_id="thread_bpfo_answer",
        case_id=case["id"],
        asset_id=case["asset_id"],
        user_id=case["user_id"],
        seed="complete",
        gate_enabled=True,
        ticket=case["message"],
    )

    _, result = await workflow.run(state)

    assert result.response is not None
    answer = " ".join([result.response.summary, *result.response.explanation]).lower()
    assert "bpfo" in answer
    assert "pista externa" in answer
    assert "107.4 hz" in answer
    assert "investigação foi consolidada" not in answer
    assert any("baseline invalidado" in item.lower() for item in result.response.limitations)


@pytest.mark.asyncio
async def test_rms_fallback_explains_delay_without_exposing_internal_governance(workflow):
    case = next(item for item in CASES if item["ticket_id"] == "TKT-INV-05")
    state = AgentState(
        run_id="test_rms_answer",
        thread_id="thread_rms_answer",
        case_id=case["id"],
        asset_id=case["asset_id"],
        user_id=case["user_id"],
        seed="complete",
        gate_enabled=True,
        ticket=case["message"],
    )

    _, result = await workflow.run(state)

    assert result.response is not None
    answer = " ".join(
        [
            result.response.summary,
            *result.response.explanation,
            *result.response.next_steps,
        ]
    ).lower()
    assert "3.274 mm/s" in answer
    assert "limiar de 2.6 mm/s" in answer
    assert "processamento" in answer and "atrasado" in answer
    assert "sujeita à aprovação" not in answer
    assert "reprocess_analysis" not in answer
    assert "an_9902" not in " ".join(result.response.next_steps)
    assert len(result.recommendations) == 1


def test_state_reducers_accept_snapshots_and_deltas_without_duplication():
    first = {"id": "tool_1"}
    second = {"id": "tool_2"}
    assert merge_sequence([first], [first, second]) == [first, second]
    assert merge_sequence([first], [second]) == [first, second]
    assert merge_mapping({"baseline": {"mode": "complete"}}, {"rms": {}}) == {
        "baseline": {"mode": "complete"},
        "rms": {},
    }
    first_recommendation = {
        "kind": "reprocess_analysis",
        "target_id": "an_1",
        "justification": "Primeira justificativa.",
    }
    revised_recommendation = {
        **first_recommendation,
        "justification": "Justificativa revisada.",
    }
    assert merge_recommendations(
        [first_recommendation], [revised_recommendation]
    ) == [revised_recommendation]


def test_classifier_falls_back_to_open_investigation_for_ambiguous_ticket():
    modality, intent = classify_ticket("A máquina está com um comportamento estranho.")
    assert modality.value == "investigar"
    assert intent == "open_investigation"


@pytest.mark.parametrize(
    ("verdict", "expected_node"),
    [
        ("approve", "writer"),
        ("revise_classification", "classifier"),
        ("revise_sources", "source_plan"),
        ("revise_investigation", "investigator"),
        ("escalate", "finalize"),
    ],
)
def test_each_review_verdict_routes_to_the_responsible_stage(
    workflow, verdict, expected_node
):
    runtime = RuntimeVerdict(
        verdict=verdict,
        safe=True,
        grounded=verdict not in {"revise_sources", "revise_investigation"},
        complete=verdict not in {"revise_sources", "revise_investigation"},
        suggested_intent="open_investigation"
        if verdict == "revise_classification"
        else None,
        missing_sources=["knowledge"] if verdict == "revise_sources" else [],
        unsupported_claims=["afirmação"] if verdict == "revise_investigation" else [],
    )

    assert workflow._route_runtime({"runtime_verdict": runtime}) == expected_node


@pytest.mark.parametrize(
    "verdict",
    ["revise_classification", "revise_sources", "revise_investigation"],
)
def test_non_actionable_revision_never_repeats_an_agent(workflow, verdict):
    runtime = RuntimeVerdict(
        verdict=verdict,
        safe=True,
        grounded=False,
        complete=False,
    )

    assert workflow._route_runtime({"runtime_verdict": runtime}) == "finalize"


@pytest.mark.asyncio
async def test_unverified_objection_replaces_report_with_validated_local_fallback(
    workflow, monkeypatch
):
    original = InvestigationReport(
        conclusion="Conclusão livre contestada.",
        evidence_ids=["ev_1"],
    )
    conservative = InvestigationReport(
        conclusion="Conclusão local conservadora.",
        evidence_ids=["ev_1"],
    )

    async def advisory_objection(*args, **kwargs):
        del args, kwargs
        return RuntimeVerdict(
            verdict="approve",
            safe=True,
            grounded=True,
            complete=True,
            safe_fallback_required=True,
            reasons=["Objeção plausível, mas não verificável."],
        ), AgentEvent(
            role="judge",
            model="judge-model",
            status="completed",
            summary="Parecer consultivo.",
        )

    monkeypatch.setattr(workflow_module, "review_with_llm", advisory_objection)
    monkeypatch.setattr(workflow_module, "fallback_report", lambda state: conservative)
    monkeypatch.setattr(
        workflow_module,
        "deterministic_review",
        lambda state, report: RuntimeVerdict(
            verdict="approve",
            safe=True,
            grounded=True,
            complete=True,
        ),
    )

    update = await workflow._reviewer(
        {
            "investigation": original,
            "recommendations": [],
            "hypotheses": [],
            "decisions": [],
            "review_history": [],
            "review_revision_count": 0,
        }
    )

    assert update["runtime_verdict"].verdict == "approve"
    assert update["investigation"] == conservative
    assert update["rejected_report"] == original
    assert update["review_feedback"] is None
    assert update["review_revision_count"] == 0


@pytest.mark.asyncio
async def test_writer_semantic_drift_uses_local_response_without_another_llm_call(
    workflow, monkeypatch
):
    approved = InvestigationReport(
        conclusion="Os valores atuais são compatíveis com a ausência de insight.",
        evidence_ids=["ev_1"],
    )
    calls = 0

    async def drifting_writer(*args, **kwargs):
        nonlocal calls
        del args, kwargs
        calls += 1
        return DraftResponse(
            summary="O equipamento está em condição normal e sem anomalia.",
            explanation=["Os dados de qualidade são adequados."],
            evidence_ids=["ev_1"],
        ), AgentEvent(
            role="writer",
            model="writer-model",
            status="completed",
            summary="Redação concluída.",
        )

    monkeypatch.setattr(workflow_module, "write_with_llm", drifting_writer)
    update = await workflow._writer(
        {
            "investigation": approved,
            "runtime_verdict": RuntimeVerdict(
                verdict="approve",
                safe=True,
                grounded=True,
                complete=True,
            ),
            "evidence": [],
            "gaps": [],
        }
    )

    assert calls == 1
    assert update["draft"].summary == approved.conclusion
    assert update["agent_events"][0].status == "fallback"
    assert update["agent_events"][0].failure_reason == "writer_claim_drift"
    assert update["final_response_valid"] is True


@pytest.mark.asyncio
async def test_writer_schema_error_uses_local_fallback_without_failing_run(
    settings, workflow, monkeypatch
):
    approved = InvestigationReport(
        conclusion="A alteração proposta ainda depende de aprovação humana.",
        evidence_ids=["ev_1"],
    )
    fallback = DraftResponse(
        summary=approved.conclusion,
        explanation=["O relatório não possui hipótese confirmada com segurança."],
        evidence_ids=["ev_1"],
    )

    async def invalid_writer(*args, **kwargs):
        del args, kwargs
        return fallback, AgentEvent(
            role="writer",
            model=settings.writer_model or "writer-model",
            status="fallback",
            summary="Redação local usada porque a saída violou o schema.",
            error="ValidationError: explanation.5 deveria ser string",
            failure_stage="schema",
            failure_reason="schema_validation_failed",
        )

    monkeypatch.setattr(workflow_module, "write_with_llm", invalid_writer)
    update = await workflow._writer(
        {
            "investigation": approved,
            "runtime_verdict": RuntimeVerdict(
                verdict="approve",
                safe=True,
                grounded=True,
                complete=True,
            ),
            "evidence": [],
            "gaps": [],
        }
    )

    assert update["draft"].summary == approved.conclusion
    assert update["final_response_valid"] is True
    assert update["agent_events"][0].status == "fallback"
    assert update["agent_events"][0].failure_reason == "schema_validation_failed"


@pytest.mark.asyncio
async def test_one_review_can_replace_rejected_outputs_and_second_rejection_escalates(
    settings, workflow, monkeypatch
):
    requested = RuntimeVerdict(
        verdict="revise_investigation",
        safe=True,
        grounded=False,
        complete=False,
        unsupported_claims=["A conclusão excede a evidência."],
        reasons=["Refaça somente a síntese."],
    )

    async def request_revision(*args, **kwargs):
        del args, kwargs
        return requested, AgentEvent(
            role="judge",
            model="judge-model",
            status="completed",
            summary="Correção solicitada.",
        )

    monkeypatch.setattr(workflow_module, "review_with_llm", request_revision)
    report = InvestigationReport(
        conclusion="Conclusão rejeitada.",
        evidence_ids=["ev_1"],
        hypotheses=[
            InvestigationHypothesis(
                statement="Hipótese rejeitada.",
                status="supported",
                evidence_ids=["ev_1"],
            )
        ],
        recommendation=ActionRecommendation(
            kind="inspect_asset",
            justification="Recomendação antiga.",
        ),
    )
    base = {
        "investigation": report,
        "recommendations": [report.recommendation],
        "hypotheses": ["Hipótese rejeitada."],
        "decisions": [],
        "review_history": [],
        "review_revision_count": 0,
    }

    first = await workflow._reviewer(base)
    assert first["runtime_verdict"].verdict == "revise_investigation"
    assert first["review_revision_count"] == 1
    assert first["investigation"] is None
    assert first["rejected_report"] == report
    assert first["recommendations"] == []
    assert first["hypotheses"] == []

    second = await workflow._reviewer(
        {
            **base,
            "review_revision_count": 1,
            "review_history": first["review_history"],
        }
    )
    assert second["runtime_verdict"].verdict == "escalate"
    assert "Limite de uma correção" in second["runtime_verdict"].reasons[-1]


@pytest.mark.asyncio
async def test_escalation_marks_rejected_findings_as_preliminary(settings):
    workflow = AgentWorkflow(settings)
    report = InvestigationReport(
        conclusion="Conclusão contestada.",
        evidence_ids=["ev_1"],
        hypotheses=[
            InvestigationHypothesis(
                statement="Hipótese contestada.",
                status="supported",
                evidence_ids=["ev_1"],
            )
        ],
    )
    update = await workflow._finalize(
        {
            "runtime_verdict": RuntimeVerdict(
                verdict="escalate",
                safe=True,
                grounded=False,
                complete=False,
                unsupported_claims=["Hipótese contestada."],
                reasons=["O juiz rejeitou a hipótese."],
            ),
            "investigation": report,
            "intent": "open_investigation",
            "ticket": "Explique o caso.",
            "user_id": "usr",
            "asset_id": "asset",
            "recommendations": [],
            "evidence": [],
            "gaps": [],
            "conflicts": [],
            "decisions": [],
        }
    )

    escalation = update["escalation"]
    assert escalation.findings[0].status == "open"
    assert escalation.findings[0].statement.startswith("Achado preliminar/contestado:")
    assert escalation.review_reasons == ["O juiz rejeitou a hipótese."]


@pytest.mark.asyncio
async def test_explicit_escalation_summary_uses_the_customer_request_not_a_fake_objection(
    settings,
):
    workflow = AgentWorkflow(settings)
    report = InvestigationReport(
        conclusion="O cliente solicitou avaliação humana.",
        evidence_ids=["ev_1"],
        needs_human=True,
    )
    update = await workflow._finalize(
        {
            "runtime_verdict": RuntimeVerdict(
                verdict="escalate",
                safe=True,
                grounded=True,
                complete=True,
                reasons=["Encaminhamento humano solicitado."],
            ),
            "investigation": report,
            "intent": "explicit_escalation",
            "ticket": "Encaminhe para engenharia sem resposta automática.",
            "user_id": "usr",
            "asset_id": "asset",
            "recommendations": [],
            "evidence": [],
            "gaps": [],
            "conflicts": [],
            "decisions": [],
        }
    )

    escalation = update["escalation"]
    assert "solicitou encaminhamento à engenharia" in escalation.summary
    assert "avaliação humana" in escalation.summary
    assert "juiz encontrou" not in escalation.summary


@pytest.mark.asyncio
async def test_native_sqlite_checkpoint_resumes_in_a_new_workflow(settings, workflow):
    case = next(item for item in CASES if item["ticket_id"] == "TKT-CTX-02")
    state = AgentState(
        run_id="test_resume",
        thread_id="thread_resume_native_sqlite",
        case_id=case["id"],
        asset_id=case["asset_id"],
        user_id=case["user_id"],
        seed="complete",
        gate_enabled=True,
        ticket=case["message"],
    )

    first_process = AgentWorkflow(settings, workflow.client_factory)
    paused = await first_process.pause_after(state, "classifier")
    assert paused.current_stage == "classifier"
    history_before = await first_process.checkpoint_history(state.thread_id)
    assert history_before
    assert history_before[0]["next"] == ["source_plan"]

    resumed_nodes: list[str] = []
    second_process = AgentWorkflow(settings, workflow.client_factory)
    final, result = await second_process.run(
        state,
        lambda node, _: resumed_nodes.append(node),
        resume=True,
    )

    assert result.status.value == "completed"
    assert final.current_stage == "completed"
    assert "context" not in resumed_nodes
    assert "classifier" not in resumed_nodes
    assert resumed_nodes[0] == "source_plan"
    assert len(await second_process.checkpoint_history(state.thread_id)) > len(history_before)
