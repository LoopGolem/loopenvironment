# LoopShell V0.8-D.1B — Prova de registro transacional

**GO para o adaptador experimental.** O estágio começou em
`5d7f0da`, após a incorporação do PR #34 e a remoção da branch remota.
O trabalho usou um worktree limpo e preservou os arquivos anteriores
do laboratório. [PR #34](https://github.com/LoopGolem/loopenvironment/pull/34).

| Dimensão | Classificação | Evidência |
| --- | --- | --- |
| Modelo de domínio | GO | Regras D.1A reutilizadas. Confirmação individual, autoria, revisão, expiração e texto inerte. |
| Persistência e recuperação | GO no perfil de laboratório | Instalação explícita do esquema, reabertura, recuperação de recibos, erro de commit e interrupções reais de processo. |
| Concorrência | GO no perfil ensaiado | Dois adaptadores SQLite concorreram pela mesma revisão. A política compartilhada ordenou revogação com aceite, retirada e confirmação. |
| Autorização experimental | GO em um processo | Verificador de sujeitos individuais, escopo exato, rotação, expiração pré-commit e negativa após reinício sem grants. |
| Contrato RPC proposto | Em revisão | Versão, schemas, grants, projeções, paginação, erros e menor subconjunto documentados. |
| Integração efetiva com LoopBridge | Não qualificada | A prova usa adaptador e armazenamento experimental. Ingresso real, autoridade entre processos e provisionamento de identidades seguem para revisão. |

## Resultados de recuperação

- **Antes do commit.** O processo saiu abruptamente após preparar
  as alterações. Reabrir mostrou oferta, revisão e autoria anteriores,
  sem recibo nem evento de aceite.
- **Durante o commit.** O processo saiu pelo callback de progresso
  da VM SQLite enquanto executava `COMMIT`. O teste aceita somente
  um estado integral. Estado, revisão, autor, recibo e auditoria
  precisam pertencer à mesma transação, e a repetição deve concluir
  com um único aceite.
- **Depois do commit.** O processo saiu antes da entrega do recibo.
  Reabrir mostrou o aceite completo. O mesmo pedido devolveu o
  recibo original na revisão 3.
- **Confirmação incerta.** Um erro SQLite injetado após o commit
  produziu `commit_unknown`. A consulta e repetição após reabertura
  reconciliaram o resultado. Um erro antes do commit reverteu tudo.
- **Abertura e prazos.** Versão futura, arquivo corrompido, revisão
  inválida, perda do caminho e vínculo inconsistente foram recusados.
  Reabrir com clock monotônico de política reiniciado preservou o
  prazo UTC. A reversão da hora bloqueou a operação e o prazo vencido
  foi materializado uma vez.

O teste de interrupção durante `COMMIT` verifica atomicidade observável
após saída de processo. A prova deixa a perda de energia, sincronização
do dispositivo e restauração de backup para outra qualificação.

## Resultados de autorização

Os testes suspenderam uma transação após preparar SQL e verificaram que
uma leitura independente ainda via o estado anterior. Uma revogação
concorrente aguardou a conclusão e em seguida recusou a repetição do
pedido. Uma expiração de grant antes do commit bloqueou inclusive a
primeira escrita. A rotação invalidou apenas a credencial anterior.
A revogação de autorização do emissor manteve elegível a oferta já
publicada sob a política D.1A. A revogação do executor retira seus
objetivos ainda abertos.

A auditoria e os recibos excluíram texto e credenciais. O texto
persistido continuou literal e o teste registrou zero execuções
de shell, processos ou avaliação de código. Workspace, stream,
captura, entrada e controle continuaram sem grant para o executor.
A lease solicitada ao contrato atual de sessão foi negada.
[Decisões e contrato candidato](../design/LOOPSHELL_V0_8_D1B_DURABLE_REGISTRY.md).

## Reprodução

Debian 13.7, Python 3.13.5 e SQLite 3.46.1 da biblioteca padrão. As
fixtures usam bancos descartáveis e credenciais sintéticas.

```sh
/usr/bin/python3 -B -m unittest discover -s tests -p '*objective_registry.py' -v
/usr/bin/python3 -B -m unittest discover -s tests
```

A execução focada aprovou 50 casos, dos quais 28 são do adaptador
durável. A suíte completa verificou 403 testes, com `LOOPSHELL_TEST_GTK=1`
em um Sway descartável para incluir as regressões GTK. O ensaio usou
apenas dependências já presentes e um runtime temporário.
[A.1 descreve a configuração descartável](LOOPSHELL_V0_8_A_LAYOUT.md#reprodução).

O Sway principal conservou PID, hora de início, configuração, versão,
saídas e workspaces. [D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5),
[M1.3B](M1_3B_TRUSTED_INPUT_FEASIBILITY.md),
[GTK 2→1](LOOPSHELL_V0_8_A_LAYOUT.md#fechamento-a2--escala-121) e o
[desempenho PARTIAL da C.4](LOOPSHELL_V0_8_C4_PERFORMANCE.md) seguem
com suas qualificações independentes.
