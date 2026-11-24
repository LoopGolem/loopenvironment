# LoopShell V0.8-A — validação do layout ancorado

**Data** 2026-11-23. **Resultado geral** PARTIAL.

| Dimensão | Resultado | Evidência |
| --- | --- | --- |
| Funcional | GO no perfil ensaiado | Painel e console nativos, oito ajustes em execução, comandos locais, preferências restauradas e fechamento independente. |
| Geometria | GO nas quatro combinações estáveis | O tamanho e a posição medidos das superfícies e o tiling de duas janelas Foot coincidiram com as zonas reservadas em oito ajustes. |
| Integração Sway | PARTIAL | Modo, escala 1→2 e recuperação do modo compacto na escala 2 passaram. A volta de 2 para 1 exigiu reiniciar a LoopShell para recuperar as dimensões preferidas. |
| Segurança | GO no escopo funcional da interface | O ensaio confirmou o ciclo independente de uma sessão privada. O console é local e a LoopShell não autentica no Bridge, solicita grants ou recebe credenciais. Isolamento global mantém a qualificação própria. |

## Ambiente e dependências

Debian 13.7 amd64 em VirtualBox, kernel `6.12.117+deb13-amd64`, Sway 1.10.1,
GTK 4.18.6, PyGObject 3.50.0, libwayland-client 1.23.1 e Foot 1.21.0.
O ensaio A.1 usou um Sway descartável com backend headless do wlroots,
Pixman (wlroots 0.18.2), GTK Cairo, um output `HEADLESS-1` e D-Bus separado. O Sway principal,
PID 1638, conservou o processo, a versão, a configuração e a saída `Virtual-1`
1640×670 na escala 1. Os resultados de IPC e o hash da configuração coincidiram
antes e depois.

O ensaio anterior demonstrou uma prévia GTK4 em janela comum por falta da
biblioteca. Para A.1, os únicos pacotes obtidos foram
`libgtk4-layer-shell0` e `gir1.2-gtk4layershell-1.0` 1.0.4-2 amd64, do
repositório APT configurado `deb.debian.org/debian trixie/main`.
Os SHA-256 dos arquivos coincidiram com o índice do APT. A extração forneceu
`libgtk4-layer-shell.so.1.0.4`, o link `libgtk4-layer-shell.so.0`,
`Gtk4LayerShell-1.0.typelib` e a documentação dos pacotes. O `ldd`
resolveu libc, GLib/GObject, GTK4, Wayland client e suas dependências nas
bibliotecas existentes. Os pacotes permaneceram ausentes da instalação do Debian.

O Sway processa a zona do painel em `overlay` antes da zona do console em
`top`. O cliente solicita foco de teclado sob demanda no protocolo v4.
A prévia de uma janela continua disponível com `--preview`, em compositores
incompatíveis e em monitores lógicos menores que 520×320. Os limites das
preferências são 200–480 px e 120–400 px, medidos em coordenadas lógicas.
O cálculo considera as duas zonas da LoopShell. Outros painéis também podem
reservar espaço. [Sway 1.10.1](https://github.com/swaywm/sway/blob/1.10.1/sway/desktop/layer_shell.c)
· [API gtk4-layer-shell 1.0.4](https://github.com/wmww/gtk4-layer-shell/blob/v1.0.4/include/gtk4-layer-shell.h).

## Medições das quatro combinações

Em 1024×768, a prova alterou os controles GTK e acionou **Aplicar layout**
sem reiniciar o cliente. O protocolo Wayland registrou as zonas solicitadas
e os tamanhos configurados. O tamanho de cada superfície foi conferido no GDK.
A origem foi medida pela diferença entre as coordenadas enviadas ao cursor do
Sway e as coordenadas locais observadas pelo GTK. O IPC do Sway forneceu a área
útil e os retângulos das duas janelas Foot. Em cada caso, elas cobriram toda a
área útil, sem interseção entre si ou com as duas superfícies após o layout
estabilizar.

| Painel + console | Zonas, largura e altura | Painel | Console | Área útil |
| --- | ---: | ---: | ---: | ---: |
| Esquerda + inferior | 260 / 180 | 260×768 | 764×180 | 764×588 em (260, 0) |
| Esquerda + inferior | 200 / 120 | 200×768 | 824×120 | 824×648 em (200, 0) |
| Esquerda + superior | 290 / 200 | 290×768 | 734×200 | 734×568 em (290, 200) |
| Esquerda + superior | 370 / 220 | 370×768 | 654×220 | 654×548 em (370, 220) |
| Direita + inferior | 280 / 170 | 280×768 | 744×170 | 744×598 em (0, 0) |
| Direita + inferior | 410 / 240 | 410×768 | 614×240 | 614×528 em (0, 0) |
| Direita + superior | 240 / 150 | 240×768 | 784×150 | 784×618 em (0, 150) |
| Direita + superior | 480 / 400 | 480×768 | 544×400 | 544×368 em (0, 400) |

Em cada ajuste, um ponteiro e um teclado virtuais exclusivos do Sway
descartável permitiram verificar foco por clique no primeiro Foot, digitar
`help` no console e voltar o foco ao segundo Foot. O console exibiu a lista
de operações indisponíveis. No ensaio anterior, `echo example` retornou
a mensagem de comando demonstrativo desconhecido.

Antes da correção, a primeira configuração do console era 1024×180 e esse
buffer foi enviado antes da correção para 764×180. A LoopShell agora mostra o
console após o primeiro frame do painel para que a zona do painel já valha
quando o Sway configurar o console. O primeiro `configure` passou a ser
764×180 com as reservas 260/180. A prova registrou também 544×400 já no
primeiro `configure` do console nos dois reinícios com reservas 480/400.
Uma verificação adicional, com o renderizador GTK padrão, também recebeu
764×180 no primeiro `configure` para as zonas 260/180.
[Retângulos, zonas, origem do ponteiro e resultados brutos normalizados](evidence/LOOPSHELL_V0_8_A1_ANCHORED.json).

## Resolução, escala e sessão privada

- Em 1280×720 na escala 1, a área útil foi 800×320 com zonas 480/400.
  Ao subir para escala 2, a saída lógica passou a 640×360, as zonas se
  ajustaram a 320/160 e o Sway entregou 320×200 aos dois Foot.
- Em 960×600 na escala 2, a saída lógica de 480×300 acionou a prévia e liberou
  ambas as zonas. Voltar para 1280×720 ainda na escala 2 restaurou o layout
  ancorado. A mudança de escala pode passar por uma área útil intermediária
  enquanto Sway e cliente processam a nova geometria.
- Ao voltar para escala 1, o IPC do Sway e a superfície GDK registraram a
  nova escala, mas o monitor GDK continuou em 640×360 em vez de 1280×720.
  As zonas ficaram em 320/160, deixando uma área útil de 960×560. Depois
  de voltar a 1024×768 e reiniciar a LoopShell, a nova conexão GDK leu a
  saída corretamente e recuperou as preferências 480/400. O código do GTK
  4.18.6 é compatível com o sintoma, pois pode ignorar a atualização do fator
  de escala depois de definir a escala lógica. O reinício é a recuperação
  verificada nesse ambiente.
  [Monitor GDK](https://github.com/GNOME/gtk/blob/4.18.6/gdk/gdkmonitor.c#L588-L621)
  · [Backend Wayland do GDK](https://github.com/GNOME/gtk/blob/4.18.6/gdk/wayland/gdkdisplay-wayland.c#L2253-L2298).
- A tentativa anterior retornou `private_session_failed`. No diagnóstico
  delimitado, o mesmo caminho de criação de instância do laboratório
  (`loopbridge.private_session.Instance`, raiz e identidade descartáveis)
  iniciou o Sway privado e o broker e chegou a `ready`. A causa do erro
  anterior permaneceu indeterminada. A instância manteve identificador, PID
  e status enquanto a LoopShell abriu, fechou pelo botão, reabriu com as
  preferências persistidas e terminou por `SIGTERM`. Após cada saída,
  as zonas foram liberadas. O fixture encerrou apenas sua própria instância
  no fim do teste.

## Reprodução

Da raiz do checkout, use uma sessão de barramento temporária com
`dbus-run-session -- bash`. Os comandos abaixo habilitam o backend temporariamente no Debian amd64.

```bash
lab=$(mktemp -d /tmp/loopshell-v08a1.XXXXXX)
(
  cd "$lab"
  apt-get --print-uris download libgtk4-layer-shell0=1.0.4-2 gir1.2-gtk4layershell-1.0=1.0.4-2
  apt-get download libgtk4-layer-shell0=1.0.4-2 gir1.2-gtk4layershell-1.0=1.0.4-2
  sha256sum ./*.deb
  for deb in ./*.deb; do dpkg-deb -x "$deb" packages; done
)
lib="$lab/packages/usr/lib/x86_64-linux-gnu"
ldd "$lib/libgtk4-layer-shell.so.0"
mkdir -m 700 "$lab/run"
cat > "$lab/sway.conf" <<'CONFIG'
xwayland disable
output * mode 1024x768
seat seat0 fallback true
default_border pixel 0
focus_follows_mouse no
CONFIG
env -u SWAYSOCK -u WAYLAND_DISPLAY -u WAYLAND_SOCKET -u DISPLAY \
  XDG_RUNTIME_DIR="$lab/run" WLR_BACKENDS=headless WLR_RENDERER=pixman \
  WLR_HEADLESS_OUTPUTS=1 sway -c "$lab/sway.conf" > "$lab/sway.log" 2>&1 &
compositor=$!
trap 'kill "$compositor" 2>/dev/null; wait "$compositor" 2>/dev/null' EXIT
for attempt in {1..50}; do
  sockets=("$lab"/run/sway-ipc.*.sock)
  [[ -S "${sockets[0]}" && -S "$lab/run/wayland-1" ]] && break
  sleep .05
done
[[ -S "${sockets[0]}" && -S "$lab/run/wayland-1" ]] || exit 1
export XDG_RUNTIME_DIR="$lab/run" WAYLAND_DISPLAY=wayland-1 SWAYSOCK="${sockets[0]}"
foot --app-id loopshell-lab-foot-a /usr/bin/sleep 120 &
foot --app-id loopshell-lab-foot-b /usr/bin/sleep 120 &
```

Para repetir uma linha da tabela, altere `side`, `edge`, `width` e `height`
a cada execução. Os valores válidos são `left`/`right` e `top`/`bottom`.

```bash
printf '%s\n' '{"side":"left","edge":"bottom","width":260,"height":180}' > "$lab/layout.json"
env LD_LIBRARY_PATH="$lib" GI_TYPELIB_PATH="$lib/girepository-1.0" \
  GDK_BACKEND=wayland GSK_RENDERER=cairo GIO_USE_VFS=local WAYLAND_DEBUG=client \
  /usr/bin/python3 -B -m loopshell --config "$lab/layout.json" 2> "$lab/wayland.log" &
shell=$!
```

Após as superfícies mapearem, confira `set_exclusive_zone` e `configure`
em `"$lab/wayland.log"`. O comando `swaymsg -r -t get_workspaces` mostra
a área útil e `swaymsg -r -t get_tree` mostra os retângulos Foot. Aplique
`swaymsg output HEADLESS-1 mode 1280x720` e
`swaymsg output HEADLESS-1 scale 2` no compositor descartável para repetir a
sequência de modos e escala. Para o teste de foco, use um seat de teste
com dispositivos Wayland virtuais conectados somente ao socket descartável,
clique em cada janela e confira `focused` no IPC, os eventos
`wl_keyboard.enter` no protocolo e a resposta do console a `help`.
Feche a LoopShell e confira a liberação das zonas antes de repetir com outro JSON.

## Critérios A–H

| Critério | Resultado |
| --- | --- |
| A | GO. Painel esquerdo e direito com altura integral nos oito ajustes. |
| B | GO. Console superior e inferior ocupou a largura restante nos oito ajustes. |
| C | GO para ajustes em execução nas quatro combinações. O retorno da escala 2→1 ficou parcial por causa da geometria do GDK. |
| D | GO para duas janelas Foot em tiling e foco de ida e volta. Janelas flutuantes, múltiplos outputs e docks concorrentes ficam fora desta medição. |
| E | GO no fixture local. A mesma sessão privada permaneceu `ready` após fechamento e reinício da LoopShell. |
| F | GO para a separação funcional. O cliente se manteve na sessão gráfica em que foi iniciado e não usou credenciais, grants ou APIs de controle. A prova não mede isolamento de clientes com o mesmo UID. |
| G | GO. O painel e o console identificam conteúdo demonstrativo e `help` lista operações indisponíveis. |
| H | GO. Apenas o Sway descartável recebeu configuração e comandos do ensaio. |

`/usr/bin/python3 -B -m unittest discover -s tests -p test_loopshell_layout.py -v`
passou 12 testes, incluindo a espera pelo primeiro frame do painel.
`/usr/bin/python3 -B -m unittest discover -s tests` passou 301 testes.
A evidência gráfica é geométrica e protocolar, sem avaliação de desempenho,
monitores múltiplos ou escalas fracionárias.

O [D4.2C](../design/TRUSTED_SERVICE_SMOKE_D42C.md#gate-3-functional-result)
continua restrito ao smoke funcional cross-UID no perfil opt-in.
O isolamento de host permanece PARTIAL. [D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5)
e [M1.3B](M1_3B_TRUSTED_INPUT_FEASIBILITY.md) preservam seus gates. A evidência
de foco refere-se somente ao desktop de teste.
