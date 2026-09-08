# 08 — Operação

## Decisões vigentes

- Python 3.12+, React/TypeScript/Vite, FastAPI e LangGraph;
- cinco modelos configuráveis por papel;
- Groq via API compatível com OpenAI;
- SSE somente para observar progresso;
- SQLite para execuções/revisões e outro arquivo para checkpoints nativos;
- no máximo uma correção automática confirmada por regra local;
- nenhuma mutação no grafo: ações são recomendações para aprovação humana;
- contingências locais explícitas para falha ou ausência dos modelos.

## API própria

| rota | uso |
|---|---|
| `GET /api/personas` | identidades sintéticas associadas aos casos |
| `GET /api/demo-cases` | os 17 inputs, sem gabarito |
| `POST /api/sessions` | sessão de demonstração |
| `POST /api/runs` | cria ou reaproveita uma análise pela chave de idempotência |
| `GET /api/runs/{id}` | status, revisão e etapa atual |
| `GET /api/runs/{id}/events` | progresso SSE; nunca inicia processamento |
| `GET /api/runs/{id}/result` | relatório consolidado |
| `GET /api/admin/runs` | lista interna de análises |
| `GET /api/admin/runs/{id}/checkpoints` | marcos seletivos de auditoria |
| `GET /api/admin/benchmarks/latest` | último relatório externo |

`POST /api/runs?wait=true` existe para testes e CLI. A interface usa execução assíncrona.

## Configuração de modelos

Copie `.env.example` para `.env`, crie uma chave em `https://console.groq.com/keys` e defina
`GROQ_API_KEY`. A credencial é lida apenas pelo backend. As variáveis de modelo são:

```dotenv
LLM_PROVIDER=groq
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_CLASSIFIER_MODEL=openai/gpt-oss-20b
LLM_SOURCE_SELECTOR_MODEL=openai/gpt-oss-20b
LLM_INVESTIGATOR_MODEL=openai/gpt-oss-120b
LLM_JUDGE_MODEL=openai/gpt-oss-120b
LLM_WRITER_MODEL=openai/gpt-oss-20b
LLM_INVESTIGATOR_MAX_TOKENS=1600
MAX_ANALYSIS_DETAILS=4
```

Depois de alterar modelo, prompt ou regra, incremente `PIPELINE_VERSION`. A assinatura efetiva
inclui essa versão, os cinco modelos, os limites de fontes/revisões e o mapeamento entre versões
e IDs de modelo, portanto resultados antigos não serão reutilizados. A candidata atual é
`multiagent-groq-v23`; a variável de ambiente tem precedência sobre o default do código.

`BENCHMARK_REPORT_PATH` escolhe explicitamente o artefato mostrado no painel. O padrão aponta
para a amostra de desenvolvimento seed 1, sem misturá-la ao relatório legado `latest.json`.

## Idempotência e frescor

`investigation_key` identifica o fluxo lógico. Entrada idêntica reutiliza execução em andamento ou
resultado concluído dentro de `RESULT_REUSE_TTL_SECONDS`. Contexto novo gera `revision + 1` e
`parent_run_id`. Após o TTL, as fontes industriais são consultadas novamente.

Essa estratégia evita duplicação por clique/reconexão e também evita cache eterno. Uma futura
integração com dados reais pode acrescentar versão por fonte ou watermark de coleta.

## Checkpoints e segurança

O LangGraph persiste estado nativo para retomada. A tabela da aplicação grava apenas
`classifier`, `source_plan`, `source_collect`, `source_select`, `investigator`,
`sufficiency_gate`, `reviewer`, `writer` e `finalize`. Assim, consultas e escolhas de fontes
aparecem enquanto a análise está em andamento.

O agente de fontes só recebe um catálogo de tools GET. O juiz trabalha antes do redator e emite
objeções estruturadas, mas somente o compilador determinístico pode devolver uma vez à etapa
responsável. Objeção não verificável troca o relatório por uma contingência local validada, ou
escalona se ela também falhar. O redator não recebe tools. O resultado mantém `actions=[]`
e toda recomendação possui `requires_human_approval=true`.

## Comandos

```bash
make dev
make test
make lint
make benchmark          # usa os cinco modelos do .env
make benchmark-offline  # testa apenas contingências locais
make experiment         # gate ligado × desligado com os modelos configurados
make dataset-check      # verifica o dataset congelado sem regenerá-lo
```

Para repetir somente um caso que falhou por erro transitório do provedor:

```bash
PYTHONPATH=backend/src:. .venv/bin/python -m evals.runners.benchmark \
  --dataset expanded --split development --case-id EVAL-027-V2 --seed complete --gate on
```

O benchmark offline não mede a proposta principal; serve para garantir que uma falha de provedor
produza saída conservadora e auditável.

Os benchmarks com LLM usam 65 segundos entre casos por padrão. Os alvos do dataset expandido
executam `dataset-check`; somente `make dataset` regenera os arquivos.
