from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

import tractian_agent.agents.llm as llm_module
import tractian_agent.agents.multiagent as multiagent_module
from tractian_agent.agents.llm import structured_call
from tractian_agent.agents.multiagent import (
    ClassificationOutput,
    _factual_context_for_llm,
    _safe_queries,
    classify_with_llm,
    fallback_plan,
    plan_with_llm,
    review_with_llm,
    synthesize_with_llm,
)
from tractian_agent.domain.models import (
    ActionRecommendation,
    AgentEvent,
    EnvelopeMode,
    Evidence,
    InvestigationHypothesis,
    InvestigationPlan,
    InvestigationReport,
    RuntimeVerdict,
)


class ExampleOutput(BaseModel):
    answer: str


def test_classifier_schema_only_accepts_canonical_intents():
    intent_schema = ClassificationOutput.model_json_schema()["properties"]["intent"]

    assert "rms_without_insight" in intent_schema["enum"]
    assert "possible_false_positive" in intent_schema["enum"]
    assert "request_diagnosis" not in intent_schema["enum"]


def test_electrical_plan_uses_a_query_that_matches_the_knowledge_catalog():
    plan = fallback_plan("electrical_or_mechanical")

    assert plan.knowledge_queries == ["eletrica"]


def test_literal_search_queries_are_reduced_to_distinct_searchable_terms():
    assert _safe_queries(
        [
            "Motor de mesa BPFO 76",
            "Criticidade motor indução",
            "BPFO 76 8 Hz motor",
        ],
        3,
    ) == ["BPFO", "Criticidade"]
    assert _safe_queries(
        [
            "procedimento de rolamento motor indução",
            "validação torque baseline motor",
            "reaprendizado baseline refiner",
        ],
        3,
    ) == ["procedimento", "torque", "reaprendizado"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ticket", "model_intent", "expected_intent"),
    [
        (
            "Preciso do procedimento de rolamento, torque e reaprendizado do baseline.",
            "request_retraining",
            "bearing_procedure",
        ),
        (
            "Não quero resposta automática. Encaminhe a análise para engenharia.",
            "request_specialist",
            "explicit_escalation",
        ),
    ],
)
async def test_classifier_contract_corrects_composite_procedure_and_handoff(
    settings, monkeypatch, ticket, model_intent, expected_intent
):
    async def fake_structured_call(*_, **__):
        return ClassificationOutput(
            modality="recomendar",
            intent=model_intent,
            justification="Classificação do modelo.",
        ), AgentEvent(
            role="classifier",
            model="test-model",
            status="completed",
            summary="ok",
        )

    monkeypatch.setattr(multiagent_module, "structured_call", fake_structured_call)

    modality, intent, reason, _ = await classify_with_llm(settings, ticket)

    assert intent == expected_intent
    assert "ajustado pela política" in reason
    assert modality.value == (
        "contextualizar" if expected_intent == "bearing_procedure" else "recomendar"
    )


@pytest.mark.asyncio
async def test_unconfigured_model_records_structured_fallback_reason(settings):
    output, event = await structured_call(
        settings,
        role="classifier",
        model=None,
        schema=ExampleOutput,
        system_prompt="Teste.",
        payload={},
        max_tokens=10,
    )

    assert output is None
    assert event.failure_stage == "configuration"
    assert event.failure_reason == "model_not_configured"
    assert event.attempts == 0
    assert event.token_usage_complete is True


@pytest.mark.asyncio
async def test_structured_call_uses_the_role_model_and_serializes_evidence(settings, monkeypatch):
    captured: dict = {}

    class StubClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, path, json):
            captured["path"] = path
            captured["request"] = json
            request = httpx.Request("POST", f"http://provider{path}")
            return httpx.Response(
                200,
                request=request,
                json={
                    "choices": [{"message": {"content": '{"answer":"ok"}'}}],
                    "usage": {
                        "prompt_tokens": 40,
                        "completion_tokens": 5,
                        "total_tokens": 45,
                    },
                },
            )

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", StubClient)
    configured = settings.model_copy(
        update={
            "llm_base_url": "http://provider",
            "llm_api_key": "secret",
            "llm_classifier_model": "small-classifier",
            "llm_investigator_model": "strong-investigator",
            "llm_judge_model": "strong-judge",
            "llm_writer_model": "small-writer",
        }
    )
    evidence = Evidence(
        id="ev_1",
        claim="Desvio confirmado.",
        source_event_id="tool_1",
        source_path="/assets/a/rms",
        fields=["samples"],
        mode=EnvelopeMode.COMPLETE,
    )

    output, event = await structured_call(
        configured,
        role="classifier",
        model=configured.classifier_model,
        schema=ExampleOutput,
        system_prompt="Responda em JSON.",
        payload={"evidence": evidence},
        max_tokens=100,
    )

    assert output == ExampleOutput(answer="ok")
    assert event.model == "small-classifier"
    assert event.prompt_tokens == 40
    assert event.completion_tokens == 5
    assert event.total_tokens == 45
    assert captured["request"]["model"] == "small-classifier"
    serialized = json.loads(captured["request"]["messages"][1]["content"])
    assert serialized["evidence"]["id"] == "ev_1"


@pytest.mark.asyncio
async def test_structured_call_retries_json_object_when_provider_rejects_schema(
    settings, monkeypatch
):
    requests: list[dict] = []

    class StubClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, path, json):
            requests.append(json.copy())
            request = httpx.Request("POST", f"http://provider{path}")
            if len(requests) == 1:
                return httpx.Response(405, request=request, text="json_schema unsupported")
            return httpx.Response(
                200,
                request=request,
                json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]},
            )

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", StubClient)
    configured = settings.model_copy(
        update={"llm_base_url": "http://provider", "llm_api_key": "secret"}
    )

    output, event = await structured_call(
        configured,
        role="writer",
        model="ibm-granite/granite-4.2-8b:fastest",
        schema=ExampleOutput,
        system_prompt="Responda em JSON.",
        payload={"question": "teste"},
        max_tokens=100,
    )

    assert output == ExampleOutput(answer="ok")
    assert event.status == "completed"
    assert len(requests) == 2
    assert requests[0]["response_format"]["type"] == "json_schema"
    assert requests[1]["response_format"] == {"type": "json_object"}
    assert "JSON" in requests[0]["messages"][0]["content"]
    assert "JSON Schema" in requests[1]["messages"][0]["content"]
    assert '"answer"' in requests[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_structured_call_retries_temporary_provider_unavailability(
    settings, monkeypatch
):
    attempts = 0

    class StubClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, path, json):
            nonlocal attempts
            del json
            attempts += 1
            request = httpx.Request("POST", f"http://provider{path}")
            if attempts < 3:
                return httpx.Response(503, request=request, text="high demand")
            return httpx.Response(
                200,
                request=request,
                json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]},
            )

    async def no_wait(_: float):
        return None

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", StubClient)
    monkeypatch.setattr(llm_module.asyncio, "sleep", no_wait)
    configured = settings.model_copy(
        update={"llm_base_url": "http://provider", "llm_api_key": "secret"}
    )

    output, event = await structured_call(
        configured,
        role="judge",
        model="gemini-test",
        schema=ExampleOutput,
        system_prompt="Responda em JSON.",
        payload={"question": "teste"},
        max_tokens=100,
    )

    assert output == ExampleOutput(answer="ok")
    assert event.status == "completed"
    assert attempts == 3


@pytest.mark.asyncio
async def test_structured_call_honors_groq_retry_after_from_error_body(
    settings, monkeypatch
):
    attempts = 0
    waits: list[float] = []

    class StubClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, path, json):
            nonlocal attempts
            del json
            attempts += 1
            request = httpx.Request("POST", f"https://api.groq.com/openai/v1{path}")
            if attempts == 1:
                return httpx.Response(
                    429,
                    request=request,
                    json={
                        "error": {
                            "message": "Rate limit reached. Please try again in 17.895s."
                        }
                    },
                )
            return httpx.Response(
                200,
                request=request,
                json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]},
            )

    async def record_wait(seconds: float):
        waits.append(seconds)

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", StubClient)
    monkeypatch.setattr(llm_module.asyncio, "sleep", record_wait)
    configured = settings.model_copy(
        update={
            "llm_provider": "groq",
            "llm_base_url": "https://api.groq.com/openai/v1",
            "groq_api_key": "gsk_test",
        }
    )

    output, event = await structured_call(
        configured,
        role="judge",
        model="openai/gpt-oss-120b",
        schema=ExampleOutput,
        system_prompt="Revise a entrada.",
        payload={"question": "teste"},
        max_tokens=100,
    )

    assert output == ExampleOutput(answer="ok")
    assert event.status == "completed"
    assert attempts == 2
    assert waits == [pytest.approx(18.395)]


@pytest.mark.asyncio
async def test_structured_call_retries_one_timeout_before_failing_or_succeeding(
    settings, monkeypatch
):
    attempts = 0

    class StubClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, path, json):
            nonlocal attempts
            del json
            attempts += 1
            request = httpx.Request("POST", f"http://provider{path}")
            if attempts == 1:
                raise httpx.ReadTimeout("modelo demorou para responder", request=request)
            return httpx.Response(
                200,
                request=request,
                json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]},
            )

    async def no_wait(_: float):
        return None

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", StubClient)
    monkeypatch.setattr(llm_module.asyncio, "sleep", no_wait)
    configured = settings.model_copy(
        update={"llm_base_url": "http://provider", "llm_api_key": "secret"}
    )

    output, event = await structured_call(
        configured,
        role="investigator",
        model="gemini-test",
        schema=ExampleOutput,
        system_prompt="Responda em JSON.",
        payload={"question": "teste"},
        max_tokens=100,
    )

    assert output == ExampleOutput(answer="ok")
    assert event.status == "completed"
    assert attempts == 2


@pytest.mark.asyncio
async def test_structured_call_retries_truncated_json_with_a_larger_budget(
    settings, monkeypatch
):
    requests: list[dict] = []

    class StubClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, path, json):
            requests.append(json.copy())
            request = httpx.Request("POST", f"http://provider{path}")
            if len(requests) == 1:
                return httpx.Response(
                    200,
                    request=request,
                    json={
                        "choices": [
                            {
                                "finish_reason": "length",
                                "message": {"content": '{"answer":"resposta cortada'},
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                request=request,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": '{"answer":"ok"}'},
                        }
                    ]
                },
            )

    async def no_wait(_: float):
        return None

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", StubClient)
    monkeypatch.setattr(llm_module.asyncio, "sleep", no_wait)
    configured = settings.model_copy(
        update={"llm_base_url": "http://provider", "llm_api_key": "secret"}
    )

    output, event = await structured_call(
        configured,
        role="investigator",
        model="gemini-test",
        schema=ExampleOutput,
        system_prompt="Responda em JSON.",
        payload={"question": "teste"},
        max_tokens=100,
    )

    assert output == ExampleOutput(answer="ok")
    assert event.status == "completed"
    assert [item["max_tokens"] for item in requests] == [100, 1100]


@pytest.mark.asyncio
async def test_structured_call_disables_qwen38_thinking_for_short_structured_output(
    settings, monkeypatch
):
    captured: dict = {}

    class StubClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, path, json):
            captured.update(json)
            request = httpx.Request("POST", f"http://provider{path}")
            return httpx.Response(
                200,
                request=request,
                json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]},
            )

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", StubClient)
    configured = settings.model_copy(
        update={"llm_base_url": "http://provider", "llm_api_key": "secret"}
    )

    output, _ = await structured_call(
        configured,
        role="investigator",
        model="Qwen/Qwen3.8-27B:fastest",
        schema=ExampleOutput,
        system_prompt="Responda em JSON.",
        payload={"question": "teste"},
        max_tokens=100,
    )

    assert output == ExampleOutput(answer="ok")
    assert captured["chat_template_kwargs"] == {
        "enable_thinking": False,
        "preserve_thinking": False,
    }


@pytest.mark.asyncio
async def test_valid_llm_plan_is_not_silently_replaced_by_intent_rules(settings, monkeypatch):
    async def fake_structured_call(*_, **__):
        return (
            InvestigationPlan(
                tools=["knowledge", "spectrum"],
                required_tools=["knowledge"],
                knowledge_queries=["frequência", "BPFO"],
            ),
            AgentEvent(
                role="source_selector",
                model="test-model",
                status="completed",
                summary="Plano criado.",
            ),
        )

    monkeypatch.setattr(multiagent_module, "structured_call", fake_structured_call)

    plan, _ = await plan_with_llm(
        settings,
        {
            "ticket": "O que é BPFO?",
            "intent": "bpfo_definition",
            "asset": {},
        },
    )

    assert plan.knowledge_queries == ["frequência", "BPFO"]
    assert plan.tools == ["knowledge", "spectrum"]
    assert plan.required_tools == ["spectrum"]


def test_pipeline_signature_changes_with_models_and_pipeline_version(settings):
    first = settings.model_copy(
        update={
            "llm_classifier_model": "classifier-a",
            "llm_source_selector_model": "source-a",
            "llm_investigator_model": "investigator-a",
            "llm_judge_model": "judge-a",
            "llm_writer_model": "writer-a",
        }
    )
    changed_model = first.model_copy(update={"llm_judge_model": "judge-b"})
    changed_source_model = first.model_copy(update={"llm_source_selector_model": "source-b"})
    changed_rules = first.model_copy(update={"pipeline_version": "multiagent-report-v6"})
    changed_provider = first.model_copy(update={"llm_provider": "groq"})
    changed_limit = first.model_copy(update={"max_source_documents": 7})
    changed_analysis_limit = first.model_copy(update={"max_analysis_details": 7})
    changed_output_limit = first.model_copy(update={"llm_investigator_max_tokens": 900})

    assert first.pipeline_signature != changed_model.pipeline_signature
    assert first.pipeline_signature != changed_source_model.pipeline_signature
    assert first.pipeline_signature != changed_rules.pipeline_signature
    assert first.pipeline_signature != changed_provider.pipeline_signature
    assert first.pipeline_signature != changed_limit.pipeline_signature
    assert first.pipeline_signature != changed_analysis_limit.pipeline_signature
    assert first.pipeline_signature != changed_output_limit.pipeline_signature


@pytest.mark.asyncio
async def test_investigator_receives_rejected_report_feedback_and_primary_facts(settings, monkeypatch):
    captured = {}

    async def fake_structured_call(*_, **kwargs):
        captured.update(kwargs["payload"])
        return InvestigationReport(
            conclusion="A objeção foi considerada.",
            evidence_ids=["ev_1"],
            hypotheses=[],
        ), AgentEvent(
            role="investigator",
            model="model",
            status="completed",
            summary="ok",
        )

    monkeypatch.setattr(multiagent_module, "structured_call", fake_structured_call)
    feedback = RuntimeVerdict(
        verdict="revise_investigation",
        safe=True,
        grounded=True,
        complete=False,
        unsupported_claims=["Remova a afirmação de execução."],
    )
    rejected = InvestigationReport(conclusion="Uma ação foi executada.", evidence_ids=["ev_1"])
    state = {
        "ticket": "Explique.",
        "intent": "open_investigation",
        "evidence": [
            Evidence(
                id="ev_1",
                claim="Valor coletado.",
                source_event_id="tool_1",
                source_path="/assets/a/rms",
                fields=["samples"],
                mode=EnvelopeMode.COMPLETE,
            )
        ],
        "active_evidence_ids": ["ev_1"],
        "factual_context": [
            {"field": "samples", "value": [{"value": 2.0}]},
            {"field": "unit", "value": "mm/s"},
        ],
        "active_envelopes": {"rms": {"data": {"samples": [{"value": 2.0}]}}},
        "review_feedback": feedback,
        "rejected_report": rejected,
    }

    await synthesize_with_llm(settings, state)

    assert captured["review_feedback"] == feedback
    assert captured["rejected_report"] == rejected
    assert captured["factual_context"][0]["values"]["samples"][0]["value"] == 2.0
    assert captured["factual_context"][0]["values"]["unit"] == "mm/s"
    assert "active_envelopes" not in captured


@pytest.mark.asyncio
async def test_investigator_action_contract_is_owned_by_policy(settings, monkeypatch):
    captured = {}

    async def fake_structured_call(*_, **kwargs):
        captured.update(kwargs["payload"])
        return InvestigationReport(
            conclusion="A mudança solicitada depende de aprovação humana.",
            evidence_ids=["ev_1"],
            hypotheses=[],
            recommendation=ActionRecommendation(
                kind="update_asset",
                target_id="M428",
                params={"changes": {"criticality": "high"}},
                justification="Parâmetros incorretos gerados pelo modelo.",
            ),
        ), AgentEvent(
            role="investigator",
            model="model",
            status="completed",
            summary="ok",
        )

    monkeypatch.setattr(multiagent_module, "structured_call", fake_structured_call)
    state = {
        "ticket": "Mude a criticidade para média após aprovação.",
        "intent": "update_criticality",
        "asset_id": "asset_M428",
        "evidence": [
            Evidence(
                id="ev_1",
                claim="Ativo carregado.",
                source_event_id="tool_1",
                source_path="/assets/asset_M428",
                fields=["id", "criticality"],
                mode=EnvelopeMode.COMPLETE,
            )
        ],
        "active_evidence_ids": ["ev_1"],
    }

    result, event = await synthesize_with_llm(settings, state)

    expected = captured["required_recommendation"]
    assert expected["target_id"] == "asset_M428"
    assert expected["params"] == {"changes": {"criticality": "medium"}}
    assert result.recommendation is not None
    assert result.recommendation.model_dump(mode="json") == expected
    assert event.status == "completed"
    assert "normalizada pela política" in event.summary


@pytest.mark.asyncio
async def test_investigator_removes_formal_action_from_informational_report(
    settings, monkeypatch
):
    async def fake_structured_call(*_, **__):
        return InvestigationReport(
            conclusion="Consulte o catálogo do fabricante para obter o torque exato.",
            evidence_ids=["ev_1"],
            hypotheses=[],
            recommendation=ActionRecommendation(
                kind="collect_more_data",
                justification="Buscar o catálogo.",
            ),
        ), AgentEvent(
            role="investigator",
            model="model",
            status="completed",
            summary="ok",
        )

    monkeypatch.setattr(multiagent_module, "structured_call", fake_structured_call)
    state = {
        "ticket": "Qual é o procedimento e o torque?",
        "intent": "bearing_procedure",
        "evidence": [
            Evidence(
                id="ev_1",
                claim="Procedimento recuperado.",
                source_event_id="tool_1",
                source_path="/knowledge/kb_1",
                fields=["body"],
                mode=EnvelopeMode.COMPLETE,
            )
        ],
        "active_evidence_ids": ["ev_1"],
    }

    result, event = await synthesize_with_llm(settings, state)

    assert result.recommendation is None
    assert event.status == "completed"
    assert "normalizada pela política" in event.summary


@pytest.mark.asyncio
async def test_investigator_removes_open_hypothesis_asserted_in_conclusion(
    settings, monkeypatch
):
    async def fake_structured_call(*_, **__):
        return InvestigationReport(
            conclusion=(
                "O RMS medido foi 2.547 mm/s. Use o torque conforme o catálogo do fabricante. "
                "O torque deve ser verificado com torquímetro calibrado."
            ),
            evidence_ids=["ev_1"],
            hypotheses=[
                InvestigationHypothesis(
                    statement="O torque deve seguir o catálogo do fabricante.",
                    status="supported",
                    evidence_ids=["ev_1"],
                ),
                InvestigationHypothesis(
                    statement="O torque pode ser verificado com torquímetro calibrado.",
                    status="open",
                    evidence_ids=[],
                ),
            ],
        ), AgentEvent(
            role="investigator",
            model="model",
            status="completed",
            summary="ok",
        )

    monkeypatch.setattr(multiagent_module, "structured_call", fake_structured_call)
    state = {
        "ticket": "Qual é o procedimento e o torque?",
        "intent": "bearing_procedure",
        "evidence": [
            Evidence(
                id="ev_1",
                claim="Procedimento recuperado.",
                source_event_id="tool_1",
                source_path="/knowledge/kb_1",
                fields=["body"],
                mode=EnvelopeMode.COMPLETE,
            )
        ],
        "active_evidence_ids": ["ev_1"],
    }

    result, event = await synthesize_with_llm(settings, state)

    assert result.conclusion == (
        "O RMS medido foi 2.547 mm/s. Use o torque conforme o catálogo do fabricante."
    )
    assert "torquímetro calibrado" not in result.conclusion
    assert "hipótese aberta na conclusão" in event.summary


@pytest.mark.asyncio
async def test_investigator_neutralizes_quality_judgment_without_model_requirements(
    settings, monkeypatch
):
    async def fake_structured_call(*_, **__):
        return InvestigationReport(
            conclusion="A qualidade dos dados está adequada (completude 0.98 e SNR 18.2 dB).",
            evidence_ids=["ev_1"],
            hypotheses=[],
        ), AgentEvent(
            role="investigator", model="model", status="completed", summary="ok"
        )

    monkeypatch.setattr(multiagent_module, "structured_call", fake_structured_call)
    state = {
        "ticket": "Está tudo normal?",
        "intent": "open_investigation",
        "evidence": [
            Evidence(
                id="ev_1",
                claim="Qualidade consultada.",
                source_event_id="tool_1",
                source_path="/assets/asset_1/data-quality",
                fields=["completeness", "snr_db"],
                mode=EnvelopeMode.COMPLETE,
            )
        ],
        "active_evidence_ids": ["ev_1"],
    }

    result, event = await synthesize_with_llm(settings, state)

    assert "adequada" not in result.conclusion.lower()
    assert "indicadores de qualidade" in result.conclusion.lower()
    assert "juízo de qualidade" in event.summary


@pytest.mark.asyncio
async def test_judge_receives_additional_context_and_same_primary_facts(settings, monkeypatch):
    captured = {}

    async def fake_structured_call(*_, **kwargs):
        captured.update(kwargs["payload"])
        return RuntimeVerdict(
            verdict="approve",
            safe=True,
            grounded=True,
            complete=True,
        ), AgentEvent(role="judge", model="judge", status="completed", summary="ok")

    monkeypatch.setattr(multiagent_module, "structured_call", fake_structured_call)
    state = {
        "ticket": "Explique.",
        "additional_context": "A medição é posterior à manutenção.",
        "intent": "open_investigation",
        "evidence": [
            Evidence(
                id="ev_1",
                claim="Valor coletado.",
                source_event_id="tool_1",
                source_path="/assets/a/rms",
                fields=["samples"],
                mode=EnvelopeMode.COMPLETE,
            )
        ],
        "active_evidence_ids": ["ev_1"],
        "factual_context": [{"field": "samples", "value": [{"value": 2.0}]}],
        "gates": [{"gate": "sufficiency", "passed": True, "enabled": True}],
    }
    report = InvestigationReport(conclusion="O valor é 2.", evidence_ids=["ev_1"])

    await review_with_llm(settings, state, report)

    assert captured["additional_context"] == state["additional_context"]
    assert captured["factual_context"] == _factual_context_for_llm(state)


def test_groq_uses_its_own_api_key_and_enables_the_pipeline(settings):
    configured = settings.model_copy(
        update={
            "llm_provider": "groq",
            "llm_base_url": "https://api.groq.com/openai/v1",
            "llm_api_key": "stale-key-from-another-provider",
            "groq_api_key": "gsk_test",
            "llm_classifier_model": "openai/gpt-oss-20b",
            "llm_investigator_model": "openai/gpt-oss-120b",
            "llm_judge_model": "openai/gpt-oss-120b",
            "llm_writer_model": "openai/gpt-oss-20b",
        }
    )

    assert configured.effective_llm_api_key == "gsk_test"
    assert configured.uses_groq is True
    assert configured.llm_enabled is True


@pytest.mark.asyncio
async def test_groq_uses_best_effort_json_schema_and_groq_key(settings, monkeypatch):
    captured: dict = {}

    class StubClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, path, json):
            captured["request"] = json
            request = httpx.Request("POST", f"https://api.groq.com/openai/v1{path}")
            return httpx.Response(
                200,
                request=request,
                json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]},
            )

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", StubClient)
    configured = settings.model_copy(
        update={
            "llm_provider": "groq",
            "llm_base_url": "https://api.groq.com/openai/v1",
            "llm_api_key": "do-not-use",
            "groq_api_key": "gsk_test",
        }
    )

    output, event = await structured_call(
        configured,
        role="classifier",
        model="openai/gpt-oss-20b",
        schema=ExampleOutput,
        system_prompt="Responda em JSON.",
        payload={"question": "teste"},
        max_tokens=100,
    )

    assert output == ExampleOutput(answer="ok")
    assert event.status == "completed"
    assert captured["client"]["headers"]["Authorization"] == "Bearer gsk_test"
    assert captured["request"]["response_format"]["json_schema"]["strict"] is False
    assert captured["request"]["max_completion_tokens"] == 100
    assert "max_tokens" not in captured["request"]
    assert captured["request"]["reasoning_effort"] == "low"
    assert captured["request"]["include_reasoning"] is False


@pytest.mark.asyncio
async def test_groq_retries_json_generation_cut_off_with_more_tokens(settings, monkeypatch):
    requests: list[dict] = []

    class StubClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, path, json):
            requests.append(json.copy())
            request = httpx.Request("POST", f"https://api.groq.com/openai/v1{path}")
            if len(requests) == 1:
                return httpx.Response(
                    400,
                    request=request,
                    json={
                        "error": {
                            "code": "json_validate_failed",
                            "message": "Failed to generate JSON.",
                            "failed_generation": (
                                "max completion tokens reached before generating "
                                "a valid document"
                            ),
                        }
                    },
                )
            return httpx.Response(
                200,
                request=request,
                json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]},
            )

    async def no_wait(_: float):
        return None

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", StubClient)
    monkeypatch.setattr(llm_module.asyncio, "sleep", no_wait)
    configured = settings.model_copy(
        update={
            "llm_provider": "groq",
            "llm_base_url": "https://api.groq.com/openai/v1",
            "groq_api_key": "gsk_test",
        }
    )

    output, event = await structured_call(
        configured,
        role="classifier",
        model="openai/gpt-oss-20b",
        schema=ExampleOutput,
        system_prompt="Classifique a entrada.",
        payload={"question": "teste"},
        max_tokens=100,
    )

    assert output == ExampleOutput(answer="ok")
    assert event.status == "completed"
    assert [item["max_completion_tokens"] for item in requests] == [100, 1100]
    assert all(
        item["response_format"]["type"] == "json_schema" for item in requests
    )
