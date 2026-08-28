# 04. Arquitetura

Descreve as fronteiras do sistema, o fluxo do atendimento e a relação entre agentes,
políticas, persistência, interface e evals.

---

## 1. Fronteiras

```text
React
  │  chama apenas a API da aplicação
  ▼
FastAPI do projeto
  │
  ▼
LangGraph multiagente
  │  usa tools instrumentadas
  ▼
API industrial TRACTIAN
```

O frontend nunca chama a API industrial diretamente. O backend controla identidade,
permissões, rastreabilidade e execução do agente.

---

## 2. Experiências da aplicação

### 2.1 Cliente

Seleciona uma persona de demonstração, escolhe um ativo, abre um chamado, acompanha o
progresso e consulta resposta e histórico. A persona referencia um usuário sintético real;
as permissões vêm de `GET /users/me` com `x-user-id`.

### 2.2 Administração

Inspeciona execuções, estado, checkpoints, tools, evidências, conflitos, gates, avaliação
de runtime e benchmark. O papel administrativo da aplicação não altera as permissões
industriais do usuário atendido.

---

## 3. Fluxo principal

```text
chamado
  ▼
contexto determinístico
  ▼
classificador
  ├──────────────┬──────────────┐
  ▼              ▼              ▼
contextualizar  investigar     executar
  └──────────────┴──────┬───────┘
                        ▼
              gate de suficiência
               │                │
           suficiente       insuficiente
               │                └──► preparar escalonamento
               ▼
          ação proposta?
           │          │
          não        sim
           │          ▼
           │    gate pré-ação
           │      │        │
           │   permite   bloqueia
           │      ▼        └──► orientar/escalar
           │   executar e validar
           └──────────┬───────────┘
                      ▼
              resposta provisória
                      ▼
              avaliação de runtime
       ┌──────────────┼───────────────┐
       ▼              ▼               ▼
    aprovar        reescrever     investigar/escalar
       │              └── limite ──────┘
       ▼
entregar ao cliente + consolidar resultado
```

Um checkpoint é salvo ao término de cada etapa. Loops de reescrita ou investigação possuem
limites para impedir ciclos.

---

## 4. Estado compartilhado

Um único `AgentState` acompanha a execução e é compartilhado pelos especialistas:

- `run_id`, `thread_id`, `case_id`, `session_id`, `asset_id`, `user_id` e `seed`;
- chamado, modalidade e status da execução;
- perfil e permissões industriais;
- configuração do ativo;
- eventos de tools e envelopes completos;
- evidências com referência de origem;
- lacunas, conflitos, hipóteses e decisões intermediárias;
- ação proposta, autorização, execução e validação;
- resultados dos gates;
- resposta provisória, parecer de runtime e contadores de repetição;
- decisão final ou pacote de escalonamento.

As listas acumulativas usam reducers do LangGraph para que ramos e subgrafos não
sobrescrevam histórico.

---

## 5. Componentes determinísticos

### 5.1 Contexto

Consulta usuário e ativo antes do raciocínio com LLM. Identidade digitada na interface não
concede permissão.

### 5.2 Cliente e tools

Encapsulam os endpoints industriais e registram tool, argumentos, resposta, `mode`, notas,
latência e erro. Leituras degradadas continuam explícitas.

### 5.3 Políticas

Regras Python isoladas e testáveis tratam:

- permissão exigida por ação;
- suficiência de evidência;
- arbitragem de divergências;
- proteção pré-ação;
- limites de repetição e política de escalonamento.

### 5.4 Persistência

O checkpointer SQLite mantém o histórico de estados. Tabelas da aplicação indexam personas,
sessões, execuções e resultados consolidados. JSONL e tracing externo não fazem parte do
escopo adotado.

---

## 6. Agentes especializados

### 6.1 Classificador

Escolhe `contextualizar`, `investigar` ou `executar` com saída estruturada. Classificações
ambíguas seguem para investigação, onde o gate de suficiência impede conclusões sem apoio.

### 6.2 Contextualizador

Busca conhecimento e o conecta ao ativo quando necessário. Não inventa partes ausentes nem
executa mutações.

### 6.3 Investigador

É um subgrafo com consultas condicionais, não uma sequência que chama todos os endpoints:

1. análises existentes e seus detalhes;
2. cobertura e requisitos do modelo;
3. modo de detecção;
4. baseline quando aplicável;
5. qualidade comparada aos requisitos;
6. RMS e espectro quando decisivos;
7. conhecimento necessário à explicação.

`symptom` não exige baseline `established`. Como a análise expõe `model_version`, mas não
`model_id`, a integração mantém um mapeamento configurado entre versão e identificador do
modelo.

### 6.4 Executor

Interpreta a intenção e propõe a ação, mas não contorna o gate pré-ação. A mutação é chamada
uma vez e seu retorno é validado. 400 e 403 são resultados explícitos, não instruções para
tentar argumentos menos seguros.

### 6.5 Redator

Recebe apenas evidências aprovadas e produz uma resposta Pydantic. Não possui tools.

### 6.6 Avaliador de runtime

Combina validações determinísticas com um LLM-as-a-judge direto e devolve um parecer
operacional: `approve`, `rewrite`, `investigate_more` ou `escalate`. Não acessa gabarito.

---

## 7. Tratamento dos envelopes

| `mode` | comportamento |
|---|---|
| `complete` | pode sustentar conclusão, sujeito às regras do ramo |
| `partial` | somente campos presentes são utilizáveis; o gate avalia se bastam |
| `inconclusive` | registra tentativa e impede conclusão não sustentada |
| `conflict` | aplica arbitragem; divergência real termina em escalonamento |
| `unavailable` | registra indisponibilidade; repetir com o mesmo seed não resolve |

Retries são reservados a falhas transitórias de transporte. Nunca são aplicados cegamente
a ações irreversíveis.

---

## 8. Escalonamento e permissões

Escalar pode significar duas coisas diferentes:

- decisão recomendada: evidência insuficiente exige humano;
- ação executada: `POST /cases/{caseId}/escalate` foi autorizado e aceito.

Sem permissão `escalate`, o sistema prepara o pacote, mas não afirma que a ação ocorreu.
Toda mutação exige justificativa válida e passa pelo gate pré-ação.

---

## 9. Checkpoints, resultado e interface

Todos os nós usam o mesmo `thread_id`. O estado final contém listas acumuladas de tools,
decisões e evidências; o histórico de checkpoints permite verificar ordem e localizar
falhas.

Ao final, um `RunResult` menor consolida:

- status e decisão;
- resposta entregue;
- evidências e lacunas principais;
- ação e escalonamento efetivamente executados;
- resultado dos gates e da avaliação de runtime;
- métricas operacionais e referência ao `thread_id`.

O frontend consome `RunResult` para as telas comuns e consulta checkpoints somente na área
administrativa.

---

## 10. Avaliação em duas camadas

### 10.1 Dentro do fluxo

Protege o atendimento antes da entrega. Como faz parte do produto, também pode errar.

### 10.2 Benchmark externo

Executa os casos e usa o gabarito em uma etapa posterior à execução para medir agente, gate
e avaliador de runtime. As verificações objetivas incluem decisão, tools, dependências de ordem,
argumentos, permissões, mutações e schemas; DeepEval complementa critérios semânticos.
