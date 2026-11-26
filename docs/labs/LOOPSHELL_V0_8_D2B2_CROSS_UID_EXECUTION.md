# V0.8-D.2B.2 — Qualificação cross-UID da supervisão

**Resultado global PARTIAL.** A execução supervisionada teve **GO experimental**
nas fases A–D. A remoção da fixture teve **GO** e o baseline da unidade
instalada foi preservado. A preservação do baseline gráfico agregado ficou
**INCONCLUSIVA**. Nenhuma violação de segurança foi observada no ensaio.

A [evidência JSON sanitizada](evidence/LOOPSHELL_V0_8_D2B2_CROSS_UID_EXECUTION.json)
consolida as saídas de terminal fornecidas pelo operador
(`operator_supplied_terminal_output`). O operador executou e encerrou a
prova manualmente. Os [testes locais do preflight](LOOPSHELL_V0_8_D2B1_CROSS_UID_PREFLIGHT.md#evidência-local-do-preflight)
usaram o mesmo UID e simularam a instalação cross-UID. A coleta histórica
abaixo e os testes sintéticos da metodologia futura têm procedências
distintas. Esta consolidação usou as saídas fornecidas e a revisão Git,
sem acesso ao clone ou repetição do ensaio.

## Revisão e ambiente

O [PR #42](https://github.com/LoopGolem/loopenvironment/pull/42) incorporou
o preflight D.2B.1 à `main` por squash. A revisão confirmou no GitHub o
merge e, localmente, a igualdade das árvores e o SHA-256 do TAR reexportado
do commit aprovado com a mesma máscara.

| Item | Valor |
| --- | --- |
| Commit de squash na `main` | `c90056b430bbd251f74fc28dd1172c8ecaf23cc7` |
| Commit aprovado para o ensaio | `aed93a79bcdb5e212607443310124f7da3fa6c20` |
| Árvore Git de ambos | `6a1561100f7a206697ca1d72edf5347e708a5f17` |
| SHA-256 do TAR aprovado | `b1398475031faf7fa2ee7ff2d7686bc7a0ffb50ad2ad198407455af78bfe4545` |
| Ambiente informado | Debian GNU/Linux 13.7 (trixie), VirtualBox, hostname `looplab-d1c3` |
| Snapshot prévio confirmado pelo operador | `D2B1 - Baseline antes do ensaio cross-UID` |
| Run ID | `a4336395664c0954` |
| Desktop e serviço experimental | `vboxuser` (`1000:1000`) e `loopbridge-svc` (`980:980`) |
| Unidade instalada no início | `loopbridge.service` inativa e desabilitada |

O operador descartou o clone anterior da D.1C.4 e clonou integralmente o
Lab original em uma VM independente. Confirmou o isolamento previsto e a
presença das dependências. O machine ID foi regenerado e conferido entre
systemd e D-Bus. O boot ID foi verificado antes de conceder uma nova
autorização explícita para a fixture, com janela de 20 minutos nos relógios
UTC e monotônico.

No Lab original, antes da clonagem, o operador produziu o TAR via
`git -c tar.umask=0022 archive`. Conferiu o SHA-256 na exportação
direta do commit aprovado, na cópia armazenada no Lab original e na
cópia herdada pelo clone. A clonagem transportou o TAR aprovado e
dispensou a transferência por ISO prevista no [runbook](LOOPSHELL_V0_8_D2B1_CROSS_UID_PREFLIGHT.md).

| Provisionamento observado | Identidade e modo |
| --- | --- |
| `/run/loop-supervision-d2b1-a4336395664c0954` | `0755`, root:root |
| `private` | `0700`, `980:980` |
| `ingress` | `0710`, `980:980`, ACL nominal de travessia `user:1000:--x` |
| Socket RPC | `0620` |
| Código extraído | Dono root, sem escrita pelo grupo ou terceiros |

## Fase A — Ingresso e isolamento

O broker inicial teve PID `2837`. Após reinício, o PID foi `3019`.
As duas instâncias usaram UID/GID `980:980`, com cliente sob UID `1000`.
`SO_PEERCRED` confirmou as identidades esperadas. Cada instância recusou a
credencial inválida e o principal sem grant. Nenhum dado auxiliar foi
observado no RPC. A sentinela usou o FD `4` nas duas instâncias.

| Acesso direto pelo UID 1000 | PID 2837 | PID 3019 |
| --- | --- | --- |
| Travessia do diretório privado | `EACCES` | `EACCES` |
| Listagem do diretório privado | `EACCES` | `EACCES` |
| Leitura do SQLite | `EACCES` | `EACCES` |
| Leitura do manifesto | `EACCES` | `EACCES` |
| Conexão ao socket sentinela privado | `EACCES` | `EACCES` |
| Abertura do descritor sentinela em `/proc` | `EACCES` | `EACCES` |

Foram **12 negativas diretas**, todas com `errno 13`. O alcance desta
evidência é a fixture com uma sentinela experimental.

## Fases B e C — Fluxo e disputas de supervisão

Registro, confirmação, oferta e aceite foram concluídos. Nove tentativas
foram admitidas com autorização de execução separada e os grants de
supervisão foram armados explicitamente. O observador recebeu recusa ao
solicitar controle. O ensaio preservou o recibo de passo e exercitou
separadamente os prazos virtuais do harness e a janela real de operação.

| Caso | Computações observadas e esperadas |
| --- | ---: |
| `flow` | 2 |
| `before_dispatch` | 0 |
| `pause_running` | 2 |
| `step_race` | 1 |
| `revoked` | 1 |
| `advance_expired` | 1 |
| `cancelled` | 1 |
| `attempt_expired` | 0 |
| `interrupted` | 1 |
| **Total** | **9** |

A auditoria confirmou o resultado inteiro `5` e teve como SHA-256
terminal de referência
`647b2b120690bb9144f2b575e1a501658270b0e3f3fe681c631e0eea59ccb4ec`.
O contador de computações não rastreadas foi zero. O primeiro broker
encerrou com `interrupted_pending_dispatch`. Os sockets foram removidos,
a sentinela foi fechada e o banco permaneceu disponível para reabertura.

## Fase D — Recuperação

O broker de PID `3019` reabriu com o mesmo `DatabasePin` original,
`24:2195:24:2198`. As seis negativas diretas foram repetidas. Auditoria e
controle foram recusados antes da reemissão de grants. O operador reemitiu
explicitamente os grants de auditoria e de reconciliação do recibo histórico.

O histórico terminal, o resultado inteiro `5` e as causas
`advance_expired` e `attempt_expired` foram preservados. O recibo foi
reconciliado e o despacho interrompido voltou como `uncertain`.
A instância de recuperação registrou zero computações e zero computações
não rastreadas. O segundo broker encerrou normalmente com `requested`.

## Fase E — Cleanup e preservação

A inspeção pré-cleanup confirmou o encerramento dos processos da fixture,
inclusive os auxiliares, sockets removidos, ausência de montagens na raiz,
conteúdo esperado e baseline da unidade instalada preservado. Após perder a
sessão administrativa original, o operador abriu uma nova sessão root
exclusivamente para cleanup. Conferiu de novo a identidade da VM e do boot,
a propriedade e as permissões da fixture, a ausência dos PIDs `2837` e
`3019`, dos sockets e de montagens. Executou `rm -r --one-file-system`
somente na raiz exata da fixture.

```text
FIXTURE REMOVIDA
BASELINE DA UNIDADE PRESERVADO
CLEANUP GO
```

O cleanup prosseguiu sem reinício do broker, renovação da aprovação ou
substituição do `DatabasePin`. O snapshot é evidência da preparação.

## Limitação do baseline gráfico agregado

| Captura | SHA-256 agregado |
| --- | --- |
| Anterior ao ensaio | `868ad6cc1597f64bb98e9a46b77e2728164db5865d8aa9840314140e3b2dcab2` |
| Primeira captura posterior | `d68e6b92af7136e389925a56e8ce1b1577ac0a9a857498adda1f48684a4c58e6` |
| Segunda captura posterior | `862adb9b81ced81b2c99e4b97b29fad5aa69fe8ddabf560f2ef53b2a15e3da0c` |

**Observado após o ensaio.** Sway 1.10.1 respondia sob PID `1571` e UID
`1000`, iniciado às 05:28:30, antes do provisionamento às 05:34. O socket
IPC era compatível com esse PID e UID. A configuração carregada apontava
para o caminho esperado. A saída era `Virtual-1`, 1640 × 670. O workspace
`1` abrigava dois terminais Foot, com representação `H[foot foot]`.

**Hipótese e limite.** O agregado incluía estado das saídas, representação
do workspace, propriedades visuais e informações dinâmicas da sessão,
como a ordem de foco. O operador alternou terminais durante o procedimento.
Mudança dinâmica legítima é uma hipótese plausível. Sem capturas
individuais anteriores, é impossível identificar quais componentes
divergiram ou confirmar a igualdade byte a byte da configuração. Os
dados também não estabelecem bypass ou alteração indevida do Sway.

A [metodologia revisada](LOOPSHELL_V0_8_D2B1_CROSS_UID_PREFLIGHT.md#baseline-gráfico-para-qualificações-futuras)
se destina a ensaios futuros. Na D.2B.2, aplica-se a exigência original
de baselines gráficos agregados coincidentes para o GO global.

## Consolidação e transição

| Gate | Resultado |
| --- | --- |
| D.2B.1 | **Preflight incorporado à `main`** |
| D.2B.2, fases A–D | **GO experimental** |
| Cleanup da fixture | **GO** |
| Baseline da unidade instalada | **Preservado** |
| Preservação do baseline gráfico agregado | **INCONCLUSIVA** |
| D.2B.2 global | **PARTIAL** |
| Isolamento de recursos gráficos privados reais | **NOT RUN** |
| [D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5) | **PARTIAL** |
| [M1.3B](../ROADMAP.md#m13b--trusted-input--enforcement-feasibility) | **Independente** |

As fases A–D fundamentam a [proposta D.2C](../ROADMAP.md#v08-d2c--first-mediated-capability).
O primeiro efeito externo deve ser mediado pelo LoopBridge em recurso
descartável de workspace, com autorização específica, impossibilidade de
acesso direto pelo UID executor e prova independente do efeito. A
recuperação precisa distinguir despacho durável de efeito confirmado e
manter como incerto um desfecho sem evidência suficiente.
