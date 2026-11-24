# V0.8-D.1C.2 — Fronteira operacional e qualificação cross-UID

**Resultado geral PARTIAL.** O perfil restrito passou as provas locais
de política, RPC e recuperação. O ensaio com cliente admitido e broker
sob UIDs Linux distintos continua pendente.

## Ambiente e preflight

Debian 13.7, kernel 6.12.117+deb13-amd64, Python 3.13.5, SQLite 3.46.1
e Sway 1.10.1. O PR #36 estava em `main` no commit `edab043`, com a
branch remota de D.1C.1 removida e o workspace de integração limpo.

O desktop executava como UID 1000. A conta existente `loopbridge-svc`
(UID 980) pertencia ao perfil instalado de `loopbridge.service`,
inativo. Os diretórios operacionais existentes eram distintos dos
diretórios temporários do ensaio. A inspeção por `getent`, `stat` e
`systemctl show` não identificou um perfil descartável autorizado.
A conta, o serviço instalado e suas ACLs não foram alterados. O ensaio
rodou sob o UID 1000 e usou ACLs somente em diretórios descartáveis
pertencentes a esse mesmo UID.

## Evidência executada

- O administrador registrou o executor, o executor confirmou o próprio
  vínculo e o emissor publicou um objetivo pelo Registry-only RPC.
  O executor consultou, aceitou e recuperou o recibo depois de
  reiniciar o broker. A credencial inválida e a credencial válida
  sem grant receberam `denied`.
- O manifesto protegido validou geração, digest e schema; os casos
  sem pins, sem manifesto, com symlink, chaves duplicadas, credencial
  em claro ou grant de sessão foram recusados. O SQLite preservou
  metadados de auditoria e recibos. Os tokens sintéticos ficaram fora
  do manifesto, do banco e dos erros. Os verificadores ficaram fora do banco.
- Troca de credencial invalidou conexões antigas; a desativação e o
  descarte de verificadores antigos sobreviveram ao reinício do broker.
  A retirada do grant do emissor bloqueou publicação e retirada,
  preservando a oferta já entregue. A revogação concorrente aguardou
  o commit vencedor e negou a repetição. A expiração durante a
  transação anulou a mudança antes do commit.
- O banco recusou outro inode, arquivo simbólico, journal simbólico,
  diretório substituído, ancestral gravável e versão incompatível.
  Na corrupção, o serviço falhou e preservou o arquivo. A prova
  de recuperação gerou um backup SQLite real e tentou movê-lo para
  o caminho ativo. O pin atual recusou a cópia. Restaurar um
  manifesto antigo com o pin atual também foi recusado. Um commit
  com confirmação incerta retornou `commit_unknown` e o mesmo
  `request_id` reconciliou a decisão com o banco original.
- O listener `CrossUIDIngress` foi realmente aberto num diretório
  temporário. A ACL nomeada e o modo `0620` do socket foram
  verificados. O peer real era o UID 1000, fora da lista do fixture.
  Mesmo com um token válido, recebeu `denied` de acordo com o
  `SO_PEERCRED` observado no broker. A resposta Unix não trouxe
  descritores auxiliares. O socket foi removido ao fechar o perfil.
- As provas positivas usaram sockets Unix locais e a política
  `PeerAdmission.local_only`. São testes de contrato no mesmo UID.
  O perfil restrito recusou versões históricas e as operações de
  sessão. Os testes históricos exerceram o outro broker e confirmaram
  a compatibilidade e as negativas de lease, controle, mídia,
  captura, workspace e input. O texto de aparência executável
  foi recuperado literalmente sem criar o arquivo que nomeava.

## Matriz de qualificação

| Dimensão | Resultado | Alcance observado |
| --- | --- | --- |
| Provisionamento de identidades | GO | Manifesto, pins e reinício do perfil restrito em laboratório. O dono e o ciclo de entrega operacional dos pins exigem aprovação. |
| Proteção e rotação de credenciais | PARTIAL | Verificadores privados, rotação, aposentadoria e desativação testadas localmente. A proteção frente ao desktop real aguarda o segundo UID. |
| Política de grants | GO | Escopo exato, origem no manifesto, expiração e persistência do snapshot aprovado. |
| Revogação concorrente | GO | Disputa entre publicação local da política e a transação de aceite, inclusive repetição negada. |
| Proteção do banco | PARTIAL | Checagem de inode, permissões, ancestrais, journal e schema testadas. Negativa cross-UID de acesso direto ainda pendente. |
| Durabilidade e recuperação | GO | Recibos, commit incerto, rejeição de cópias antigas pelo pin atual e inspeção da cópia em quarentena. A reativação após perda do banco ativo fica fora do escopo validado. |
| Ingresso cross-UID | NOT RUN | ACL e negativa kernel/RPC com peer fora da lista em fixture local. Nenhum par admitido executou sob UID distinto do broker. |
| Negativas de acesso aos recursos privados | NOT RUN | Abrir o SQLite, atravessar recursos exclusivos, conectar a Wayland/Sway/D-Bus e reutilizar FDs sob UID desktop distinto aguardam um ambiente autorizado. |
| Compatibilidade histórica | GO | Regressões D.1A, D.1B, D.1C.1 e broker histórico. |
| Separação da autoridade de sessão | GO | Sem adaptadores no Registry-only. Negativas de operações reais no RPC com fixture do broker histórico. |

## Reprodução local

```sh
/usr/bin/python3 -B -m unittest discover -s tests -p 'test_registry_operational.py' -v
/usr/bin/python3 -B -m unittest discover -s tests -p '*registry*.py'
/usr/bin/python3 -B -m unittest discover -s tests
```

Para incluir as regressões GTK, usar o Sway headless descartável
com Cairo/Pixman e `LOOPSHELL_TEST_GTK=1` descrito no
[ensaio D.1C.1](LOOPSHELL_V0_8_D1C1_TRUSTED_REGISTRY.md#reprodução).
Os testes focados usam `TemporaryDirectory` e SQLite da biblioteca
padrão. O caso de ACL depende de Linux com POSIX ACL disponível e
de um usuário de teste sem privilégios.

A execução final aprovou 76 testes focados, incluindo 12 novos casos,
e 429 na suíte completa com GTK. A primeira execução completa
encontrou uma corrida no teste histórico de timeout. A injeção de
timeout agora afeta somente o cliente do teste, deixando o peer
da fixture receber normalmente.

O Sway principal conservou PID 1638, hora de início, versão,
configuração em disco e carregada, saídas e workspaces. A comparação
usou somente consultas IPC e hashes locais. O Sway descartável e
os diretórios temporários foram encerrados e removidos.

## Plano para uma prova autorizada entre UIDs

1. Selecionar um clone descartável ou um perfil temporário aprovado
   pelo operador. Registrar baseline do Sway principal e confirmar
   que o serviço e o desktop têm UIDs distintos. O operador
   precisa autorizar especificamente a execução sob o UID previsto e
   o provisionamento local de diretórios e ACLs. Se já houver contas
   dedicadas na cópia, reutilizá-las. Reservar um terceiro UID já
   provisionado para o peer fora da lista, quando disponível.
2. Em um caminho novo, por exemplo `/run/loop-registry-d1c2`, o
   administrador cria um ancestral root `0755` e os diretórios
   irmãos `private` e `ingress`, ambos do UID e GID dedicados.
   O primeiro fica `0700` e sem ACL padrão. O segundo recebe
   somente `u::rwx,u:<desktop-uid>:--x,g::---,m::--x,o::---`,
   sem ACL padrão. Verificar com `stat` e `getfacl -n`. A ACL
   resultante deve ser `0710`. Usar código verificado acessível
   ao serviço em um diretório de leitura protegido. Manter o
   diretório privado e o código de fixture separados de qualquer
   instalação LoopBridge existente.
3. Em um processo temporário sob o UID de serviço, chamar
   `initialize_registry_database(private)` uma vez. Criar o manifesto
   sintético v1 conforme o [contrato](../design/LOOPSHELL_V0_8_D1C2_OPERATIONAL_REGISTRY.md#manifesto-privado-v1).
   Entregar as credenciais por um canal de laboratório protegido e
   manter `DatabasePin` e `PolicyPin` em controle administrativo
   separado. Iniciar o broker de laboratório sob o UID dedicado
   com o seguinte arranjo Python, sem instalar uma unidade systemd.

   ```python
   from signal import SIGINT, SIGTERM, signal
   from threading import Event

   from experiments.registry_operational import serve_operational_registry
   from loopbridge.service_ingress import CrossUIDIngress, PeerAdmission

   stop = Event()
   signal(SIGINT, lambda *_: stop.set())
   signal(SIGTERM, lambda *_: stop.set())
   policy = PeerAdmission(service_uid, frozenset({desktop_uid}))
   ingress = CrossUIDIngress(ingress_path, private_path, policy)
   with serve_operational_registry(
       ingress, database_pin=database_pin, policy_pin=policy_pin
   ):
       stop.wait()
   ```

   Os paths são objetos `pathlib.Path`. Passar os UIDs e pins por
   configuração administrativa. Antes de publicar uma revogação,
   sincronizar o novo manifesto e registrar seu pin atual no
   controle independente. Encerrar o exemplo com SIGTERM e
   reiniciar com o pin atual. Para ensaiar publicação ao vivo,
   o supervisor deve chamar `control.reload(pin)` dentro do
   contexto do broker pelo canal administrativo aprovado.
4. De um processo desktop, comprovar UID e ACL efetivos e usar
   `loopbridge.protocol.RPC(sock, version='registry/1')` para
   autenticar e executar o fluxo de teste com cada credencial
   sintética apropriada. Exercitar também token inválido, token sem
   grant e token aposentado em conexões novas e preexistentes.
   De outro UID fora da ACL, registrar a negativa de conexão pelo
   kernel. Manter a negativa de `SO_PEERCRED` no fixture local para
   separar as duas camadas de proteção. A partir de um processo
   desktop, o seguinte teste mínimo confirma o UID real do broker,
   autentica um executor de laboratório e lê as ofertas autorizadas.

   ```python
   from getpass import getpass
   import socket

   from loopbridge.protocol import RPC
   from loopbridge.service_ingress import peer_uid

   with socket.socket(socket.AF_UNIX) as peer:
       peer.connect(str(ingress_path / 'registry.sock'))
       assert peer_uid(peer) == service_uid
       rpc = RPC(peer, version='registry/1')
       authenticated = rpc.call('auth', credential=getpass('Credencial sintética: '))
       assert authenticated['principal'] == executor_principal
       offers = rpc.call('objective.list_offers', executor_id=executor_id, limit=16)
       print(f"{len(offers['items'])} ofertas autorizadas")
   ```

5. Sob o UID desktop, verificar que listagem/travessia no diretório
   privado, leitura do SQLite e manifesto e abertura de sockets
   privados de fixture são recusadas. Usar listeners sentinela
   e FDs sintéticos no diretório privado do serviço. Tentar
   a abertura do descritor por `/proc/<pid>/fd/<n>` a partir
   do desktop, além de verificar `recvmsg` no RPC e inventariar os
   FDs do cliente e do serviço. Relatar sentinelas como tal.
   Sockets reais Wayland, Sway IPC e D-Bus privados exigem a fixture
   gráfica separadamente autorizada de
   [D4.2C](../design/TRUSTED_SERVICE_SMOKE_D42C.md). Este Registry
   não os inicia nem os recebe.
6. Revalidar revogação, reinício, recuperação do recibo com o mesmo
   request ID e rejeição de manifesto e banco restaurados. Registrar
   UIDs, modos, resultado dos acessos, sem tokens, corpos ou dumps
   de descritores. Fechar processos e remover somente os recursos
   do ensaio. Comparar novamente PID, configuração, saídas e
   workspaces do Sway principal.

## Riscos residuais

O provisionador é parte da base de confiança. Substituir também o
pin que ele mantém ou restaurar toda a VM pode reintroduzir um estado
antigo. O pin de inode não detecta todas as sobrescritas feitas no
mesmo inode pelo UID de serviço. A D.1C.2 ainda precisa da prova de
UID distinto e de um procedimento aprovado de reativação após perda
do banco ativo. A [matriz D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5),
M1.3B, GTK 2→1 e o desempenho da V0.8-C continuam independentes.
