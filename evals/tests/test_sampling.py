from __future__ import annotations

import pytest

from evals.runners.benchmark import sample_cases_by_scenario, select_case_by_id


def cases() -> list[dict]:
    return [
        {
            "id": f"scenario-{scenario}-v{variant}",
            "ticket_id": f"EVAL-{scenario}-{variant}",
            "scenario_id": f"scenario-{scenario}",
            "variant": variant,
        }
        for scenario in range(1, 7)
        for variant in range(1, 4)
    ]


def test_sampling_is_reproducible_and_uses_distinct_scenarios():
    first = sample_cases_by_scenario(cases(), sample_size=4, sample_seed=17)
    repeated = sample_cases_by_scenario(
        list(reversed(cases())), sample_size=4, sample_seed=17
    )

    assert [case["id"] for case in first] == [case["id"] for case in repeated]
    assert len({case["scenario_id"] for case in first}) == 4


def test_sampling_seed_changes_the_selection():
    first = sample_cases_by_scenario(cases(), sample_size=4, sample_seed=1)
    second = sample_cases_by_scenario(cases(), sample_size=4, sample_seed=2)

    assert [case["id"] for case in first] != [case["id"] for case in second]


def test_sampling_rejects_more_cases_than_available_scenarios():
    with pytest.raises(ValueError, match="excede os 6 cenários"):
        sample_cases_by_scenario(cases(), sample_size=7, sample_seed=1)


@pytest.mark.parametrize("identifier", ["scenario-2-v3", "EVAL-2-3", "eval-2-3"])
def test_single_case_selection_accepts_internal_or_readable_id(identifier):
    selected = select_case_by_id(cases(), identifier)

    assert [item["id"] for item in selected] == ["scenario-2-v3"]


def test_single_case_selection_rejects_unknown_id():
    with pytest.raises(ValueError, match="Caso não encontrado"):
        select_case_by_id(cases(), "EVAL-404")
