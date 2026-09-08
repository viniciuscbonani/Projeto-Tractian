PYTHON ?= python3
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
BENCHMARK_DELAY_SECONDS ?= 65
BENCHMARK_SAMPLE_SIZE ?= 5
BENCHMARK_SAMPLE_SEED ?= 1

.DEFAULT_GOAL := help
.PHONY: help setup test lint dev dev-industrial dev-backend dev-frontend build-frontend dataset dataset-check benchmark benchmark-offline benchmark-smoke benchmark-dev benchmark-validation benchmark-test experiment up down logs

help: ## Lista os comandos do projeto
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Cria o ambiente Python e instala API industrial, backend e testes
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e "./api-tractian/api[dev]" -e "./backend[dev]"
	@echo "Backend pronto. Para a interface: cd frontend && npm install"

test: ## Executa contratos, políticas, 17 fluxos e testes de evals/frontend
	$(PY) -m pytest -q api-tractian/api/tests backend/tests evals/tests
	@if command -v npm >/dev/null 2>&1 && [ -d frontend/node_modules ]; then cd frontend && npm test; else echo "Node/npm ou node_modules ausente; teste JS ignorado."; fi

lint: ## Verifica estilo Python e compilação do frontend
	$(VENV)/bin/ruff check backend/src backend/tests evals scripts
	@if command -v npm >/dev/null 2>&1 && [ -d frontend/node_modules ]; then cd frontend && npm run build; else echo "Node/npm ou node_modules ausente; build JS ignorado."; fi

dev: ## Sobe API industrial, backend e frontend com encerramento coordenado
	bash scripts/dev.sh

dev-industrial: ## Sobe somente a API industrial em :8000
	cd api-tractian/api && ../../$(PY) -m uvicorn app.main:app --host 127.0.0.1 --port 8000

dev-backend: ## Sobe somente a API da aplicação em :8001
	PYTHONPATH=backend/src $(PY) -m uvicorn tractian_agent.api.main:app --host 127.0.0.1 --port 8001

dev-frontend: ## Sobe somente o React em :5173
	cd frontend && npm run dev

build-frontend: ## Gera o bundle de produção React
	cd frontend && npm run build

dataset: ## Regenera os 111 casos e valida a separação desenvolvimento/validação/teste
	PYTHONPATH=backend/src:. $(PY) scripts/build_eval_dataset.py

dataset-check: ## Verifica o dataset congelado sem regenerar arquivos
	PYTHONPATH=backend/src:. $(PY) -m pytest -q evals/tests/test_dataset.py

benchmark: ## Executa os 17 casos com gate ligado (API industrial precisa estar ativa)
	PYTHONPATH=backend/src:. $(PY) -m evals.runners.benchmark --gate on --delay-between-cases $(BENCHMARK_DELAY_SECONDS)

benchmark-offline: ## Valida somente as contingências locais, sem chamar LLMs
	PYTHONPATH=backend/src:. $(PY) -m evals.runners.benchmark --gate on --offline

benchmark-smoke: dataset-check ## Sorteia cenários de desenvolvimento com LLM de forma reproduzível
	PYTHONPATH=backend/src:. $(PY) -m evals.runners.benchmark --dataset expanded --split development --sample-size $(BENCHMARK_SAMPLE_SIZE) --sample-seed $(BENCHMARK_SAMPLE_SEED) --delay-between-cases $(BENCHMARK_DELAY_SECONDS)

benchmark-dev: dataset-check ## Executa os 60 casos usados para aprimorar prompts
	PYTHONPATH=backend/src:. $(PY) -m evals.runners.benchmark --dataset expanded --split development --delay-between-cases $(BENCHMARK_DELAY_SECONDS)

benchmark-validation: dataset-check ## Executa os 27 casos usados para escolher entre versões
	PYTHONPATH=backend/src:. $(PY) -m evals.runners.benchmark --dataset expanded --split validation --delay-between-cases $(BENCHMARK_DELAY_SECONDS)

benchmark-test: dataset-check ## Executa uma única avaliação final nos 24 casos congelados
	PYTHONPATH=backend/src:. $(PY) -m evals.runners.benchmark --dataset expanded --split test --delay-between-cases $(BENCHMARK_DELAY_SECONDS)

experiment: ## Compara gate ligado e desligado e grava results/latest.json
	PYTHONPATH=backend/src:. $(PY) -m evals.runners.benchmark --experiment --delay-between-cases $(BENCHMARK_DELAY_SECONDS)

up: ## Sobe o ambiente completo em containers
	docker compose -f infra/compose.yaml up --build -d

down: ## Encerra os containers locais
	docker compose -f infra/compose.yaml down

logs: ## Acompanha logs dos containers
	docker compose -f infra/compose.yaml logs -f
