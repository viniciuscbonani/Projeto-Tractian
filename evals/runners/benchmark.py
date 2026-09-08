from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tractian_agent.config import Settings
from tractian_agent.domain.models import AgentState
from tractian_agent.graph import AgentWorkflow

from evals.metrics.objective import evaluate_trace
from evals.metrics.semantic import evaluate_with_deepeval, semantic_status


async def execute_condition(
    cases: list[dict[str, Any]],
    *,
    gate_enabled: bool,
    industrial_url: str,
    seed: str,
    offline: bool = False,
    delay_between_cases: float = 0,
) -> list[dict[str, Any]]:
    settings = Settings(industrial_api_url=industrial_url, default_seed=seed)
    if offline:
        settings = settings.model_copy(
            update={
                "llm_base_url": None,
                "llm_api_key": None,
                "llm_model": None,
                "runtime_judge_model": None,
                "llm_classifier_model": None,
                "llm_source_selector_model": None,
                "llm_investigator_model": None,
                "llm_judge_model": None,
                "llm_writer_model": None,
            }
        )
    workflow = AgentWorkflow(settings)
    traces: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index:02d}/{len(cases)}] {case['ticket_id']} gate={'on' if gate_enabled else 'off'}")
        state = AgentState(
            run_id=f"eval_{'on' if gate_enabled else 'off'}_{case['id']}",
            thread_id=(
                f"eval_thread_{gate_enabled}_{case['id']}_{seed}_{settings.pipeline_signature}"
            ),
            case_id=case["id"],
            company_id=case["company_id"],
            asset_id=case["asset_id"],
            user_id=case["user_id"],
            seed=seed,
            gate_enabled=gate_enabled,
            ticket=case["message"],
        )
        started = perf_counter()
        try:
            final, result = await workflow.run(state)
            result_payload = result.model_dump(mode="json")
            # Metadado interno para medir o classificador. Não aparece na entrada do agente.
            result_payload["_actual_intent"] = final.intent
            traces.append(
                {
                    "case": case,
                    "result": result_payload,
                    "events": [event.model_dump(mode="json") for event in final.tool_events],
                    "technical_error": None,
                }
            )
        except Exception as exc:  # noqa: BLE001 - benchmark deve concluir os demais casos
            technical_error = f"{type(exc).__name__}: {exc}"
            partial = await workflow.latest_checkpoint(state.thread_id)
            partial_events = partial.tool_events if partial else []
            partial_agent_events = partial.agent_events if partial else []
            if hasattr(exc, "event"):
                partial_agent_events = [*partial_agent_events, exc.event]
            traces.append(
                {
                    "case": case,
                    "result": {
                        "status": "failed",
                        "metrics": {"duration_ms": (perf_counter() - started) * 1000},
                        "agent_events": [
                            event.model_dump(mode="json") for event in partial_agent_events
                        ],
                    },
                    "events": [event.model_dump(mode="json") for event in partial_events],
                    "technical_error": technical_error,
                }
            )
            readable_error = technical_error.replace("\n", " ")[:1000]
            print(f"  falha técnica: {readable_error}")
        if index < len(cases) and delay_between_cases > 0:
            print(f"  aguardando {delay_between_cases:g}s para respeitar o RPM do provedor")
            await asyncio.sleep(delay_between_cases)
    return traces


def apply_gabarito(
    traces: list[dict[str, Any]], expected_paths: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    # O gabarito entra somente aqui, após todas as respostas já terem sido produzidas.
    expected_by_id = {item["id"]: item for item in expected_paths}
    rows: list[dict[str, Any]] = []
    for trace in traces:
        row = evaluate_trace(
            trace["case"],
            expected_by_id[trace["case"]["id"]],
            trace["result"],
            trace["events"],
        )
        row["deepeval"] = evaluate_with_deepeval(
            trace["case"], trace["result"], trace["events"]
        )
        row["technical_error"] = trace.get("technical_error")
        rows.append(row)
    return rows


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = max(1, len(rows))
    agent_events = [event for row in rows for event in row["agent_events"]]

    def percentile(values: list[float], fraction: float) -> float:
        if not values:
            return 0
        ordered = sorted(values)
        index = round((len(ordered) - 1) * fraction)
        return ordered[index]

    def operational_metrics(role: str) -> dict[str, Any]:
        selected = [event for event in agent_events if event["role"] == role]
        latencies = [float(event["latency_ms"]) for event in selected]
        count = max(1, len(selected))
        known_total_tokens = [
            int(event["total_tokens"])
            for event in selected
            if event.get("total_tokens") is not None
        ]
        attempts = sum(int(event.get("attempts") or 0) for event in selected)
        measured_attempts = sum(
            int(event.get("attempts") or 0)
            for event in selected
            if event.get("token_usage_complete") is True
        )
        return {
            "calls": len(selected),
            "fallback_rate": sum(event["status"] == "fallback" for event in selected) / count,
            "failure_rate": sum(event["status"] == "failed" for event in selected) / count,
            "latency_p50_ms": percentile(latencies, 0.50),
            "latency_p95_ms": percentile(latencies, 0.95),
            "models": sorted(
                {str(event["model"]) for event in selected if event.get("model")}
            ),
            "prompt_tokens": sum(
                int(event["prompt_tokens"])
                for event in selected
                if event.get("prompt_tokens") is not None
            ),
            "completion_tokens": sum(
                int(event["completion_tokens"])
                for event in selected
                if event.get("completion_tokens") is not None
            ),
            "total_tokens": sum(known_total_tokens) if known_total_tokens else None,
            "attempts": attempts,
            "token_measurement_coverage": measured_attempts / attempts if attempts else None,
        }

    def bad_release(row: dict[str, Any]) -> bool:
        artifacts = row["artifacts"]
        if not isinstance(artifacts.get("response"), dict):
            return False
        verdict = artifacts.get("runtime_verdict") or {}
        gates = artifacts.get("gates") or []
        latest_gate = gates[-1] if gates else {}
        report = artifacts.get("investigation") or {}
        response = artifacts.get("response") or {}
        recommendations = artifacts.get("recommendations") or []
        response_ids = set(response.get("evidence_ids") or [])
        report_ids = set(report.get("evidence_ids") or [])
        public_text = " ".join(
            [
                response.get("summary", ""),
                *response.get("explanation", []),
                *response.get("next_steps", []),
                *response.get("limitations", []),
            ]
        )
        return bool(
            verdict.get("verdict") != "approve"
            or verdict.get("safe") is not True
            or verdict.get("grounded") is not True
            or verdict.get("complete") is not True
            or verdict.get("intent_aligned", True) is not True
            or verdict.get("recommendation_supported", True) is not True
            or verdict.get("missing_sources")
            or verdict.get("unsupported_claims")
            or (latest_gate.get("enabled", True) and latest_gate.get("passed") is not True)
            or artifacts.get("final_response_valid") is False
            or not response_ids
            or not response_ids.issubset(report_ids)
            or any(item.get("requires_human_approval") is not True for item in recommendations)
            or re.search(r"\b(?:ev|kb|an|asset|case|usr)_[a-z0-9_-]+\b", public_text, re.IGNORECASE)
        )

    fallback_events = sum(event["status"] == "fallback" for event in agent_events)
    token_values = [
        int(event["total_tokens"])
        for event in agent_events
        if event.get("total_tokens") is not None
    ]

    completed_rows = [row for row in rows if row["checks"]["completed"]]
    classifier_rows = [
        row for row in completed_rows if row.get("actual_intent") is not None
    ]
    decision_rows = [
        row for row in completed_rows if row.get("actual_decision") is not None
    ]
    summary = {
        "cases": len(rows),
        "completion_rate": sum(row["checks"]["completed"] for row in rows) / total,
        "objective_score": sum(row["objective_score"] for row in rows) / total,
        "classifier_intent_accuracy": sum(
            row["checks"]["classifier_intent"] for row in classifier_rows
        )
        / max(1, len(classifier_rows)),
        "classifier_evaluated_cases": len(classifier_rows),
        "decision_accuracy": sum(row["checks"]["decision"] for row in decision_rows)
        / max(1, len(decision_rows)),
        "decision_evaluated_cases": len(decision_rows),
        "required_tool_coverage": sum(row["required_tool_coverage"] for row in rows) / total,
        "schema_validity": sum(row["checks"]["schema"] for row in rows) / total,
        "mean_tool_calls": sum(row["tool_calls"] for row in rows) / total,
        "mean_duration_ms": sum(row["duration_ms"] for row in rows) / total,
        "llm_tokens": sum(token_values) if token_values else None,
        "estimated_llm_cost_usd": None,
        "fallback_events": fallback_events,
        "fallback_rate": fallback_events / max(1, len(agent_events)),
        "unsafe_mutations": sum(row["unsafe_mutations"] for row in rows),
        "forbidden_tool_calls": sum(row["forbidden_tool_calls"] for row in rows),
        "argument_errors": (
            sum(row["argument_errors"] for row in rows if row.get("argument_errors") is not None)
            if any(row.get("argument_errors") is not None for row in rows)
            else None
        ),
        "empty_searches": sum(row.get("empty_searches", 0) for row in rows),
        "released_responses": sum(
            isinstance(row["artifacts"].get("response"), dict) for row in rows
        ),
        "revisions_requested": sum(
            any(
                item.get("verdict", "").startswith("revise_")
                for item in row["artifacts"].get("review_history", [])
            )
            for row in rows
        ),
        "revisions_resolved": sum(
            len(row["artifacts"].get("review_history", [])) > 1
            and (row["artifacts"].get("runtime_verdict") or {}).get("verdict") == "approve"
            for row in rows
        ),
        "judge_objections": sum(
            len(item.get("advisory_objections", []))
            for row in rows
            for item in row["artifacts"].get("review_history", [])
        ),
        "judge_objection_cases": sum(
            any(
                item.get("advisory_objections")
                for item in row["artifacts"].get("review_history", [])
            )
            for row in rows
        ),
        "conservative_containments": sum(
            any(
                item.get("safe_fallback_required") is True
                for item in row["artifacts"].get("review_history", [])
            )
            and (row["artifacts"].get("runtime_verdict") or {}).get("verdict")
            == "approve"
            for row in rows
        ),
        "technical_failures": sum(bool(row.get("technical_error")) for row in rows),
        "unsafe_answer_terms": sum(not row["checks"]["answer_safety"] for row in rows),
        "protective_escalations": sum(
            row["actual_decision"] == "escalar" and row["expected_decision"] == "escalar"
            for row in rows
        ),
        "unnecessary_escalations": sum(
            row["actual_decision"] == "escalar" and row["expected_decision"] != "escalar"
            for row in rows
        ),
        "unwarranted_confidence": sum(
            row["actual_decision"] is not None
            and row["actual_decision"] != "escalar"
            and row["expected_decision"] == "escalar"
            for row in rows
        ),
        "runtime_bad_releases": sum(bad_release(row) for row in rows),
        "semantic": semantic_status(rows),
    }
    summary["by_agent"] = {
        "classifier": {
            **operational_metrics("classifier"),
            "intent_accuracy": summary["classifier_intent_accuracy"],
        },
        "source_selector": {
            **operational_metrics("source_selector"),
            "required_tool_coverage": summary["required_tool_coverage"],
        },
        "investigator": {
            **operational_metrics("investigator"),
            "required_tool_coverage": summary["required_tool_coverage"],
        },
        "judge": {
            **operational_metrics("judge"),
            "decision_accuracy": summary["decision_accuracy"],
            "objections": summary["judge_objections"],
            "objection_cases": summary["judge_objection_cases"],
            "conservative_containments": summary["conservative_containments"],
            "unnecessary_escalations": summary["unnecessary_escalations"],
            "unwarranted_confidence": summary["unwarranted_confidence"],
        },
        "writer": {
            **operational_metrics("writer"),
            "expected_term_coverage": summary["semantic"]["expected_term_coverage"],
            "unsafe_answer_terms": summary["unsafe_answer_terms"],
        },
    }
    return summary


def dataset_paths(dataset: str) -> tuple[Path, Path]:
    if dataset == "regression":
        return (
            ROOT / "api-tractian" / "agent-input" / "cases.json",
            ROOT / "api-tractian" / "eval" / "expected-paths.json",
        )
    base = ROOT / "evals" / "datasets" / "v1"
    return base / "inputs.json", base / "expected.json"


def sample_cases_by_scenario(
    cases: list[dict[str, Any]], *, sample_size: int, sample_seed: int
) -> list[dict[str, Any]]:
    """Seleciona cenários distintos e uma variante por cenário de forma reproduzível."""
    if sample_size < 1:
        raise ValueError("--sample-size deve ser maior que zero.")

    by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        scenario_id = case.get("scenario_id")
        if not scenario_id:
            raise ValueError("A amostragem requer scenario_id em todos os casos.")
        by_scenario[str(scenario_id)].append(case)

    scenario_ids = sorted(by_scenario)
    if sample_size > len(scenario_ids):
        raise ValueError(
            f"--sample-size={sample_size} excede os {len(scenario_ids)} cenários disponíveis."
        )

    rng = random.Random(sample_seed)
    selected_scenarios = rng.sample(scenario_ids, sample_size)
    selected_cases: list[dict[str, Any]] = []
    for scenario_id in selected_scenarios:
        variants = sorted(
            by_scenario[scenario_id],
            key=lambda case: (int(case.get("variant", 0)), str(case["id"])),
        )
        selected_cases.append(rng.choice(variants))
    return selected_cases


def select_case_by_id(cases: list[dict[str, Any]], identifier: str) -> list[dict[str, Any]]:
    """Seleciona um caso exato pelo ID interno ou pelo ticket legível."""

    normalized = identifier.strip().casefold()
    selected = [
        case
        for case in cases
        if normalized
        in {
            str(case.get("id", "")).casefold(),
            str(case.get("ticket_id", "")).casefold(),
        }
    ]
    if not selected:
        raise ValueError(f"Caso não encontrado no dataset/split: {identifier}.")
    if len(selected) > 1:
        raise ValueError(f"Identificador de caso ambíguo: {identifier}.")
    return selected


async def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    configured_settings = Settings(
        industrial_api_url=args.industrial_url,
        default_seed=args.seed,
    )
    if not args.offline and not configured_settings.llm_enabled:
        raise RuntimeError(
            "LLMs não estão habilitados. Confira LLM_PROVIDER, a chave do provedor, "
            "LLM_BASE_URL e os cinco papéis LLM_*_MODEL no .env."
        )
    if args.offline:
        print("LLM: modo offline; somente contingências locais serão avaliadas.")
    else:
        print(
            "LLM: "
            f"provider={configured_settings.llm_provider} "
            f"classifier={configured_settings.classifier_model} "
            f"source_selector={configured_settings.source_selector_model} "
            f"investigator={configured_settings.investigator_model} "
            f"judge={configured_settings.judge_model} "
            f"writer={configured_settings.writer_model}"
        )
    cases_path, expected_path = dataset_paths(args.dataset)
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if args.split != "all":
        if args.dataset == "regression":
            raise ValueError("--split só pode ser usado com --dataset expanded.")
        cases = [case for case in cases if case["split"] == args.split]
    if args.variant is not None:
        if args.dataset == "regression":
            raise ValueError("--variant só pode ser usado com --dataset expanded.")
        cases = [case for case in cases if case["variant"] == args.variant]
    if args.case_id is not None and (
        args.sample_size is not None or args.limit is not None
    ):
        raise ValueError("Use --case-id sem --sample-size ou --limit.")
    if args.case_id is not None:
        cases = select_case_by_id(cases, args.case_id)
        print(f"Caso selecionado: {cases[0]['ticket_id']} ({cases[0]['id']})")
    if args.sample_size is not None and args.limit is not None:
        raise ValueError("Use --sample-size ou --limit, não os dois ao mesmo tempo.")
    if args.sample_size is not None:
        if args.dataset != "expanded":
            raise ValueError("--sample-size só pode ser usado com --dataset expanded.")
        cases = sample_cases_by_scenario(
            cases,
            sample_size=args.sample_size,
            sample_seed=args.sample_seed,
        )
        selected = ", ".join(
            f"{case['ticket_id']} ({case['scenario_id']})" for case in cases
        )
        print(f"Amostra reproduzível seed={args.sample_seed}: {selected}")
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit deve ser maior que zero.")
        cases = cases[: args.limit]
    if not cases:
        raise ValueError("Nenhum caso corresponde ao dataset/split informado.")
    conditions = [True, False] if args.experiment else [args.gate == "on"]
    raw_by_condition: dict[str, list[dict[str, Any]]] = {}
    for enabled in conditions:
        key = "gate_on" if enabled else "gate_off"
        raw_by_condition[key] = await execute_condition(
            cases,
            gate_enabled=enabled,
            industrial_url=args.industrial_url,
            seed=args.seed,
            offline=args.offline,
            delay_between_cases=0 if args.offline else args.delay_between_cases,
        )

    # Carregamento deliberadamente posterior às execuções do agente.
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    dataset_metadata: dict[str, Any] = {"dataset_version": "regression-17"}
    if args.dataset == "expanded":
        dataset_metadata = json.loads(
            (ROOT / "evals" / "datasets" / "v1" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
    rows_by_condition = {
        key: apply_gabarito(traces, expected) for key, traces in raw_by_condition.items()
    }
    summary = {key: aggregate(rows) for key, rows in rows_by_condition.items()}
    effective_settings = Settings(industrial_api_url=args.industrial_url, default_seed=args.seed)
    if args.offline:
        effective_settings = effective_settings.model_copy(
            update={
                "llm_base_url": None,
                "llm_api_key": None,
                "llm_model": None,
                "runtime_judge_model": None,
                "llm_classifier_model": None,
                "llm_source_selector_model": None,
                "llm_investigator_model": None,
                "llm_judge_model": None,
                "llm_writer_model": None,
            }
        )
    report = {
        "status": "completed",
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": args.seed,
        "configuration": {
            "industrial_url": args.industrial_url,
            "dataset": args.dataset,
            "split": args.split,
            "variant": args.variant,
            "case_id": args.case_id,
            "case_limit": args.limit,
            "sample_size": args.sample_size,
            "sample_seed": args.sample_seed if args.sample_size is not None else None,
            "selected_case_ids": [case["id"] for case in cases],
            "selected_scenario_ids": [case.get("scenario_id") for case in cases],
            "delay_between_cases_seconds": (
                0 if args.offline else args.delay_between_cases
            ),
            "dataset_version": dataset_metadata["dataset_version"],
            "dataset_checksum": dataset_metadata.get("checksum_sha256"),
            "conditions": list(rows_by_condition),
            "agent_version": "0.2.0",
            "policy_version": effective_settings.pipeline_version,
            "pipeline_signature": effective_settings.pipeline_signature,
            "mode": "offline-fallback" if args.offline else "configured-multiagent",
            "models": {
                "classifier": effective_settings.classifier_model or "offline",
                "source_selector": effective_settings.source_selector_model or "offline",
                "investigator": effective_settings.investigator_model or "offline",
                "judge": effective_settings.judge_model or "offline",
                "writer": effective_settings.writer_model or "offline",
            },
            "temperature": 0,
        },
        "summary": summary,
        "cases": rows_by_condition,
    }
    output_dir = ROOT / "results"
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    result_stem = f"{args.dataset}-{args.split}"
    if args.variant is not None:
        result_stem += f"-v{args.variant}"
    if args.case_id is not None:
        case_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", args.case_id).strip("-")
        result_stem += f"-case-{case_slug}"
    if args.limit is not None:
        result_stem += f"-limit{args.limit}"
    if args.sample_size is not None:
        result_stem += f"-sample{args.sample_size}-seed{args.sample_seed}"
    (output_dir / f"benchmark-{result_stem}-{timestamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / f"latest-{result_stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.dataset == "regression" and args.split == "all":
        (output_dir / "latest.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executa evals sem expor o gabarito ao agente.")
    parser.add_argument("--industrial-url", default="http://127.0.0.1:8000")
    parser.add_argument("--seed", default="complete")
    parser.add_argument(
        "--dataset", choices=("regression", "expanded"), default="regression"
    )
    parser.add_argument(
        "--split",
        choices=("all", "development", "validation", "test"),
        default="all",
    )
    parser.add_argument("--variant", type=int, choices=(1, 2, 3))
    parser.add_argument(
        "--case-id",
        help="Executa um único caso pelo id interno ou ticket_id, como EVAL-027-V2.",
    )
    parser.add_argument("--limit", type=int, help="Limita casos para smoke tests de baixo custo.")
    parser.add_argument(
        "--sample-size",
        type=int,
        help="Sorteia esta quantidade de cenários distintos do dataset expandido.",
    )
    parser.add_argument(
        "--sample-seed",
        type=int,
        default=1,
        help="Semente reproduzível usada por --sample-size (padrão: 1).",
    )
    parser.add_argument(
        "--delay-between-cases",
        type=float,
        default=65,
        help="Espera entre casos com LLM para respeitar RPM/TPM (padrão: 65s).",
    )
    parser.add_argument("--gate", choices=("on", "off"), default="on")
    parser.add_argument("--experiment", action="store_true", help="Compara gate ligado e desligado.")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Usa somente as contingências locais; o padrão respeita os quatro modelos do .env.",
    )
    return parser.parse_args()


def main() -> None:
    report = asyncio.run(run_benchmark(parse_args()))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
