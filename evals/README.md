# Evals

Benchmark externo do sistema completo. Usa somente os resultados e checkpoints produzidos
pela execução; o gabarito nunca entra no contexto do agente nem do avaliador de runtime.

- `metrics/`: métricas determinísticas e métricas DeepEval;
- `runners/`: execução de casos, seeds e configurações;
- `tests/`: regressões agênticas executáveis por `pytest`;
- `reports/`: geração de tabelas e gráficos, sem resultados gerados versionados.
