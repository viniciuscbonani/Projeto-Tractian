# 03. Diferenciais e hipótese experimental

Registra os elementos que diferenciam a solução de um agente básico com tools.

---

## 1. Gate determinístico de suficiência

Antes de permitir uma conclusão ou recomendação, o sistema verifica por código se a evidência
necessária está disponível.

O gate considera, no mínimo:

- `mode` e campos presentes nas consultas decisivas;
- conflitos ainda não resolvidos;
- compatibilidade entre qualidade observada e requisitos do modelo;
- evidência exigida para a conclusão ou recomendação proposta.

Uma resposta `partial` não é rejeitada automaticamente: ela pode sustentar uma conclusão se
contiver todos os campos decisivos para aquele ramo. O gate mede condições observáveis, não
uma confiança subjetiva declarada pelo LLM.

---

## 2. Juiz antes do redator

Todo relatório técnico passa por avaliação antes de chegar ao redator:

1. verificações locais conferem evidências, lacunas e consistência com o gate;
2. um LLM-as-a-judge forte avalia fundamentação, honestidade, completude e excesso de
   confiança;
3. o parecer estruturado escolhe entre aprovar, investigar mais ou escalar;
4. somente então um modelo menor redige a apresentação.

O retorno à investigação tem limite explícito. Ausência real de evidência não é resolvida
melhorando a redação: produz revisão humana.

O juiz é um guardrail e também é objeto do benchmark externo. Sua aprovação
não constitui prova independente de correção.

---

## 3. Política para fontes divergentes

A arbitragem ocorre por regras determinísticas, nesta ordem:

1. verificar se as fontes descrevem o mesmo instante;
2. comparar a integridade dos envelopes;
3. preferir o endpoint dedicado ao conceito sobre uma cópia embutida;
4. confrontar as evidências técnicas disponíveis;
5. se nenhum critério resolver, classificar a divergência como real e escalar.

Toda arbitragem fica no estado. O sistema não seleciona silenciosamente a fonte que mais
favorece uma hipótese.

---

## 4. Raciocínio auditável por estado

O projeto não depende de chain of thought privado do modelo. Cada etapa grava dados
operacionais estruturados no estado compartilhado:

- tool, argumentos, resultado, `mode`, notas, latência e erro;
- evidência adicionada e campo de origem;
- lacunas e conflitos;
- regra aplicada;
- conclusão intermediária e próximo nó;
- recomendação de ação e sua justificativa;
- gate e parecer do juiz;
- modelo, latência, fallback e erro de cada agente.

O checkpointer preserva snapshots sucessivos da mesma execução. No final, um resultado
consolidado referencia o histórico necessário aos evals e à interface administrativa.

---

## 5. Escalonamento como resultado útil

O pacote de escalonamento contém:

- chamado, usuário e ativo;
- consultas realizadas e condição dos envelopes;
- evidências, hipóteses eliminadas, lacunas e conflitos;
- motivo exato que impediu a conclusão segura;
- recomendações que dependem de aprovação humana.

O sistema não chama o endpoint de escalonamento. Ele prepara o pacote e informa a necessidade de
encaminhamento por alguém autorizado.

---

## 6. Interface interna de análise

O frontend React possui uma única experiência para o time da TRACTIAN: iniciar uma simulação,
acompanhar os cinco agentes, inspecionar fontes, relatório e juiz e visualizar uma prévia da resposta. Não
há chat. A parte técnica fica recolhida para não competir com o relatório.

A entrada inicial é uma persona de demonstração ligada a um `x-user-id` válido. O nome
exibido nunca concede permissão. A seleção de persona não constitui autenticação.

---

## 7. Hipótese experimental principal

> Um gate explícito de suficiência de evidência reduz respostas confiantes e erradas sem
> aumentar proporcionalmente o escalonamento desnecessário.

### 7.1 Comparação

Os 17 casos correspondentes aos 16 cenários são executados com modelo, prompts,
configuração e seeds controlados em duas condições:

- gate ligado;
- gate desligado.

### 7.2 Resultados principais

| | conclusão correta | conclusão incorreta ou não fundamentada |
|---|---:|---:|
| não escalou | resposta útil | confiança indevida |
| escalou | escalonamento desnecessário | escalonamento protetivo |

Também são medidos decisão, tools necessárias e proibidas, argumentos, permissões,
fundamentação, estabilidade, custo e latência. O caminho não precisa ser idêntico ao
gabarito quando outra trajetória válida satisfizer as dependências obrigatórias.

---

## 8. Limites

- o gate depende de declarar corretamente a evidência decisiva de cada ramo;
- o LLM julgador pode compartilhar erros com o gerador;
- checkpoints só preservam aquilo que o estado registra explicitamente;
- personas de demonstração não são autenticação;
- os dados e cenários são sintéticos.
