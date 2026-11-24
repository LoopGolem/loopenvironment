# V0.8-D.1C.2 — Fronteira restrita do Registry

O perfil experimental reutiliza o RPC `registry/1` da
[D.1C.1](LOOPSHELL_V0_8_D1C1_TRUSTED_REGISTRY.md), a autorização por
executor da [D.1A](LOOPSHELL_V0_8_D1A_OBJECTIVE_CONTRACTS.md) e as
transações da [D.1B](LOOPSHELL_V0_8_D1B_DURABLE_REGISTRY.md).

## Atores

| Ator | Autoridade |
| --- | --- |
| Administrador de provisionamento | Autoriza o manifesto e mantém a referência confiável da política e do banco fora dos dados restauráveis. Dispõe de um caminho administrativo separado do RPC. |
| Principal administrador do Registry | Autentica-se individualmente e registra somente os executores cobertos por seus grants explícitos. |
| Principal emissor | Cria, oferece e retira seus objetivos no executor autorizado. |
| Principal executor | Confirma o próprio vínculo e consulta ou responde às suas ofertas com os grants aplicáveis. |
| UID dedicado do serviço | Possui os recursos privados e executa o broker, a política e as transações. O transporte consulta o UID real do par pelo kernel. |
| UID desktop e cliente admitido | O ACL permite atravessar o diretório de ingresso e conectar ao socket. Cada cliente ainda apresenta credenciais e precisa de grants específicos. |

O perfil expõe somente a versão do Registry em um endpoint próprio.
Ele opera sem adaptadores de sessão e sem credenciais históricas. O
serviço instalado e seus listeners continuam com o comportamento existente.
Os papéis e grants de sessão seguem as ADRs de
[identidade](../DECISIONS/0008-operator-neutral-authority.md),
[mediação](../DECISIONS/0007-unified-input-mediation.md),
[UID de serviço](../DECISIONS/0012-trusted-service-identity-boundary.md) e
[fronteiras de missão](../DECISIONS/0013-loopshell-layout-and-mission-boundaries.md).

## Autoridade local

O manifesto possui versão, geração, verificadores individuais, identidades
desativadas e grants exatos com prazo UTC. O provisionador fornece a geração
e o SHA-256 esperados por um canal administrativo confiável. Arquivos
restaurados não são fonte desse pin. O perfil exige um manifesto válido
antes de abrir o socket. Um snapshot de política publicado substitui o
anterior sob o mesmo mutex usado pela autorização e pelas transações.

### Manifesto privado v1

O arquivo `policy.json` pertence ao UID de serviço, tem modo `0600` e
fica no diretório privado. O schema documentado abaixo usa um único
grant para demonstrar o formato. O fluxo completo precisa dos grants
explícitos de cada operação.

```json
{
  "version": 1,
  "generation": 1,
  "principals": {
    "00000000000000000000000000000001": "<sha256 do bearer sintético>",
    "00000000000000000000000000000002": null
  },
  "retired_verifiers": [],
  "grants": [
    {
      "principal": "00000000000000000000000000000001",
      "scope": "registry.executor.register",
      "executor": "0000000000000000000000000000000a",
      "expires_unix": 1800000000
    }
  ]
}
```

Gerar credenciais sintéticas de alta entropia com
`secrets.token_urlsafe(32)`. Entregar cada segredo somente ao cliente
apropriado por um canal aprovado. O manifesto aceita verificadores
SHA-256 de 64 caracteres hexadecimais minúsculos. O valor `null`
preserva a identidade desativada. O limite é de 128 principais, 1.024
grants e 1.024 verificadores aposentados, respeitando o teto de 128 KiB
para a codificação JSON.

O provisionador conserva um `PolicyPin(generation, sha256)` fora do
diretório de backup. Para iniciar ou atualizar, publica o manifesto
com substituição atômica e sincronização do arquivo e do diretório.
O supervisor entrega o pin aprovado ao processo. Durante a execução,
`RegistryControl.reload(pin)` só aceita uma geração maior. A troca
entra em vigor quando o processo instala o snapshot validado. Uma
atualização inválida é recusada e o último snapshot validado permanece
em vigor. Em uma revogação urgente sem atualização válida, o
supervisor deve fechar o ingresso e encerrar o perfil.

Para rotacionar, manter o ID do principal, substituir seu verificador
e acrescentar o anterior a `retired_verifiers`. Para desativar, usar
`null`, remover os grants do principal e aposentar o último
verificador. Uma atualização ativa preserva os históricos de
desativação e aposentadoria. A antiga credencial e as conexões ligadas
a ela deixam de autenticar. O aceite anterior continua história
durável. A desativação do principal deixa o registro do executor
intacto. Revogar o registro é a transição de domínio da D.1A e fica
fora deste RPC. Revogar somente um grant mantém a identidade.
A perda de autoridade do emissor impede novas ações e repetições dele.
As ofertas já publicadas continuam acessíveis segundo os grants
do destinatário.

A ordem de locks é supervisor de atualização, mutex de identidades
e grants, lock do Registry e transação SQLite. Os workers nunca
adquirem o lock do supervisor. A política usa prazos absolutos UTC
e o Registry aplica o limite de retrocesso de relógio da D.1B. O
broker revalida o vínculo e os grants usados antes de confirmar a
transação. Uma revogação publicada primeiro impede a decisão.
Se o commit ganhar, sua decisão persiste e a revogação se aplica
às operações seguintes, inclusive repetições. A ordem demonstrada
é intra-processo.

## Banco e recuperação

A inicialização explícita usa `initialize_registry_database(private)`
em um diretório novo e privado. Ela admite somente um banco novo, sob
o lock do diretório. A partida normal exige um `DatabasePin` fornecido
pelo supervisor e nunca cria ou repina um banco. O pin identifica o
diretório e o arquivo por dispositivo e inode. O supervisor deve
guardá-lo independentemente do diretório restaurável. Em caso de
provisionamento incerto, o perfil fica fechado.

A proteção abre cada componente de caminho com `O_NOFOLLOW` e
`O_CLOEXEC`. Os ancestrais pertencem a root ou ao UID do serviço,
sem escrita por grupo ou outros. A exceção são diretórios de root
com sticky bit, como `/tmp`, cujos descendentes continuam sendo
validados. O diretório privado é `0700` e sem ACL padrão. O SQLite
e seus journals admitidos são arquivos regulares `0600`, do mesmo
dispositivo, com um único link. O processo mantém o inode do banco
aberto, checa a ligação do diretório e do banco antes de abrir o
SQLite e repete a verificação antes do commit. O adaptador também
valida esquema, versão, metadados duráveis e integridade na
reabertura. A proteção depende da exclusividade do UID de serviço
e da integridade do kernel. Um processo com autoridade de escrita
do próprio serviço, root, uma cópia antiga escrita no mesmo inode
ou a restauração da VM inteira ficam fora da proteção por inode
e pin. A API de SQLite abre por caminho sob diretórios protegidos.

Para backup, primeiro parar o ingresso e aguardar a drenagem das
conexões. Preservar o banco atual, mesmo após uma falha. Capturar
uma cópia consistente com a API `sqlite3.Connection.backup` para um
diretório de quarentena privado em vez de copiar um arquivo em uso.
Verificar `PRAGMA integrity_check` na cópia. Registrar a geração de
política, os pins e a hora do backup separadamente. Proteger cópias
como o banco de origem, pois elas contêm os textos dos objetivos.

Uma restauração é para inspeção offline em quarentena. A troca da
cópia para o caminho ativo é recusada pelo pin, e a política antiga
é recusada pela geração e digest esperados. Nenhuma restauração
automática, repinagem ou rollback da autoridade está disponível.
Antes de reativar um serviço que perdeu o banco ativo, reconciliar
grants, revogações, objetivos terminais e recibos com fontes
confiáveis. O procedimento de reativação depois dessa perda ainda
precisa de aprovação. Se um commit tiver resposta incerta e o banco
ativo estiver íntegro, autenticar novamente e repetir os mesmos
parâmetros e `request_id` sob autorização vigente, conforme a D.1B.

## Ingresso e descritores

`serve_operational_registry` exige um `CrossUIDIngress` explícito.
Reutiliza o contrato do
[ingresso D2](TRUSTED_SERVICE_INGRESS_D2.md) e a separação do
[ciclo D3](TRUSTED_SERVICE_LIFECYCLE_D3.md). O diretório
de ingresso é do serviço, com travessia concedida ao UID admitido.
A ACL do socket concede conexão a esse UID. O broker confere
`SO_PEERCRED` e exige autenticação individual antes do Registry.
O processo usa threads e tráfego JSON no socket. Ele não inicia
sessões privadas nem transfere descritores Wayland, Sway, D-Bus,
mídia, input ou workspace. A validação real entre UIDs distintos
ainda depende de um ambiente descartável autorizado.
[Relatório e plano de qualificação](../labs/LOOPSHELL_V0_8_D1C2_OPERATIONAL_REGISTRY.md).
