# Backend

API da aplicação, execução do agente e persistência. O backend é o único componente que
conversa com a API industrial: o navegador nunca chama `api-tractian/` diretamente.

O código Python fica em `src/tractian_agent/` e os testes em `tests/`.
