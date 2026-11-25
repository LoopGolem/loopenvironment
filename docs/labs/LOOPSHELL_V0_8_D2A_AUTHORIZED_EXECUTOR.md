# V0.8-D.2A — Primeiro executor autorizado

**Resultado: GO experimental no perfil local descartável.** O primeiro
executor do LoopBridge realizou `2 + 3` em memória após autorização
explícita, com início durável e resultado inteiro `5` consultável por
um principal com grant de auditoria. O aceite pelo Registry registrou
apenas o recebimento. [Contrato D.2A](../design/LOOPSHELL_V0_8_D2A_EXECUTOR.md).

## Base e implementação

O PR [#39](https://github.com/LoopGolem/loopenvironment/pull/39) estava
incorporado à `main` em `51655318f4827b93eb710a50273cb739ec28da15`.
A árvore de integração estava limpa. O trabalho usou um worktree
dedicado na branch `codex/v08d2a-authorized-executor`. As evidências
locais de M1.3B.2 ficaram em seu checkout original. O [GO experimental
D.1C.4](LOOPSHELL_V0_8_D1C4_CROSS_UID_EXECUTION.md) continua restrito à
entrega do Registry.

| Arquivo | Papel |
| --- | --- |
| [execution_lab.py](../../experiments/execution_lab.py) | Perfil opt-in, RPC `execution/1`, grants exatos, cálculo e decisões do ciclo. |
| [execution_storage.py](../../experiments/execution_storage.py) | Esquema, consulta ao alvo confiável, eventos duráveis e recuperação. |
| [durable_objective_registry.py](../../experiments/durable_objective_registry.py) e [registry_lab.py](../../experiments/registry_lab.py) | Reuso experimental de autenticação, SQLite e locks com os valores históricos preservados por padrão. |
| [test_execution_d2a.py](../../tests/test_execution_d2a.py) | Provas em sockets Unix e SQLite temporários, com relógio controlado, eventos e barreiras. |
| [Contrato D.2A](../design/LOOPSHELL_V0_8_D2A_EXECUTOR.md), este relatório e [roadmap](../ROADMAP.md#v08--loopshell-and-session-supervisor) | Decisões, qualificação e escopo do marco. |

O autorizador e o executor têm grants distintos, vinculados a principal
autenticado, executor, objetivo, revisão e operação. O início exige a
identidade do principal confirmado no Registry. A política e o estado
do Registry permanecem estáveis até o commit que admite, inicia,
cancela ou publica. Uma única transação SQLite consulta a revisão
aceita e grava o evento da execução. O estado atual vem do último evento.

`admitted` pode ir para `running`, `cancelled`, `revoked` ou
`expired`. A partir de `running` também são possíveis `completed`,
`failed` e `uncertain`. A revisão começa em 1 e chega no máximo a 3.
Eventos registram vínculo, atores, prazos e desfechos sem credenciais ou
texto do objetivo.

## Matriz de qualificação

| Prova | Resultado observado |
| --- | --- |
| Cadastro, entrega e execução | Executor cadastrado e confirmado. Objetivo criado, oferecido e aceito sem tentativa de execução. Autorização explícita admitiu uma tentativa. Início durável precedeu o cálculo, e o auditor leu o inteiro `5` na revisão 3. |
| Identidade e autoridade | Recusa de cliente anônimo, principal errado mesmo com grant de operação no escopo, grant ausente, objetivo não aceito, executor fora do escopo ou indisponível, revisão obsoleta e autorização expirada. Um autorizador distinto do emissor do Registry concluiu o fluxo sob grant próprio. |
| Entrada, isolamento e auditoria | Operação desconhecida, identidades no payload, argumentos, versões, métodos e campos inesperados ou duplicados foram recusados. O texto com aparência de comando permaneceu no Registry. Só o auditor autorizado obteve os eventos e o resultado. O broker histórico não expôs `execution/1`. |
| Início e encerramento concorrentes | A admissão confirmada antes da revogação permaneceu no histórico. Revogação anterior bloqueou a admissão. Cancelamento, revogação e expiração anteriores ao início bloquearam a chamada. Após o início, cancelamento, revogação, expiração, rotação de credencial e indisponibilidade impediram sucesso quando venceram a publicação. Publicação confirmada sobreviveu aos concorrentes. |
| Idempotência e falhas | Pedidos simultâneos retornaram o mesmo ID. Divergências foram recusadas. Inícios simultâneos despacharam uma soma. Falha de cálculo ou retorno inválido gravaram `failed` sanitizado. Revogar com erro de commit removeu a autoridade, e reemitir o grant não reativou a tentativa. |
| Banco e recuperação | O esquema histórico foi recusado no perfil D.2A. Uma trilha sem início durável falhou na validação da reabertura. Após commit ambíguo ou parada abrupta, um início durável sem resultado passou a `uncertain`, e uma admissão pendente foi revogada. A conclusão confirmada com resposta perdida foi reconciliada. Uma nova execução após a interrupção exigiu nova autorização. |

## Reprodução e regressões

Ambiente local com Python 3.13.5, SQLite 3.46.1 e Sway 1.10.1. O
perfil pode ser reproduzido pelo primeiro teste da tabela, que inicia
seu próprio servidor `execution-lab.sock` e aplica credenciais e grants
descartáveis. A suíte GTK usou Sway headless com Pixman, saída 1280×800,
Cairo e D-Bus descartável. Foram usadas as variáveis
`LOOPSHELL_TEST_GTK=1`, `GSK_RENDERER=cairo` e `GIO_USE_VFS=local`
do [procedimento D.1C.1](LOOPSHELL_V0_8_D1C1_TRUSTED_REGISTRY.md#reprodução).

| Comando | Resultado |
| --- | --- |
| `/usr/bin/python3 -B -m unittest discover -s tests -p 'test_execution_d2a.py' -v` | 21 testes aprovados. |
| `/usr/bin/python3 -B -m unittest discover -s tests -p '*registry*.py'` | 88 testes aprovados. |
| `/usr/bin/python3 -B -m unittest discover -s tests -p 'test_loopbridge*.py'` | 62 testes aprovados. |
| `/usr/bin/python3 -B -m unittest discover -s tests` | 462 testes, com 454 aprovados e 8 GTK omitidos por opt-in. |
| `/usr/bin/python3 -B -m unittest discover -s tests` na fixture GTK acima | 462 testes aprovados, incluindo as 8 regressões GTK. |
| `git diff --check`, links locais e correspondência entre contrato e schema RPC | Aprovados. A prova de armazenamento verificou também integridade SQLite e chaves estrangeiras. |

A [CI existente](../../.github/workflows/regression.yml) inclui os
novos testes na suíte completa. O resultado da CI deste candidato é
registrado no PR.

## Limites e próximo marco

O GO cobre a fixture local sob o mesmo UID, com armazenamento privado
confiável e uma operação determinística em memória. Cross-UID D.2A e
acesso a recursos gráficos privados reais estão **NOT RUN**. A
[matriz D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5)
permanece **PARTIAL** e [M1.3B](../ROADMAP.md#m13b--trusted-input--enforcement-feasibility)
segue como gate independente. O clone D.1C.4, contas Linux, ACLs,
serviços instalados e a configuração do Sway principal ficaram fora
da prova.

A política de execução é volátil, o armazenamento tem capacidade fixa
de 256 tentativas e a materialização de expiração é sob demanda. Após
uma interrupção, recuperar depende do banco preservado e da verificação
da parada da instância anterior. Esses limites são adequados ao cálculo
puro. Efeitos externos, armazenamento adulterado, revogação distribuída
e garantias de execução exatamente uma vez para outros tipos de
operação estão fora da qualificação.

Próximo marco recomendado é a revisão independente da fronteira D.2A e
da evidência do PR. Se essa revisão exigir prova cross-UID da execução,
a prova deve ter plano e autorização próprios. D.2B, D.2C e integração
de agente de IA dependem de decisão posterior.
