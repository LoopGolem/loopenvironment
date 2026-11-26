# V0.8-D.2B — Execução supervisionada

**GO experimental no perfil local descartável.** Um executor autenticado
armou uma tentativa em pausa. Um principal com grant de supervisão
autorizou o avanço, solicitou pausa e retomou o trabalho. O serviço
registrou exatamente os dois despachos do plano fixo e publicou o inteiro
`5` após a última etapa verificada. O observador acompanhou o progresso
por um grant próprio. O auditor leu o resultado e a trilha ordenada.
[Contrato D.2B](../design/LOOPSHELL_V0_8_D2B_SUPERVISED_EXECUTION.md).

## Base e decisões

O [PR #40](https://github.com/LoopGolem/loopenvironment/pull/40) foi
incorporado à `main` em `c0b1778806d0e1b103a944394bbaef68087eb0db`.
A comparação de árvores confirmou a inclusão da correção
`bde59a3dd0b4a7f1b0a407db3529de0ba5fc775e`. O desenvolvimento usou
um worktree limpo na branch `codex/v08d2b-supervised-execution`.
O checkout histórico conservou a evidência local de M1.3B.2.

A D.2B reutiliza a admissão, a autoridade de execução, a persistência e
o relógio da D.2A. O plano `add_in_two_stages` verifica o inteiro `2`
da primeira etapa e soma `3` na segunda. A tentativa conserva os
estados da D.2A. A supervisão projeta `paused`, `pause_requested`,
`stepping` ou `flowing` durante `running`. O broker confirma pausa na
fronteira entre despachos ou após a verificação da etapa em curso. Um
passo confirmou somente uma etapa. Continuar exigiu um novo comando
autorizado. Grants de supervisão e de progresso fixam a tentativa exata.
A trilha de eventos tem revisão crescente e é confirmada no mesmo
SQLite que o ciclo da tentativa. O histórico `execution/1` continua
disponível em seu perfil próprio.

| Arquivos | Papel |
| --- | --- |
| [supervision_lab.py](../../experiments/supervision_lab.py) e [supervision_storage.py](../../experiments/supervision_storage.py) | Protocolo, controles, plano, projeção, armazenamento e recuperação D.2B. |
| [execution_lab.py](../../experiments/execution_lab.py) e [execution_storage.py](../../experiments/execution_storage.py) | Pontos de extensão do perfil, autoridade, relógio e persistência existentes. |
| [supervised_execution.py](../../tools/supervised_execution.py) | Cliente tipado com entrada mascarada de credencial e verificação do UID do peer. |
| [test_supervised_execution.py](../../tests/test_supervised_execution.py) | Provas com sockets Unix, SQLite, relógio controlado e barreiras. |

## Evidências

| Prova | Resultado |
| --- | --- |
| Progresso e publicação | Zero chamadas ao iniciar em pausa. O fluxo completo invocou as etapas `(1, None)` e `(2, 2)`, nessa ordem. O resultado só apareceu em auditoria autorizada após a conclusão. |
| Acknowledgement cooperativo | Com avanço autorizado e nenhum despacho, a pausa confirmou com zero chamadas. Durante a etapa, o estado ficou `pause_requested`, com a etapa corrente visível. A verificação da etapa confirmou a pausa. Novo `continue` despachou a etapa que faltava. |
| Passo e concorrência | Dois pedidos simultâneos para a mesma revisão produziram um despacho e uma recusa por revisão obsoleta. A repetição do vencedor retornou o mesmo recibo, inclusive após perda real da resposta no socket. Contadores registraram uma chamada efetiva até o próximo comando. |
| Autoridade | Observador, auditor, emissor e executor sem grant de supervisão foram recusados. Outro objetivo e outra tentativa do mesmo objetivo ficaram fora do escopo de progresso e passo. Campos extras e o plano da D.2A foram recusados no protocolo D.2B. |
| Cancelamento, revogação e expiração | Cancelar em pausa impediu avanço. Cancelar durante a etapa manteve o desfecho imutável. Revogação de execução, revogação e reemissão de `continue`, expiração e rotação de credencial impediram resultado tardio e novo despacho. |
| Recuperação e auditoria | Commit ambíguo de despacho e parada abrupta durante computação reabriram em `uncertain`, com zero redespachos. Uma tentativa pausada entre etapas foi revogada. Conclusão confirmada sobreviveu. Após reinício, leitura sem reemissão de grant foi recusada. Alteração da sequência durável foi recusada na abertura. |
| Compatibilidade e relógio | Os dois protocolos recusaram retrocesso abaixo de commit do outro. A D.2A recusou o banco D.2B. A regressão completa exercitou a D.2A e o Registry históricos. |
| Isolamento da operação | A única função de computação somou constantes em memória e recebeu somente estado interno verificado. Texto do objetivo com aparência de comando ficou inerte. A trilha e o snapshot excluíram credenciais, texto e resultado intermediário. |

## Revisão independente e consistência de recuperação

No commit `8924bc1`, a D.2B registrava `expired` quando o prazo de
`continue` era alcançado durante uma etapa. O teste usou TTL 120 s,
grant de avanço de 5 s e uma barreira na primeira etapa. Em T+5, o
serviço registrou `expired`, com uma chamada efetiva à primeira etapa,
zero à segunda e nenhum resultado. Depois de encerrar o broker
ordenadamente, a abertura do mesmo SQLite retornou `invalid_storage`.
O validador comum comparava o timestamp da expiração somente com o
prazo original de T+120. O teste foi executado antes da alteração do
código de produção.

```sh
/usr/bin/python3 -B -m unittest discover -s tests -p 'test_supervised_execution.py' \
    -v -k test_continue_grant_expires_during_step_boundary
```

A correção preservou os checks comuns do ciclo e manteve a regra
histórica da D.2A. Na D.2B, a recuperação valida a origem pelo
timestamp e pelo comando efetivamente ativo na trilha ordenada.
O prazo daquele comando já era durável. A auditoria agora o projeta
em `deadline_unix_ms`. `status` e `audit` distinguem
`attempt_expired` e `advance_expired`. O SQLite conserva as mesmas
tabelas e versões, inclusive para os bancos criados antes da correção.

| Cobertura corretiva | Resultado |
| --- | --- |
| Expiração de autoridade | `continue` venceu antes do primeiro despacho, durante a primeira etapa e na última etapa com pausa solicitada. `step` venceu durante a etapa única. Cada caso reabriu com somente o grant de auditoria reemitido, sem redespacho ou resultado fictício. |
| Prazo da própria tentativa | A tentativa expirou em pausa com o motivo `attempt_expired`. Reabertura conservou o histórico. A D.2A reabriu uma expiração legítima e continuou recusando uma expiração antes do prazo. |
| Expiração e publicação final | O vencimento injetado depois de preparar o resultado e antes do commit abortou a publicação e preservou somente a primeira etapa verificada. Quando a publicação confirmou primeiro, o inteiro `5` permaneceu no histórico após o prazo e a reabertura. |
| Históricos antecipados inválidos | Foram recusadas trilhas estruturalmente válidas no SQLite, com timestamps concordantes nas duas tabelas, que tentavam justificar expiração antecipada por um passo consumido ou por um `continue` ainda dentro do prazo. |
| Recibo e estado atual | O cliente reconciliou recibos históricos de `pause`, `step` e `continue` após a conclusão. Os recibos mantiveram as revisões originais. O snapshot autorizado de `status` mostrou a revisão terminal e o estado `completed`. |

## Reprodução

`serve_supervision_lab` abre `supervised-lab.sock` em diretório privado
já existente. O teste `test_reference_client_uses_typed_commands_and_masks_credential`
fornece uma fixture completa de Registry, inscrição confiável de grants
e três chamadas do cliente de referência. Em uma fixture ativa, use
`--socket` com o caminho do socket experimental. O cliente solicita a
credencial em terminal com entrada mascarada.

```sh
/usr/bin/python3 -B -m tools.supervised_execution --help
/usr/bin/python3 -B -m tools.supervised_execution --socket "$socket" status "$attempt"
/usr/bin/python3 -B -m tools.supervised_execution --socket "$socket" step "$attempt" "$revision" "$request"
/usr/bin/python3 -B -m tools.supervised_execution --socket "$socket" audit "$attempt"
```

O ID da solicitação tem 32 dígitos hexadecimais minúsculos. Use a revisão
do snapshot para um comando novo e repita os mesmos campos para reconciliar
um comando cuja resposta se perdeu. Acompanhamento durante um avanço usa
outra conexão. O cliente é independente da janela de sessão LoopShell.

## Qualificação

A suíte padrão não opta pelos testes GTK. A prova GTK ocorreu em Sway
headless com Pixman, saída 1280×800, Cairo e D-Bus descartável, seguindo
o [procedimento D.1C.1](LOOPSHELL_V0_8_D1C1_TRUSTED_REGISTRY.md#reprodução).

| Comando | Resultado |
| --- | --- |
| `/usr/bin/python3 -B -m unittest discover -s tests -p 'test_supervised_execution.py'` | 29 aprovados. |
| Mesmo comando com `test_execution_d2a.py` | 33 aprovados. |
| Mesmo comando com `*registry*.py` | 88 aprovados. |
| Mesmo comando com `test_loopbridge*.py` | 62 aprovados. |
| Mesmo comando com `test_loopshell*.py`, `test_activity_view.py` e `test_combined_view.py` em execuções separadas | 50 no total, com 42 aprovados e 8 GTK omitidos por opt-in. |
| `/usr/bin/python3 -B -m unittest discover -s tests` | 503 no total, com 495 aprovados e 8 GTK omitidos por opt-in. |
| Mesmo comando com `LOOPSHELL_TEST_GTK=1` na fixture gráfica | 503 aprovados, incluindo as 8 regressões GTK. |
| `git diff --check`, links locais, contrato RPC e schemas | Aprovados. Os testes também verificaram integridade SQLite e chaves estrangeiras. |

A [CI do repositório](../../.github/workflows/regression.yml) executa a
suíte completa. Os resultados da CI do candidato ficam no PR.

## Limites e próximo marco

A prova usa mesmo UID, política volátil, até oito comandos de avanço
por tentativa com uma pausa reservada por avanço e computação
cooperativa pura. O desligamento pode deixar um despacho com desfecho
incerto. A reabertura confirma apenas o que ficou durável. A validação
da origem da expiração pressupõe o SQLite confiável e preservado e o
piso temporal compartilhado. A trilha não oferece
atestação contra adulteração privilegiada do banco, do relógio ou
rollback integral da VM. Avaliação de supervisão gráfica, operações
externas e preempção de código arbitrário ficam fora do GO.

Cross-UID da execução está **NOT RUN**, [D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5)
permanece **PARTIAL** e [M1.3B](../ROADMAP.md#m13b--trusted-input--enforcement-feasibility)
segue independente. A recomendação é revisar o diff corretivo e
aprovar o merge manual do PR #41 com a CI aprovada. A seleção do escopo
de D.2C é uma decisão posterior.
