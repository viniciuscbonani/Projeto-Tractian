# Backend

API da aplicação, execução do agente e persistência. O backend é o único componente que
conversa com a API industrial: o navegador nunca chama `api-tractian/` diretamente.

O código Python fica em `src/tractian_agent/` e os testes em `tests/`.

## Executar

Na raiz do projeto:

```bash
make setup
make dev-industrial  # terminal 1
make dev-backend     # terminal 2
```

A documentação própria fica em `http://127.0.0.1:8001/docs`. A configuração dos cinco modelos
fica em `.env.example`; contingências locais existem para falhas, mas o uso principal é
multiagente. `MODEL_VERSION_MAP` documenta a ponte
temporária `model_version=3.2.1` → `model_id=mdl_vib_v3`, necessária porque a análise não expõe o
identificador do modelo.

`APP_DATABASE_PATH` guarda sessões, execuções, resultados e os snapshots exibidos na interface.
`GRAPH_CHECKPOINT_PATH` guarda os checkpoints nativos do LangGraph usados para histórico e
retomada pelo `thread_id`.

O grafo ativo usa somente leituras. Timeouts são erros tipados e geram lacunas explícitas; uma
recomendação de ação nunca é transformada em `POST` ou `PATCH` pelo agente.
