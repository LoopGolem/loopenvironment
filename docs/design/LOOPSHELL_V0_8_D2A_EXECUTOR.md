# V0.8-D.2A — Contrato do primeiro executor autorizado

**Escopo experimental.** A operação soma duas constantes em memória. O
perfil local e descartável usa identidade individual e o Registry
autenticado, conforme a [proposta](LOOPSHELL_V0_8_D2A_EXECUTOR_PROPOSAL.md)
e os [contratos D.1C.1](LOOPSHELL_V0_8_D1C1_TRUSTED_REGISTRY.md) e
[D.1C.2](LOOPSHELL_V0_8_D1C2_OPERATIONAL_REGISTRY.md). A prova cross-UID
[D.1C.4](../labs/LOOPSHELL_V0_8_D1C4_CROSS_UID_EXECUTION.md) é do Registry.
D5 permanece PARTIAL e [M1.3B](../ROADMAP.md#m13b--trusted-input--enforcement-feasibility)
permanece independente.

## Fronteiras e autoridade

1. O Registry recebe, oferece e registra o aceite. A D.2A consulta
   somente os identificadores, estados, revisões, prazo e vínculo relevantes.
   O texto fica no Registry e não entra no executor.
2. Um principal autenticado solicita `execution.authorize`. O LoopBridge
   avalia separadamente o grant de autorização desse principal e o grant
   de operação do principal registrado no executor. Ambos devem estar
   inscritos no ingresso. A identidade vem do vínculo da conexão
   autenticada. O UID Linux só admite o peer ao socket.
3. A decisão positiva admite uma tentativa específica na mesma transação
   que grava a decisão. O ID retornado é referência e exige autorização
   a cada uso. A tentativa fixa as duas concessões, o executor e sua
   revisão, o principal vinculado, o objetivo aceito e sua revisão, o
   tipo de operação e o prazo. O prazo é o menor entre o TTL solicitado,
   a validade das duas concessões e a validade do objetivo.
4. Só o principal vinculado, com grant vigente para a operação, pode
   solicitar `execution.start`. O LoopBridge verifica novamente o alvo
   e as duas concessões, confirma `running` em disco e libera uma única
   chamada de soma. Uma repetição de início não libera outra chamada.
5. O LoopBridge verifica o retorno inteiro `5`, revalida o alvo e a
   autoridade e confirma a publicação em SQLite. O RPC de início devolve
   um recibo de estado. O resultado fica disponível por auditoria.
6. Cancelamento e leitura exigem grants próprios. O supervisor confiável
   da fixture configura os grants e pode revogá-los. Não há RPC de
   administração de grants. O supervisor usa armazenamento privado e
   só atende ao perfil opt-in local.

Cada grant é a tupla exata de principal, permissão
(`authorize`, `perform`, `cancel` ou `audit`), executor, objetivo, revisão
aceita e operação. Não há curingas, papéis implícitos, sessão ou herança
do Registry. Um principal pode ter várias permissões explícitas. O grant
`audit` abrange as tentativas daquele alvo exato, inclusive seu resultado
e histórico após o encerramento. O grant `cancel` permite cancelar uma
tentativa específica naquele escopo. A política local fica em memória,
e cada concessão tem uma geração. A revogação ou a troca de geração
invalida a concessão fixada em tentativas abertas. Uma credencial
rotacionada invalida o vínculo antigo no ingresso.

## RPC experimental

O perfil abre `execution-lab.sock` e aceita apenas `registry/1` e
`execution/1`. O primeiro usa os contratos históricos de entrega. Os
brokers de sessão e os perfis históricos do Registry continuam com os
endpoints e as versões originais. O transporte usa o enquadramento JSON-RPC
do LoopBridge, rejeita objetos com chaves duplicadas e encerra quadros com
envelope ou versão inválidos. Cada método exige os campos exatos da tabela.

| Método em `execution/1` | Campos de `params` | Retorno |
| --- | --- | --- |
| `auth` | `credential` | Principal resolvido e ID da conexão |
| `execution.authorize` | `request_id`, `executor_id`, `objective_id`, `accepted_revision`, `operation`, `ttl_seconds` | Recibo da tentativa |
| `execution.start` | `attempt_id` | Recibo da tentativa |
| `execution.cancel` | `attempt_id` | Recibo da tentativa |
| `execution.audit` | `attempt_id` | Vínculo da tentativa e eventos com ator, revisão, instante, estado e desfecho |

IDs têm 32 dígitos hexadecimais minúsculos. Revisões são inteiros entre
1 e 2⁵³−1. O TTL é um inteiro de 1 a 300 segundos. A única operação é
`add_fixed_constants` e não aceita argumentos. O recibo contém `id`,
`state` e `revision`. O auditor recebe também as identidades relevantes,
ID da solicitação e prazo em milissegundos UTC. O alcance da autorização
é fixado antes do cálculo e não se estende a nenhum recurso externo.
Falhas retornam códigos estáveis e mensagens sem dados do pedido. A D.2A
reutiliza `denied` (−32001), `method_not_found` (−32601),
`invalid_params` (−32602), `stale_revision` (−32040),
`objective_expired` (−32041), `executor_unavailable` (−32042),
`invalid_state` (−32043), `request_conflict` (−32044), `capacity`
(−32045) e os erros de armazenamento e relógio do Registry. O prazo de
uma concessão ou autorização de execução vencido retorna
`authorization_expired` (−32060).

## Estados, disputas e relógio

| Estado anterior | Estados possíveis | Revisão |
| --- | --- | --- |
| Inexistente | `admitted` | 1 |
| `admitted` | `running`, `cancelled`, `revoked`, `expired` | 2 |
| `running` | `completed`, `failed`, `cancelled`, `revoked`, `expired`, `uncertain` | 3 |

Estados terminais são imutáveis. O cálculo não usa I/O nem executa
subprocessos. Depois de confirmado o início, a soma pode terminar em
memória durante um cancelamento ou uma revogação. O cálculo obtido nesse
caso é descartado quando o encerramento já venceu a disputa de publicação.

O mutex de identidade e políticas precede o lock do Registry e a
transação `BEGIN IMMEDIATE`. O cálculo ocorre fora desses locks. A
admissão, o início, o cancelamento e a publicação se ordenam pelos
commits vencedores dessa região crítica. A remoção de um grant pelo
supervisor se ordena pela sua aplicação no mesmo mutex, que cobre também
a gravação dos encerramentos. Uma falha de gravação mantém o grant
revogado. A geração impede que uma nova concessão reative a anterior.
Revogação ou cancelamento após a publicação preservam a conclusão. O
relógio UTC é conferido no ingresso da decisão e antes do commit. Se o
prazo usado na decisão vencer antes do commit, a decisão é refeita sob o
mesmo mutex e com a hora atual. Uma amostra menor que o instante observado
na tentativa anterior da mesma decisão retorna `clock_uncertain`. O
prazo é exclusivo. Expiração sem atividade é observável pelo prazo
registrado e materializada em uma transição quando a tentativa volta a
um caminho de execução ou cancelamento. Um alvo fora do estado ou da
revisão exigidos impede início e publicação.

| Disputa | Decisão observável |
| --- | --- |
| Autorização e revogação | Remoção do grant antes da admissão impede o recibo. Se a admissão confirmar primeiro, o recibo existe e a tentativa aberta passa a `revoked`. |
| Início e cancelamento | Cancelamento confirmado em `admitted` impede o início. Se `running` confirmar primeiro, o cancelamento pode vencer a publicação. |
| Início e expiração | O prazo deve permanecer vigente na última amostragem antes do commit do início. Uma expiração posterior impede a publicação. |
| Publicação e revogação ou cancelamento | A remoção do grant ou o cancelamento que ganha a região crítica impede `completed`. Uma publicação já confirmada permanece no histórico. |
| Solicitações idempotentes simultâneas | A primeira admissão que confirma fixa a tupla do pedido. Um pedido elegível com a mesma tupla reconcilia a tentativa. Um pedido elegível divergente recebe `request_conflict`. |

## Persistência e recuperação

A fixture usa um banco novo, com identificação própria, que contém as
tabelas experimentais de entrega e execução. Uma transação de execução
consulta a entrega e grava o ciclo de execução na mesma conexão SQLite,
sem alterar registros de entrega. O estado atual e sua revisão são a
projeção do último evento durável. A chave estrangeira, as restrições de
esquema e a validação de abertura protegem o formato da trilha. A D.2A
reutiliza o SQLite estrito, journal de rollback `DELETE`, sustentação
`synchronous=EXTRA`, contorno privado e validação de relógio com marca
d'água. O esquema histórico permanece idêntico no seu perfil. Não há
migração nem abertura desses bancos no perfil alternativo.

No perfil D.2A, os dois protocolos e a abertura do banco consultam o
maior marcador confirmado entre `registry_clock` e `execution_clock`.
Um relógio abaixo desse piso retorna `clock_uncertain`. A última amostra
UTC validada antes do commit é usada para verificar os grants
consultados no Registry ou os prazos aplicáveis em Execution. A
transação confirma a própria marca junto com eventuais mudanças de
estado e auditoria. Uma consulta de auditoria pode avançar a marca
temporal sem alterar a tentativa ou seus eventos. O timestamp de um
evento identifica o momento da decisão. A marca identifica a última
amostra validada da transação confirmada.

Uma amostra só observada antes de uma transação abortada não avança o
piso compartilhado. Quando o prazo observado força a repetição interna
da decisão, a amostra vale como limite em memória para essa decisão.
Em caso de `commit_unknown`, o banco preservado determina se a marca e
as alterações da transação foram confirmadas. Os perfis históricos
mantêm sua validação temporal e esquema.

O par de principal autorizador e `request_id` é único. O LoopBridge
verifica os grants atuais do autorizador e do executor e a elegibilidade
do alvo solicitado antes de consultar esse par. Um pedido inelegível
recebe o erro de autorização ou do alvo independentemente do uso anterior
do ID. Pedidos elegíveis com a tupla idêntica reconciliam a tentativa na
janela original. Pedidos elegíveis divergentes recebem apenas
`request_conflict`, sem o recibo anterior. Os prazos são revalidados
antes de comunicar o conflito. Cada principal tem seu próprio namespace
e a reserva do ID permanece após o desfecho. A fixture retém tentativas
e eventos para auditoria e recusa nova admissão ao atingir a capacidade.
O histórico não contém bearer tokens, hashes de credencial, labels nem
texto do objetivo.

Na reabertura, uma tentativa admitida torna-se `revoked` porque a política
de execução anterior não é recuperada. Uma tentativa em execução torna-se
`uncertain` com motivo sanitizado. Uma conclusão durável é preservada.
Falha ou resposta perdida no commit exigem reconciliação por recibo ou
auditoria. Não se repete a operação de uma tentativa cujo início já foi
gravado. Prosseguir com trabalho após interrupção exige nova autorização,
com novo `request_id`. A garantia experimental cobre despacho único e
publicação durável para a operação em memória no mesmo banco preservado.
Operações com efeitos externos exigirão outros contratos e provas.

O diretório da fixture deve ser privado e pertencer ao usuário do
processo. Após uma parada abrupta, o supervisor verifica que o processo
anterior terminou e remove o socket residual da própria fixture antes
de reabrir o banco preservado. O ensaio assume controle desse diretório
e do processo confiável. A trilha SQLite não atesta integridade diante
de adulteração pelo mesmo UID do serviço ou por um ator privilegiado.
O piso temporal assume uma fonte UTC confiável e a preservação do
banco ativo. Alteração privilegiada do relógio e restauração integral
da VM estão fora dessa garantia.
