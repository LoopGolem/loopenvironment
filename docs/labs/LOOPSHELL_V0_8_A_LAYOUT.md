# LoopShell V0.8-A — primeira prova de layout

**Data:** 2026-11-23. **Resultado geral:** PARTIAL.

| Dimensão | Resultado | Evidência |
| --- | --- | --- |
| Funcional | PARTIAL | Prévia GTK4 aberta em Sway, com orientação, preferências, reinício e console demonstrados. |
| Geometria de janelas | PARTIAL | Limites e solicitações de âncora testados deterministicamente. As duas superfícies simultâneas ainda precisam de medição. |
| Integração Sway | PARTIAL | Prévia e duas janelas Foot coexistiram no Sway do laboratório. O backend layer-shell aguarda a biblioteca e o typelib. |
| Segurança | PARTIAL | O cliente implementa entrada local e geometria. O Bridge permanece fora de seu fluxo. Sobrevivência de uma sessão privada e negação de acesso no cenário gráfico ainda precisam de evidência. |

## Ambiente e escolha de backend

Debian 13.7 em VirtualBox, kernel `6.12.117+deb13-amd64`, Sway 1.10.1, GTK 4.18.6,
PyGObject 3.50.0, Wayland client 1.23.1 e Foot 1.21.0. A sessão principal
tinha um output `Virtual-1` em 1640×670, escala 1, e uma janela em tela cheia.
Para os testes, foi iniciado outro processo Sway com configuração temporária,
backend headless do wlroots, Pixman, output 1024×768 e barramento D-Bus temporário.
O Sway principal manteve PID, output, resolução e escala durante o preflight e os testes.

`pkg-config`, o inventário de pacotes e a busca nos diretórios de bibliotecas
confirmaram a ausência de `gtk4-layer-shell`. A simulação
`apt-get -s --no-install-recommends install libgtk4-layer-shell0 gir1.2-gtk4layershell-1.0`
identificou somente dois novos pacotes, versão 1.0.4-2, com cerca de 23 kB
combinados. A execução local preservou a instalação do sistema.

A integração candidata usa duas superfícies no primeiro monitor anunciado pelo
GTK. O Sway processa a zona exclusiva do painel em `overlay` antes da zona do
console em `top`. O painel usa âncoras superior, inferior e lateral, o console
usa ambas as laterais e uma borda horizontal. Ambos pedem foco de teclado sob
demanda, disponível no protocolo layer-shell v4.
[Sway 1.10.1](https://github.com/swaywm/sway/blob/1.10.1/sway/desktop/layer_shell.c)
· [API gtk4-layer-shell 1.0.4](https://github.com/wmww/gtk4-layer-shell/blob/v1.0.4/include/gtk4-layer-shell.h).

No GTK4 disponível, uma janela comum gerenciada pelo Sway pode mostrar os
controles, o prompt e as orientações, mas não reservar essas zonas. Usar
`swaymsg` no cliente para mover janelas, forçar gaps ou alinhar janelas flutuantes
acrescentaria uma dependência do estado do gerenciador e não forneceria reservas
por superfície. Por isso, o fallback implementado indica **Prévia · Sem reserva
no Sway** e usa uma única janela comum.

## Reprodução

Do checkout, em uma sessão GTK4, execute com preferências descartáveis:

```sh
lab=$(mktemp -d /tmp/loopshell-v08a.XXXXXX)
GDK_BACKEND=wayland /usr/bin/python3 -B -m loopshell --config "$lab/layout.json"
```

Para forçar a prévia, acrescente `--preview`. Com a biblioteca e o typelib
disponíveis, o modo padrão usa layer-shell em compositor Wayland com protocolo
v4 ou posterior. Use **Aplicar layout** para persistir lado, borda, largura e
altura. O caminho padrão é `$XDG_CONFIG_HOME/loopenvironment/loopshell-layout.json`,
com fallback para `~/.config` quando a variável está ausente ou é relativa.
Os limites são 200–480 px de largura e 120–400 px de altura, em coordenadas
lógicas. A geometria é reduzida quando o monitor exige. Abaixo de 520×320 px
lógicos, a interface retorna à prévia para liberar o espaço e manter o console
acessível. A preferência original é reaplicada quando o monitor volta a caber.
A margem calculada para o workspace considera as duas zonas da LoopShell.
Outros painéis também podem reservar espaço.

Para reproduzir o teste sem tocar na sessão gráfica principal, rode em outro
terminal com um diretório temporário próprio para o runtime. Para isolar também o
barramento, abra primeiro `dbus-run-session -- bash`:

```bash
lab=$(mktemp -d /tmp/loopshell-v08a.XXXXXX)
cat > "$lab/sway.conf" <<'CONFIG'
xwayland disable
output * mode 1024x768
CONFIG
env -u SWAYSOCK -u WAYLAND_DISPLAY -u WAYLAND_SOCKET -u DISPLAY \
  XDG_RUNTIME_DIR="$lab" WLR_BACKENDS=headless WLR_RENDERER=pixman \
  WLR_HEADLESS_OUTPUTS=1 sway -c "$lab/sway.conf" &
compositor=$!
trap 'kill "$compositor" 2>/dev/null; wait "$compositor" 2>/dev/null' EXIT
```

Aguarde os sockets no diretório temporário e aponte os clientes para eles:

```bash
export XDG_RUNTIME_DIR="$lab"
outputs=("$lab"/wayland-*)
sockets=("$lab"/sway-ipc.*.sock)
export WAYLAND_DISPLAY="${outputs[0]##*/}" SWAYSOCK="${sockets[0]}"
GDK_BACKEND=wayland GIO_USE_VFS=local /usr/bin/python3 -B -m loopshell \
  --config "$lab/layout.json" &
foot --app-id loopshell-lab-foot-a /usr/bin/sleep 30 &
foot --app-id loopshell-lab-foot-b /usr/bin/sleep 30 &
swaymsg -r -t get_tree
swaymsg -r -t get_workspaces
```

Os testes gráficos executados usaram `dbus-run-session` para isolar também o
barramento. Na mesa gráfica do laboratório, use `help` e um comando desconhecido
como `echo example` para verificar as duas respostas. Para medir o backend
layer-shell, repita nas quatro combinações de bordas, altere as dimensões e
compare as áreas antes e depois. `WAYLAND_DEBUG=client` registra as dimensões
configuradas das duas superfícies. Faça a troca de modo e escala somente no
Sway descartável.

## Evidência e critérios

- `python3 -m unittest discover -s tests -p test_loopshell_layout.py -v`
  passou 10 testes e cobre limites, orientação, ordem de camadas, foco sob demanda, configuração
  inválida, falta da biblioteca, modo compacto e gravação/recuperação.
- `/usr/bin/python3 -B -m unittest discover -s tests` passou 299 testes,
  incluindo regressões de autorização de apresentação, ingress e ciclo de vida do LoopBridge.
- Um teste GTK temporário acionou as mudanças para direita e topo, aplicou
  300×215 px, leu o JSON resultante e acionou `help` e `echo example` na entrada.
  A prévia montou, reordenou as regiões e exibiu as respostas esperadas.
- Duas execuções do comando padrão abriram a prévia, por ausência da biblioteca,
  com duas janelas Foot em tiling. A área do workspace permaneceu 1024×768.
  As duas janelas Foot continuaram presentes depois de fechar a prévia
  normalmente e depois de terminá-la por sinal.
- Em outra execução, `swaymsg output HEADLESS-1 mode 1280x720` e em seguida
  `swaymsg output HEADLESS-1 scale 2` mudaram a área lógica a 1280×720 e
  640×360. Prévia e Foot continuaram mapeados ao alterar o output e ao voltar
  para 1024×768, escala 1.
- O manager descartável da V0.6 sinalizou prontidão, mas `private.start`
  retornou `private_session_failed` antes do teste de fechamento. O teste
  básico de namespace com Bubblewrap passou. Nenhuma sessão privada ficou
  disponível para verificar continuidade.

| Critério | Resultado neste ensaio |
| --- | --- |
| A | Pendente. Âncoras esquerda/direita e altura integral cobertas pelas solicitações testadas, sem medição do painel nativo. |
| B | Pendente. Âncoras topo/rodapé cobertas pelas solicitações testadas, sem medição da largura restante no Sway. |
| C | Pendente. Limites lógicos e fallback compacto cobertos em testes, sem medição de redimensionamento com as zonas ativas. |
| D | Parcial. Duas janelas Foot funcionaram com a prévia. Falta medir tiling, foco e janelas flutuantes com as duas zonas ativas. |
| E | Pendente. O reinício da prévia foi observado. O manager descartável não conseguiu iniciar a sessão privada. |
| F | Parcial. O cliente usa o display da sessão em que é iniciado e grava preferências de layout. Seu código não abre conexão com o Bridge nem solicita grants. Falta a prova em execução junto a uma sessão privada. |
| G | Confirmado. Os estados de exemplo e o console foram identificados como simulados. `help` mostrou operações indisponíveis e `echo example` recebeu a resposta de comando desconhecido. |
| H | Confirmado no ensaio. A configuração do Sway de teste ficou em um diretório temporário, e o processo e o output do Sway principal foram conferidos ao final. |

Não foram medidos escala, troca de resolução, múltiplos monitores, desempenho
ou latência no modo ancorado. A captura da prévia por snapshot GTK não produziu
um artefato. A geometria, o foco e a acomodação de outros painéis ainda precisam
de observação em uma sessão de teste. O próximo ensaio requer acesso temporário à
biblioteca e ao typelib e deve medir as zonas ativas antes de alterar a classificação.

O smoke [D4.2C](../design/TRUSTED_SERVICE_SMOKE_D42C.md#gate-3-functional-result)
continua restrito à observação autenticada no perfil opt-in da VM offline.
O isolamento de host permanece PARTIAL. [D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5)
e [M1.3B](M1_3B_TRUSTED_INPUT_FEASIBILITY.md) preservam seus gates de qualificação.
