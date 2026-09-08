from __future__ import annotations

import json
import os
from typing import Any


def deepeval_available() -> bool:
    try:
        import deepeval  # noqa: F401
    except ImportError:
        return False
    return True


def evaluate_with_deepeval(
    case: dict[str, Any], result: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Executa relevância e fidelidade quando o extra e DEEPEVAL_MODEL estão configurados."""
    model = os.getenv("DEEPEVAL_MODEL")
    response = result.get("response")
    if not (model and deepeval_available() and isinstance(response, dict)):
        return None
    from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric
    from deepeval.test_case import LLMTestCase

    actual_output = " ".join(
        [response["summary"], *response["explanation"], *response["next_steps"]]
    )
    retrieval_context = [
        json.dumps(event["envelope"]["data"], ensure_ascii=False)
        for event in events
        if event.get("envelope") and event["envelope"].get("data")
    ]
    test_case = LLMTestCase(
        input=case["message"],
        actual_output=actual_output,
        retrieval_context=retrieval_context,
    )
    metrics = {
        "answer_relevancy": AnswerRelevancyMetric(threshold=0.7, model=model),
        "faithfulness": FaithfulnessMetric(threshold=0.7, model=model),
    }
    output: dict[str, Any] = {}
    for name, metric in metrics.items():
        metric.measure(test_case)
        output[name] = {"score": metric.score, "reason": metric.reason, "passed": metric.is_successful()}
    return output


def semantic_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Separa cobertura lexical esperada de avaliações semânticas opcionais."""
    evaluated = [row["deepeval"] for row in rows if row.get("deepeval")]
    return {
        "engine": "deepeval" if evaluated else "lexical_expected_terms",
        "expected_term_coverage": (
            sum(row["semantic_proxy"] for row in rows) / len(rows) if rows else 0
        ),
        "deepeval_cases": len(evaluated),
        "note": (
            "DeepEval executou relevância e fidelidade com o modelo configurado."
            if evaluated
            else (
                "Configure o extra evals e DEEPEVAL_MODEL para relevância/fidelidade; "
                "a cobertura lexical abaixo mede apenas termos esperados, não grounding semântico."
            )
        ),
    }
