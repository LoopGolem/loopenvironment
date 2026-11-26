# V0.8-D.2B.1 — Preflight de execução supervisionada cross-UID

**PREPARED / NOT EXECUTED.** O perfil, o driver e o procedimento foram
preparados. A autorização para dois UIDs reais pertence a um ensaio
posterior. O [PR #41](https://github.com/LoopGolem/loopenvironment/pull/41)
foi incorporado à `main` em `049b82bc686938debeb8e79ecd294b421220c043`
com árvore idêntica à de `24584ddb3bba6f36c4e03669fc509717e3d91ebe`.
O desenvolvimento partiu de worktree limpo e preservou o checkout
histórico e as evidências locais de M1.3B.2.
[Contrato D.2B.1](../design/LOOPSHELL_V0_8_D2B1_CROSS_UID_SUPERVISION.md).

O GO local da [D.2B](LOOPSHELL_V0_8_D2B_SUPERVISED_EXECUTION.md) sustenta
o plano e os controles. O GO cross-UID da
[D.1C.4](LOOPSHELL_V0_8_D1C4_CROSS_UID_EXECUTION.md) sustenta o Registry
no clone, com sentinelas. D5 segue PARTIAL e M1.3B segue independente.
O isolamento de recursos gráficos reais continua NOT RUN.

## Evidência local do preflight

A prova do driver usa dois processos sucessivos de broker, sockets Unix,
`SO_PEERCRED` real sob o mesmo UID e SQLite real. O adaptador de teste
simula somente a configuração de dois UIDs e a ACL do listener. As
barreiras, contadores, perda de controle, reabertura, consulta de
auditoria e retorno `5` percorrem o código do driver. A abertura do
banco com pin errado, política inválida, peer inesperado e aprovações
inválidas foi recusada. Os testes herdados D.1C.3 cobrem a inspeção de
grupos, privilégios, descritores e dados auxiliares. Os seis probes
de isolamento D.2B.1 com UIDs distintos estão **NOT RUN**.

| Comando | Resultado |
| --- | --- |
| `/usr/bin/python3 -B -m tools.supervision_cross_uid --run-id 0123456789abcdef plan` | PREPARED / NOT EXECUTED. Sem escrita. |
| `/usr/bin/python3 -B -m unittest discover -s tests -p 'test_supervision_cross_uid.py'` | 13 testes aprovados. |
| Mesmo comando com `test_execution_d2a.py`, `test_supervised_execution.py` e `*registry*.py` | 33 D.2A, 29 D.2B e 88 testes do Registry aprovados. |
| `/usr/bin/python3 -B -m unittest discover -s tests` | 516 no total, com 508 aprovados e 8 GTK omitidos por opt-in. |
| Mesmo comando com `LOOPSHELL_TEST_GTK=1` em Sway headless e D-Bus descartáveis | 516 testes aprovados, incluindo as 8 regressões GTK. |
| Schemas, links, blocos Bash e `git diff --check` | Aprovados. Os blocos futuros foram verificados com `bash -n`. |

O perfil e cliente estão em [supervision_operational.py](../../experiments/supervision_operational.py)
e [supervised_execution.py](../../tools/supervised_execution.py).
O [driver](../../tools/supervision_cross_uid.py),
o [fluxo desktop](../../tools/supervision_cross_uid_flow.py) e
os [testes](../../tests/test_supervision_cross_uid.py) definem o ensaio.
A [CI](../../.github/workflows/regression.yml) executa as regressões no PR.

## Matriz para a prova futura

| Fase | Evidência obrigatória | Resultado atual |
| --- | --- | --- |
| A — Ingresso e isolamento | Dois UIDs reais, `SO_PEERCRED` com PID/UID/GID esperados, credencial válida, negativas de credencial errada e de principal sem grant. Com a sentinela viva, seis negativas por instância para travessia, listagem, banco, manifesto, conexão privada e abertura de descritor em `/proc`. `EACCES` ou `EPERM` com ausência de mensagens auxiliares. | PREPARED / NOT EXECUTED |
| B — Fluxo | Cadastro, confirmação, oferta, aceite, admissão própria, zero progresso e chamadas antes do avanço, um passo, retorno a pausa, continuação, segundo despacho, resultado inteiro `5` e auditoria separada. Observador recusado em passo, avanço e cancelamento. | PREPARED / NOT EXECUTED |
| C — Disputas | Pausa antes do despacho e pausa pendente durante etapa. Dois pedidos concorrentes de passo e replay do vencedor. Revogação, expiração de avanço e da tentativa e cancelamento, com contadores e ausência de sucesso tardio. | PREPARED / NOT EXECUTED |
| D — Reinício | Interrupção coordenada de worker com despacho durável, encerramento da instância, novo PID e mesmo pin, negativos antes da reemissão, histórias terminais com o mesmo hash, recibo histórico reconciliado e interrupção em `uncertain`. Ambos os motivos de expiração persistem. Zero computações após reinício. | PREPARED / NOT EXECUTED |
| E — Cleanup | Processos exatos encerrados, sockets e descritor sentinela liberados, nenhuma montagem dentro da raiz, remoção da fixture aprovada e baselines da unidade instalada e do Sway coincidentes. | PREPARED / NOT EXECUTED |

**GO cross-UID** requer A–E integralmente demonstradas no clone e
evidência revisável de kernel e RPC. **PARTIAL** cobre interrupção,
falha de ambiente ou evidência faltante sem violação observada.
**NO-GO** cobre sucesso de acesso direto, transferência de descritor,
bypass de autoridade, identidade de peer inesperada no ingresso
qualificado, duplicação, falso acknowledgement ou sucesso tardio.
A ausência de um arquivo sentinela, `ENOENT` ou timeout não prova negação.
Divergência de identidade, pin, byte de arquivo, aprovação de execução
expirada ou falha de limpeza interrompem o procedimento.

## Preparação do operador

### 1. Autorizar clone e transferir a revisão

Exigir autorização nova e explícita para a fixture D.2B.1, seus dois
UIDs e a janela. Usar o clone independente Debian 13 `looplab-d1c3`
somente se o operador confirmar o hostname, machine ID exclusivo,
boot ID e snapshot aprovado no host. Confirmar `loopbridge-svc`
`980:980` e `vboxuser` `1000:1000`. Se a instalação do clone diferir,
parar e revisar a configuração candidata. A autorização D.1C.4 tem
seu próprio escopo.

Na origem confiável, exportar o **commit completo revisado** e levar
o TAR ao clone por mídia de leitura aprovada, como uma ISO anexada
manualmente pelo operador no VirtualBox. Fornecer commit e SHA-256 em
um canal confiável independente da mídia. O clone pode ficar sem rede.
A aprovação deve identificar o TAR e a janela. Os comandos abaixo
são para execução **posterior** pelo operador.

```bash
test -n "$D2B1_COMMIT" && git rev-parse --verify "$D2B1_COMMIT^{commit}"
test "$(git rev-parse "$D2B1_COMMIT")" = "$D2B1_COMMIT"
git archive --format=tar --output "$D2B1_ARCHIVE" "$D2B1_COMMIT"
sha256sum -- "$D2B1_ARCHIVE"
```

### 2. Capturar baselines e verificar pré-requisitos

Na sessão gráfica existente do desktop, colete o hash abaixo antes e
depois do ensaio. Use a mesma sessão e o mesmo socket real de Sway.
Saídas e workspaces devem ser comparados em uma área de trabalho ociosa.
Os dados da sessão ficam locais. A evidência exportada pode registrar
somente o resultado da comparação.

```bash
sway_baseline() {
  local pid
  pid=$(pgrep -x -u "$(id -u)" sway) || return
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  {
    ps -p "$pid" -o pid=,lstart=,uid=
    swaymsg -r -t get_version
    swaymsg -r -t get_config
    swaymsg -r -t get_outputs
    swaymsg -r -t get_workspaces
  } | sha256sum
}
set -o pipefail
sway_baseline
```

Os blocos administrativos seguintes pressupõem sessão root já
autorizada no clone, tracing desligado e aprovação para criar e
remover somente o diretório exclusivo da fixture. Registre o estado
da unidade e confirme o snapshot no host antes de prosseguir.

```bash
set +x
set -euo pipefail
umask 022
test "$(id -u):$(id -g)" = 0:0
test "$(hostname)" = looplab-d1c3
test "$(cat /etc/machine-id)" = "${D2B1_EXPECTED_MACHINE_ID:?ID do clone aprovado}"
test "$(id -u vboxuser):$(id -g vboxuser)" = 1000:1000
test "$(id -u loopbridge-svc):$(id -g loopbridge-svc)" = 980:980
for tool in setpriv setfacl getfacl findmnt sha256sum tar python3; do
  command -v "$tool" >/dev/null
done
test "$(systemctl show loopbridge.service -p ActiveState --value)" = inactive
test "$(systemctl show loopbridge.service -p UnitFileState --value)" = disabled
d2b1_unit() {
  {
    systemctl show loopbridge.service -p ActiveState -p UnitFileState -p FragmentPath -p MainPID
    systemctl cat loopbridge.service
  } | sha256sum
}
D2B1_UNIT_BEFORE=$(d2b1_unit)
```

### 3. Provisionar somente a fixture

```bash
: "${D2B1_ARCHIVE:?TAR revisado na mídia de leitura}"
: "${D2B1_ARCHIVE_SHA:?SHA-256 recebido por canal confiável}"
[[ "$D2B1_ARCHIVE_SHA" =~ ^[0-9a-f]{64}$ ]]
test -f "$D2B1_ARCHIVE" && test ! -L "$D2B1_ARCHIVE"
D2B1_RUN=$(/usr/bin/python3 -c 'import secrets; print(secrets.token_hex(8))')
D2B1_ROOT="/run/loop-supervision-d2b1-$D2B1_RUN"
mkdir -m 0755 -- "$D2B1_ROOT"
mkdir -m 0755 -- "$D2B1_ROOT/source"
install -o 0 -g 0 -m 0600 -- "$D2B1_ARCHIVE" "$D2B1_ROOT/source.tar"
printf '%s  %s\n' "$D2B1_ARCHIVE_SHA" "$D2B1_ROOT/source.tar" | sha256sum -c -
tar --no-same-owner -xf "$D2B1_ROOT/source.tar" -C "$D2B1_ROOT/source"
D2B1_BAD_SOURCE=$(find -P "$D2B1_ROOT/source" \( ! -user root -o -perm /022 \) -print -quit)
test -z "$D2B1_BAD_SOURCE"
install -d -o 980 -g 980 -m 0700 -- "$D2B1_ROOT/private" "$D2B1_ROOT/ingress"
setfacl --set 'u::rwx,u:1000:--x,g::---,m::--x,o::---' "$D2B1_ROOT/ingress"
stat -c '%a %u:%g %n' "$D2B1_ROOT" "$D2B1_ROOT/private" "$D2B1_ROOT/ingress"
getfacl -np "$D2B1_ROOT/ingress"
```

A última etapa de aprovação abre uma janela de 20 minutos. O broker
verifica o prazo e termina se o pipe administrativo fechar. Mantenha
uma única sessão administrativa para conservar a semente descartável
e o pin original em memória. Os comandos se destinam à sessão
descrita, com tracing desligado, sem exportar a semente.

```bash
/usr/bin/python3 - "$D2B1_ROOT" "$D2B1_RUN" <<'PY'
import json, os, socket, sys, time
from pathlib import Path

root, run_id = sys.argv[1:]
approval = dict(version=1, profile='supervision-d2b1', run_id=run_id,
                hostname=socket.gethostname(), machine_id=Path('/etc/machine-id').read_text().strip(),
                boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                expires_unix=int(time.time()) + 1200, expires_monotonic=int(time.monotonic()) + 1200,
                service=[980, 980], desktop=[1000, 1000])
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
with os.fdopen(os.open(Path(root) / 'approval.json', flags, 0o444), 'w') as out:
    print(json.dumps(approval), file=out)
PY
cd -- "$D2B1_ROOT/source"
/usr/bin/python3 -B -m tools.supervision_cross_uid --run-id "$D2B1_RUN" plan
unset D2B1_SEED
D2B1_SEED=$(/usr/bin/python3 -c 'import secrets; print(secrets.token_hex(32))')
```

### 4. Carregar funções e iniciar

A sessão administrativa retransmite ao pipe do broker apenas os casos
fixos de barreira. O desktop recebe as credenciais sintéticas derivadas
da semente pelo pipe anônimo e usa RPC para a execução. As funções
confiam nos PIDs dos filhos iniciados pela própria sessão. O cliente
de referência pode usar os mesmos PID, UID e GID verificados, mediante
os três argumentos `--service-*`.

```bash
d2b1_field() {
  /usr/bin/python3 -c '
import json, sys
value = json.load(sys.stdin)[sys.argv[1]]
print(value if isinstance(value, (str, int)) else json.dumps(value, separators=(",", ":")))
' "$1"
}
d2b1_role() {
  local uid=$1 gid=$2
  shift 2
  if [[ -v D2B1_OUT ]]; then exec {D2B1_OUT}<&-; fi
  if [[ -v D2B1_IN ]]; then exec {D2B1_IN}>&-; fi
  exec /usr/bin/setpriv --reuid="$uid" --regid="$gid" --clear-groups --no-new-privs \
    /usr/bin/env -i PATH=/usr/bin:/bin /usr/bin/python3 -B -u \
    -m tools.supervision_cross_uid --run-id "$D2B1_RUN" "$@"
}
d2b1_read() {
  IFS= read -r -t 15 D2B1_EVENT <&"$D2B1_OUT"
  printf '%s\n' "$D2B1_EVENT"
  test "$(d2b1_field event <<<"$D2B1_EVENT")" = "$1"
}
d2b1_start() {
  coproc D2B1_BROKER { d2b1_role 980 980 broker "$@"; }
  D2B1_CHILD=$D2B1_BROKER_PID
  exec {D2B1_OUT}<&"${D2B1_BROKER[0]}"
  exec {D2B1_IN}>&"${D2B1_BROKER[1]}"
  printf '%s\n' "$D2B1_SEED" >&"$D2B1_IN"
  d2b1_read broker_ready
  D2B1_PID=$(d2b1_field broker_pid <<<"$D2B1_EVENT")
  D2B1_FD=$(d2b1_field sentinel_fd <<<"$D2B1_EVENT")
  D2B1_PIN=$(d2b1_field database_pin <<<"$D2B1_EVENT")
  test "$D2B1_PID" = "$D2B1_CHILD"
  test "$(d2b1_field run_id <<<"$D2B1_EVENT")" = "$D2B1_RUN"
  test -S "$D2B1_ROOT/private/registry-sentinel.sock"
  test -f "/proc/$D2B1_PID/fd/$D2B1_FD"
}
d2b1_desktop() {
  printf '%s\n' "$D2B1_SEED" | (
    d2b1_role 1000 1000 desktop --phase "$1" --broker-pid "$D2B1_PID" --sentinel-fd "$D2B1_FD" "${@:2}"
  )
}
d2b1_stopped() {
  d2b1_read broker_stopped
  test "$(d2b1_field reason <<<"$D2B1_EVENT")" = "$1"
  wait "$D2B1_CHILD"
  exec {D2B1_OUT}<&-
  exec {D2B1_IN}>&-
  unset D2B1_OUT D2B1_IN
  test ! -e "/proc/$D2B1_PID/fd/$D2B1_FD"
  test ! -e "$D2B1_ROOT/private/registry-sentinel.sock"
  test ! -e "$D2B1_ROOT/ingress/supervised.sock"
}
d2b1_start --phase initial
D2B1_ORIGINAL_PIN=$D2B1_PIN
D2B1_ORIGINAL_PID=$D2B1_PID
d2b1_desktop prepare
printf 'arm\n' >&"$D2B1_IN"
d2b1_read fixture_armed
D2B1_ATTEMPTS=$(d2b1_field attempts <<<"$D2B1_EVENT")
```

### 5. Exercitar controles e interrupção coordenada

```bash
exec {D2B1_DESKTOP_OUT}< <(d2b1_desktop active --attempts "$D2B1_ATTEMPTS")
D2B1_DESKTOP_CHILD=$!
D2B1_ACTIVE_COMPLETE=no
while IFS= read -r -t 15 line <&"$D2B1_DESKTOP_OUT"; do
  printf '%s\n' "$line"
  case "$(d2b1_field event <<<"$line")" in
    release_required)
      case_id=$(d2b1_field case <<<"$line")
      case "$case_id" in
        before_dispatch|pause_running|step_race|revoked|advance_expired|cancelled|attempt_expired|interrupted)
          printf 'release %s\n' "$case_id" >&"$D2B1_IN" ;;
        *) exit 1 ;;
      esac ;;
    recovery_reference)
      D2B1_AUDIT_SHA=$(d2b1_field audit_sha256 <<<"$line")
      [[ "$D2B1_AUDIT_SHA" =~ ^[0-9a-f]{64}$ ]] ;;
    desktop_active_complete) D2B1_ACTIVE_COMPLETE=yes ;;
    *) exit 1 ;;
  esac
done
exec {D2B1_DESKTOP_OUT}<&-
test "$D2B1_ACTIVE_COMPLETE" = yes
wait "$D2B1_DESKTOP_CHILD"
d2b1_stopped interrupted_pending_dispatch
```

A contagem esperada em ordem é `flow=2`, `before_dispatch=0`,
`pause_running=2`, `step_race=1`, `revoked=1`, `advance_expired=1`,
`cancelled=1`, `attempt_expired=0` e `interrupted=1`. A chamada do
último caso termina em memória e seu retorno fica retido na barreira.
O controle administrativo encerra a instância com despacho persistido
e sem confirmação de conclusão. A nova instância deve recuperar esse despacho como
`uncertain`.

### 6. Reabrir com o pin original e conferir a recuperação

```bash
d2b1_start --phase restart --database-pin "$D2B1_ORIGINAL_PIN"
test "$D2B1_PID" != "$D2B1_ORIGINAL_PID"
test "$D2B1_PIN" = "$D2B1_ORIGINAL_PIN"
d2b1_desktop before-regrant --previous-pid "$D2B1_ORIGINAL_PID" --attempts "$D2B1_ATTEMPTS"
printf 'reissue\n' >&"$D2B1_IN"
d2b1_read recovery_grants_reissued
d2b1_desktop recovered --previous-pid "$D2B1_ORIGINAL_PID" \
  --attempts "$D2B1_ATTEMPTS" --audit-sha256 "$D2B1_AUDIT_SHA"
printf 'stop\n' >&"$D2B1_IN"
d2b1_stopped requested
unset D2B1_SEED
```

### 7. Parada, evidência e limpeza

Em caso de erro, feche o pipe ou envie `stop` à instância identificada.
Antes de enviar sinal, confirme o PID exato do filho com
`ps -p "$D2B1_CHILD" -o pid,lstart,uid,args` e identifique o comando
da fixture. Se for necessário, use `kill -TERM -- "$D2B1_CHILD"` e aguarde
o filho. Preserve banco e pin para a análise enquanto o ensaio estiver
incompleto. Uma restauração de snapshot depende da decisão do operador.
Nunca substitua o pin por um obtido de um banco reaparecido.

Guarde somente JSON sanitizado, comparação de baselines e resultados
de cleanup. A aprovação, semente, bearers, manifesto e SQLite ficam
fora da evidência exportada. Confirme a ausência de montagens
e o conteúdo da raiz exclusiva antes da remoção autorizada.

```bash
unset D2B1_SEED
cd /run
[[ "$D2B1_ROOT" =~ ^/run/loop-supervision-d2b1-[0-9a-f]{16}$ ]]
test -d "$D2B1_ROOT" && test ! -L "$D2B1_ROOT"
test "$(stat -c '%a:%u:%g' "$D2B1_ROOT")" = 755:0:0
for socket in ingress/supervised.sock private/registry-sentinel.sock; do
  test ! -e "$D2B1_ROOT/$socket" && test ! -L "$D2B1_ROOT/$socket"
done
D2B1_MOUNTS=$(findmnt -rn -o TARGET)
if awk -v root="$D2B1_ROOT" '$0 == root || index($0, root "/") == 1 { found=1 } END { exit !found }' \
  <<<"$D2B1_MOUNTS"; then exit 1; fi
find -P "$D2B1_ROOT" -xdev -print
test "$(d2b1_unit)" = "$D2B1_UNIT_BEFORE"
```

Depois de revisar a listagem e repetir a baseline de Sway na sessão
desktop, autorize a remoção exclusivamente da raiz confirmada.

```bash
[[ "$D2B1_ROOT" =~ ^/run/loop-supervision-d2b1-[0-9a-f]{16}$ ]]
rm -r --one-file-system -- "$D2B1_ROOT"
test ! -e "$D2B1_ROOT"
test "$(d2b1_unit)" = "$D2B1_UNIT_BEFORE"
```
