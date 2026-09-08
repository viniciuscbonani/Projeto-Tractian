# 02. Stack

Registra as tecnologias adotadas e a função de cada componente. O percurso
da informação está em `04-arquitetura.md`; os diferenciais e a hipótese experimental estão
em `03-diferenciais.md`.

---

## 1. Restrições herdadas

A API industrial é entregue implementada e não é modificada pelo projeto.

| item | valor |
|---|---|
| Linguagem da API | Python ≥ 3.10 |
| Servidor industrial | FastAPI em `http://localhost:8000` |
| Contrato | OpenAPI 3.1, 18 endpoints em sete categorias |
| Identificação | header `x-user-id`, que define perfil e permissões |
| Determinismo | query param `seed`, que fixa os modos das consultas |
| Envelope de leitura | `{mode, data, notes}` |

O material original permanece isolado em `api-tractian/`.

---

## 2. Núcleo do backend

### 2.1 Python e FastAPI

Python implementa agente, políticas, tools e evals. Uma API FastAPI própria serve o
frontend, inicia execuções e expõe histórico. O navegador não chama a API industrial
diretamente.

### 2.2 Cliente industrial com `httpx`

O cliente propaga `x-user-id` e `seed`, valida respostas e preserva o envelope completo.
`httpx` fornece a interface assíncrona usada pelas tools.

### 2.3 Contratos com Pydantic

Pydantic valida entradas, envelopes, estado, eventos de tool, evidências, relatório técnico,
recomendações, parecer do juiz e resultado consolidado.

---

## 3. Agente e modelos

### 3.1 Orquestração com LangGraph

Controla o estado compartilhado, os agentes especializados, subgrafos, transições, loops
limitados e checkpoints. Regras críticas ficam em Python; não são delegadas apenas ao
prompt.

### 3.2 Acesso ao LLM por interface compatível com OpenAI

Provedor, endpoint, modelo e parâmetros são definidos por configuração. Classificador, agente de
fontes, investigador, juiz e redator possuem variáveis e prompts próprios.

### 3.3 Sistema multiagente

O sistema possui cinco agentes: classificador, agente de fontes, investigador, juiz e redator. Contexto, gate de
suficiência, validação final e persistência são componentes locais, não agentes adicionais.

---

## 4. Persistência e rastreabilidade

### 4.1 Checkpoints com SQLite

Um `thread_id` identifica cada execução. O checkpointer salva o estado após cada etapa e
permite recuperar o histórico. Todos os especialistas operam sobre o mesmo estado.

### 4.2 Histórico da aplicação em SQLite

Sessões de demonstração, execuções e resultados consolidados ficam no banco local. O escopo
adotado não depende de JSONL nem de uma plataforma externa de tracing.

---

## 5. Avaliação

### 5.1 Revisão antes da redação

O LLM-as-a-judge recebe o relatório técnico antes do redator e produz um parecer estruturado:
aprovar, revisar classificação/fontes/investigação ou escalar. Um piso local impede aprovação sem evidência. O fluxo não
executa ações irreversíveis.

### 5.2 Benchmark com `pytest` e DeepEval

O benchmark externo avalia o agente inteiro, inclusive o gate e o parecer do juiz:

- `pytest` e Python para decisão, leituras, recomendações, schemas e ausência de mutações;
- DeepEval para fundamentação, honestidade, completude e outros critérios semânticos.

O gabarito é usado somente no benchmark; nunca entra no estado do atendimento.

---

## 6. Frontend em React

A interface possui uma única área interna de análises: inicia uma simulação, acompanha os cinco
agentes e mostra relatório, juiz, recomendações, prévia da resposta e benchmark.

O frontend usa React com TypeScript e recebe atualizações de progresso pela API própria.

---

## 7. Decisão descartada: servidor MCP

MCP adiciona outra fronteira de processo sem resolver diretamente calibração, divergência,
rastreabilidade ou avaliação. Por esse motivo, as tools são implementadas como funções
Python no mesmo processo do agente.

---

## 8. Resumo da stack

| componente | tecnologia | função |
|---|---|---|
| Linguagem | Python ≥ 3.10 | agente, tools, políticas e evals |
| API própria | FastAPI | comunicação com o frontend |
| Cliente industrial | `httpx` | consumo assíncrono da API entregue |
| Contratos | Pydantic | validação de entradas, estados e saídas |
| Orquestração | LangGraph | fluxo multiagente e checkpoints |
| Persistência | SQLite | histórico operacional e sessões |
| Interface de LLM | wire format OpenAI | configuração independente de provedor |
| Juiz | LLM forte + piso local | revisão do relatório antes da redação |
| Benchmark objetivo | `pytest` | métricas determinísticas e regressão |
| Benchmark semântico | DeepEval | critérios avaliados por LLM |
| Frontend | React + TypeScript | painel interno de análises |
