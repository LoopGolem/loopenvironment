# V0.8-D.1C.1 — Ingresso experimental do Registry

A D.1C.1 ensaia o fluxo RPC da [proposta D.1B](LOOPSHELL_V0_8_D1B_DURABLE_REGISTRY.md)
em um broker LoopBridge descartável. A construção do broker de laboratório é
explícita e separada do serviço operacional. Ela reutiliza o enquadramento
JSON-RPC, os limites de conexão, a admissão por credenciais de par Unix
e a verificação de segredos por digest.

## Fronteira de confiança

Cada principal do Registry recebe um identificador opaco de laboratório e
um verificador individual em memória. Os clientes apresentam a credencial
em `auth` na versão `registry/1`. O UID do socket só participa da admissão.
O Registry recebe internamente a conexão admitida e vinculada ao
verificador. `bound_principal_id` designa o destinatário de um registro.
O ator de toda operação vem da conexão autenticada. Os papéis históricos
continuam no namespace e na autenticação existentes.

A versão `registry/1` só despacha operações do Registry. Uma conexão
autenticada no Registry precisa autenticar-se explicitamente com uma
credencial histórica para usar uma versão de sessão, e vice-versa. Toda
tentativa de autenticação limpa o vínculo anterior. Os grants de laboratório
são configurados pelo harness para um principal, operação e executor exatos.
O Registry usa somente esses grants e as regras da D.1B. Uma decisão de
aceite grava estado e autoria.

A ordem é mutex da política e das identidades, lock do Registry, transação
SQLite. A validação do vínculo e a consulta dos grants ocorrem sob o mutex.
O vínculo e os grants consultados são revalidados antes do commit, inclusive
em pedidos idempotentes. A revogação e a rotação usam o mesmo mutex. Uma
revogação que vence a disputa impede a transição. Se o commit vencer, o
efeito já decidido persiste e as novas ações e repetições dependem dos grants
vigentes. A expiração de grants também é checada imediatamente antes do
commit. A rotação invalida conexões vinculadas ao verificador anterior e
preserva grants e recibos do mesmo principal. Essa ordenação é local ao
processo confiável. Uma política externa exigiria coordenação demonstrável.

O banco e o socket pertencem a um diretório privado do laboratório. A
reabertura exige configuração explícita da política, que permanece em
memória. O armazenamento preserva as transações e a auditoria própria do Registry.
A auditoria de sessões fica separada. O banco aplica as
regras de prazo da D.1B. Um erro de commit requer reconciliação por
`request_id`, sob autenticação e autorização válidas.

A separação segue o [modelo de operadores](../OPERATOR_MODEL.md)
e as ADRs de [identidade](../DECISIONS/0008-operator-neutral-authority.md),
[ingresso](../DECISIONS/0012-trusted-service-identity-boundary.md) e
[fronteiras de missão](../DECISIONS/0013-loopshell-layout-and-mission-boundaries.md).
As credenciais históricas e individuais têm verificadores distintos. O
destinatário indicado no registro precisa pertencer ao catálogo individual
do laboratório. Rótulo, UID, parâmetros do cliente e texto do objetivo
ficam fora da decisão de identidade.

## Contrato do laboratório

Os métodos implementam os schemas, projeções e códigos de erro da
[proposta D.1B](LOOPSHELL_V0_8_D1B_DURABLE_REGISTRY.md#proposta-rpc-para-integração-posterior)
com as seguintes decisões locais.

- `auth` recebe somente `credential`. O catálogo suporta até 128
  principais opacos. Os segredos sintéticos são gerados com
  `secrets.token_urlsafe(32)`. O laboratório provisiona somente
  os verificadores SHA-256 individuais para o Registry.
- Os identificadores de entidade, vínculo e idempotência têm 32 caracteres
  hexadecimais minúsculos. Em uma fixture nova, devem ser gerados
  separadamente das credenciais. Revisões de mutação vão de 1 a 2⁵³−1.
- O envelope tem limite de 8.192 bytes com a quebra de linha. O rótulo tem
  até 128 bytes UTF-8, o texto até 2.048 bytes UTF-8 e a validade até
  86.400 segundos. Conteúdo submetido que contenha um dos segredos
  sintéticos atualmente configurados é recusado. Autenticação, auditoria e
  erros nunca gravam as credenciais apresentadas. O filtro de conteúdo
  reconhece credenciais sintéticas configuradas, com o formato de
  provisionamento do laboratório.
- Há nove métodos além de `auth`: `executor.register`,
  `executor.confirm`, `executor.status`, `objective.create`,
  `objective.offer`, `objective.list_offers`, `objective.status`,
  `objective.respond` e `objective.withdraw`. O harness administra grants
  fora do RPC. A perda do grant do emissor impede novas ações e repetições
  dele. Ofertas publicadas continuam acessíveis ao destinatário enquanto
  os requisitos próprios dele forem satisfeitos.
- A listagem busca ofertas atuais sob o grant aplicável. O cursor guarda
  os IDs restantes da primeira página em memória, na ordem de inserção
  do domínio D.1B. A paginação usa de 1 a 16 registros e aceita somente
  o mesmo principal e executor. Prossegue por até 60 segundos a partir
  da primeira página, ignora ofertas recém-criadas fora do conjunto e
  pula ofertas retiradas ou vencidas. O cache mantém até 64 cursores e
  invalida todos no reinício. A sequência persistente de ofertas
  proposta na D.1B fica para uma eventual paginação operacional.
- `content_limit` (-32052) recusa uma projeção de texto que exceda o
  limite RPC. Reabrir o banco criado pelo próprio ensaio é o perfil
  validado. Importar registros D.1B com outros IDs ou conteúdo maior
  requer uma política de migração.
- A perda do socket depois de uma decisão durável pode impedir a entrega
  do recibo. Um erro de confirmação do SQLite retorna `commit_unknown`.
  O cliente autentica novamente e reconcilia com os mesmos parâmetros e
  `request_id` enquanto o recibo estiver retido e houver autorização.
  O broker espera um pedido explícito do cliente para reconciliar.

## Limite operacional

O protótipo não inclui provisionamento operacional, distribuição de grants,
migração ou backup de bancos de produção. Uma etapa futura deve revisar
a proteção do banco sob uma identidade de serviço dedicada, a admissão e
a revogação operacionais, os limites e a integração com os processos
confiáveis existentes. A prova local mantém independentes o isolamento do
host, D5 e M1.3B. [Relatório do laboratório](../labs/LOOPSHELL_V0_8_D1C1_TRUSTED_REGISTRY.md).
