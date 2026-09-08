import pytest
from pydantic import ValidationError

from tractian_agent.domain.models import (
    EnvelopeMode,
    InvestigationPlan,
    NewInvestigationPlan,
    QueryEnvelope,
    RuntimeVerdict,
)


def test_query_envelope_preserves_degraded_mode_notes_and_data():
    envelope = QueryEnvelope(
        mode=EnvelopeMode.PARTIAL,
        data={"asset_id": "asset_1", "present": True},
        notes="campo x ausente",
    )
    assert envelope.mode == EnvelopeMode.PARTIAL
    assert envelope.data["present"] is True
    assert envelope.notes == "campo x ausente"


def test_runtime_verdict_is_structured():
    with pytest.raises(ValidationError):
        RuntimeVerdict(
            verdict="talvez",
            safe=True,
            grounded=True,
            complete=True,
        )


@pytest.mark.parametrize(
    ("legacy", "normalized"),
    [("rewrite", "revise_investigation"), ("investigate_more", "revise_sources")],
)
def test_legacy_v5_v6_verdicts_remain_readable(legacy, normalized):
    verdict = RuntimeVerdict(
        verdict=legacy,
        safe=True,
        grounded=False,
        complete=False,
    )

    assert verdict.verdict == normalized


def test_inconsistent_approve_is_normalized_before_it_can_release_a_response():
    verdict = RuntimeVerdict(
        verdict="approve",
        safe=True,
        grounded=False,
        complete=True,
        unsupported_claims=["Afirmação sem suporte."],
    )

    assert verdict.verdict == "revise_investigation"


def test_new_plan_rejects_unknown_status_but_legacy_checkpoint_remains_readable():
    with pytest.raises(ValidationError):
        NewInvestigationPlan(analysis_status="finished")

    assert InvestigationPlan(analysis_status="finished").analysis_status == "finished"
