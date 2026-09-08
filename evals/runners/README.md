# Runners

Executores reproduzíveis da regressão original e do dataset expandido. O runner aceita
`--dataset expanded --split development|validation|test`, continua após falhas técnicas
isoladas e carrega o gabarito somente depois que todas as execuções terminam. Para repetir uma
falha transitória sem consumir novamente a amostra inteira, use `--case-id EVAL-027-V2`; o valor
também pode ser o ID interno `eval_v1_criticality_m428_v2`.
