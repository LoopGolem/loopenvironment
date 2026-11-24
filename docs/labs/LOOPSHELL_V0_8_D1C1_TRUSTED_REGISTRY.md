# V0.8-D.1C.1 — Ensaio de Registry RPC autenticado

**Resultado: GO para a integração local experimental.** A prova usou
LoopBridge e SQLite reais, credenciais sintéticas e um socket Unix
descartável por execução. A política de laboratório foi configurada
explicitamente no processo do broker. O PR #35 já estava incorporado
à `main` em `ca7e9d5`, com a branch remota de D.1B removida.

## Evidências

- O administrador registrou o executor. O destinatário confirmou o
  vínculo com sua credencial individual. Um terceiro com grant de
  confirmação e identidade divergente foi recusado. O mesmo UID
  Linux, por si só, também foi insuficiente.
- O emissor criou e publicou objetivos. O destinatário listou somente
  suas ofertas, consultou o texto autorizado, aceitou uma oferta e
  recusou outra. O emissor retirou a terceira. A lista omitiu os
  corpos. O teste recuperou literalmente o texto de aparência
  executável e verificou a ausência do arquivo que o texto nomeava.
- O SQLite preservou a revisão 3, o autor e a auditoria de cada
  transição. O mesmo `request_id` retornou o recibo original. Três
  instâncias sequenciais do serviço rodaram em processos distintos.
  Na segunda, autenticação sem grants recusou consulta e replay. Na
  terceira, novas conexões autenticadas com os grants explícitos
  recuperaram os três estados e o recibo. Um replay com outra decisão
  falhou com `request_conflict`. `PRAGMA integrity_check` retornou `ok`.
- A disputa entre aceite e retirada por duas conexões gravou uma só
  revisão 3. A outra recebeu `stale_revision`. A revogação de grant
  aguardou o commit em andamento e depois recusou resposta e replay.
  A expiração de um grant antes do commit reverteu a alteração
  preparada. A rotação invalidou as conexões antigas e manteve o
  recibo acessível ao mesmo principal após nova autenticação válida.
- A desconexão depois de a transação entrar no commit impediu a
  entrega da resposta. A exceção injetada após o commit retornou
  `commit_unknown`. Ambos os recibos foram reconciliados em nova
  conexão após reabrir o serviço. Falha de gravação, objetivo vencido
  e retrocesso do relógio geraram erros distintos.
- A prova de compatibilidade abriu uma conexão histórica no mesmo
  broker descartável e chamou `discover` sobre uma sessão de
  fixture. A auditoria dessa sessão omitiu a atividade do Registry.
  O broker normal também foi exercitado em socket separado.
  Recusou a versão experimental e não criou o banco do Registry.
- As verificações contra operações de sessão usaram a superfície
  real de `DesktopBroker`, uma sessão de fixture e um adaptador que
  detecta chamadas. Uma identidade do Registry com objetivo aceito
  não conseguiu usar descoberta, lease, janelas, mídia, captura,
  workspace ou teclado. A fixture manteve seu conjunto de grants e
  nenhuma lease ou chamada ao adaptador foi criada.
- Quadros acima de 8.192 bytes e chaves JSON duplicadas encerraram
  a conexão. Os limites de texto, revisão, validade e paginação
  foram exercitados. Os testes também verificaram erros sanitizados,
  omissão de corpos nas listas e ausência das credenciais do ensaio
  no banco e no log do broker.

## Matriz

| Dimensão | Resultado | Alcance |
| --- | --- | --- |
| Integração RPC | GO | Nove métodos experimentais e autenticação em socket Unix real. |
| Identidade individual | GO | Vínculo exato, negação entre principais e rotação no processo local. |
| Grants e revogação | GO | Escopo por executor, revalidação e ordenação com a escrita local. |
| Persistência e recuperação | GO | Reinício em processos distintos, falhas injetadas e reconciliação de recibos. |
| Concorrência | GO | Duas conexões e disputa de transições; política e transações no mesmo processo. |
| Compatibilidade com clientes existentes | GO | Versões históricas e autenticação válidas sob o broker normal e no perfil de laboratório. |
| Separação entre objetivos e autoridade de sessão | GO | Prova na fronteira RPC com sessão de fixture e adaptador monitorado. |
| Isolamento do host | PARTIAL | Diretório e socket privados no perfil local. A prova compartilha o UID do laboratório e não qualifica D5 ou M1.3B. |

## Reprodução

Debian 13.7, Python 3.13.5, SQLite 3.46.1 e Sway 1.10.1. As provas
RPC criam diretórios temporários e credenciais descartáveis. O teste
`test_process_restart_preserves_objectives_receipt_author_and_audit`
é o menor ensaio completo.

```sh
/usr/bin/python3 -B -m unittest discover -s tests -p 'test_trusted_registry_rpc.py' -v
/usr/bin/python3 -B -m unittest discover -s tests -p '*registry*.py'
```

Os 64 testes focados e os 417 da suíte completa passaram. Para incluir
as regressões GTK, foi executada com `LOOPSHELL_TEST_GTK=1`, Cairo
para GTK, Pixman para wlroots, saída headless 1280×800 e bus D-Bus
descartável. O procedimento a seguir usa somente dependências presentes
na VM.

```sh
env -u DISPLAY -u WAYLAND_DISPLAY -u WAYLAND_SOCKET -u SWAYSOCK dbus-run-session -- bash -eu <<'SH'
runtime=$(mktemp -d /tmp/loop-d1c1-gtk.XXXXXX)
export XDG_RUNTIME_DIR="$runtime" WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_HEADLESS_OUTPUTS=1
clean() {
    if test -n "${graphics_pid:-}"; then
        kill "$graphics_pid" 2>/dev/null || true
        wait "$graphics_pid" 2>/dev/null || true
    fi
    rm -rf -- "$runtime"
}
trap clean EXIT
printf 'output HEADLESS-1 mode 1280x800\n' > "$runtime/sway.conf"
sway -c "$runtime/sway.conf" > "$runtime/sway.log" 2>&1 &
graphics_pid=$!
for attempt in $(seq 1 60); do
    test ! -S "$runtime/wayland-1" || break
    sleep 0.1
done
if ! test -S "$runtime/wayland-1"; then
    cat "$runtime/sway.log"
    exit 1
fi
export WAYLAND_DISPLAY=wayland-1 LOOPSHELL_TEST_GTK=1 GSK_RENDERER=cairo GIO_USE_VFS=local
/usr/bin/python3 -B -m unittest discover -s tests
SH
```

O Sway principal conservou o PID 1638, a hora de início, a versão, a
configuração carregada e em disco, as saídas e os workspaces. A
comparação usou apenas consultas IPC e hashes do estado JSON. O
diretório da regressão gráfica e os sockets RPC descartáveis foram
removidos ao fim dos ensaios.

## Qualificação pendente

O ensaio mantém a política em memória e depende da coordenação entre
identidade, grants e SQLite no mesmo processo. A qualificação operacional
precisa revisar o provisionamento e a rotação de principais, a origem
dos grants, sua revogação sob o UID de serviço e a proteção e recuperação
do banco. Os limites de isolamento do host, D5, M1.3B, a escala GTK 2→1
e o desempenho da C.4 seguem independentes.
[Contrato e decisões do ensaio](../design/LOOPSHELL_V0_8_D1C1_TRUSTED_REGISTRY.md).
