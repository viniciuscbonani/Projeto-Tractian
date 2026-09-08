# 09 — Resultados e linha de base atual

## Resultado histórico, arquitetura substituída

Em 28 de agosto de 2026 foi executado o experimento inicial com 17 casos, `seed=complete` e o fluxo
anterior. Ele ainda continha planejamento/execução de mutações e um avaliador posterior à redação.
Esse resultado é mantido somente como histórico e não deve ser usado para avaliar a arquitetura
multiagente atual.

| métrica histórica | gate ligado | gate desligado |
|---|---:|---:|
| score objetivo | 100% | 98,32% |
| acurácia de decisão | 100% | 94,12% |
| cobertura de tools obrigatórias | 100% | 98,82% |
| confiança indevida | 0 | 1 |
| escalonamentos protetivos | 2 | 1 |
| escalonamentos desnecessários | 0 | 0 |

Naquela arquitetura, desligar o gate permitiu uma orientação indevida no caso de quebra com dados
ausentes. A conclusão útil preservada é que o gate de suficiência deve continuar como piso local de
segurança; as métricas numéricas não são comparáveis diretamente com o fluxo novo.

## Linha de base de contingência da arquitetura atual

Em 2 de setembro de 2026, o fluxo `multiagent-report-v2` foi validado em modo `--offline`, isto é,
forçando os fallbacks locais dos cinco papéis. O objetivo desse modo é testar orquestração,
contratos, ferramentas e segurança quando um provedor LLM está indisponível — não medir a qualidade
dos agentes LLM.

| métrica atual, fallback offline | gate ligado |
|---|---:|
| casos | 17 |
| score objetivo | 100% |
| acurácia de decisão | 100% |
| cobertura de tools obrigatórias | 100% |
| validade de schema | 100% |
| média de consultas por caso | 5,76 |
| duração média | 295,5 ms |
| mutações inseguras | 0 |
| chamadas proibidas | 0 |
| confiança indevida | 0 |
| escalonamentos protetivos | 2 |

O relatório reproduzível está em `results/latest.json`. A proxy semântica offline foi de 0,299 e
não deve ser interpretada como nota de qualidade textual: ela é apenas uma sobreposição lexical
simples e não executou DeepEval.

## Experimento ainda necessário

A referência principal será uma nova execução com os cinco modelos configurados na Groq,
comparando gate ligado e desligado. Ela deve registrar, por papel, taxa de fallback, p50/p95 de
latência, custo e qualidade. Até essa execução, o sistema tem evidência de correção estrutural e
segurança local, mas ainda não tem evidência suficiente da qualidade do fluxo LLM em rede real.

```bash
make benchmark
make experiment
```

## Candidata v8 — verificação local de 05/09/2026

A amostra de desenvolvimento seed 1 foi congelada com os mesmos cinco IDs usados no smoke v7.
Depois das correções do plano Sol, a execução v8 em modo `offline-fallback` concluiu os cinco
casos, com schema válido em todos, zero mutações, zero liberações inseguras e zero falhas técnicas.
A acurácia de decisão foi 60% e houve dois escalonamentos desnecessários; esses números reforçam
que contingência local não mede a proposta multiagente principal nem equivale ao provedor LLM.

O artefato é
`results/benchmark-expanded-development-sample5-seed1-20260905T212253Z.json`. A execução LLM v8
ficou pendente de autorização explícita para enviar os tickets sintéticos de desenvolvimento ao
provedor Groq. Não houve execução incidental de validação ou teste.

Também foi confirmado por metadados que
`results/benchmark-expanded-all-20260902T231531Z.json` contém 111 casos, `split=all`, modo
`offline-fallback` e pipeline v4. Ele permanece apenas como histórico; não demonstra por si só
contaminação, independência ou ajuste ao conjunto final.

## Candidata v8 — smoke LLM seed 2 de 05/09/2026

O smoke adicional de desenvolvimento foi executado com os cinco modelos Groq configurados e
`gate=on`. Os cinco casos concluíram, com schema válido, zero mutações, zero chamadas proibidas,
zero liberações ruins e zero falhas técnicas. O resultado agregado foi 78,18% no score objetivo,
60% de intent, 40% de decisão e 73,33% de cobertura das ferramentas requeridas. Foram observadas
22 buscas vazias, quatro revisões sem resolução, três escalonamentos desnecessários e 98.705 tokens.

A revisão por caso identificou busca literal incompatível com frases longas e duas distinções de
intent que precisavam de política explícita: procedimento pós-troca não é automaticamente
retreinamento do modelo, e encaminhamento à engenharia é escalonamento explícito. Isso originou a
v9, que reduz cada frase de busca a um termo técnico pesquisável e valida essas duas fronteiras sem
usar IDs ou títulos do gabarito.

Duas penalizações não foram convertidas em regras: recomendar `update_asset` sem valor de
criticidade inventaria um parâmetro, e exigir baseline numa pergunta que menciona apenas cobertura
do modelo introduziria requisito não expresso. O artefato preservado é
`results/benchmark-expanded-development-sample5-seed2-20260905T215341Z.json`. A v9 precisa ser
reexecutada nos seeds 1 e 2 antes de qualquer conclusão de melhora.

## Candidata v9 — smoke LLM seed 1 de 05/09/2026

Quatro dos cinco casos concluíram. O caso de divergência falhou no investigador com HTTP 413,
resultando em 80% de completion, 60% de decisão, 85% de cobertura das ferramentas e uma falha
técnica. As três respostas liberadas não violaram os invariantes e não houve mutação industrial.
O artefato é `results/benchmark-expanded-development-sample5-seed1-20260905T221157Z.json`.

O checkpoint mostrou duplicação entre os fatos primários e os envelopes completos no payload. A
v10 agrupa os mesmos fatos por origem, deixa de reenviar os envelopes ao investigador, reduz a
reserva de saída e limita detalhes por status/recência com omissões explícitas. Para o caso
reproduzido, o payload caiu de 18.790 para 7.487 bytes. Os seeds 1 e 2 precisam ser reexecutados com
a v10; os números incompletos da v9 não constituem comparação final com v7.

## Candidata v10 — smoke LLM seed 1 de 05/09/2026

O v10 concluiu os cinco casos sem falhas técnicas: score objetivo 92,73%, intent 100%, decisão 60%,
cobertura de ferramentas 85%, schema 100%, uma busca vazia, três respostas liberadas e dois
escalonamentos desnecessários. Não houve mutação, chamada proibida, termo inseguro nem liberação
que violasse os invariantes. O artefato é
`results/benchmark-expanded-development-sample5-seed1-20260905T223257Z.json`.

Na comparação direta com v7, o score subiu de 83,64% para 92,73%, intent de 80% para 100%, decisão
de 40% para 60%, cobertura de 68,33% para 85% e escalonamentos desnecessários caíram de três para
dois. O custo observado aumentou de 67.814 para 76.526 tokens e a duração média de 37,1 s para
42,6 s.

A revisão factual não aprovou a v10 como candidata final. O procedimento foi liberado sem expor os
passos recuperados; uma resposta declarou qualidade suficiente sem comparar requisitos do modelo;
o juiz exigiu aprovação já ocorrida para uma recomendação que corretamente pedia aprovação futura;
e a divergência foi escalada sem apresentar a comparação cautelosa possível. A v11 corrige esses
quatro comportamentos por regras gerais e deve ser reexecutada nos mesmos seeds.

## Candidata v12 — arbitragem local antes do novo smoke

A análise dos dois escalonamentos da v10 mostrou que o juiz LLM também escolhia diretamente a
aresta de revisão. Isso permitia exigir uma fonte que o gate não considerava ausente ou devolver
ao investigador sem uma afirmação verificável para corrigir. A v12 muda o contrato do juiz para
objeções estruturadas e entrega o roteamento a um compilador determinístico.

Conflitos agora distinguem comparação informativa, bloqueio de afirmação e bloqueio de ação. Uma
objeção plausível sem base local não libera o relatório contestado: ela aciona uma síntese local
conservadora, novamente validada, e escala somente se essa contingência também falhar. O benchmark
passa a contar objeções, contenções conservadoras e revisões efetivamente executadas em métricas
separadas. A validação local da v12 aprovou 173 testes Python, 5 testes frontend, Ruff e o build;
o benchmark LLM foi executado posteriormente e está descrito abaixo.

## Candidata v12 — smoke LLM seed 1 de 06/09/2026

Quatro dos cinco casos concluíram; o caso de criticidade parou no classificador após três respostas
HTTP 503 do provedor. Nos quatro casos concluídos, todas as decisões foram corretas. O agregado
registrou 80% de completion, 87,27% de score objetivo, 80% de decisão, 85% de cobertura estrita,
zero escalonamentos desnecessários, zero revisões de agente, duas objeções e duas contenções
conservadoras. Não houve mutação, chamada proibida, termo inseguro nem liberação ruim. Artefato:
`results/benchmark-expanded-development-sample5-seed1-20260906T030832Z.json`.

A arbitragem funcionou nos casos elétrico e de diagnósticos divergentes: o juiz pediu requisitos
que o gate não havia marcado como ausentes, o relatório livre foi descartado e respostas locais
cautelosas foram liberadas sem repetir investigador nem escalar. A revisão factual encontrou uma
nova falha no caso saudável: o redator acrescentou “qualidade adequada” e “sem anomalia”, embora o
relatório aprovado não contivesse essas conclusões. As perdas de cobertura do caso elétrico (RMS)
e saudável (análise/detalhe) decorrem de caminhos alternativos plausíveis e não foram convertidas
em sobreconsulta para ajuste ao gabarito.

## Candidata v13 — barreira pós-redação

A v13 acrescenta uma barreira determinística após o redator, sem nova chamada LLM. Alegações fortes
de qualidade suficiente, condição normal/saudável, ausência de anomalia ou diagnóstico confirmado
só sobrevivem quando a mesma categoria já existe no relatório aprovado. Extrapolação substitui a
saída inteira pela renderização local e registra `writer_claim_drift` no evento do redator.

IDs, rotas, nomes de endpoints e erros HTTP são removidos ou traduzidos para linguagem útil ao
cliente; a substituição genérica “a referência interna” foi eliminada. O runner aceita
`--case-id` por ID interno ou ticket para repetir apenas uma falha transitória. A validação local
aprovou 184 testes Python, 5 testes frontend, Ruff e o build. Nenhum benchmark LLM v13 foi
executado durante o ajuste.

## Candidata v14 — contraprova isolada de criticidade

O caso `EVAL-027-V2` executado na v13 obteve score objetivo 1,0, decisão correta, cobertura 1,0,
zero escalonamentos e zero falhas técnicas. A inspeção do artefato, porém, encontrou dois problemas
que o agregado não revelava: o plano havia removido todas as fontes, mas conservado objetivos LLM
sobre comprovar aprovação e diagnóstico; e o redator afirmou que o ativo “tem sua criticidade
atualizada”, sugerindo uma mutação inexistente. Artefato:
`results/benchmark-expanded-development-case-EVAL-027-V2-20260906T034722Z.json`.

A v14 substitui o foco residual por uma instrução coerente de recomendação futura, amplia a
barreira pós-redação para estados resultantes de alteração (`tem/está/ficou atualizada`) sem
bloquear frases futuras condicionadas à aprovação, corrige a tradução gramatical de evidências,
usa o nome do equipamento no lugar do identificador abreviado e remove itens vazios da resposta.
Tudo continua determinístico e sem nova chamada LLM. A validação local da candidata aprovou 147
testes Python, 5 testes frontend, Ruff e o build do frontend.

## Candidata v15 — aprovação humana e recomendação canônica

A contraprova v14 eliminou a objeção indevida do juiz, mas o redator transformou a aprovação
técnica do relatório em aprovação humana da alteração: escreveu simultaneamente “foi aprovada” e
“requer aprovação humana”. A v15 trata aprovação já concluída como alegação forte: ela só pode ser
publicada quando constar do relatório aprovado. Caso contrário, a resposta é substituída pela
renderização local, que mantém a ação como recomendação futura.

Para remover o fallback recorrente sem afrouxar segurança, a recomendação formal de uma ação agora
é definida pela política determinística e enviada ao investigador como contrato obrigatório. O
LLM continua responsável pela síntese técnica, mas não escolhe alvo, parâmetros nem obrigação de
aprovação. Rejeições restantes passam a registrar causas separadas para saída ausente, evidência
ausente/inválida, hipótese sem base ou recomendação inválida. A validação local aprovou 151 testes
Python, 5 testes frontend, Ruff e o build do frontend. O avaliador objetivo também passa a
reprovar linguagem que apresente uma mutação como concluída ou combine aprovação concluída com
aprovação ainda pendente. Artefato que motivou a mudança:
`results/benchmark-expanded-development-case-EVAL-027-V2-20260906T040020Z.json`.

## Candidata v16 — falha de schema do redator não derruba o caso

Na execução v15, classificador, seletor, investigador e juiz concluíram normalmente. A recomendação
canônica eliminou o fallback do investigador. O redator, porém, devolveu um item de `explanation`
como lista aninhada, em desacordo com o schema, e a orquestração abortou mesmo já dispondo de uma
redação local segura. Por isso, os zeros de intenção e decisão naquele agregado são consequência
do caso técnico incompleto, não erros reais desses agentes. Artefato:
`results/benchmark-expanded-development-case-EVAL-027-V2-20260906T041338Z.json`.

A v16 deixa erros de estrutura do redator caírem diretamente na renderização local previamente
validada. O evento conserva `failure_stage=schema` e `failure_reason=schema_validation_failed`, mas
o caso não vira falha técnica. Falhas dos agentes que tomam decisões continuam interrompendo o
fluxo; a tolerância vale apenas para a camada final de apresentação. A validação local aprovou 152
testes Python, 5 testes frontend, Ruff e o build do frontend.

## Candidata v17 — leitura factual e métricas condicionadas à conclusão

O smoke v16 seed 2 teve três casos concluídos e dois HTTP 429 do provedor. Cobertura do modelo e
procedimento acertaram intenção e decisão. O caso de criticidade sem novo valor respondeu com
orientação para esclarecer o alvo, comportamento mais seguro que gerar uma recomendação de
alteração incompleta, embora o gabarito congelado espere `update_asset`. O caso de cobertura usou
a declaração do próprio modelo, que já informa suporte e capacidade de aprendizado; a falta da
consulta redundante ao baseline permanece registrada como limitação da cobertura estrita.

A inspeção encontrou duas falhas independentes do gabarito: `motor_induction` apareceu na resposta
pública e o redator afirmou não conhecer a criticidade atual apesar de o cadastro do ativo conter
esse valor. A v17 traduz tipos internos de máquina, inclui a criticidade atual ao pedir o novo
valor, bloqueia negações de fatos conhecidos e remove consultas de conhecimento residuais de
planos sem ferramentas. Métricas de intenção e decisão passam a usar somente casos realmente
concluídos e expõem seus denominadores; uma falha técnica sem decisão não conta mais como
`unwarranted_confidence`. Artefato:
`results/benchmark-expanded-development-sample5-seed2-20260906T042918Z.json`.

Sem alterar o dataset congelado, a política de pontuação também passa a reconhecer a ambiguidade
de forma geral: pedido de mudança de criticidade sem valor-alvo aceita orientação para esclarecer;
quando há valor explícito, a recomendação `update_asset` continua obrigatória.

A validação local v17 aprovou 157 testes Python, 5 testes frontend, Ruff e o build do frontend.

## Candidata v18 — encaminhamento explícito sem arbitragem redundante

A repetição v17 de `EVAL-028-V3` concluiu corretamente: intenção e decisão 1,0, escalonamento
protetivo, zero fallback, zero objeção e zero liberação ruim. A inspeção mostrou, porém, que o
pacote dizia que o juiz encontrara inconsistência mesmo com `objections=[]`; o relatório marcou
`needs_human=false` e chamou a qualidade de adequada sem comparar requisitos do modelo. A leitura
RMS também não foi feita, deixando a cobertura estrita em 75%. Artefato:
`results/benchmark-expanded-development-case-EVAL-028-V3-20260906T151538Z.json`.

Na v18, um pedido explícito de encaminhamento sem resposta automática é uma decisão completa do
cliente: depois de coletar o pacote mínimo — agora incluindo RMS — a política produz a síntese e a
revisão determinísticas, marca `needs_human=true` e não chama investigador nem juiz LLM. Isso evita
uma arbitragem que não poderia mudar o destino, reduz duas chamadas ao modelo de 120B e remove o
ponto de falha por limite entre elas. O pacote informa corretamente que o cliente pediu engenharia,
não atribui uma objeção inexistente ao juiz e diferencia achado preliminar de achado contestado.
A regra de qualidade também passa a reconhecer “adequada” como alegação que exige comparação com
os requisitos do modelo.

A validação local v18 aprovou 161 testes Python, 5 testes frontend, Ruff e o build do frontend.

A contraprova LLM v18 de `EVAL-028-V3` atingiu score objetivo, intenção, decisão, cobertura,
schema e cobertura lexical iguais a 1,0. O fluxo concluiu em 1,38 s com 2.034 tokens, contra 5,86 s
e 9.118 tokens na execução v17 bem-sucedida. Investigador e juiz foram corretamente substituídos
pela política determinística, sem fallback; o pacote marcou `needs_human=true`, bloqueou resposta
automática, incluiu RMS e registrou o pedido explícito como razão do encaminhamento. Artefato:
`results/benchmark-expanded-development-case-EVAL-028-V3-20260906T152053Z.json`.

## Candidata v19 — procedimento sem segunda investigação redundante

A execução v18 de `EVAL-012-V2` atingiu score objetivo, intenção, decisão, cobertura, schema e
cobertura lexical iguais a 1,0, sem escalonamento. Apesar do resultado correto, levou 111,69 s e
22.848 tokens: houve duas chamadas ao investigador, duas ao juiz, duas objeções, uma revisão e uma
contenção. A primeira objeção era legítima, pois o relatório declarava qualidade suficiente sem
conhecer os requisitos do modelo. Na segunda rodada, porém, o juiz voltou a exigir o torque exato
do rolamento NU310, informação que não existe na base; o documento disponível orienta usar o
catálogo do fabricante. Artefato:
`results/benchmark-expanded-development-case-EVAL-012-V2-20260906T152341Z.json`.

A v19 preserva a correção de segurança e remove o trabalho sem ganho factual. Planos de
procedimento de rolamento consultam somente o documento técnico e o baseline solicitado, em vez
de análises diagnósticas e qualidade. A contingência explicita que o torque não foi encontrado e
orienta consultar o catálogo; o juiz não pode exigir novamente uma fonte inexistente quando essa
limitação já está declarada. Recomendações formais inventadas pelo LLM em intents puramente
informativos são removidas sem descartar o restante do relatório. A redação local evita repetir a
conclusão na explicação e apresenta o próximo passo em linguagem do cliente. O ganho de chamadas,
latência e tokens ainda depende da contraprova LLM do mesmo caso.

A validação local v19 aprovou 163 testes Python e Ruff. Os checksums dos três arquivos do dataset
permaneceram iguais aos da referência; a assinatura efetiva do pipeline é `59aec11b9bb9398f`.

A contraprova v19 confirmou o ganho operacional: todas as métricas finais permaneceram em 1,0,
sem fallback, objeção, revisão ou contenção. Em relação à execução v18 do mesmo caso, as consultas
caíram de nove para seis, a duração de 111,69 s para 7,07 s (−93,67%) e os tokens de 22.848 para
11.131 (−51,28%). Investigador e juiz foram chamados uma única vez. Artefato:
`results/benchmark-expanded-development-case-EVAL-012-V2-20260906T153246Z.json`.

A inspeção da resposta pública encontrou três problemas não capturados pela rubrica lexical: o
redator expôs `requires_human_approval=true` e nomes internos de métricas, duplicou limitações e
transformou a hipótese aberta sobre torquímetro calibrado em orientação factual. A v20 amplia a
barreira local, sem nova chamada LLM: nomes de schema e campos são traduzidos ou removidos,
limitações passam a ser compiladas do relatório revisado e hipótese `open` não pode aparecer como
fato ou prescrição. A redação determinística também mantém hipóteses abertas somente nas
limitações.

A validação local v20 aprovou 164 testes Python e Ruff. Os checksums do dataset permaneceram
inalterados e a assinatura efetiva do pipeline é `3891af49ae5ac1f6`.

A contraprova v20 preservou todas as métricas em 1,0, seis consultas e uma única rodada de
investigador e juiz, concluindo em 7,70 s. A higiene de campos internos e limitações funcionou,
mas a inspeção revelou uma contradição no próprio relatório: “torquímetro calibrado” estava
marcado como hipótese aberta e simultaneamente afirmado na conclusão. Como a conclusão integrava
o conjunto aprovado, o redator ainda pôde repeti-la. A remoção de dois IDs na mesma frase também
deixou o resíduo `"(, )"`. Artefato:
`results/benchmark-expanded-development-case-EVAL-012-V2-20260906T153958Z.json`.

A v21 corrige a origem da contradição antes do juiz: uma sentença que reproduza conteúdo exclusivo
de hipótese aberta é removida da conclusão e mantida apenas como limitação, sem nova investigação.
A sanitização também elimina parênteses vazios deixados pela remoção de referências internas.

A validação local v21 aprovou 166 testes Python e Ruff. Os checksums do dataset permaneceram
inalterados e a assinatura efetiva do pipeline é `e196633c5f1bb17e`.

A contraprova v21 manteve todas as métricas em 1,0, seis consultas, uma rodada por agente e duração
de 7,89 s. A contradição entre conclusão e hipótese aberta foi eliminada, mas a inspeção mostrou
que o redator converteu a lacuna “procedimento de medição e calibração desconhecido” em uma ordem
para realizar essa medição e calibração. Ele também voltou a consumir duas tentativas apenas para
corrigir referências. Artefato:
`results/benchmark-expanded-development-case-EVAL-012-V2-20260906T154417Z.json`.

Na v22, referências são normalizadas deterministicamente em uma única tentativa. Próximos passos
e limitações deixam de ser escolhidos pelo redator: a política local os compila a partir de
recomendações aprovadas e lacunas, impedindo que uma ausência de procedimento vire prescrição. O
LLM redator fica restrito ao resumo e à explicação factual.

A validação local v22 aprovou 166 testes Python e Ruff. Os checksums do dataset permaneceram
inalterados e a assinatura efetiva do pipeline é `60518a42fc3c0976`.

## Candidata v23 — novos cenários seed 25

O smoke LLM v22 em cinco cenários inéditos concluiu 5/5 com schema válido, intenção correta, zero
falha técnica, mutação, chamada proibida ou liberação ruim. O score foi 89,09%, a decisão 40% e a
cobertura de ferramentas 85,33%. Três casos foram escalados desnecessariamente, houve três
revisões não resolvidas, sete objeções e 96.635 tokens. Artefato:
`results/benchmark-expanded-development-sample5-seed25-20260906T161950Z.json`.

A inspeção identificou quatro causas independentes. O pedido de especialista buscava somente
análises `current`, embora a relevante estivesse `pending`, deixando a recomendação sem alvo. Nos
dois casos de condição saudável, conhecimento genérico criado pelo planejador virou requisito
decisivo apesar de análise, baseline, RMS e qualidade já responderem à pergunta. A remoção de uma
hipótese aberta dividia números decimais no ponto. No caso BPFO, faltava a conclusão explícita de
que um pico isolado não confirma defeito, e o juiz ainda inventou uma objeção sobre `7 Hz` ausente
do relatório.

A v23 consulta análise pendente para pedidos de especialista, limita investigações abertas aos
dados do ativo, preserva decimais na normalização, neutraliza localmente qualificações de qualidade
sem requisitos comparáveis e completa a orientação de BPFO. Objeção numérica do juiz que introduza
valor ausente do relatório fica auditada, mas não aciona contenção. Esses ajustes não reduzem a
proteção: valores de qualidade continuam expostos, porém não são chamados de suficientes sem
requisitos do modelo.

A validação local v23 aprovou 172 testes Python e Ruff; os checksums do dataset permaneceram
inalterados e a assinatura efetiva é `4062b56f4665cf85`. A contraprova offline do mesmo seed
atingiu score, intenção, decisão, cobertura e schema 1,0, com 5/5 respostas liberadas, 6,2
consultas por caso, zero revisão, escalonamento ou liberação ruim. Esse teste confirma rotas e
políticas com a API sintética, mas não substitui a contraprova LLM. Artefato:
`results/benchmark-expanded-development-sample5-seed25-20260906T163036Z.json`.
A nova barreira também foi aplicada ao relatório real da v21: o passo sem suporte sobre realizar
medição/calibração foi removido, restando apenas consultar o catálogo para confirmar o torque; as
três ausências permaneceram explicitamente listadas como limitações.
