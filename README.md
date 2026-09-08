# Projeto TRACTIAN

Projeto individual da parceria Inteli × TRACTIAN para construir e avaliar um sistema multiagente
de investigação industrial. Cinco agentes classificam o caso, escolhem fontes, investigam evidências, revisam o
relatório técnico e preparam uma resposta. O sistema recomenda ações para decisão humana; nunca as executa.

## Estado da implementação

O escopo essencial está implementado de ponta a ponta:

- backend FastAPI com LangGraph, cinco papéis LLM, contratos Pydantic e tools de leitura;
- idempotência versionada, revisões, checkpointer e histórico operacional em SQLite;
- painel React interno com relatório da investigação, parecer do juiz, recomendações e prévia de resposta;
- regressão de 17 casos e dataset v1 com 111 casos separados em desenvolvimento, validação e teste;
- contingências locais explícitas para indisponibilidade de modelos.

## Início rápido

Requisitos: Python 3.12+ e Node.js 20+.

```bash
make setup
cd frontend && npm install && cd ..
make dev
```

Abra `http://127.0.0.1:5173`. As APIs ficam em `:8000/docs` (industrial) e `:8001/docs`
(aplicação). Alternativamente, `make up` sobe tudo em containers e publica a interface em
`http://localhost:8080`.

Para usar a proposta multiagente, copie `.env.example` para `.env`, informe uma chave da
Groq em `GROQ_API_KEY` e configure os cinco modelos `LLM_*_MODEL`. Sem chave,
o sistema funciona em contingência, útil para testes mas não como configuração principal.

## Verificação e experimento

```bash
make test       # contratos, políticas, API própria e os 17 fluxos
make benchmark  # requer a API industrial ativa; grava results/latest.json
make experiment # gate ligado × desligado
make benchmark-smoke      # 5 casos antes de consumir a quota do lote completo
make benchmark-dev        # 60 casos para aprimoramento
make benchmark-validation # 27 casos para seleção de versão
make benchmark-test       # 24 casos finais congelados
```

O runner carrega o gabarito somente depois de produzir as respostas. O fluxo do agente nunca
importa `api-tractian/eval/` e qualquer mutação é tratada como violação.
Os alvos do dataset expandido apenas verificam o conjunto congelado antes do benchmark; use
`make dataset` deliberadamente quando quiser regenerá-lo.

## Documentação

1. [`01-problema.md`](docs/01-problema.md): domínio, atores, dificuldades e escopo;
2. [`02-stack.md`](docs/02-stack.md): tecnologias e decisões de arquitetura;
3. [`03-diferenciais.md`](docs/03-diferenciais.md): gate de suficiência, divergências e hipótese;
4. [`04-arquitetura.md`](docs/04-arquitetura.md): fluxo, responsabilidades e tratamento de erros;
5. [`05-plano-implementacao.md`](docs/05-plano-implementacao.md): sequência e definição de pronto;
6. [`08-operacao.md`](docs/08-operacao.md): API própria, comandos e decisões implementadas.
7. [`09-resultados-experimento.md`](docs/09-resultados-experimento.md): primeira execução gate ON × OFF.

## Estrutura

```text
Projeto-Tractian/
├── api-tractian/  # API e material original fornecidos
├── backend/       # FastAPI, LangGraph, domínio, tools e persistência
├── frontend/      # painel React interno de análises
├── evals/         # benchmark externo, métricas e runners
├── infra/         # execução local e implantação
└── scripts/       # automações reprodutíveis
```

## Visão técnica

O material original está em `api-tractian/`, com 17 casos. O dataset expandido v1 usa 37 cenários
factuais e três formulações de cada um, sem misturar ativos entre desenvolvimento e teste. O
núcleo usa Python, FastAPI, LangGraph, checkpoints SQLite e frontend React. O juiz revisa o
relatório técnico antes do redator; `pytest`, métricas objetivas e integração opcional com DeepEval compõem
o benchmark externo.
