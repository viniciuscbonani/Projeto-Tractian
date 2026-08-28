# Projeto TRACTIAN

Projeto individual da parceria Inteli × TRACTIAN para construir e avaliar um agente de IA
capaz de atender chamados de suporte industrial. O agente consulta uma API de monitoramento,
reúne evidências e decide entre orientar o cliente, executar uma ação autorizada ou escalar
o caso com contexto para um engenheiro.

## Documentação

1. [`01-problema.md`](docs/01-problema.md): domínio, atores, dificuldades e escopo;
2. [`02-stack.md`](docs/02-stack.md): tecnologias e decisões de arquitetura;
3. [`03-diferenciais.md`](docs/03-diferenciais.md): gate de suficiência, divergências e hipótese;
4. [`04-arquitetura.md`](docs/04-arquitetura.md): fluxo, responsabilidades e tratamento de erros.

## Estrutura

```text
Projeto-Tractian/
├── api-tractian/  # API e material original fornecidos
├── backend/       # FastAPI, LangGraph, domínio, tools e persistência
├── frontend/      # aplicação React cliente e administrativa
├── evals/         # benchmark externo, métricas e runners
├── infra/         # execução local e implantação
└── scripts/       # automações reprodutíveis
```

## Visão técnica

O material original está em `api-tractian/`, com 17 casos distribuídos em 16 cenários. O
núcleo usa Python, FastAPI, LangGraph, checkpoints SQLite e frontend React. O atendimento
possui avaliação de runtime antes da entrega; `pytest` e DeepEval compõem o benchmark externo.
