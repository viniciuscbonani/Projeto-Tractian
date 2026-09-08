# 04. Arquitetura

O produto é uma ferramenta interna de investigação. Ele recebe um caso já aberto, reúne
evidências industriais, produz um relatório para engenharia e mostra uma prévia da resposta que
poderia ser usada pelo atendimento. Não é um chat e não executa mudanças na plataforma.

---

## 1. Fronteiras

```text
Painel React interno
        │
        │ POST cria análise; GET/SSE apenas observa
        ▼
FastAPI da aplicação ── SQLite de execuções, revisões e resultados
        │
        ▼
LangGraph multiagente ── SQLite de checkpoints nativos
        │
        │ somente tools GET instrumentadas
        ▼
API industrial TRACTIAN
```

O frontend nunca chama a API industrial. O backend controla identidade, rastreabilidade,
idempotência e quais tools cada agente pode usar.

---

## 2. Entrada e idempotência

Antes de iniciar o grafo, a API resolve uma `investigation_key`. Para casos de demonstração ela
é o `case_id`; para outras entradas é derivada de usuário, ativo e mensagem normalizada.

Cada registro também guarda:

- `input_hash`: usuário, ativo, caso, mensagem, contexto adicional, seed e gate;
- `pipeline_signature`: versão do fluxo e modelos dos cinco agentes;
- `revision` e `parent_run_id`;
- instante da última atualização.

As regras são:

1. mesma chave, mesmo input e mesma assinatura, ainda em execução: devolver a execução existente;
2. mesma entrada concluída dentro do TTL: reaproveitar o resultado;
3. contexto adicional diferente: criar nova revisão e consultar novamente os dados industriais;
4. modelo, prompt ou regra alterados: mudar `PIPELINE_VERSION` ou um modelo, invalidando a
   assinatura e criando nova revisão;
5. resultado mais antigo que `RESULT_REUSE_TTL_SECONDS`: executar novamente para reduzir o risco
   de usar dados industriais vencidos.

Na nova revisão, a classificação pode ser reaproveitada quando a mensagem e a assinatura não
mudaram. Investigação e julgamento não são reaproveitados, pois dependem de dados e contexto
potencialmente novos. Isso é cache versionado, não uma promessa de “exactly once”.

---

## 3. Fluxo multiagente

```text
chave/idempotência
       │
       ▼
contexto técnico (GET usuário + ativo)
       │
       ▼
1. CLASSIFICADOR — LLM pequeno
       │
       ▼
2. AGENTE DE FONTES — LLM pequeno
   planeja GETs → busca candidatos → escolhe até dois documentos reais
       │
       ▼
3. INVESTIGADOR — LLM forte
   consolida as evidências em relatório técnico
       │
       ▼
gate determinístico de suficiência
       │
       ▼
4. JUIZ — LLM forte
   └── registra objeções semânticas estruturadas, sem escolher a próxima aresta
       │
       ▼
compilador determinístico de revisão
   ├── violação/fonte verificável → etapa responsável (no máximo uma vez)
   ├── objeção plausível não verificável → síntese local conservadora + nova validação
   ├── resposta segura impossível → bloqueio e revisão humana
   └── sem objeção → redação
       │
       ▼
5. REDATOR — LLM menor (somente depois de approve)
       │
       ▼
validador local de schema, citações, linguagem pública e ampliação semântica
       │
       ▼
relatório interno + prévia de resposta
```

O juiz fica antes do redator deliberadamente. Ele avalia o relatório estruturado, mas não controla
o roteamento. O código local confere IDs, fatos primários, fontes do gate, recomendação, aprovação
humana e impacto dos conflitos. Uma objeção do juiz que não possa ser ligada a essas regras não é
ignorada nem devolvida cegamente ao investigador: o relatório contestado é descartado e uma
síntese local conservadora precisa passar pela mesma validação. Se nem ela for segura e útil, o
caso é escalonado.

Conflitos carregam impacto explícito. `informational` deve aparecer em comparações sem bloquear a
resposta; `blocks_claim` proíbe uma conclusão categórica enquanto preserva orientação cautelosa;
`blocks_action` reprova o gate e impede a ação até resolução ou revisão humana.

O validador posterior ao redator não é um sexto agente: é código local. A reparação LLM existente
trata apenas referências estruturadas inválidas. Números novos, execução, linguagem interna ou
conclusão forte ausente do relatório substituem imediatamente toda a redação pela contingência
local, sem uma nova chamada ao modelo.

---

## 4. Responsabilidade dos cinco agentes

### 4.1 Classificador

Escolhe `contextualizar`, `investigar` ou `recomendar` e produz um intent em saída estruturada.
Pedidos de reprocessamento, alteração, especialista ou retreinamento são classificados como
recomendação, nunca como autorização para executar.

### 4.2 Agente de fontes

Escolhe até oito categorias de leitura e marca quais são decisivas. Se precisar de conhecimento,
gera até três consultas curtas para o `GET /knowledge/search`. Depois compara semanticamente os
candidatos com a pergunta e seleciona no máximo dois documentos.

Somente IDs realmente retornados pela API podem ser usados em `GET /knowledge/{id}`. Duplicatas e
IDs inventados são descartados e registrados como lacuna. Um plano LLM válido não recebe fontes
fixas silenciosamente; tabelas por intenção existem apenas na contingência offline.

### 4.3 Investigador

Recebe as fontes já coletadas e cria um relatório estruturado com conclusão, IDs que sustentam a
conclusão, hipóteses com suas próprias citações, desconhecidos e possível recomendação. Não possui
mais a responsabilidade de escolher documentos.

### 4.4 Juiz

Recebe pergunta, intenção, plano, seleção, evidências e relatório. Retorna uma lista de objeções
tipadas: intenção divergente, fonte ausente, afirmação sem suporte, recomendação insegura, conflito
decisivo ou necessidade humana. Não recebe um campo que escolha a próxima aresta.

O compilador local confronta essas objeções com o gate e as invariantes. Só há nova coleta quando
a fonte também está ausente no gate; só há nova síntese quando uma regra local identifica uma
afirmação específica. Parecer sem base acionável aciona a contingência local validada e não
consome a única revisão automática.

O juiz usa o mesmo modelo forte do investigador por padrão. Trocar por outro modelo forte pode
ser útil para reduzir erros correlacionados, mas deve ser comparado no benchmark antes.

### 4.5 Redator

Não possui tools. Converte somente o relatório já revisado em texto claro, próximos passos e
limitações. Como não toma a decisão técnica, pode usar um modelo menor e mais rápido.

---

## 5. Modelos e provedor

A configuração recomendada para Groq é:

| papel | variável | modelo inicial | motivo |
|---|---|---|---|
| classificador | `LLM_CLASSIFIER_MODEL` | `openai/gpt-oss-20b` | tarefa curta e estruturada |
| fontes | `LLM_SOURCE_SELECTOR_MODEL` | `openai/gpt-oss-20b` | planejamento e seleção curta |
| investigador | `LLM_INVESTIGATOR_MODEL` | `openai/gpt-oss-120b` | síntese técnica |
| juiz | `LLM_JUDGE_MODEL` | `openai/gpt-oss-120b` | decisão de maior risco |
| redator | `LLM_WRITER_MODEL` | `openai/gpt-oss-20b` | apresentação de conteúdo aprovado |

O endpoint usado é `https://api.groq.com/openai/v1` e a credencial fica em `GROQ_API_KEY`.
Cada chamada exige JSON estruturado e possui timeout. Falhas transitórias de conexão, limite ou
indisponibilidade recebem tentativas curtas. Se um agente LLM ainda falhar, a execução termina
como falha técnica; ela não é convertida em recomendação de revisão humana.

---

## 6. Estado e relatório

O `AgentState` preserva identificadores, revisão, contexto, plano, consultas, candidatos, seleção,
eventos de tools, envelopes, evidências, lacunas, conflitos, decisões, histórico de pareceres,
relatório, recomendações e resposta apresentada.

Eventos, evidências e decisões são append-only. Hipóteses, recomendações, relatório, resposta e
parecer atual são substituídos numa correção para impedir que conteúdo rejeitado sobreviva.

`RunResult` consolida somente o necessário para a interface e avaliação:

- decisão e modalidade;
- relatório da investigação;
- decisão compilada e objeções consultivas do juiz;
- resposta apresentada;
- recomendações que exigem aprovação humana;
- evidências, lacunas e métricas;
- modelo, status, latência e erro de cada agente.

`actions` permanece vazio por compatibilidade de schema. O fluxo ativo não contém nó executor e
o teste de regressão exige zero eventos `POST`/`PATCH`.

---

## 7. Checkpoints seletivos

O checkpointer nativo do LangGraph mantém retomada técnica. A API persiste snapshots de auditoria
somente nos marcos que ajudam uma pessoa a entender o caso:

- classificador: classificação e intent;
- planejamento: categorias e consultas de fonte;
- coleta: dados industriais e candidatos retornados;
- seleção: documentos escolhidos, justificativas e lacunas;
- investigador: relatório, evidências e lacunas;
- gate: campos decisivos disponíveis;
- juiz: objeções, decisão compilada, eventual contenção e tentativa de correção;
- redator: resposta apresentada;
- finalização: decisão consolidada.

Investigador e juiz continuam sendo os checkpoints principais do relatório; as três etapas de
fontes permitem acompanhar o progresso sem esperar a execução inteira terminar.

---

## 8. Interface

Há uma única experiência interna chamada **Análises**. Ela permite selecionar um caso sintético,
acrescentar contexto para uma revisão e acompanhar:

- os cinco agentes, seus modelos, latências, tokens e uso de fallback;
- consultas, candidatos, documentos escolhidos e lacunas do agente de fontes;
- relatório, evidências rastreadas, suficiência e pontos em aberto;
- parecer do juiz;
- recomendações não executadas;
- prévia da resposta em formato de mensagem, apenas para demonstrar como seria apresentada;
- consultas e checkpoints técnicos em uma seção recolhida.

Não existe campo livre de chat nem área “cliente”. Criar processamento continua sendo `POST`; o
SSE/GET apenas observa uma execução por ID, evitando que reconexões iniciem trabalho duplicado.

---

## 9. Padrões aproveitados do Projeto-Nvidia

O repositório [Projeto-Nvidia](https://github.com/viniciuscbonani/Projeto-Nvidia) confirmou três
padrões úteis: estado tipado com atualizações parciais no
[grafo](https://github.com/viniciuscbonani/Projeto-Nvidia/blob/main/app/graph.py), streaming de
progresso e relatório técnico recolhível. Esses padrões foram adaptados ao React/Vite e ao estado
industrial atual; não houve migração para Next.js ou Tailwind.

Um padrão não foi copiado: iniciar análise em uma rota `GET` de streaming. `EventSource` pode
reconectar automaticamente e repetir efeitos. Este projeto mantém `POST /api/runs` para criar e
`GET /api/runs/{id}/events` apenas para acompanhar, combinado com a chave de idempotência.

---

## 10. Avaliação

O benchmark usa os cinco modelos configurados no `.env` por padrão. `--offline` existe apenas
para testar contingências locais. O gabarito é carregado depois das execuções e agora avalia:

- decisão e recomendação correta;
- cobertura e ordem das leituras;
- schema, cobertura das fontes esperadas e termos esperados;
- ausência total de mutações;
- escalonamento como pacote para humano, nunca como ação executada;
- objeções do juiz, contenções conservadoras, revisões realmente executadas;
- avaliação semântica opcional, latência, tokens e uso de fallback. Cobertura lexical não é
  apresentada como grounding; custo fica `null` enquanto não houver tabela de preços.

O dataset v1 expande as 17 regressões para 111 execuções, formadas por 37 cenários factuais com
três variações de linguagem. Desenvolvimento, validação e teste são separados por ativo e cenário;
o gabarito permanece fora do contexto do grafo e só é carregado depois das execuções.
