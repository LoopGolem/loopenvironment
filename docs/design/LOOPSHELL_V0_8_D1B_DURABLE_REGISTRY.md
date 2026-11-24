# V0.8-D.1B — Registro durável e fronteira de autorização

**Implementação experimental e proposta de integração.** A D.1B
reutiliza as transições do domínio D.1A com um armazenamento SQLite e
uma política local. A integração do serviço e os contratos RPC
abaixo aguardam revisão arquitetural.
[Domínio D.1A](LOOPSHELL_V0_8_D1A_OBJECTIVE_CONTRACTS.md) ·
[Relatório de laboratório](../labs/LOOPSHELL_V0_8_D1B_DURABLE_REGISTRY.md).

## Decisões e alternativas

| Tema | Decisão do experimento | Alternativa descartada neste perfil |
| --- | --- | --- |
| Identidade | Principal individual estável, resolvido pelo verificador de confiança. O vínculo pendente é confirmado pelo próprio principal. | Usar os três papéis históricos, o rótulo do executor ou o UID como identidade de agente. |
| Escopo | Permissão exata por principal, ação e ID do executor, com prazo. A política é configurada pelo harness e fica em memória. | Herança por nome, escopo curinga e reaproveitamento dos grants de sessão. |
| Transação | SQLite da biblioteca padrão, tabelas `STRICT`, chaves estrangeiras, `BEGIN IMMEDIATE`, journal `DELETE` e `synchronous=EXTRA`. | Dump JSON regravado fora da transação ou região crítica limitada ao processo. Diagnóstico e durabilidade com WAL ficam para outro perfil. |
| Autorização | Política mantida estável até o resultado do commit e escopos revalidados imediatamente antes dele. | Consultar um snapshot de grants fora da transação ou confiar em campos do pedido para reconstruir o ator. |
| Prazos | UTC em segundos Unix e marcador durável do maior instante confirmado. | Persistir o valor retornado por `monotonic()` entre boots. |
| Recibos e auditoria | Recibos com janela de 24 h e cotas separadas. Auditoria de transições baseada em metadados. | Evicção FIFO de recibos vigentes e auditoria com conteúdo ou credenciais. |
| Recuperação | Instalação transacional do esquema inicial, validação ao abrir e repetição com o mesmo ID diante de commit incerto. | Recriar silenciosamente um banco ausente após a abertura ou confirmar sucesso após uma exceção no commit. |

[ADR 0007](../DECISIONS/0007-unified-input-mediation.md) ·
[ADR 0008](../DECISIONS/0008-operator-neutral-authority.md) ·
[ADR 0012](../DECISIONS/0012-trusted-service-identity-boundary.md) ·
[ADR 0013](../DECISIONS/0013-loopshell-layout-and-mission-boundaries.md).

## Fronteira experimental

O verificador recebe uma credencial transitória e resolve o ID de um
principal individual. O teste usa sujeitos distintos dos papéis
`owner`, `delegate` e `observer`. O ID associado a um registro é
o alvo do vínculo. O ator da solicitação deriva sempre da autenticação.
A rotação substitui o verificador e invalida o bearer anterior,
preservando o principal, seus grants e a chave de idempotência.

A ordem é **lock da política → lock da instância Registry →
transação SQLite**. O adaptador de confiança mantém seu lock desde a
verificação da identidade até fechar a transação. O Registry verifica
o escopo sobre o executor exato. Após preparar as escritas, revalida
os escopos consultados e a hora na entrada do commit. Se um grant
vencer antes dessa checagem, a transação é revertida. Essa checagem
marca a última decisão de autorização antes da sincronização em disco.
Nenhum callback de política chama o Registry de volta.

Na disputa entre revogar um grant e aceitar, retirar ou confirmar,
a ação já em transação pode concluir sob o grant que manteve o lock.
Uma revogação que adquire o lock primeiro faz a operação ser negada.
O teste de concorrência com conexões SQLite independentes também
exercita a revisão única de um objetivo. Um único adaptador de
política compartilhado é condição da prova de ordenação de grants.
O lock experimental não cobre políticas externas ou outros processos.

Preserva-se a semântica D.1A para o emissor. Revogar a autorização de
emissão impede que o emissor crie, ofereça ou retire com aquele grant.
Uma oferta já publicada continua elegível para um destinatário
autorizado até expirar, ser retirada com autoridade vigente ou
o executor ser revogado. Rascunhos continuam privados. Revogar o
executor retira seus objetivos abertos na mesma transação. Uma decisão
terminal anterior permanece registrada. O aceite é somente uma decisão
de recebimento e preserva a autoridade de sessão. Uma política futura
de cancelamento de todas as ofertas do emissor exige decisão explícita.

## Persistência, prazos e recuperação

O banco fica num diretório privado fornecido pelo laboratório, com
arquivo regular, sem hard link e modo `0600`. Os registros e o texto
são armazenados em claro dentro dessa fronteira experimental. Os
bancos são descartáveis. Identidades, credenciais, verificadores e
grants precisam ser reconfigurados pela autoridade de confiança
ao reiniciar. Sem esse contexto, a política começa sem escopos.
O perfil usa filesystem local e depende da semântica de sincronização
fornecida pelo SQLite, pelo filesystem e pelo dispositivo.

A criação explícita com `create=True` instala o esquema de versão
0 para 1 em uma transação num SQLite vazio. A reabertura exige um
banco existente e inicializado. Ela valida identificador de aplicação, versão,
DDL, integridade SQLite, chaves estrangeiras e invariantes dos
registros. A leitura dos registros também valida relações, tipos,
revisões e estados. Esquema incompatível ou banco inconsistente
bloqueia o uso. Uma perda de caminho durante a operação retorna
falha de armazenamento.

O banco grava o último instante UTC confirmado a cada transação
bem-sucedida. Se o relógio local ficar abaixo desse marcador ou
recuar durante a operação, o acesso falha fechado com
`clock_uncertain`. Restaurar uma hora confiável que alcance o
marcador permite reabrir. Avanços contam como tempo transcorrido.
Um avanço indevido pode antecipar expiração e encerrar a janela de
recibos. Uma correção para trás pode suspender o uso até recuperação
do marcador. Antes do primeiro avanço após reinício, o processo
depende da hora fornecida pelo host. Uma fonte de tempo confiável
e o procedimento de recuperação de relógio exigem revisão antes de
produção.

O instante de decisão é amostrado dentro da transação. Um objetivo
aberto expira quando o prazo de criação é atingido, inclusive após
reinício. Uma consulta autorizada ou transição pertinente materializa
a expiração e a audita uma vez. A expiração independe das leases de
sessão e do relógio monotônico de grants locais.

Estado, revisão, autor, recibo, marcador de tempo e metadados de
auditoria são gravados na mesma transação. Um erro de gravação
anterior ao commit retorna falha. Uma exceção durante o commit
retorna `commit_unknown`. Nesse caso, reabra, autentique novamente e
repita o mesmo pedido dentro da janela. Se o commit anterior for
visível, o recibo original é devolvido. Se a transação tiver sido
revertida, uma chamada ainda válida pode efetivá-la. O resultado só
é devolvido após confirmação do SQLite. Recuperação por cópia de
segurança anterior e rollback do host permanecem hipóteses para
uma etapa posterior.

### Retenção e dados sensíveis

| Dado | Limite e política |
| --- | --- |
| Executores e objetivos | 64 executores e 256 objetivos. Registros terminais e seus IDs ficam retidos pela vida do banco. Ao atingir o limite, novas criações são recusadas e transições autorizadas continuam possíveis. |
| Texto | 4.096 bytes UTF-8 no domínio e 128 bytes para rótulo. A validação D.1A e a preservação literal continuam em vigor. |
| Recibos | 1.024 comuns e 320 reservados para revogação de executor e retirada explícita. O recibo guarda hash da assinatura e resultado, com retenção de 24 h UTC desde a decisão. Remoção preguiçosa somente após o prazo. Cota cheia recusa a operação atomicamente. |
| Auditoria | Até 1.024 transições, incluindo expiração e retiradas derivadas. Guarda hora, ator quando aplicável, tipo, ID, estado e revisão. A poda afeta somente auditoria. |
| Credenciais e conteúdo | Credenciais e verificadores ficam fora do banco. O corpo fica na tabela de objetivos, sujeito a leitura autorizada. Recibos e auditoria preservam metadados, sem duplicar o corpo. |

## Proposta RPC para integração posterior

**Versão candidata `registry/1`.** O envelope JSON-RPC mantém
`jsonrpc`, `version`, `id`, `method` e `params`. A admissão de uma
versão nova no LoopBridge depende de revisão. Campos desconhecidos,
duplicados e claims de ator ou UID no payload são recusados.
IDs e `request_id` são ASCII do domínio, com 1–64 caracteres.
Revisões e prazos enviados são inteiros positivos. A revisão no
RPC tem máximo de 2⁵³−1 e `ttl_seconds` tem máximo de 86.400.
No RPC candidato o nome mantém 128 bytes e o
corpo fica limitado a 2.048 bytes UTF-8, além do limite de 8.192
bytes do envelope codificado. Isso mantém os registros do laboratório
que excedam o limite de RPC fora do fluxo inicial de exposição.

Todas as mutações levam `request_id` e devolvem `{id, revision,
state}`. Mutações sobre registros existentes levam `expected_revision`.
Os grants candidatos abaixo usam o namespace `registry` e requerem
o executor exato. Para objetivo existente, o serviço resolve o executor
a partir do registro. A autorização do destinatário também exige
o vínculo confirmado. A autorização do emissor é revalidada na ação
dele. A rotação de credenciais não altera esses escopos.

| Método | Parâmetros adicionais | Grant candidato e projeção |
| --- | --- | --- |
| `executor.register` | `executor_id`, `bound_principal_id`, `label` | `registry.executor.register` no executor exato. Retorna recibo pendente. |
| `executor.confirm` | `executor_id`, `expected_revision` | `registry.executor.confirm` e identidade vinculada. Retorna recibo. |
| `executor.transition` | `executor_id`, `expected_revision`, `action` | `registry.executor.manage`. Enum `suspend`, `resume`, `revoke`. |
| `executor.status` | `executor_id` | `registry.executor.read`. ID, rótulo, estado e revisão. Vínculo e autor pedem projeção administrativa em revisão. |
| `objective.create` | `objective_id`, `executor_id`, `text`, `ttl_seconds` | `registry.objective.author`. Recibo criado. |
| `objective.offer`, `objective.withdraw` | `objective_id`, `expected_revision` | `registry.objective.author` e emissor original. Retorna recibo. |
| `objective.respond` | `objective_id`, `expected_revision`, `decision` | `registry.objective.respond`, executor disponível e vínculo confirmado. Enum `accept`, `decline`. |
| `objective.status` | `objective_id` | `registry.objective.read` e regra D.1A de emissor/destinatário. ID, executor, autoria, estado, revisão, prazo e texto autorizado. |
| `objective.list_offers` | `executor_id`, `limit`, `cursor` opcional | `registry.objective.read` e identidade vinculada ao executor disponível. Metadados sem corpo mais `next_cursor` anulável. |

Projeção candidata de `executor.status` com `{id, label, state,
revision}`. A de `objective.status` usa `{id, executor_id, issuer_id,
state, revision, expires_unix_ms, text}`. Objetivos são dados de
texto e os estados são os enums D.1A. A lista devolve
`{items, next_cursor}`. Cada item contém `{id, executor_id, state,
revision, expires_unix_ms}`. O prazo de saída é um inteiro em ms
UTC desde o epoch Unix.

Paginação candidata de 1 a 16 registros. O primeiro pedido fixa um
limite superior numa sequência de ofertas persistente. Um cursor
opaco, autenticado e de duração limitada prende limite superior,
posição, principal, executor e instalação. Cada página revalida o
mesmo grant, pula ofertas retiradas ou vencidas e omite corpos e
recibos. Um cursor inválido ou fora do escopo retorna erro e exige
nova consulta. Novas ofertas aparecem em uma consulta nova.

Erros propostos incluem `invalid_params` (-32602), `denied`
(-32001, inclusive objeto fora do escopo ou desconhecido),
`stale_revision` (-32040), `objective_expired` (-32041),
`executor_unavailable` (-32042), `invalid_state` (-32043),
`request_conflict` (-32044), `capacity` (-32045),
`storage_unavailable` (-32046), `invalid_storage` (-32047),
`commit_unknown` (-32048), `clock_uncertain` (-32049),
`already_exists` (-32050) e `invalid_cursor` (-32051).
A mensagem é estática. Metadados de erro excluem conteúdo e
credenciais. O código `commit_unknown` sinaliza uma transição que
deve ser reconciliada pelo mesmo `request_id`.

O menor subconjunto viável usa `executor.register`,
`executor.confirm`, `executor.status`, `objective.create`,
`objective.offer`, `objective.list_offers`, `objective.status`,
`objective.respond` e `objective.withdraw`. A revogação de grants
precisa estar disponível por uma política de confiança já aprovada
ao ensaiar esse subconjunto. Transição administrativa de executor
e leitura de auditoria podem ter revisão de superfície separada.

## Aprovações pendentes

Revisar provisionamento e rotação de identidades individuais, ingresso e
versão RPC, namespaces e delegação de grants, política para ofertas de
emissores revogados, atomicidade entre revogação real e escrita e prazo
de retenção. Definir dono e proteção do banco, fonte de hora, migração,
limpeza segura, recuperação de backup e projeção de auditoria antes de
dar acesso a clientes do LoopBridge. A ligação eventual precisa partir
da identidade autenticada pelo ingresso existente. O adaptador
experimental aceita um verificador injetado e demonstra o que precisa
ser serializado. D5, M1.3B e as qualificações V0.8-C seguem separadas.
