# Evals

Benchmark externo do sistema completo. Usa somente os resultados e checkpoints produzidos
pela execução; o gabarito nunca entra no contexto do agente nem do juiz.

- `metrics/`: métricas determinísticas e métricas DeepEval;
- `datasets/v1/`: 111 entradas versionadas, gabarito separado e manifesto;
- `runners/`: execução de casos, seeds e configurações;
- `tests/`: regressões agênticas executáveis por `pytest`;
- `reports/`: geração de tabelas e gráficos, sem resultados gerados versionados.

## Executar

Com a API industrial em `:8000`:

```bash
make benchmark
make experiment

# Base expandida (API industrial ativa e modelos configurados)
make benchmark-smoke
make benchmark-dev
make benchmark-validation
make benchmark-test

# Repete somente um caso que falhou por indisponibilidade do provedor
PYTHONPATH=backend/src:. .venv/bin/python -m evals.runners.benchmark \
  --dataset expanded --split development --case-id EVAL-027-V2 --gate on
```

O runner primeiro executa todos os casos usando apenas `agent-input/cases.json`. Só depois carrega
`eval/expected-paths.json` e calcula decisão, cobertura/ordem de leituras, recomendações,
ausência de mutações, schemas, liberações ruins e bloqueios indevidos. O relatório vai para o
artefato `latest-<dataset>-<split>.json` correspondente. O painel usa o caminho explícito de
`BENCHMARK_REPORT_PATH`. Os cinco modelos do `.env` são usados por padrão;
`--offline` testa somente as contingências locais. Sem DeepEval configurado, registra-se apenas a
cobertura lexical dos termos esperados, sem chamá-la de grounding semântico.

## Dataset expandido v1

A API industrial contém material para 37 cenários factuais úteis. Cada cenário recebeu três
formulações, totalizando 111 casos:

| grupo | casos | cenários | ativos | uso |
| --- | ---: | ---: | ---: | --- |
| desenvolvimento | 60 | 20 | 15 | aprimorar prompts e estrutura |
| validação | 27 | 9 | 5 | escolher entre versões |
| teste | 24 | 8 | 5 | avaliação final congelada |

O agrupamento é feito por ativo e cenário. Portanto, fatos do mesmo equipamento e suas
paráfrases não atravessam os grupos. `inputs.json` contém apenas o que o sistema pode ver;
`expected.json` contém intenção, decisão, consultas esperadas e termos de resposta, sendo
carregado somente depois da execução. `make dataset` regenera os arquivos e os testes verificam
contagem, checksum, separação e ausência de gabarito nas entradas.

Comece por `make benchmark-smoke`: são cinco cenários e aproximadamente 25 chamadas LLM. Um
`make benchmark-dev` completo costuma fazer pelo menos 300 chamadas (classificador, planejamento
de fontes, seleção quando há candidatos, investigador, juiz e redator), além de uma eventual
correção. Os comandos de
validação e teste devem ser usados depois de uma versão candidata, para preservar quota e a
independência do conjunto final.

Os benchmarks com LLM aguardam 65 segundos entre casos para reduzir picos de RPM. O intervalo pode
ser ajustado sem editar arquivos, por exemplo `make benchmark-smoke BENCHMARK_DELAY_SECONDS=40`.
O modo `--offline` ignora o intervalo porque não acessa um provedor.
`--case-id` aceita tanto `EVAL-027-V2` quanto o ID interno completo e não pode ser combinado com
`--sample-size` ou `--limit`.

Os 111 itens não equivalem a 111 falhas industriais independentes: são 37 situações factuais
com variações linguísticas. Esta versão é suficiente para medir classificação, investigação,
decisão e segurança sem depender somente dos 17 casos originais. Antes de tratá-la como referência
industrial, o gabarito dos cenários novos deve ser revisado por uma pessoa especialista da
TRACTIAN. A API ainda tem pouca diversidade de modelos e documentação técnica, e vários ativos
adicionais são controles saudáveis.

A cobertura de caminho do v1 é estrita e admite apenas a sequência registrada no gabarito. Por
isso, fontes alternativas tecnicamente adequadas podem perder pontos. Os casos elétrico M312 e
saudável H110 ficam documentados como divergências da rubrica; o agente não recebe consultas
extras apenas para elevar essa métrica. Uma futura versão do dataset deve preservar
`strict_path_coverage` e acrescentar capacidades de evidência com caminhos alternativos,
congeladas antes dos splits de validação e teste.
