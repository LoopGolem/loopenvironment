# V0.8-D.2B — Ciclo de execução supervisionada

**Escopo experimental local.** O Registry preserva o ciclo de objetivo e o
aceite registra recebimento. A tentativa conserva a autoridade e os estados
da [D.2A](LOOPSHELL_V0_8_D2A_EXECUTOR.md). O serviço escolhe um plano fechado
de duas etapas, `add_in_two_stages`. A primeira calcula `1 + 1`, e a
segunda soma `3` ao inteiro verificado da primeira. Duas etapas bastam
para verificar pausa entre despachos e diferença entre progresso e
resultado final. O plano, seus dados e a ordem vêm do serviço. O texto
do objetivo permanece no Registry.

## Estados e fronteira cooperativa

A tentativa usa `admitted → running → completed` e os mesmos desfechos
`failed`, `cancelled`, `revoked`, `expired` e `uncertain` da D.2A.
Supervisão existe durante `running`. O início confirmado arma a tentativa
em `paused`, com zero etapas despachadas. A etapa corrente só existe
após seu despacho durável. O progresso avança quando o serviço confirma
o resultado daquela etapa. A última verificação e a publicação do
resultado inteiro `5` são atômicas.

| Decisão | Semântica |
| --- | --- |
| `pause` | Se a fronteira está livre, confirma `paused` e invalida a permissão de avanço. Se há despacho pendente de conclusão, grava `pause_requested`. A etapa em curso pode terminar. Sua conclusão confirmada passa a `paused`, salvo desfecho terminal. |
| `step` | Somente em `paused`. Autoriza uma etapa em `stepping`. O despacho é registrado antes da chamada em memória. Depois de verificar a etapa, o serviço volta a `paused` ou confirma o desfecho terminal. |
| `continue` | Somente em `paused`. Autoriza o fluxo em `flowing`. Cada despacho e cada conclusão revalidam o vínculo, os grants, as gerações e o prazo. |
| `cancel` | Encerra a tentativa em aberto conforme a D.2A. Cancelamento, revogação ou expiração que vencem a transação impedem novos despachos e publicação de sucesso. |

Admissão, decisões de controle, despacho, conclusão da etapa e publicação
se ordenam por commit sob o mutex de política e a transação SQLite.
A computação roda fora dos locks, no worker da própria chamada de
`step` ou `continue`. Outro cliente autenticado pode observar ou pausar
por outra conexão. Cada avanço usa a revisão do comando que o autorizou.
Uma pausa confirmada invalida o comando anterior. Uma permissão de passo
é consumida pelo único despacho e pela volta à fronteira pausada. Durante
`pause_requested`, a permissão corrente só pode validar o desfecho da
etapa já despachada.

## Autoridade, protocolo e projeções

O opt-in `supervised-lab.sock` aceita `registry/1` e `execution/2`.
`registry/1` mantém a API de entrega. O perfil D.2A continua oferecendo
`execution/1` para `add_fixed_constants` em seu próprio socket e banco.
As duas versões usam envelopes estritos e autenticação individual.

| Método `execution/2` | Campos de `params` |
| --- | --- |
| `auth` | `credential` |
| `execution.authorize` | `request_id`, `executor_id`, `objective_id`, `accepted_revision`, `operation`, `ttl_seconds` |
| `execution.start`, `execution.pause`, `execution.step`, `execution.continue`, `execution.cancel` | `attempt_id`, `expected_revision`, `request_id` |
| `execution.status`, `execution.audit` | `attempt_id` |

A autorização usa o par de grants de admissão e execução da D.2A, com
escopo exato no plano acima. O início exige a identidade do executor
confirmado. Um principal com grant exato pode operar a supervisão
independentemente da autoria do objetivo. Os grants `progress`, `pause`,
`step` e `continue` são independentes e exigem o ID exato da tentativa,
além do escopo do alvo. O serviço configura esses grants após a admissão.
`cancel` e `audit` mantêm o escopo explícito da D.2A por executor, objetivo,
revisão e plano. As permissões são locais e voláteis, e a identidade
vem do ingresso. Cada decisão de controle verifica a revisão atual da
tentativa supervisionada. O grant de avanço é fixado por principal,
geração e prazo para os despachos daquele comando.

O recibo de admissão ou controle contém `id`, `revision` e `kind`.
Na admissão idempotente, esses campos descrevem a tentativa reconciliada.
No controle, descrevem o evento confirmado pelo comando naquela revisão.
O recibo histórico de `pause`, `step` ou `continue` continua descrevendo
essa decisão quando uma repetição autorizada reconcilia o mesmo ID por
tentativa e principal. Reutilização divergente e controle inédito com
revisão antiga são recusados. Após perda de resposta, repita a solicitação
original para obter seu recibo. Para exibir o estado efetivo, o cliente
de referência e uma futura interface gráfica dependem do snapshot de
`status`, com seu próprio grant e sua revisão. Um `pause_requested`
recuperado de um recibo histórico pode anteceder um desfecho terminal.

`status` projeta tentativa, objetivo, estado, plano, etapa corrente,
etapas concluídas e totais, situação de pausa, motivo sanitizado e
revisão. `audit` inclui o resultado terminal e a sequência integral
de eventos com revisões, timestamps e atores. O prazo UTC também fica
visível no snapshot. Assim como na D.2A, uma tentativa ociosa materializa
a expiração ao voltar a uma decisão de execução ou cancelamento. A
projeção não transporta
credenciais, verificadores, texto, valores intermediários, caminhos ou
autoridade. A checagem de grants no broker segue a separação de
[Sessão, Activity e Combined](LOOPSHELL_V0_8.md), com revisão durável
por tentativa e snapshot completo. O cliente de referência usa o mesmo
transporte autenticado sem alterar a interface gráfica do LoopShell.

## Armazenamento e recuperação

O banco da D.2B usa `application_id = 0x4C4F5358` e `user_version = 1`.
O esquema explícito acrescenta uma
trilha de supervisão ordenada, gravada junto às transições da tentativa.
Reutiliza os locks, o SQLite e o piso temporal compartilhado D.2A.
Cada tentativa admite até oito comandos de avanço. A trilha reserva
espaço para a pausa de cada avanço, conclusão, cancelamento e recuperação.
O serviço valida o encadeamento e a correspondência das trilhas ao
reabrir o banco. Bancos históricos conservam seu formato e endpoint.
A D.2B exige um banco criado para seu perfil.

### Expiração e validação retrospectiva

O estado terminal `expired` tem duas origens. A projeção sanitizada
distingue `attempt_expired` e `advance_expired` com base no evento
durável e no prefixo ordenado da trilha de supervisão.

| Motivo projetado | Evidência exigida |
| --- | --- |
| `attempt_expired` | O timestamp do evento alcançou o prazo original da tentativa. Essa regra também cobre prazos simultâneos. |
| `advance_expired` | O evento antecede o prazo da tentativa. No prefixo que termina imediatamente antes do evento, há um comando `step` ou `continue` ainda ativo e seu prazo efetivo foi alcançado. |

A D.2B verifica a correspondência entre o evento de ciclo e sua entrada
ordenada de supervisão. A validação reconstrói qual avanço estava
ativo, inclusive durante `pause_requested`. Um avanço consumido pelo
passo ou invalidado pela pausa confirmada deixa de fundamentar
expiração antecipada. O comando aceito já grava o prazo efetivo,
limitado pelo grant de avanço e pela tentativa. A auditoria autorizada
projeta esse dado como `deadline_unix_ms` no evento do comando.
Assim a recuperação usa o SQLite preservado e dispensa a reemissão
dos grants anteriores. Os schemas permanecem iguais. Na D.2A, a única
evidência aceita continua sendo o prazo original da tentativa.

O serviço confere esse prazo antes de publicar o resultado. Se o
prazo de avanço vencer enquanto a conclusão final está preparada em
SQLite, a transação perde a disputa e o resultado fica ausente.
Uma publicação já confirmada permanece no histórico.

### Reabertura do perfil

Na reabertura, uma tentativa aberta sem etapa despachada pendente é
revogada. Uma etapa com despacho confirmado e sem desfecho leva a
`uncertain`. Nenhum grant anterior é restaurado. Recibos e desfechos
confirmados podem ser lidos sob autoridade vigente. Um commit ambíguo
de despacho pode deixar a etapa pendente até cancelamento, revogação
ou recuperação. Se somente a decisão de avanço confirmar e o despacho
nem chegar a ser registrado, uma nova pausa pode invalidar o avanço
pendente. Repetir o comando nunca recupera o direito de despachar.

A fronteira qualificada é a verificação de uma operação cooperativa e
pura. A pausa aguarda a confirmação daquela fronteira. O experimento
não amplia as garantias para execução arbitrária, operações externas,
rollback da VM, recursos gráficos ou [takeover e preempção M1.3B](DELIVERY_ACKNOWLEDGEMENT_V1.md).
A [matriz D5](TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5)
permanece PARTIAL e a execução cross-UID está NOT RUN.
