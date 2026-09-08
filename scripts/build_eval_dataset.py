"""Gera o dataset de avaliação v1 sem misturar entradas e gabaritos.

O split é feito por ativo. Assim, paráfrases e fatos do mesmo equipamento nunca
aparecem em desenvolvimento e teste ao mesmo tempo.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.metrics.objective import (
    EXPECTED_DECISIONS,
    EXPECTED_RECOMMENDATIONS,
    SEMANTIC_TERMS,
)

OUTPUT = ROOT / "evals" / "datasets" / "v1"

ASSET_SPLITS = {
    # Desenvolvimento: cobre todos os comportamentos que serão ajustados.
    "asset_M101": "development",
    "asset_M102": "development",
    "asset_C710": "development",
    "asset_S420": "development",
    "asset_M208": "development",
    "asset_H110": "development",
    "asset_F115": "development",
    "asset_C210": "development",
    "asset_R310": "development",
    "asset_M312": "development",
    "asset_F520": "development",
    "asset_G715": "development",
    "asset_S425": "development",
    "asset_M428": "development",
    "asset_X216": "development",
    # Validação: usada para decidir entre versões de prompt/arquitetura.
    "asset_V301": "validation",
    "asset_G501": "validation",
    "asset_B211": "validation",
    "asset_P712": "validation",
    "asset_F215": "validation",
    # Teste: congelado; não deve orientar alterações de prompt.
    "asset_B204": "test",
    "asset_M205": "test",
    "asset_M605": "test",
    "asset_C510": "test",
    "asset_M612": "test",
}

ORIGINAL_INTENTS = {
    "TKT-INV-04": "break_without_alert",
    "TKT-INV-05": "rms_without_insight",
    "TKT-INV-06": "possible_false_positive",
    "TKT-INV-07": "electrical_or_mechanical",
    "TKT-INV-08": "divergent_diagnoses",
    "TKT-INV-09": "stale_after_maintenance",
    "TKT-INV-10": "poor_signal_quality",
    "TKT-INV-11": "model_coverage",
    "TKT-INV-11b": "symptom_without_baseline",
    "TKT-EXE-12": "reprocess",
    "TKT-EXE-13": "request_specialist",
    "TKT-EXE-14": "update_criticality",
    "TKT-EXE-15": "request_retraining",
    "TKT-EXE-16": "explicit_escalation",
    "TKT-CTX-01": "bearing_procedure",
    "TKT-CTX-02": "bpfo_definition",
    "TKT-CTX-03": "rms_threshold",
}

# Duas formulações novas por caso original. A mensagem original é a variante 1.
ORIGINAL_VARIANTS = {
    "TKT-INV-04": [
        "O redutor parou sem gerar alerta. Os dados explicam por que não houve aviso?",
        "A correia ficou sem o redutor e ninguém recebeu insight antes da quebra. O que faltou?",
    ],
    "TKT-INV-05": [
        "O RMS do compressor passou do normal, mas o diagnóstico não apareceu. Está atrasado?",
        "Há uma tendência de RMS crescente no compressor e nenhum insight. Verifique o processamento.",
    ],
    "TKT-INV-06": [
        "O spindle está estável, embora o insight diga desbalanceamento. Esse resultado se sustenta?",
        "A máquina roda lisa e apareceu desbalanceamento. Confira se pode ser falso positivo.",
    ],
    "TKT-INV-07": [
        "A vibração aumentou rapidamente no motor. Há evidência de origem elétrica?",
        "Esse salto de vibração pode ser elétrico ou ainda faltam bandas no espectro?",
    ],
    "TKT-INV-08": [
        "O especialista indicou base solta e o modelo, desalinhamento. Em quem devo confiar?",
        "Há dois diagnósticos: desalinhamento e base solta. Use o espectro para comparar.",
    ],
    "TKT-INV-09": [
        "O rolamento foi trocado e o insight antigo continua ativo. Ele ficou desatualizado?",
        "Depois da manutenção o mesmo alerta de falha permaneceu. O baseline anterior ainda vale?",
    ],
    "TKT-INV-10": [
        "O sinal do ventilador está ruim. A confiança alta do insight ainda é válida?",
        "Com SNR baixo e dados incompletos, posso confiar no insight do ventilador?",
    ],
    "TKT-INV-11": [
        "O modelo atende motor de corrente contínua e consegue aprender baseline nele?",
        "Verifique a cobertura do modelo para este motor CC antigo.",
    ],
    "TKT-INV-11b": [
        "Como houve alerta de lubrificação se o motor novo ainda está sem baseline?",
        "O baseline está aprendendo, mas apareceu falta de lubrificação. Isso pode ser sintomático?",
    ],
    "TKT-EXE-12": [
        "Após trocar o rolamento, reprocessa a análise para considerar a condição nova.",
        "O reparo terminou. Recomende reprocessar o insight antigo, sem executar a ação.",
    ],
    "TKT-EXE-13": [
        "Quero que um especialista revise o diagnóstico desse compressor.",
        "O insight não convence; encaminha a análise do compressor para um especialista.",
    ],
    "TKT-EXE-14": [
        "Muda a criticidade do ventilador de alta para média, sujeita à aprovação.",
        "O ativo perdeu impacto produtivo. Muda a criticidade para média.",
    ],
    "TKT-EXE-15": [
        "O modelo erra repetidamente nesse spindle. Treina de novo depois de validar os dados.",
        "Treina de novo o modelo para o spindle; os diagnósticos estão divergindo.",
    ],
    "TKT-EXE-16": [
        "Não dá para resolver remotamente. Encaminha o redutor para atendimento em campo.",
        "Os dados são insuficientes e preciso de suporte presencial. Encaminha para engenharia.",
    ],
    "TKT-CTX-01": [
        "Qual é o procedimento de troca do rolamento e como validar torque e baseline depois?",
        "Preciso do procedimento aplicável ao rolamento deste motor, inclusive cuidados pós-troca.",
    ],
    "TKT-CTX-02": [
        "Explique BPFO e relacione o termo ao pico mostrado no espectro da bomba.",
        "Por que aparece BPFO no espectro e o que essa frequência representa no rolamento?",
    ],
    "TKT-CTX-03": [
        "Qual é o limiar de RMS deste ventilador? Ele vem do baseline ou de uma tabela fixa?",
        "Explique como o alarme RMS é calculado para o ativo e se existe um valor universal.",
    ],
}


def steps(*values: str) -> list[dict[str, str]]:
    return [{"step": value} for value in values]


ADDITIONAL_SCENARIOS: list[dict[str, Any]] = [
    {
        "scenario_id": "healthy_m101",
        "asset_id": "asset_M101",
        "root_question": "Os dados atuais sustentam ausência de condição crítica?",
        "mode": "complete",
        "intent": "open_investigation",
        "decision": "orientar",
        "terms": ["sadio", "baseline", "rms"],
        "path": steps(
            "GET /assets/asset_M101/analyses",
            "GET /analyses/an_9911",
            "GET /assets/asset_M101/baseline",
            "GET /assets/asset_M101/data-quality",
        ),
        "messages": [
            "O motor principal está sem alerta. Os dados atuais indicam operação normal?",
            "Confirme se o motor da forja está dentro da condição aprendida.",
            "Não apareceu insight no motor principal; isso é coerente com os dados?",
        ],
    },
    {
        "scenario_id": "healthy_h110",
        "asset_id": "asset_H110",
        "root_question": "O martelete está dentro da faixa saudável?",
        "mode": "complete",
        "intent": "open_investigation",
        "decision": "orientar",
        "terms": ["sadio", "rms", "baseline"],
        "path": steps(
            "GET /assets/asset_H110/analyses",
            "GET /analyses/an_9912",
            "GET /assets/asset_H110/baseline",
            "GET /assets/asset_H110/data-quality",
        ),
        "messages": [
            "O martelete está sem diagnóstico. Ele parece saudável nos dados?",
            "Revise a condição atual do martelete hidráulico e diga se há desvio.",
            "A ausência de insight no martelete é compatível com RMS e baseline?",
        ],
    },
    {
        "scenario_id": "healthy_f115",
        "asset_id": "asset_F115",
        "root_question": "A ausência de alerta no ventilador é coerente?",
        "mode": "complete",
        "intent": "open_investigation",
        "decision": "orientar",
        "terms": ["sadio", "rms", "baseline"],
        "path": steps(
            "GET /assets/asset_F115/analyses",
            "GET /analyses/an_9913",
            "GET /assets/asset_F115/baseline",
            "GET /assets/asset_F115/data-quality",
        ),
        "messages": [
            "O ventilador de resfriamento não tem alertas. Está tudo normal?",
            "Confira se os dados sustentam condição saudável no ventilador.",
            "Por que não existe insight para o ventilador de resfriamento?",
        ],
    },
    {
        "scenario_id": "bpfo_c210",
        "asset_id": "asset_C210",
        "root_question": "Um pico BPFO baixo em ativo saudável confirma falha?",
        "mode": "complete",
        "intent": "bpfo_definition",
        "decision": "orientar",
        "terms": ["bpfo", "pista externa", "não confirma"],
        "path": steps(
            "GET /knowledge/search",
            "GET /knowledge/kb_glos_001",
            "GET /assets/asset_C210/spectrum",
            "GET /assets/asset_C210/analyses",
            "GET /analyses/an_9914",
        ),
        "messages": [
            "O compressor saudável tem um pico BPFO pequeno. Isso já significa falha?",
            "Explique o BPFO do compressor de ar e se o pico isolado confirma defeito.",
            "Há BPFO no espectro, mas a análise está saudável. Como interpretar?",
        ],
    },
    {
        "scenario_id": "threshold_r310",
        "asset_id": "asset_R310",
        "root_question": "Qual é o limiar RMS derivado do baseline do rolo?",
        "mode": "complete",
        "intent": "rms_threshold",
        "decision": "orientar",
        "terms": ["baseline", "referência", "limiar"],
        "path": steps(
            "GET /knowledge/search",
            "GET /knowledge/kb_guid_001",
            "GET /assets/asset_R310/baseline",
            "GET /assets/asset_R310/rms",
            "GET /assets/asset_R310/data-quality",
        ),
        "messages": [
            "Qual é o limiar RMS do rolo de prensa e como ele foi calculado?",
            "O alarme do rolo usa tabela fixa ou referência do próprio baseline?",
            "Explique o valor de alarme RMS aplicável ao rolo de prensa.",
        ],
    },
    {
        "scenario_id": "procedure_m312",
        "asset_id": "asset_M312",
        "root_question": "Qual procedimento aplicar ao rolamento do motor do refiner?",
        "mode": "complete",
        "intent": "bearing_procedure",
        "decision": "orientar",
        "terms": ["fabricante", "torque", "baseline"],
        "path": steps(
            "GET /knowledge/search",
            "GET /knowledge/kb_proc_001",
            "GET /assets/asset_M312/baseline",
        ),
        "messages": [
            "Qual procedimento devo seguir para trocar o rolamento do motor do refiner?",
            "Preciso do procedimento de rolamento, torque e reaprendizado do baseline do refiner.",
            "Oriente a troca de rolamento do motor M312 sem inventar torque específico.",
        ],
    },
    {
        "scenario_id": "healthy_f520",
        "asset_id": "asset_F520",
        "root_question": "O ventilador de exaustão permanece dentro do baseline?",
        "mode": "complete",
        "intent": "open_investigation",
        "decision": "orientar",
        "terms": ["sadio", "rms", "baseline"],
        "path": steps(
            "GET /assets/asset_F520/analyses",
            "GET /analyses/an_9917",
            "GET /assets/asset_F520/baseline",
            "GET /assets/asset_F520/data-quality",
        ),
        "messages": [
            "O ventilador de exaustão continua saudável?",
            "Revise o RMS e o baseline do ventilador sem presumir uma falha.",
            "Não há alerta no F520. Os dados justificam essa ausência?",
        ],
    },
    {
        "scenario_id": "coverage_g715",
        "asset_id": "asset_G715",
        "root_question": "O modelo cobre o tipo do gerador e aprende baseline?",
        "mode": "complete",
        "intent": "model_coverage",
        "decision": "orientar",
        "terms": ["modelo", "motor", "baseline"],
        "path": steps("GET /models/mdl_vib_v3", "GET /assets/asset_G715/baseline"),
        "messages": [
            "O modelo atende este gerador classificado como motor de indução?",
            "Verifique se o modelo cobre o tipo do G715 e aprende baseline.",
            "Esse gerador está dentro da cobertura do modelo atual?",
        ],
    },
    {
        "scenario_id": "healthy_s425",
        "asset_id": "asset_S425",
        "root_question": "O spindle secundário apresenta desvio real?",
        "mode": "complete",
        "intent": "open_investigation",
        "decision": "orientar",
        "terms": ["sadio", "rms", "baseline"],
        "path": steps(
            "GET /assets/asset_S425/analyses",
            "GET /analyses/an_9920",
            "GET /assets/asset_S425/baseline",
            "GET /assets/asset_S425/data-quality",
        ),
        "messages": [
            "O spindle secundário parece diferente, mas não há insight. Investigue os dados.",
            "Confira se existe desvio real no S425 ou se ele segue saudável.",
            "A operação do spindle está normal segundo análise e baseline?",
        ],
    },
    {
        "scenario_id": "criticality_m428",
        "asset_id": "asset_M428",
        "root_question": "Recomendar mudança de criticidade sem executar mutação.",
        "mode": "complete",
        "intent": "update_criticality",
        "decision": "recomendar",
        "recommendation": "update_asset",
        "terms": ["criticidade", "aprovação"],
        "path": steps("GET /assets/asset_M428", "PATCH /assets/asset_M428"),
        "messages": [
            "Muda a criticidade do motor de mesa de baixa para média.",
            "O M428 agora afeta a produção; muda a criticidade para média após aprovação.",
            "Recomende mudar a criticidade do motor de mesa, sem alterar automaticamente.",
        ],
    },
    {
        "scenario_id": "field_x216",
        "asset_id": "asset_X216",
        "root_question": "Preparar repasse humano solicitado explicitamente.",
        "mode": "complete",
        "intent": "explicit_escalation",
        "decision": "escalar",
        "recommendation": "escalate_case",
        "terms": ["humana", "engenheiro"],
        "path": steps(
            "GET /assets/asset_X216/analyses",
            "GET /assets/asset_X216/baseline",
            "GET /assets/asset_X216/data-quality",
            "GET /assets/asset_X216/rms",
            "POST /cases/field_x216/escalate",
        ),
        "messages": [
            "Preciso de avaliação presencial no misturador. Encaminha para um engenheiro.",
            "Esse caso precisa de uma pessoa em campo; encaminha o X216 com o contexto.",
            "Não quero resposta automática. Encaminha a análise do misturador para engenharia.",
        ],
    },
    {
        "scenario_id": "electrical_m312",
        "asset_id": "asset_M312",
        "root_question": "O espectro sustenta origem elétrica no motor do refiner?",
        "mode": "complete",
        "intent": "electrical_or_mechanical",
        "decision": "orientar",
        "terms": ["elétrica", "espectro", "120"],
        "path": steps(
            "GET /assets/asset_M312/rms",
            "GET /assets/asset_M312/spectrum",
            "GET /knowledge/search",
            "GET /knowledge/kb_guid_003",
        ),
        "messages": [
            "A vibração do motor do refiner pode ser elétrica? Verifique o espectro.",
            "Há componente de origem elétrica no M312 ou os dados não sustentam isso?",
            "Compare a vibração do refiner com a banda elétrica de 120 Hz.",
        ],
    },
    {
        "scenario_id": "divergence_s420",
        "asset_id": "asset_S420",
        "root_question": "Qual fonte prevalece no conflito do spindle?",
        "mode": "conflict",
        "intent": "divergent_diagnoses",
        "decision": "orientar",
        "terms": ["baseline", "folga", "espectro"],
        "path": steps(
            "GET /assets/asset_S420/analyses",
            "GET /analyses/an_9903",
            "GET /analyses/an_9904",
            "GET /assets/asset_S420/spectrum",
        ),
        "messages": [
            "O modelo diz desbalanceamento e o especialista fala em base solta. Em quem confio?",
            "Compare os diagnósticos divergentes do spindle usando o espectro.",
            "Base solta ou desbalanceamento: qual hipótese tem melhor evidência no S420?",
        ],
    },
    {
        "scenario_id": "poor_signal_b211",
        "asset_id": "asset_B211",
        "root_question": "É seguro concluir algo com baixa qualidade e sem análise?",
        "mode": "partial",
        "intent": "poor_signal_quality",
        "decision": "orientar",
        "terms": ["snr", "completude", "insuficiente"],
        "path": steps(
            "GET /assets/asset_B211/analyses",
            "GET /assets/asset_B211/data-quality",
            "GET /models/mdl_vib_v3",
        ),
        "messages": [
            "A qualidade do sinal da bomba B211 está baixa. Posso confiar em qualquer insight?",
            "Com SNR ruim e sensor degradado, o diagnóstico da bomba seria confiável?",
            "Avalie a completude dos dados antes de confiar no insight da B211.",
        ],
    },
    {
        "scenario_id": "bpfo_p712",
        "asset_id": "asset_P712",
        "root_question": "Como interpretar BPFO baixo em uma bomba saudável?",
        "mode": "complete",
        "intent": "bpfo_definition",
        "decision": "orientar",
        "terms": ["bpfo", "pista externa", "não confirma"],
        "path": steps(
            "GET /knowledge/search",
            "GET /knowledge/kb_glos_001",
            "GET /assets/asset_P712/spectrum",
            "GET /assets/asset_P712/analyses",
            "GET /analyses/an_9918",
        ),
        "messages": [
            "Há um pico BPFO pequeno na bomba P712. Isso confirma defeito?",
            "Explique a frequência BPFO da bomba de transferência e seu significado.",
            "A análise está saudável, mas o espectro contém BPFO. Como isso é possível?",
        ],
    },
    {
        "scenario_id": "field_p712",
        "asset_id": "asset_P712",
        "root_question": "Escalonar por solicitação explícita, mesmo com dados completos.",
        "mode": "complete",
        "intent": "explicit_escalation",
        "decision": "escalar",
        "recommendation": "escalate_case",
        "terms": ["humana", "engenheiro"],
        "path": steps(
            "GET /assets/asset_P712/analyses",
            "GET /assets/asset_P712/baseline",
            "GET /assets/asset_P712/data-quality",
            "GET /assets/asset_P712/rms",
            "POST /cases/field_p712/escalate",
        ),
        "messages": [
            "Quero inspeção presencial na bomba P712. Encaminha para engenharia.",
            "Mesmo com os dados atuais, encaminha esse caso para uma pessoa em campo.",
            "Não responda automaticamente; encaminha a bomba de transferência a um engenheiro.",
        ],
    },
    {
        "scenario_id": "threshold_f215",
        "asset_id": "asset_F215",
        "root_question": "Qual limiar individual vale para o ventilador do forno?",
        "mode": "complete",
        "intent": "rms_threshold",
        "decision": "orientar",
        "terms": ["baseline", "referência", "limiar"],
        "path": steps(
            "GET /knowledge/search",
            "GET /knowledge/kb_guid_001",
            "GET /assets/asset_F215/baseline",
            "GET /assets/asset_F215/rms",
            "GET /assets/asset_F215/data-quality",
        ),
        "messages": [
            "Qual o limiar RMS do ventilador do forno?",
            "O alarme do F215 vem do baseline ou de tabela fixa?",
            "Calcule e explique o valor de alarme RMS aplicável ao ventilador do forno.",
        ],
    },
    {
        "scenario_id": "poor_signal_c510",
        "asset_id": "asset_C510",
        "root_question": "O agente admite que dados degradados não sustentam diagnóstico?",
        "mode": "partial",
        "intent": "poor_signal_quality",
        "decision": "orientar",
        "terms": ["snr", "completude", "insuficiente"],
        "path": steps(
            "GET /assets/asset_C510/analyses",
            "GET /assets/asset_C510/data-quality",
            "GET /models/mdl_vib_v3",
        ),
        "messages": [
            "A qualidade do britador está ruim e não há análise. O que dá para concluir?",
            "Posso confiar em um insight do C510 com SNR e completude baixos?",
            "Antes de diagnosticar o britador, valide a qualidade dos dados disponíveis.",
        ],
    },
    {
        "scenario_id": "procedure_m612",
        "asset_id": "asset_M612",
        "root_question": "Recuperar procedimento sem inventar torque do motor de bobina.",
        "mode": "complete",
        "intent": "bearing_procedure",
        "decision": "orientar",
        "terms": ["fabricante", "torque", "baseline"],
        "path": steps(
            "GET /knowledge/search",
            "GET /knowledge/kb_proc_001",
            "GET /assets/asset_M612/baseline",
        ),
        "messages": [
            "Qual procedimento aplicar na troca do rolamento do motor de bobina?",
            "Preciso de orientação de rolamento, torque e baseline para o M612.",
            "Mostre o procedimento seguro para trocar o rolamento sem inventar especificações.",
        ],
    },
    {
        "scenario_id": "criticality_m612",
        "asset_id": "asset_M612",
        "root_question": "Recomendar redução de criticidade sem executar alteração.",
        "mode": "complete",
        "intent": "update_criticality",
        "decision": "recomendar",
        "recommendation": "update_asset",
        "terms": ["criticidade", "aprovação"],
        "path": steps("GET /assets/asset_M612", "PATCH /assets/asset_M612"),
        "messages": [
            "Muda a criticidade do motor de bobina para média.",
            "O M612 deixou de ser gargalo; muda a criticidade depois de aprovação.",
            "Recomende mudar a criticidade do M612, sem executar a atualização.",
        ],
    },
]


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _user_by_company() -> dict[str, str]:
    # Personas válidas já presentes na API industrial.
    return {
        "comp_forja_br": "usr_ana",
        "comp_aurora": "usr_lucas",
        "comp_papel_sul": "usr_marta",
        "comp_mineracao_andes": "usr_pedro",
        "comp_petro_delta": "usr_sofia",
        "comp_acme": "usr_bruno",
        "comp_cimento_vale": "usr_carla",
        "comp_texfil": "usr_raul",
    }


def _asset_companies() -> dict[str, str]:
    # O arquivo parquet é a fonte efetiva servida pela API; pandas já é dependência do gerador.
    import pandas as pd

    assets = pd.read_parquet(ROOT / "api-tractian" / "data" / "assets.parquet")
    return dict(zip(assets["id"], assets["company_id"], strict=True))


def _source_inventory() -> dict[str, int]:
    import pandas as pd

    data_dir = ROOT / "api-tractian" / "data"
    analyses = pd.read_parquet(data_dir / "analyses.parquet")
    return {
        "assets": len(pd.read_parquet(data_dir / "assets.parquet")),
        "analyses": len(analyses),
        "abnormal_analyses": int((analyses["type"] != "none").sum()),
        "healthy_analyses": int((analyses["type"] == "none").sum()),
        "baselines": len(pd.read_parquet(data_dir / "baselines.parquet")),
        "rms_samples": len(pd.read_parquet(data_dir / "rms.parquet")),
        "spectra": len(pd.read_parquet(data_dir / "spectra.parquet")),
        "data_quality_records": len(pd.read_parquet(data_dir / "data_quality.parquet")),
        "knowledge_documents": len(pd.read_parquet(data_dir / "knowledge.parquet")),
        "model_versions": len(pd.read_parquet(data_dir / "models.parquet")),
    }


def original_scenarios() -> list[dict[str, Any]]:
    cases = json.loads(
        (ROOT / "api-tractian" / "agent-input" / "cases.json").read_text(encoding="utf-8")
    )
    expected = {
        item["id"]: item
        for item in json.loads(
            (ROOT / "api-tractian" / "eval" / "expected-paths.json").read_text(
                encoding="utf-8"
            )
        )
    }
    output = []
    for case in cases:
        ticket_id = case["ticket_id"]
        guide = expected[case["id"]]
        output.append(
            {
                "scenario_id": f"original_{slug(ticket_id)}",
                "source_case_id": case["id"],
                "asset_id": case["asset_id"],
                "company_id": case["company_id"],
                "user_id": case["user_id"],
                "root_question": guide["root_question"],
                "mode": guide["mode"],
                "intent": ORIGINAL_INTENTS[ticket_id],
                "decision": EXPECTED_DECISIONS[ticket_id],
                "recommendation": EXPECTED_RECOMMENDATIONS.get(ticket_id),
                "terms": SEMANTIC_TERMS.get(ticket_id, []),
                "path": guide["expected_path"],
                "messages": [case["message"], *ORIGINAL_VARIANTS[ticket_id]],
            }
        )
    return output


def build() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    companies = _asset_companies()
    users = _user_by_company()
    scenarios = [*original_scenarios(), *ADDITIONAL_SCENARIOS]
    inputs: list[dict[str, Any]] = []
    expected: list[dict[str, Any]] = []
    seen_messages: set[str] = set()
    assets_by_split: dict[str, set[str]] = defaultdict(set)

    for scenario_index, scenario in enumerate(scenarios, start=1):
        asset_id = scenario["asset_id"]
        split = ASSET_SPLITS[asset_id]
        company_id = scenario.get("company_id") or companies[asset_id]
        user_id = scenario.get("user_id") or users[company_id]
        messages = scenario["messages"]
        if len(messages) != 3:
            raise ValueError(f"{scenario['scenario_id']} precisa ter exatamente três variantes.")
        assets_by_split[split].add(asset_id)
        for variant, message in enumerate(messages, start=1):
            normalized = " ".join(message.lower().split())
            if normalized in seen_messages:
                raise ValueError(f"Mensagem duplicada: {message}")
            seen_messages.add(normalized)
            case_id = f"eval_v1_{scenario['scenario_id']}_v{variant}"
            ticket_id = f"EVAL-{scenario_index:03d}-V{variant}"
            inputs.append(
                {
                    "id": case_id,
                    "ticket_id": ticket_id,
                    "scenario_id": scenario["scenario_id"],
                    "source_case_id": scenario.get("source_case_id"),
                    "split": split,
                    "variant": variant,
                    "company_id": company_id,
                    "user_id": user_id,
                    "asset_id": asset_id,
                    "message": message,
                }
            )
            expected.append(
                {
                    "id": case_id,
                    "ticket_id": ticket_id,
                    "scenario_id": scenario["scenario_id"],
                    "split": split,
                    "root_question": scenario["root_question"],
                    "mode": scenario["mode"],
                    "expected_intent": scenario["intent"],
                    "expected_decision": scenario["decision"],
                    "expected_recommendation": scenario.get("recommendation"),
                    "expected_answer_terms": scenario.get("terms", []),
                    "forbidden_answer_terms": [
                        "ação foi executada com sucesso",
                        "alteração foi aplicada automaticamente",
                    ],
                    "expected_path": scenario["path"],
                    "forbidden_tools": [],
                }
            )

    if not 80 <= len(inputs) <= 120:
        raise ValueError(f"O dataset deve ter entre 80 e 120 casos; recebeu {len(inputs)}.")
    for left, left_assets in assets_by_split.items():
        for right, right_assets in assets_by_split.items():
            if left < right and left_assets & right_assets:
                raise ValueError(f"Vazamento de ativos entre {left} e {right}.")

    serialized = json.dumps(
        {"inputs": inputs, "expected": expected},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    by_split_cases = Counter(item["split"] for item in inputs)
    scenario_counts = Counter(ASSET_SPLITS[scenario["asset_id"]] for scenario in scenarios)
    manifest = {
        "dataset_version": "v1",
        "schema_version": 1,
        "checksum_sha256": sha256(serialized.encode("utf-8")).hexdigest(),
        "split_policy": "grouped_by_asset_and_scenario",
        "case_count": len(inputs),
        "scenario_count": len(scenarios),
        "variant_count_per_scenario": 3,
        "source_inventory": _source_inventory(),
        "splits": {
            split: {
                "cases": by_split_cases[split],
                "scenarios": scenario_counts[split],
                "assets": len(assets_by_split[split]),
            }
            for split in ("development", "validation", "test")
        },
        "decisions": dict(sorted(Counter(item["expected_decision"] for item in expected).items())),
        "intents": dict(sorted(Counter(item["expected_intent"] for item in expected).items())),
        "notes": [
            "inputs.json não contém gabarito e pode ser fornecido ao runner.",
            "expected.json só deve ser carregado depois das execuções.",
            "O split de teste é congelado e não deve orientar ajustes de prompt.",
        ],
    }
    return inputs, expected, manifest


def main() -> None:
    inputs, expected, manifest = build()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("inputs.json", inputs),
        ("expected.json", expected),
        ("manifest.json", manifest),
    ):
        (OUTPUT / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        f"Dataset {manifest['dataset_version']}: {manifest['case_count']} casos, "
        f"{manifest['scenario_count']} cenários."
    )
    for split, counts in manifest["splits"].items():
        print(f"  {split}: {counts}")


if __name__ == "__main__":
    main()
