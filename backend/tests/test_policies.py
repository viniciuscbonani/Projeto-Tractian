import pytest

from tractian_agent.domain.models import (
    ConflictRecord,
    EnvelopeMode,
    QueryEnvelope,
)
from tractian_agent.domain.policies import (
    resolve_conflict,
    sufficiency_gate,
)


@pytest.mark.parametrize(
    ("mode", "data", "expected"),
    [
        (EnvelopeMode.COMPLETE, {"state": "established"}, True),
        (EnvelopeMode.PARTIAL, {"state": "established"}, True),
        (EnvelopeMode.PARTIAL, {}, False),
        (EnvelopeMode.INCONCLUSIVE, {"state": "established"}, False),
        (EnvelopeMode.UNAVAILABLE, {}, False),
    ],
)
def test_sufficiency_by_mode_and_decisive_fields(mode, data, expected):
    gate = sufficiency_gate(
        {"baseline": QueryEnvelope(mode=mode, data=data)},
        {"baseline": ["state"]},
        [],
    )
    assert gate.passed is expected


def test_unresolved_conflict_blocks_sufficiency():
    conflict = ConflictRecord(
        topic="diagnóstico",
        sources=["a", "b"],
        resolved=False,
        rule="unresolved_real_divergence",
    )
    gate = sufficiency_gate({}, {}, [conflict])
    assert gate.passed is False
    assert "conflict:diagnóstico" in gate.missing


def test_informational_conflict_is_exposed_without_blocking_comparison():
    conflict = ConflictRecord(
        topic="diagnósticos divergentes",
        sources=["imbalance", "looseness"],
        resolved=False,
        rule="unresolved_real_divergence",
        impact="informational",
    )

    gate = sufficiency_gate({}, {}, [conflict])

    assert gate.passed is True
    assert gate.missing == []
    assert any("preservadas" in reason for reason in gate.reasons)


def test_empty_analysis_list_does_not_satisfy_required_details():
    gate = sufficiency_gate(
        {"analyses": QueryEnvelope(mode=EnvelopeMode.COMPLETE, data={"analyses": []})},
        {"analyses": ["analyses.0.id"]},
        [],
    )

    assert gate.passed is False
    assert "field:analyses.analyses.0.id" in gate.missing


@pytest.mark.parametrize(
    ("arguments", "rule", "resolved"),
    [
        (
            {"same_instant": False, "dedicated_source": None, "technical_support": None},
            "temporal_alignment",
            True,
        ),
        (
            {"same_instant": True, "dedicated_source": "spectrum", "technical_support": None},
            "dedicated_endpoint",
            True,
        ),
        (
            {
                "same_instant": True,
                "dedicated_source": None,
                "technical_support": "Espectro favorece folga.",
            },
            "technical_evidence",
            True,
        ),
        (
            {"same_instant": True, "dedicated_source": None, "technical_support": None},
            "unresolved_real_divergence",
            False,
        ),
    ],
)
def test_conflict_resolution_policy(arguments, rule, resolved):
    conflict = resolve_conflict("diagnóstico", ["a", "b"], **arguments)
    assert conflict.rule == rule
    assert conflict.resolved is resolved
