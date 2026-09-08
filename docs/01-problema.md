# 01. Entendimento do problema

Documento da primeira etapa do projeto. Descreve o problema a ser resolvido, os atores
envolvidos, o ambiente onde a solução vai operar e as restrições do domínio.

Requisitos, arquitetura, stack e implementação são tratados nos documentos seguintes.

---

## 1. Contexto de negócio

A TRACTIAN fornece monitoramento de condição de máquinas industriais e gestão de
manutenção. Sensores instalados em ativos (motores, redutores, compressores, bombas)
coletam vibração e outros sinais. Modelos de IA processam esses sinais e emitem
diagnósticos automáticos, chamados de **análises** ou **insights**, que indicam falhas
prováveis, com severidade e confiança.

Quando algo não bate com a expectativa do cliente, ele abre um chamado. Exemplos reais do
material entregue:

- "O redutor quebrou ontem e eu não recebi nenhum aviso. Por quê?"
- "O RMS está subindo há dias e nenhum insight foi gerado."
- "Recebi um alerta de desbalanceamento, mas a máquina foi balanceada semana passada."

Esses chamados **não são perguntas de suporte comum**. Responder exige investigar o estado
técnico do ativo: se o baseline estava válido, se os dados chegaram completos, se o modelo
cobria aquele tipo de falha, se houve manutenção recente que invalidou a referência.

---

## 2. Como funciona hoje

Um engenheiro de suporte recebe o chamado e investiga manualmente. Ele consulta a
plataforma, cruza informações de várias fontes, forma uma hipótese sobre a causa e
responde ao cliente ou executa uma ação corretiva na plataforma.

Esse trabalho é caro e não escala: cada chamado consome tempo de um especialista.

---

## 3. O problema a resolver

Substituir ou assistir esse engenheiro por um agente de IA que:

1. recebe o chamado do cliente,
2. investiga o estado do ativo consultando a plataforma,
3. interpreta as evidências, e
4. decide o que fazer.

A decisão final se enquadra em três categorias:

| decisão | significado |
|---|---|
| **Orientar** | explicar ao cliente, sem alterar nada na plataforma |
| **Agir** | executar uma ação justificada na plataforma |
| **Escalar** | encaminhar o caso para um engenheiro humano |

O agente precisa tomar **a mesma decisão que um engenheiro tomaria**.

> O quadro acima descreve o desafio original. No recorte adotado após a revisão com a liga,
> **Agir** foi substituído por **Recomendar**: o sistema prepara a ação e a justificativa, mas a
> execução fica fora do agente e depende de aprovação humana.

---

## 4. Atores

| ator | papel |
|---|---|
| **Cliente** | abre o chamado. Tem um papel na empresa (operador, mecânico, coordenador, gerente) que determina o que pode ser feito em seu nome. |
| **Agente** | investiga e decide. É o sistema a ser construído. |
| **Engenheiro humano** | recebe os casos escalados. Precisa entender o que já foi investigado. |
| **Plataforma** | fonte das evidências e alvo das ações. Exposta como API. |

---

## 5. As dificuldades reais (levantadas pela TRACTIAN no kickoff)

Estas são as dificuldades que a parceira declarou explicitamente. São elas que definem
onde está o valor do projeto.

### 5.1 Volume de contexto

Resolver um chamado exige muita regra de negócio: como interpretar um baseline, quando um
insight é confiável, que ação cabe em cada situação, o que exige permissão. Essas regras
mudam com o tempo, e precisam chegar ao agente sem que ele seja reescrito a cada mudança.

### 5.2 Avaliação é sutil

Duas perguntas que hoje não têm resposta:

- Ao mudar o prompt, como saber que o agente não piorou?
- Quando deu errado, **onde** quebrou? Foi a API que devolveu dado ruim, ou foi o agente
  que raciocinou mal?

As nuances (tom, completude, honestidade da resposta) tornam a avaliação difícil de
automatizar.

### 5.3 Calibração de confiança

O ponto que a TRACTIAN chamou de **maior dificuldade**: fazer o agente admitir que não
sabe.

Existem dois modos de falha simétricos:

- **confiante demais:** responde com convicção sobre algo que não verificou. Destrói a
  confiança do cliente.
- **incompetente demais:** escala tudo. Não gera valor nenhum; o engenheiro continua
  fazendo o trabalho.

A regra declarada é escalar diante de ambiguidade ou dúvida. Mas o agente precisa
reconhecer que está em dúvida, e essa é a parte difícil.

### 5.4 Escalonamento tem que carregar o raciocínio

Ao escalar, o agente deve entregar **todo o raciocínio acumulado até ali**, incluindo o que
consultou, o que encontrou, onde travou. Escalar sem contexto apenas transfere o problema
inteiro de volta ao humano.

### 5.5 Fontes divergentes: problema em aberto

Quando duas fontes da plataforma se contradizem, **a própria TRACTIAN não sabe qual deve
ser o comportamento correto**. Pediram explicitamente criatividade nesse ponto.


---

### 5.6 A informação chega degradada

Consultas à plataforma podem retornar dado completo, parcial, inconclusivo, conflitante,
ou simplesmente indisponível. O estado da resposta é declarado explicitamente. Um agente
que ignora esse estado passa a afirmar coisas sobre dado que não recebeu.

Isso vale inclusive para as consultas à base de conhecimento: a regra de domínio pode não
chegar no momento em que o agente precisa dela.

### 5.7 Permissões são heterogêneas

Quem abriu o chamado tem um papel, e o papel determina que ações podem ser executadas em
seu nome. É possível chegar ao diagnóstico correto e ainda assim propor uma ação que
aquele usuário não pode executar.

### 5.8 Ações são irreversíveis e exigem justificativa

Qualquer alteração de dados na plataforma precisa de justificativa. Não há ciclo de
confirmação: uma chamada aceita já é a ação executada.

## 6. Domínio técnico necessário

Esta seção existe para quem lê o documento. Sem estes conceitos não é possível entender o
que os chamados estão perguntando, nem julgar se uma resposta do agente está certa.

Nenhum conhecimento prévio é assumido.

### 6.1 De onde vem a vibração

Todo motor, redutor, bomba ou compressor vibra enquanto funciona. Isso é normal. O que
muda quando aparece um defeito é o **padrão** dessa vibração.

Um sensor colado na máquina mede a vibração o tempo todo. Dele saem duas informações
diferentes:

**RMS:** um número que resume "quanta vibração no total". É como o volume de um som:
não diz o que está tocando, só o quão alto está. Medido em milímetros por segundo (mm/s).

**Espectro:** a mesma vibração, separada por frequência. Se o RMS é o volume, o espectro é
saber *quais notas* estão tocando. Isso importa porque cada tipo de defeito produz sua
própria frequência característica. É por isso que o sistema consegue dizer *qual* é o
defeito, e não apenas que existe um.

### 6.2 O problema: quanto é "muito"?

Suponha que uma máquina esteja com RMS de 5 mm/s. Isso é ruim?

Depende inteiramente da máquina. Um britador de mineração vibra muito por natureza; 5 mm/s
pode ser um dia tranquilo. Um ventilador pequeno de precisão a 5 mm/s pode estar prestes a
quebrar.

Existem normas com tabelas por classe de máquina, mas são grosseiras. A plataforma faz
diferente, e isso é central para o projeto:

> **Baseline é o "normal" daquela máquina específica, aprendido a partir do histórico dela
> mesma.**

O sistema observa a máquina por um período enquanto ela está saudável e registra: esta aqui
vive em torno de 2,1 mm/s.

A partir disso, o **limiar de alarme** é calculado como o normal dela mais uma tolerância. Cada
máquina tem o seu.

**A consequência importante:** o limiar só existe porque o baseline existe. Sem baseline,
não há limiar. Sem limiar, não há como dizer que a vibração está alta.

### 6.3 O baseline nem sempre está pronto

Esta é a parte que faz a maioria dos chamados fazer sentido. O baseline tem três estados:

| estado | o que significa |
| :--- | :--- |
| `learning` | Máquina nova ou sensor recém-instalado. O sistema ainda não observou histórico suficiente para saber o que é normal ali. **Não existe limiar.** |
| `established` | Já aprendeu. O limiar é válido e dá para detectar desvio. |
| `invalidated` | Houve manutenção, troca de peça ou mudança de configuração. O "normal" antigo não vale mais. **Precisa reaprender do zero.** |

Se o baseline está em `learning` ou `invalidated`, a vibração pode subir sem que exista uma
referência para comparação. **O sistema não tem como avisar.**

Isso não é uma falha do sistema. É uma limitação real, e explicá-la ao cliente é
frequentemente a resposta correta.

### 6.4 Dois jeitos de detectar defeito

Nem toda falha depende do baseline. São dois mecanismos diferentes:

**Detecção por desvio:** desbalanceamento, desalinhamento, falha de rolamento e falha
elétrica. Todas funcionam comparando o sinal atual com o normal aprendido. **Exigem
baseline `established`**, senão não há de que desviar.

**Detecção por sintoma:** falha de lubrificação. Ela tem uma assinatura própria no
espectro: se essa assinatura aparece, o defeito existe, ponto. **Não precisa de baseline.**
Pode ser detectada numa máquina instalada ontem.

Esta distinção é a mais fácil de errar. Um agente que aprendeu "sem baseline não dá para
detectar nada" vai errar todo caso de lubrificação.

### 6.5 Os outros elementos

**Análise (ou insight):** o diagnóstico automático emitido pelo modelo. Traz o tipo de
falha, a severidade, o quanto o modelo está confiante, a evidência que sustenta a conclusão,
as limitações, e por qual dos dois mecanismos acima foi detectada.

**Qualidade dos dados:** o quanto o sinal chegou completo, limpo e recente. Cada modelo
declara mínimos que precisa para funcionar. Dado abaixo do mínimo não impede o diagnóstico
de ser emitido, mas reduz sua confiabilidade. O agente precisa comparar a qualidade observada
com os requisitos declarados.

**Cobertura do modelo:** nem todo modelo atende todo tipo de equipamento. Um modelo pode
não suportar máquinas de rotação muito baixa, por exemplo.

### 6.6 Como um chamado é investigado

Quase todos os chamados são variações da mesma pergunta: *"por que o sistema disse isso (ou
não disse nada)?"*

E quase todos se resolvem percorrendo esta cadeia, **nesta ordem**. Cada resposta elimina
as perguntas seguintes:

```
o cliente esperava um diagnóstico e não recebeu
(ou recebeu um que não bate com a realidade)
        ↓
o modelo cobre esse tipo de equipamento e de falha?
        ↓
esse tipo de falha é detectado por desvio ou por sintoma?
   (se for por sintoma, o baseline é irrelevante e pode ser ignorado)
        ↓
o baseline está established?
   (se learning ou invalidated, não havia limiar e não havia como avisar)
        ↓
os dados chegaram com qualidade suficiente para o modelo?
        ↓
o modelo chegou a processar, ou está atrasado?
        ↓
causa raiz identificada: orientar, agir ou escalar
```

**Esta cadeia é o que o engenheiro humano faz hoje, mentalmente.** É ela que o agente
precisa reproduzir.

### 6.7 Um exemplo completo

Chamado real do material (TKT-INV-04):

> *"O redutor da correia transportadora quebrou ontem e eu não recebi nenhum aviso. Por
> quê?"*

Sem os conceitos acima, não dá nem para classificar essa pergunta. Com eles, sabe-se que
existem cinco respostas possíveis e completamente diferentes:

1. **O baseline estava em `learning`:** máquina nova demais, sem limiar. O sistema não
   tinha como saber. Resposta: não falhamos, ainda não havia histórico.
2. **O baseline foi `invalidated`** por manutenção recente e ninguém reaprendeu. Resposta:
   há uma lacuna no processo.
3. **Os dados não chegaram:** sensor offline ou falha de leitura. Resposta: problema de
   cobertura de sensor, não de diagnóstico.
4. **O modelo não cobria** esse tipo de falha naquele equipamento.
5. **O sistema avisou e o aviso não chegou** ao cliente. Aqui sim houve falha real.

Descobrir qual delas é a certa exige consultar a plataforma na ordem da seção 6.6.

### 6.8 Onde estas regras vivem

As regras acima não precisam ser embutidas no agente. A plataforma expõe uma base de
conhecimento consultável, com procedimentos, glossário e guias de suporte, que contém boa
parte delas.

Quatro chamados perguntam diretamente por esse conteúdo: TKT-CTX-01 (procedimento de troca
de rolamento), TKT-CTX-02 (o que é BPFO), TKT-CTX-03 (a partir de que valor é alarme) e
TKT-INV-11b (como detectar sem baseline).

A forma como o agente obtém essas regras é uma decisão de arquitetura, registrada em
`04-arquitetura.md`: o conhecimento é consultado sob demanda e o estado do envelope da
consulta participa do gate de suficiência.

---

## 7. O que caracteriza uma boa solução

Critérios declarados pela parceira e pelo material acadêmico:

- **O raciocínio importa mais que a resposta.** Uma resposta certa por caminho errado vale
  menos que um caminho correto que termina em escalonamento honesto.
- **Honestidade sob incerteza.** Reportar dado ausente como ausente, não preencher lacuna
  com suposição.
- **Fundamentação.** Toda afirmação deve se apoiar em evidência efetivamente recuperada.
- **Rastreabilidade.** Deve ser possível inspecionar o que foi chamado, o que voltou e por
  que cada decisão foi tomada.
- **Comportamento previsível.** A parceira citou "parecer ter até ser um sistema
  determinístico" como algo que impressionaria.
- **Respeito a permissões e justificativas** em ações de impacto.

---

## 8. Escopo do problema

**Dentro do escopo implementado:**

- chamados de clientes sobre comportamento de monitoramento e diagnóstico de ativos
- investigação via consulta à API
- decisão entre orientar, recomendar e escalar
- recomendação estruturada de ações, sempre sujeita a aprovação humana
- painel interno de análise e prévia de como a resposta seria apresentada
- avaliação sistemática da qualidade e confiabilidade do agente construído

**Fora do escopo:**

- conversas multi-turno com o cliente além do necessário para o chamado
- chat voltado ao cliente e execução automática de ações
- interação com sistemas externos à API fornecida
- diagnóstico de vibração a partir de sinal bruto (o diagnóstico já vem pronto do modelo;
  o agente interpreta, não diagnostica)
- qualquer uso de dados reais de clientes; todo o material é sintético

---

## 9. Decisões de projeto

As principais decisões derivadas do entendimento do problema são:

| questão | encaminhamento | registro |
|---|---|---|
| Modo de operação | ferramenta interna multiagente, com recomendação ou revisão humana quando necessário | `04-arquitetura.md` |
| Fontes divergentes | arbitragem determinística; divergência real não resolvida exige escalonamento | `03-diferenciais.md` |
| Evidência suficiente | gate determinístico antes da composição da resposta | `03-diferenciais.md` e `04-arquitetura.md` |
| Pacote de escalonamento | leva consultas, evidências, lacunas, conflitos e ponto de interrupção | `04-arquitetura.md` |
| Regras de negócio | consulta sob demanda à base de conhecimento; resposta degradada permanece explícita | `04-arquitetura.md` |
| Ordem da investigação | plano do investigador LLM limitado por catálogo de tools e piso de evidência | `04-arquitetura.md` |
| Hipótese experimental | comparar o mesmo grafo com o gate ligado e desligado | `03-diferenciais.md` |

---

## 10. Referências no material entregue

| conteúdo | arquivo |
|---|---|
| Enunciado completo do projeto | `api-tractian/STUDENT-GUIDE.md` |
| Chamados que definem o espaço do problema | `api-tractian/docs/support-tickets.md` |
| 16 cenários de teste comentados | `api-tractian/docs/test-scenarios.md` |
| Modelo de dados e comportamento probabilístico | `api-tractian/docs/data-schema.md` |
| Contrato da API | `api-tractian/docs/api-contract.openapi.yaml` |
| 17 casos de entrada do agente | `api-tractian/agent-input/cases.json` (gerado por `make setup`) |
| Gabarito (uso restrito à avaliação) | `api-tractian/eval/` (gerado por `make setup`) |

Há 17 chamados, mas 16 cenários porque o CEN-07 encadeia TKT-INV-09 e TKT-EXE-12.
