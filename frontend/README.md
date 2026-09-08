# Frontend

Painel React interno para iniciar análises sintéticas, acompanhar os cinco agentes, inspecionar
o relatório técnico e o parecer do juiz, revisar recomendações e visualizar uma prévia de resposta.

Não há chat nem área de cliente. Tools e checkpoints ficam recolhidos para auditoria.

A interface segue o Brand Book 2026 da TRACTIAN: wordmark aprovado, Blue 600, Slate e Neutral
como paleta principal, cores complementares apenas para estados, Inter Tight em títulos e Inter
no corpo do produto.

## Executar

```bash
npm install
npm run dev
```

O Vite encaminha `/api` para `http://127.0.0.1:8001`. A simulação associa o caso à persona
sintética correspondente; isso demonstra contexto e não substitui autenticação.
