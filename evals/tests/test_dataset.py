from __future__ import annotations

import json
from collections import defaultdict

from scripts.build_eval_dataset import OUTPUT, build


def test_expanded_dataset_has_grouped_splits_and_separate_gabarito():
    inputs, expected, manifest = build()

    assert manifest["case_count"] == 111
    assert manifest["scenario_count"] == 37
    assert manifest["source_inventory"] == {
        "assets": 26,
        "analyses": 24,
        "abnormal_analyses": 10,
        "healthy_analyses": 14,
        "baselines": 26,
        "rms_samples": 775,
        "spectra": 25,
        "data_quality_records": 26,
        "knowledge_documents": 5,
        "model_versions": 1,
    }
    assert manifest["splits"] == {
        "development": {"cases": 60, "scenarios": 20, "assets": 15},
        "validation": {"cases": 27, "scenarios": 9, "assets": 5},
        "test": {"cases": 24, "scenarios": 8, "assets": 5},
    }
    assert {item["id"] for item in inputs} == {item["id"] for item in expected}
    assert all(not any(key.startswith("expected_") for key in item) for item in inputs)
    assert all("expected_path" in item and "expected_decision" in item for item in expected)

    splits_by_asset: dict[str, set[str]] = defaultdict(set)
    splits_by_scenario: dict[str, set[str]] = defaultdict(set)
    variants_by_scenario: dict[str, set[int]] = defaultdict(set)
    for case in inputs:
        splits_by_asset[case["asset_id"]].add(case["split"])
        splits_by_scenario[case["scenario_id"]].add(case["split"])
        variants_by_scenario[case["scenario_id"]].add(case["variant"])

    assert all(len(splits) == 1 for splits in splits_by_asset.values())
    assert all(len(splits) == 1 for splits in splits_by_scenario.values())
    assert all(variants == {1, 2, 3} for variants in variants_by_scenario.values())


def test_versioned_files_match_the_generator():
    inputs, expected, manifest = build()

    assert json.loads((OUTPUT / "inputs.json").read_text(encoding="utf-8")) == inputs
    assert json.loads((OUTPUT / "expected.json").read_text(encoding="utf-8")) == expected
    assert json.loads((OUTPUT / "manifest.json").read_text(encoding="utf-8")) == manifest
