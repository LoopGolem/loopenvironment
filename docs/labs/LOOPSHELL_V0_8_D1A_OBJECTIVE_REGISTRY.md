# LoopShell V0.8-D.1A — Prova do registro e da entrega de objetivos

**GO para o protótipo em memória.** O PR #33 foi incorporado à `main`
em `1340e88`. A branch remota de C.4 estava removida. O experimento
partiu de um worktree limpo e preservou os arquivos do laboratório
anterior. [PR #33](https://github.com/LoopGolem/loopenvironment/pull/33).

| Dimensão | Classificação | Evidência |
| --- | --- | --- |
| Domínio | GO | Registro pendente, confirmação, suspensão e revogação. Um executor consultou ofertas vigentes e registrou aceite ou recusa. |
| Consistência das transições | GO em uma instância | Prazo inclusivo, revisões, recibos por principal e corridas por barreira. Estados terminais preservados e uma única mudança por disputa. |
| Autorização abstrata | GO no adaptador de laboratório | Verificador real `Identities` com credenciais sintéticas e escopos separados por executor. Credencial incorreta, vínculo alheio, falta de escopo e repetição após revogação foram recusados. |
| Integração real com LoopBridge | Não qualificada | O módulo roda isolado em memória. Ingresso, grants de produto, persistência e auditoria estão na proposta D.1B. |

A fixture criou e ofereceu um texto que contém sintaxe de shell e
Python. O executor recuperou o texto intacto. A prova instrumentou
chamadas de shell, processos, avaliação de código e abertura de
arquivos e registrou zero chamadas durante a entrega e o aceite.
Uma sessão de teste usando as classes atuais de autoridade ficou
com a mesma revisão de política, histórico, grants e lease.
O delegado que aceitou o objetivo continuou sem acesso a workspace,
stream, captura, entrada ou controle. O pedido de lease foi negado.
Isso exercita o contrato local e sua separação da autoridade de sessão.

As corridas começam com threads sincronizadas por barreira. As asserções
aceitam as duas ordens válidas e conferem o resultado final. Casos em
ordem explícita cobrem derrota por revisão antiga, aceite anterior à
revogação, revogação anterior ao aceite e desduplicação. A fixture
mantém a política fixa durante as corridas. Alterações de escopo
entre chamadas também foram testadas. A atomicidade com um serviço
de políticas e armazenamento persistente segue para D.1B.
[Contratos D.1A e proposta D.1B](../design/LOOPSHELL_V0_8_D1A_OBJECTIVE_CONTRACTS.md).

## Reprodução

Na raiz do repositório, com Python 3.13 do Debian 13.7:

```sh
/usr/bin/python3 -B -m unittest discover -s tests -p test_objective_registry.py -v
/usr/bin/python3 -B -m unittest discover -s tests
```

A execução focada aprovou 22 testes. A suíte completa aprovou
375 testes com os casos GTK opt-in também ativados. Para reproduzir
esse modo, use um Sway headless descartável com runtime e D-Bus
isolados e execute `LOOPSHELL_TEST_GTK=1 /usr/bin/python3 -B -m unittest
discover -s tests` com o display descartável selecionado. O ensaio
usou GTK Cairo e Sway Pixman, saída 1024×768 em escala 1, com as
dependências já presentes. A regressão GTK usa janelas comuns.
[Configuração descartável de referência](LOOPSHELL_V0_8_A_LAYOUT.md#reprodução).

PID e hora de início, configuração, versão, saídas e workspaces do
Sway principal coincidiram nas leituras de antes e depois.
Os gates [D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5)
e [M1.3B](M1_3B_TRUSTED_INPUT_FEASIBILITY.md), a
[limitação GTK 2→1](LOOPSHELL_V0_8_A_LAYOUT.md#fechamento-a2--escala-121)
e a [qualificação PARTIAL de desempenho da C.4](LOOPSHELL_V0_8_C4_PERFORMANCE.md)
preservam seus próprios critérios.
