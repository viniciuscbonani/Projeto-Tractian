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

Pydantic valida entradas, envelopes, estado, eventos de tool, evidências, gates, ações,
avaliação de runtime e resultado consolidado.

---

## 3. Agente e modelos

### 3.1 Orquestração com LangGraph

Controla o estado compartilhado, os agentes especializados, subgrafos, transições, loops
limitados e checkpoints. Regras críticas ficam em Python; não são delegadas apenas ao
prompt.

### 3.2 Acesso ao LLM por interface compatível com OpenAI

Provedor, endpoint, modelo e parâmetros são definidos por configuração. Classificador,
especialistas, redator e avaliador de runtime podem usar prompts ou modelos distintos sem
alterar o grafo.

### 3.3 Sistema multiagente

O sistema reúne especialistas de contextualização, investigação e execução, coordenados
pelo grafo. Contexto, gates, políticas e persistência são componentes determinísticos, não
agentes adicionais.

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

### 5.1 Avaliação de runtime dentro do fluxo

Antes de entregar a resposta, verificações determinísticas e um LLM-as-a-judge direto
produzem um parecer estruturado: aprovar, reescrever, investigar mais ou escalar. Ações
irreversíveis passam antes por um gate determinístico próprio.

### 5.2 Benchmark com `pytest` e DeepEval

O benchmark externo avalia o agente inteiro, inclusive o gate e o avaliador de runtime:

- `pytest` e Python para decisão, tools, argumentos, permissões, schemas e ações;
- DeepEval para fundamentação, honestidade, completude e outros critérios semânticos.

O gabarito é usado somente no benchmark; nunca entra no estado do atendimento.

---

## 6. Frontend em React

A interface possui duas áreas:

- cliente: persona de demonstração, abertura de chamado, progresso, resposta e histórico;
- administração: checkpoints, tools, evidências, gates, avaliação de runtime, benchmark e
  experimentos.

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
| Avaliação de runtime | regras + LLM-as-a-judge | revisão anterior à entrega |
| Benchmark objetivo | `pytest` | métricas determinísticas e regressão |
| Benchmark semântico | DeepEval | critérios avaliados por LLM |
| Frontend | React + TypeScript | áreas de cliente e administração |
