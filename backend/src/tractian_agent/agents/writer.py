from __future__ import annotations

from typing import Any

from tractian_agent.domain.models import DraftResponse, InvestigationReport

_CUSTOMER_ACTIONS = {
    "reprocess_analysis": "reprocessar a análise para atualizar o diagnóstico",
    "request_specialist": "solicitar uma revisão do caso por um especialista",
    "update_asset": "revisar os dados cadastrais do ativo",
    "request_retraining": "avaliar a atualização do modelo com a equipe técnica",
    "collect_more_data": "coletar mais dados antes de concluir o diagnóstico",
    "inspect_asset": "realizar uma inspeção técnica do ativo",
    "escalate_case": "encaminhar o caso para avaliação da equipe técnica",
}


def write_response(state: dict[str, Any]) -> DraftResponse:
    """Contingência de apresentação; recebe somente o relatório já estruturado."""
    report = InvestigationReport.model_validate(state["investigation"])
    supported = [
        item.statement
        for item in report.hypotheses
        if item.status == "supported"
        and item.statement.strip() != report.conclusion.strip()
    ]
    open_items = [item.statement for item in report.hypotheses if item.status == "open"]
    next_steps: list[str] = []
    supported_text = " ".join(
        [
            report.conclusion,
            *(item.statement for item in report.hypotheses if item.status == "supported"),
        ]
    ).lower()
    if (
        state.get("intent") == "bearing_procedure"
        and any("torque" in item.lower() for item in report.unknowns)
        and "catálogo" in supported_text
    ):
        next_steps.append(
            "Consulte o catálogo do fabricante para confirmar o torque do rolamento e do "
            "conjunto específicos."
        )
    if report.recommendation:
        recommendation = report.recommendation
        action = _CUSTOMER_ACTIONS.get(
            recommendation.kind,
            "prosseguir com a avaliação recomendada pela equipe técnica",
        )
        next_steps.insert(
            0,
            f"Como próximo passo, recomendo {action}. {recommendation.justification}",
        )
    return DraftResponse(
        summary=report.conclusion,
        explanation=supported
        or [
            (
                "As etapas foram extraídas da documentação técnica recuperada para o caso."
                if state.get("intent") == "bearing_procedure"
                else "O relatório não possui hipótese confirmada com segurança."
            )
        ],
        next_steps=next_steps,
        evidence_ids=report.evidence_ids,
        limitations=list(
            dict.fromkeys(
                [
                    *report.unknowns,
                    *(f"Ainda precisa ser verificado: {item}" for item in open_items),
                    *state.get("gaps", []),
                ]
            )
        ),
    )
