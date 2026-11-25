# V0.8-D.1C.3 — Preflight de qualificação cross-UID

**PREPARED / NOT EXECUTED.** O driver e o procedimento estão prontos
para revisão. O preflight e as provas não privilegiadas foram executados.
O ensaio com dois UIDs reais aguarda autorização separada.

## Inventário de leitura

O PR #37 foi incorporado à `main` em `f5a25c0`, com a branch remota
anterior removida. A branch única partiu de uma árvore limpa.

| Item | Observação |
| --- | --- |
| Desktop | `vboxuser`, UID/GID 1000, com grupos suplementares 27 e 100 no login observado. |
| Serviço | `loopbridge-svc`, UID/GID 980, home `/nonexistent`, shell `/usr/sbin/nologin`. |
| Unidade instalada | `loopbridge.service` estava inativa e desabilitada. A unidade pertence ao perfil instalado. |
| Ingresso instalado | `/run/loopbridge-ingress`, 980:980, modo 0710. ACL com travessia para UID 1000. Nenhum listener LoopBridge apareceu na consulta `ss -xln`. |
| Recursos privados | `/var/lib/loopbridge`, 980:980, 0700. `/var/lib/loopbridge-admin`, 0:0, 0700. `/run/loopbridge-private` estava ausente. `/etc/loopbridge` pertence a root. |
| Runtime do desktop | `/run/user/1000`, 1000:1000, 0700. Sway principal no PID 1638. |
| Permissão de execução | O processo do preflight tinha UID/GID 1000 e capacidades efetivas zeradas. A troca para UID 980 e a criação de diretórios root em `/run` exigem o operador autorizado. |
| Ambiente descartável | A VM se identifica como VirtualBox. `VBoxManage` e um clone/snapshot autorizado não estavam acessíveis pela sessão. O operador deve confirmar o clone e o ponto de rollback no host. |

Foram usadas consultas `getent`, `id`, `systemctl show`, `stat`,
`getfacl -np`, `ss -xln`, `systemd-detect-virt` e consultas IPC de
leitura do Sway. A instalação, seus dados, verificadores, sockets,
contas, serviços, ACLs e configurações ficaram fora da execução.

## Driver e limites

O módulo `tools.registry_cross_uid` reutiliza o perfil
[D.1C.2](LOOPSHELL_V0_8_D1C2_OPERATIONAL_REGISTRY.md), a admissão
[D2](../design/TRUSTED_SERVICE_INGRESS_D2.md), o ciclo
[D3](../design/TRUSTED_SERVICE_LIFECYCLE_D3.md) e a
[ADR 0012](../DECISIONS/0012-trusted-service-identity-boundary.md).
O modo padrão `plan` emite JSON e termina.

Cada papel de execução exige um diretório novo com nome fixado em
`/run/loop-registry-d1c3-<16 hex>` e aprovação `0444` de root,
associada ao boot, aos UIDs e GIDs e válida por até 30 minutos.
O driver confere os IDs reais e efetivos, exige UIDs distintos,
ausência de grupos suplementares extras, capacidades efetivas,
permitidas e ambientes zeradas e `NoNewPrivs=1`. Ele recusa
descritores herdados além de stdio e ambiente gráfico privado. O
processo de serviço verifica a ACL e a propriedade dos diretórios.
A partida inicial exige diretórios de ingresso e dados vazios.
O reinício exige o pin obtido na partida original. O driver opera
sob os UIDs fornecidos externamente e não eleva privilégios.

A semente sintética entra por pipe anônimo e deriva credenciais
separadas para administrador, emissor, executor, executor rotacionado
e principal sem grant. A fixture usa uma semente compartilhada entre
seus dois processos para reproduzir as credenciais no reinício.
A semente fica na memória da sessão administrativa e dos processos.
Os JSON de evidência omitem semente, bearers, verificadores e corpo do
objetivo. O broker valida o UID do peer por `SO_PEERCRED`; o cliente
registra o UID efetivo observado e valida UID, GID e PID do servidor
por `SO_PEERCRED`. A identidade do cliente continua sujeita a
autenticação e grants. O ensaio só usa o executor e o objetivo
sintéticos definidos no módulo.

O socket privado `registry-sentinel.sock` e um `memfd` temporário
são **sentinelas**. O driver registra número e PID do descritor,
confere sua presença no servidor e tenta abrir o caminho em
`/proc` a partir do cliente. As respostas RPC são lidas com
`recvmsg`; dados auxiliares resultam em NO-GO, e o cliente fecha
qualquer descritor recebido. Nenhum compositor privado, Wayland,
Sway IPC, D-Bus ou serviço de produção é criado ou acessado por
esse procedimento. Os ensaios reais de display exigem plano
próprio, como o de [D4.2C](../design/TRUSTED_SERVICE_SMOKE_D42C.md).
A [matriz D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5)
e M1.3B seguem independentes.

## Reprodução autorizada futura

As etapas a seguir requerem aprovação humana separada. Confirmar o
clone descartável, registrar o ponto de restauração e aprovar a
execução como os UIDs indicados, a criação de subdiretórios temporários
em `/run`, a ACL do ingresso e a remoção ao fim. Nenhum passo
habilita uma unidade systemd, cria contas ou altera o Sway. Para a
prova mínima, usar desktop 1000:1000 e serviço 980:980 **somente se**
o clone confirmar esses IDs. Um terceiro UID/GID já existente e
aprovado é opcional.

Preparar um `git archive --format=tar <commit-revisado>` do
repositório, conferir seu SHA-256 por canal de confiança e entregar
o arquivo ao operador. Os passos a seguir usam Bash numa sessão
administrativa **já autorizada**, com tracing desligado. Executar
por blocos e interromper em caso de erro.

### Provisionar somente a fixture aprovada

```bash
set +x
set -euo pipefail
umask 022
test "$(id -u):$(id -g)" = 0:0
test "$(id -u vboxuser):$(id -g vboxuser)" = 1000:1000
test "$(id -u loopbridge-svc):$(id -g loopbridge-svc)" = 980:980
test "$(systemctl show loopbridge.service -p ActiveState --value)" = inactive
: "${D1C3_ARCHIVE:?arquivo tar do commit revisado}"
: "${D1C3_ARCHIVE_SHA:?SHA-256 aprovado do arquivo}"
test -f "$D1C3_ARCHIVE" && test ! -L "$D1C3_ARCHIVE"

D1C3_RUN=$(/usr/bin/python3 -c 'import secrets; print(secrets.token_hex(8))')
D1C3_ROOT="/run/loop-registry-d1c3-$D1C3_RUN"
D1C3_THIRD=''  # opcional, após aprovação; exemplo: 65534:65534
mkdir -m 0755 -- "$D1C3_ROOT"
mkdir -m 0755 -- "$D1C3_ROOT/source"
install -o 0 -g 0 -m 0600 -- "$D1C3_ARCHIVE" "$D1C3_ROOT/source.tar"
printf '%s  %s\n' "$D1C3_ARCHIVE_SHA" "$D1C3_ROOT/source.tar" | sha256sum -c -
tar --no-same-owner -xf "$D1C3_ROOT/source.tar" -C "$D1C3_ROOT/source"
install -d -o 980 -g 980 -m 0700 -- "$D1C3_ROOT/private" "$D1C3_ROOT/ingress"
setfacl --set 'u::rwx,u:1000:--x,g::---,m::--x,o::---' "$D1C3_ROOT/ingress"
stat -c '%a %u:%g %n' "$D1C3_ROOT" "$D1C3_ROOT/private" "$D1C3_ROOT/ingress"
getfacl -np "$D1C3_ROOT/ingress"

/usr/bin/python3 - "$D1C3_ROOT" "$D1C3_RUN" "$D1C3_THIRD" <<'PY'
import json
import os
from pathlib import Path
import sys
from time import time

root, run_id, third = sys.argv[1:]
approval = dict(version=1, run_id=run_id,
                boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                expires_unix=int(time()) + 1200, service=[980, 980], desktop=[1000, 1000],
                third=list(map(int, third.split(':'))) if third else None)
path = Path(root) / 'approval.json'
with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444), 'w') as out:
    print(json.dumps(approval), file=out)
PY
```

### Iniciar, verificar e reiniciar

O subprocesso do Registry recebe apenas comandos fixos no pipe de
controle administrativo. A sessão que autoriza a execução conserva
o pin original retornado em `broker_ready`. O reinício usa esse
valor e a geração 2 esperada, derivados do fluxo aprovado.

```bash
cd "$D1C3_ROOT/source"
unset D1C3_SEED
D1C3_SEED=$(/usr/bin/python3 -c 'import secrets; print(secrets.token_hex(32))')
d1c3_role() {
    local uid=$1 gid=$2
    shift 2
    if [[ -v D1C3_OUT ]]; then exec {D1C3_OUT}<&-; fi
    if [[ -v D1C3_IN ]]; then exec {D1C3_IN}>&-; fi
    exec /usr/bin/setpriv --reuid="$uid" --regid="$gid" --clear-groups --no-new-privs \
      /usr/bin/env -i PATH=/usr/bin:/bin /usr/bin/python3 -B -u \
      -m tools.registry_cross_uid --run-id "$D1C3_RUN" "$@"
}
d1c3_ready() {
    IFS= read -r -t 10 D1C3_READY <&"$D1C3_OUT"
    printf '%s\n' "$D1C3_READY"
    read -r D1C3_PID D1C3_FD D1C3_PIN < <(
        printf '%s\n' "$D1C3_READY" | /usr/bin/python3 -c '
import json, sys
r = json.load(sys.stdin)
assert r["event"] == "broker_ready"
print(r["broker_pid"], r["sentinel_fd"], r["database_pin"])'
    )
    test "$D1C3_PID" = "$D1C3_CHILD"
    test -f "/proc/$D1C3_PID/fd/$D1C3_FD"
}
d1c3_start() {
    coproc D1C3_BROKER { d1c3_role 980 980 broker "$@"; }
    D1C3_CHILD=$D1C3_BROKER_PID
    exec {D1C3_OUT}<&"${D1C3_BROKER[0]}"
    exec {D1C3_IN}>&"${D1C3_BROKER[1]}"
    printf '%s\n' "$D1C3_SEED" >&"$D1C3_IN"
    d1c3_ready
}
d1c3_desktop() {
    printf '%s\n' "$D1C3_SEED" | (
      d1c3_role 1000 1000 desktop --phase "$1" --broker-pid "$D1C3_PID" --sentinel-fd "$D1C3_FD"
    )
}
d1c3_stop() {
    local stopped
    printf 'stop\n' >&"$D1C3_IN"
    IFS= read -r -t 10 stopped <&"$D1C3_OUT"
    printf '%s\n' "$stopped"
    printf '%s\n' "$stopped" | /usr/bin/python3 -c '
import json, sys
r = json.load(sys.stdin)
assert r["event"] == "broker_stopped" and r["sockets_removed"]'
    wait "$D1C3_CHILD"
    exec {D1C3_OUT}<&-
    exec {D1C3_IN}>&-
    unset D1C3_OUT D1C3_IN
}

d1c3_start --phase initial
D1C3_ORIGINAL_PIN=$D1C3_PIN
D1C3_ORIGINAL_PID=$D1C3_PID
d1c3_desktop initial

if test -n "$D1C3_THIRD"; then
    (d1c3_role "${D1C3_THIRD%:*}" "${D1C3_THIRD#*:}" third)
fi

printf 'restrict\n' >&"$D1C3_IN"
IFS= read -r -t 10 D1C3_RESTRICTED <&"$D1C3_OUT"
printf '%s\n' "$D1C3_RESTRICTED" | /usr/bin/python3 -c '
import json, sys
r = json.load(sys.stdin)
assert r == {"event": "policy_restricted", "generation": 2}'
printf '%s\n' "$D1C3_RESTRICTED"
d1c3_desktop restricted
d1c3_stop

d1c3_start --phase restart --database-pin "$D1C3_ORIGINAL_PIN"
test "$D1C3_PID" != "$D1C3_ORIGINAL_PID"
test "$D1C3_PIN" = "$D1C3_ORIGINAL_PIN"
d1c3_desktop recovered
d1c3_stop
unset D1C3_SEED
```

Guardar somente as linhas JSON sanitizadas. A partida inicial
registra o cadastro e vínculo, publicação, aceite, recusa de
credencial inválida e de principal sem grant. O cliente também tenta
listar e atravessar o diretório privado, abrir banco, manifesto e
descritor e conectar à sentinela. Exigir `EACCES` ou `EPERM`
com o fixture vivo. A fase restrita prova a revogação do emissor e
a recusa de autenticação com o bearer aposentado. No reinício,
comparar PIDs e pin original, autenticar com a credencial nova e
recuperar o mesmo recibo. A negativa do terceiro é registrada
durante o primeiro broker ativo, entre as verificações do desktop.

### Dados e rollback

Encerrar o filho exato pelo pipe. Se a sequência falhar com um
filho ativo, confirmar o PID do `coproc`, UID e linha de comando
da fixture com `ps -p "$D1C3_CHILD" -o pid,lstart,uid,args` antes
de executar `kill -TERM -- "$D1C3_CHILD"` e
`wait "$D1C3_CHILD"`. Evitar busca ampla por nome de processo. Conferir que os
dois sockets e descritores sentinela desapareceram. Se a aprovação
expirar ou o pipe fechar, o broker também encerra o loop de controle.
Remover a semente da sessão e sair do diretório de código antes
de remover a fixture.

Depois de guardar a evidência sanitizada, a remoção autorizada
se restringe ao diretório deste ensaio. Inspecionar a árvore sem
seguir links e confirmar que não existem mounts dentro dela.

```bash
cd /run
[[ "$D1C3_ROOT" =~ ^/run/loop-registry-d1c3-[0-9a-f]{16}$ ]]
test -d "$D1C3_ROOT" && test ! -L "$D1C3_ROOT"
test "$(stat -c '%a:%u:%g' "$D1C3_ROOT")" = 755:0:0
test ! -e "$D1C3_ROOT/ingress/registry.sock" && test ! -L "$D1C3_ROOT/ingress/registry.sock"
test ! -e "$D1C3_ROOT/private/registry-sentinel.sock" && test ! -L "$D1C3_ROOT/private/registry-sentinel.sock"
find -P "$D1C3_ROOT" -xdev -print
rm -r --one-file-system -- "$D1C3_ROOT"
test ! -e "$D1C3_ROOT"
```

Em saída abrupta com sockets remanescentes, conferir que os PIDs
registrados encerraram e os sockets pertencem à fixture antes
da remoção externa da árvore. O rollback completo é o ponto de
restauração aprovado do clone e deve ser feito pelo operador do
hypervisor. Comparar novamente unidade instalada e Sway principal
com os baselines, inclusive PID, configuração, saídas e workspaces.

## Critérios do ensaio futuro

| Classificação | Critério |
| --- | --- |
| GO | UIDs reais distintos comprovados, ACL e modos verificados, fluxo completo e replay após reinício, negativas do desktop em todos os recursos sentinela, nenhuma transferência de descritor e cleanup completo. |
| PARTIAL | Algum item obrigatório sem prova, erro funcional, fixture ausente ou negativa ambígua. A negativa de terceiro UID é opcional e pode ficar NOT RUN se ele não estiver disponível. |
| NO-GO | Leitura ou abertura não autorizada, autenticação indevida, emissão de descritor auxiliar, autoridade IPC indevida ou alteração do ambiente protegido. |

O resultado desta missão é **PREPARED / NOT EXECUTED** para todos
os critérios entre UIDs distintos. A prova local usa payloads
sintéticos, sockets descartáveis, controles em memória e testes
determinísticos das guardas. O caminho de prova real fica fechado
até a aprovação prevista neste procedimento.

## Testes locais

```sh
/usr/bin/python3 -B -m tools.registry_cross_uid plan
/usr/bin/python3 -B -m unittest discover -s tests -p 'test_registry_cross_uid.py' -v
/usr/bin/python3 -B -m unittest discover -s tests -p '*registry*.py'
/usr/bin/python3 -B -m unittest discover -s tests
```

As regressões GTK usam um Sway headless e runtime descartáveis
como na [reprodução D.1C.1](LOOPSHELL_V0_8_D1C1_TRUSTED_REGISTRY.md#reprodução).

Passaram 12 novos testes do driver, 88 testes focados de Registry
e 441 na suíte completa com GTK. Os três blocos Bash foram validados
com `bash -n`. A passagem de controle por `coproc` também foi
ensaiada com um subprocesso simulado sob o mesmo UID.

Após a suíte, o Sway principal conservou PID 1638, hora de início,
versão, configuração carregada e em disco, saídas e workspaces.
A unidade instalada continuou inativa e desabilitada. Nenhum
diretório `/run/loop-registry-d1c3-*` foi criado.
