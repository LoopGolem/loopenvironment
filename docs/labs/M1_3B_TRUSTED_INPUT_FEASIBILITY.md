# M1.3B — Trusted Input & Enforcement Feasibility

**Resultado: NO-GO para habilitar takeover na composição atual de Sway sem
modificação + M1.3A.** Não foi encontrada uma fronteira existente que satisfaça a
barreira conjunta de input convencional e AT-SPI. A investigação foi encerrada
antes de implementar enforcement. Há diagnóstico executável, testes e evidência
real negativa; **não há POC de takeover, patch ou compositor selecionado**.

Isto não demonstra impossibilidade de um patch futuro ou de outro compositor,
nem rebaixa o GO delimitado do M1.3A. Uma alternativa ainda não construída não é
classificada como tecnicamente impossível. [Session Authority V1](../design/SESSION_AUTHORITY_V1.md)
e ADRs 0006–0008 foram preservados, sem redefinir confirmação como simples aceitação
no broker. Não se iniciou M1.3C, LoopTeach, instalação ou imagem do SO.

## Preparação e método

Foram lidos AGENTS, README, VISION, PRODUCT_DEFINITION, OPERATOR_MODEL, LOOPTEACH,
ARCHITECTURE, LOOPBRIDGE, INTERACTION_MODEL, SECURITY_MODEL, ROADMAP, índice e ADRs
0001–0009, Session Authority V1 e relatórios M1.2, preflight M1.3 e M1.3A.
Foram revisados `authority.py`, `broker.py`, `adapter.py`, isolamento e testes do
M1.3A e os diagnósticos anteriores. O [preflight histórico](M1_3_FALLBACK_HUMAN_CONTROL.md),
seus JSONs e todos os fontes/testes/evidências M1.1/M1.2/M1.3A ficaram inalterados.

`git status --short --branch`, `git branch -avv`, `git log`, `git fetch origin` e
comparação de árvores confirmaram ausência de trabalho pendente. `origin/main`
continha o squash do PR #7; `main` foi atualizada somente por fast-forward para
`4d180f09415d554e6cf885658d654e143dbd6d50`. A árvore da antiga branch local M1.3A era
idêntica; só essa branch local concluída foi removida. Foi criada a única branch
ativa além de main: `codex/m1.3b-enforcement-feasibility`. Referências remotas e a
tag local de preservação anterior permaneceram intactas.

Método delimitado: revisar contratos; examinar fontes primárias das versões
relevantes; coletar inventário sem mutação; testar uma pendência semântica real;
comparar A/B/C/D; parar se não houvesse barreira suficiente. Não foram instalados
pacotes, criadas VMs/contas, alterados serviços/configurações persistentes ou
expostos listeners de rede. Fontes upstream foram baixados somente para cache em
`/tmp/loopenvironment-m13b-sources`; não são dependências instaladas nem cópias
redistribuídas no repositório. URLs e SHA-256 estão na evidência.

## Fronteira atual: o que existe e o que falta

O M1.3A autentica o principal por conexão e serializa grants, leases, referências e
despacho semântico. `session.lock` protege a última checagem e a chamada `doAction`;
`pending` permanece até confirmação/erro. O caminho não emite input convencional,
não participa do seat do Sway e não exporta endpoint de takeover. Os métodos
`*_simulated_takeover` continuam exclusivos do modelo de testes. Uma revogação
concorrente com `doAction` aguarda o lock da sessão; ela não interrompe essa chamada.
Veja [broker](../../experiments/m1_3a/broker.py) e [adapter](../../experiments/m1_3a/adapter.py).

**Input físico e virtual.** O Sway processa teclas no caminho do seat/foco e pode
encaminhá-las para input method ou cliente. Seu estado de teclas enviadas e o
estado usado em mudanças de foco precisam participar de um handoff; um booleano
externo no broker não o faz. Isto é leitura dos caminhos upstream 1.10.1, não uma
alegação de que seu binário possua a política LoopBridge.
[Teclado](https://github.com/swaywm/sway/blob/1.10.1/sway/input/keyboard.c),
[seat](https://github.com/swaywm/sway/blob/1.10.1/sway/input/seat.c).

Os handlers de teclado/ponteiro virtual criam dispositivos e os associam a um
seat. Não há nesses handlers autenticação de principal LoopBridge ou generation.
Os contratos de injeção oferecem eventos, seat e coordenadas; não trazem uma
transação com o alvo semântico/grant/epoch. Isso exige mediação adicional, mesmo
quando o injetor é confiável.
[Input manager](https://github.com/swaywm/sway/blob/1.10.1/sway/input/input-manager.c),
[teclado virtual](https://sources.debian.org/src/wlroots/0.18.2-3/protocol/virtual-keyboard-unstable-v1.xml/),
[ponteiro virtual](https://github.com/swaywm/wlr-protocols/blob/master/unstable/wlr-virtual-pointer-unstable-v1.xml).

**IPC e desabilitação de dispositivos.** `input ... events disabled` configura
send-events via libinput; o caminho de aplicação ignora dispositivos que não são
libinput. Logo, não é um gate único para hardware e dispositivos virtuais/nested.
O IPC trata comandos/respostas e não fornece um recibo conjunto para filas Wayland
e AT-SPI ou uma ligação ao principal autenticado do broker. Acesso ao socket
continua um privilégio da sessão que não deve chegar ao cliente não confiável.
[Implementação libinput](https://github.com/swaywm/sway/blob/1.10.1/sway/input/libinput.c),
[comando events](https://github.com/swaywm/sway/blob/1.10.1/sway/commands/input/events.c),
[servidor IPC](https://github.com/swaywm/sway/blob/1.10.1/sway/ipc-server.c).

**Ordenação não é uma barreira entre todos os canais.** `wl_display.sync` ordena
requisições/eventos na conexão Wayland correspondente; um roundtrip do injetor
não é confirmação de processamento pelo cliente gráfico em outra conexão e muito
menos pelo AT-SPI em outro transporte. A API Wayland também distingue enfileirar
e despachar eventos no cliente. Teclas mantidas, modifiers e repetição exigem
tratamento explícito; ler foco e depois enviar input conserva uma corrida.
[Protocolo Wayland](https://wayland.freedesktop.org/docs/html/apa.html),
[API cliente](https://wayland.pages.freedesktop.org/wayland.freedesktop.org/docs/html/apb.html).
A documentação atual inclui versões posteriores do teclado; a coleta local
registrou `wl_seat` v9, sem presumir recursos v10.

**Semântica.** O contrato público `do_action` retorna um booleano de invocação,
sem token de geração, cancelamento ou drain comum ao compositor. No GTK 4.18.6,
DoAction de botão chega a `gtk_widget_activate`; o botão pode finalizar a ativação
por timer. Assim, resposta e efeito final são distintos. Um efeito atrasado de uma
ação já entregue **não é, isoladamente, violação** da garantia solicitada, que não
promete desfazer o passado. Já um timeout deixa a entrega sem resolução verificável;
não pode ser transformado em cancelamento ou takeover confirmado.
[API AT-SPI](https://docs.gtk.org/atspi2/method.Action.do_action.html),
[Action GTK](https://github.com/GNOME/gtk/blob/4.18.6/gtk/a11y/gtkatspiaction.c),
[GtkButton](https://github.com/GNOME/gtk/blob/4.18.6/gtk/gtkbutton.c).

## Inventário real da VM

Debian 13 existente, kernel `6.12.117+deb13-amd64`, Python `3.13.5`, Sway
`1.10.1-2`, wlroots `0.18.2-3`, Wayland cliente `1.23.1-3`, GTK `4.18.6+ds-2`,
AT-SPI `2.56.2-1+deb13u2`, Calculator `1:48.1-2+b1`, Bubblewrap
`0.12.0-1~deb13u1`. libei/libeis runtime `1.3.901-1` estão instalados; isso não
significa que exista um servidor EIS na sessão.

`get_inputs`/`get_seats` foram somente consultados: sete dispositivos (quatro
teclados e três ponteiros), um seat com capabilities 3. Não foram registrados
nomes/identificadores de hardware, keymaps ou janela focada. A presença de um
teclado não autentica owner nem cria binding de principal.

O registry anunciou teclado virtual v1, ponteiro virtual v2, transient seat v1,
security context v1 e session lock v1. **Nenhum desses managers foi ativado**;
nenhum input, lock, captura ou conteúdo de clipboard foi enviado/obtido. Presença
de um global não demonstra autorização nem enforcement de lease.

A introspecção da sessão atual voltou a não apresentar RemoteDesktop/ScreenCast;
não havia proprietário dos serviços Mutter correspondentes. Não se chamou
ConnectToEIS nem se ativou outro desktop. Há `cc`, mas faltam `pkg-config`, Meson,
Ninja, wayland-scanner e os pacotes dev consultados de Wayland/wlroots/GTK.
Weston/Cage não estão instalados. Não se tentou build nem instalação. Essas são
restrições adicionais da prova B, **não prova de impossibilidade arquitetural**.

## Comparação de alternativas

A comparação é uma avaliação técnica baseada nas fontes e no inventário, não
quatro POCs executadas. Todas preservam a exigência de Linux normal, aberto e
independente do controlador; nenhuma permite inferir autoridade pela origem física.

| Alternativa | Input físico/convencional | Coordenação AT-SPI e eventos antigos | Principal/bypass | Viabilidade, manutenção e decisão |
| --- | --- | --- | --- | --- |
| **A. Cooperação com Sway sem patch**: IPC, configuração de seat/dispositivo e injetor confiável | Existem controles de dispositivo e seat, mas não a política LoopBridge no ponto comum de entrega. Desabilitar libinput não cobre todas as origens. | O broker pode impedir novas chamadas; IPC/roundtrip não cancela mensagens ou prova conclusão semântica. Sem recibo de drain/held-state conjunto. | Credenciais/grants continuam no broker; socket Wayland/IPC direto é bypass e deve ficar oculto. Não há binding físico autenticado novo. | Pequeno custo de código, mas **NO-GO para takeover nesta composição**. Instalar um injetor não corrige a lacuna. Aplicações normais continuam compatíveis, porém a garantia não surge dessas ferramentas. |
| **B. Patch mínimo no compositor/input** | Um gate dentro do compositor pode, em princípio, cobrir origens físicas e virtuais e regular foco/pressed-state. Precisa cobrir teclado, ponteiro, input methods e caminhos auxiliares, sem deixar bypass. | Deve fechar admissão, identificar a geração em filas, resolver held-state e obter recibos reais; o patch no Sway sozinho não resolve AT-SPI/D-Bus separado. Timeout semântico mantém blocked. | Endpoint confiável deve vincular principal/sessão/generation autenticados; nenhuma label ou UID isolado serve de autorização. | **Não qualificado; não foi implementado ou refutado.** Exige desenho verificável, build deps e testes que excedem uma flag/patch local no handler. Manutenção de patch sensível a novas rotas de input. Pode preservar apps Linux sem exigir fornecedor/agente específico. |
| **C. Compositor aninhado com roteamento confiável** | Um processo aninhado pode delimitar a sessão gráfica, mas o backend Wayland recebe eventos do parent e os converte em eventos de teclado. Não cria, por si, um gate de geração nem controle do hardware do parent. | Separar display não intercepta automaticamente AT-SPI; são necessários isolamento de barramento, vínculo de apps e recibos. Filas parent/nested e teclas transferidas ao entrar/sair precisam de prova. | Clientes continuam sem sockets parent/nested. Parent, configuração e roteador seriam parte da confiança; foco recebido não é principal autenticado. | **Sway nested sem alteração também é insuficiente.** Nested com patch é uma possível bancada futura de B, não uma solução pronta. Nenhum nested foi iniciado. Há custo adicional de foco, routing e sessão; compatibilidade geral não foi medida. |
| **D. Backend EIS/portal com cooperação real** | EIS dá ao servidor controle sobre aceitação/pausa dos dispositivos emulados; não autentica automaticamente input físico como principal LoopBridge. | O contrato de pausa neutraliza estado lógico, mas não é barreira universal de AT-SPI ou aplicação. A garantia conjunta ainda exigiria implementação/recibos. | O broker deve possuir a conexão e mediar grants; o cliente não recebe o FD EIS. Permissão de portal não substitui identidade/grant da instalação. | **Indisponível pelo portal nesta sessão; não qualificado em outro backend.** Usar outro compositor demandaria outra prova autorizada. É aberto e potencialmente compatível com Linux normal, sem selecionar produto ou fornecedor. |

Para C, o fonte wlroots 0.18.2 mostra `keyboard_handle_key` encaminhando eventos,
`enter` reconstruindo teclas pressionadas e `leave` produzindo releases. É um
ponto possível para instrumentação, não uma autorização de owner/lease.
[Fonte Debian wlroots](https://sources.debian.org/src/wlroots/0.18.2-3/backend/wayland/seat.c/).
Para D, foram examinados os contratos de
[pausa EIS](https://libinput.pages.freedesktop.org/libei/interfaces/ei_device/index.html)
e [RemoteDesktop](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html).
Eles são documentação de referência atual; não se presume que o runtime instalado
implemente todos os seus recursos, e nenhuma sessão EIS foi criada.

**Decisão:** não selecionar candidata de enforcement sem fundamentação para ambas
as fronteiras. B executada em bancada nested é uma hipótese específica de próximo
experimento, condicionada a desenho/build autorizados, não uma tecnologia adotada
nem uma prova de viabilidade concluída. Não há alteração de decisão aceita que
justifique novo ADR nesta avaliação negativa.

## Diagnóstico semântico real e comportamento fechado

O novo [diagnóstico](../../experiments/m1_3b/diagnose.py) não implementa controle.
Reutiliza o M1.3A sem modificá-lo. Dois peers **do harness confiável** autenticam
owner/delegate por socketpair Unix real com SO_PEERCRED e credenciais efêmeras.
Não são apresentados como clientes isolados; as sondas Bubblewrap são separadas.
Owner delega observe/control; o delegate adquire lease e obtém handle válido.

O adaptador prepara o alvo real normalmente. Imediatamente antes da chamada
`doAction`, o diagnóstico suspende **somente sua calculadora supervisionada** por
pidfd/SIGSTOP e confirma o estado de parada com `waitpid` limitado. Um watchdog
independente de seis segundos envia SIGCONT se necessário; cleanup também retoma
antes de encerrar o próprio child. Não se suspende broker, compositor ou processo
do usuário. O watchdog não disparou nas duas execuções efetivas.

Na execução final, PID da Calculator **102612**, a operação AT-SPI real retornou
`outcome_unknown` cerca de **1002 ms** após a parada. Um pedido administrativo de
revogação concorreu com a chamada; após a liberação do lock, a revogação terminou.
O broker ficou em **blocked**, geração **1 → 1**. Ele recusou:

- nova aquisição do owner: `control_busy`;
- reinício lógico: `handoff_not_confirmed`;
- pedido antigo do delegate após revogação: `grant_denied`;
- método de takeover inexistente: `method_not_found`.

Depois do timeout/revogação, o harness desconectou o peer antigo e retomou a
calculadora. Nova descoberta Sway/AT-SPI e consulta aos campos `text` encontraram
**`7`**, embora a chamada já tivesse falhado no broker. Não houve repetição da
mutação. A conexão de acessibilidade do broker é distinta da conexão do delegate;
fechar a segunda não recolhe a mensagem da primeira.

A observação comprova **efeito tardio real e ausência de cancelamento por timeout**
nesse caso. Não mede o instante em que D-Bus colocou bytes no socket, nem identifica
uma nova entrega Wayland ou efeito irreversível externo. Não é uma violação de
handoff: **nenhum handoff foi confirmado**. Tampouco prova impossibilidade universal
de barreiras cooperativas. Ela impede tratar timeout, desconexão ou revogação como
cancelamento e demonstra por que blocked é obrigatório enquanto a entrega for
incerta. SIGCONT do harness serve apenas para observar/limpar sua fixture; o
broker permaneceu blocked e não ganhou recuperação administrativa automática.

## Testes, isolamento e evidências

A [evidência sanitizada](evidence/M1_3B_FEASIBILITY_01_NO_GO.json) contém ambiente,
inventário, URLs/hashes das fontes upstream examinadas, hashes dos fontes locais,
IDs/resultados dos testes, diagnóstico negativo real e regressão isolada real.
Não contém credenciais, handles, leases, nomes de hardware, foco, socket paths,
conteúdo do clipboard, frames ou dados de outras aplicações.

Comandos efetivamente executados na raiz:

```sh
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 -m py_compile experiments/m1_3b/diagnose.py tests/test_m1_3b.py
/usr/bin/python3 -m experiments.m1_3b.diagnose --evidence /tmp/M1_3B_DIAGNOSTIC_02.json
/usr/bin/python3 -m experiments.m1_3a.run --evidence /tmp/M1_3B_AUTHORIZED_ISOLATION_01.json
```

**101 testes aprovados, zero falhas/erros/skips:** os 96 anteriores e cinco novos
para sanitização, falhas esperadas e parada/retomada de child real via pidfd/pipe.
A primeira bateria teve um erro no cleanup do teste novo: SIGCONT em child já
encerrado retornou ESRCH. O cleanup passou a tolerar somente `ProcessLookupError`;
a bateria final passou. Isso não alterou policy, broker, adapter ou testes antigos.
O primeiro diagnóstico também observou timeout/blocked e efeito tardio; o segundo
qualifica o fonte final com espera de parada explicitamente limitada e cleanup
robusto. Aviso transitório de cache AT-SPI inexistente ocorreu nas duas descobertas;
a correlação e as consultas independentes subsequentes funcionaram.

A regressão real `m1_3a.run` terminou **GO para seu escopo original**, com owner,
delegate, observer e unenrolled, antes/depois da autenticação: endpoints protegidos
inacessíveis, cinco namespaces privados, capabilities zero, NoNewPrivs, nenhum
socket herdado, dispositivo exposto ou descritor inesperado. O baseline conectou
Sway, Wayland, AT-SPI, D-Bus, X11, PipeWire e canário abstrato. Esses resultados
repetem autorização/isolation do M1.3A; não são GO de enforcement do M1.3B.
O diagnóstico novo também executou o probe independente anterior sem grant.
Não houve bypass observado nas sondas, nem habilitação de input convencional.

| Cenário adversarial | Evidência efetiva nesta entrega |
| --- | --- |
| Revogação durante preparação, aquisição/release concorrentes, duas ações no lease, expiração | Regressões unitárias M1.3A reexecutadas; adaptador gravador, sem nova prova no compositor |
| Operação já enviada, timeout, revogação concorrente, desconexão do cliente antigo | Diagnóstico AT-SPI/Calculator real descrito acima; blocked e efeito tardio observados |
| Credenciais/referências antigas, epoch/generation incorretos, spoofing | Suíte anterior; replay e revogação também na regressão isolada real |
| Tecla mantida, modifier/repeat, alteração de foco durante handoff | **Não executados**: nenhuma candidata de enforcement ultrapassou preflight; não houve injeção ou mudança de foco programática para simular essa prova |
| Fencing e barreira reais, falha/desconexão de endpoint do compositor | **Não implementados/demonstrados**; nenhuma confirmação de takeover |
| Nested/patch/EIS em execução | **Não executados**; comparação de código/contratos/inventário somente |

Os testes abstratos antigos continuam identificados como simulação; não foi
adicionado mock de barreira. Compilação Python, `git diff --check`, links internos,
campos sanitizados, hashes e preservação integral do histórico compõem a revisão
final. Fontes upstream são referências de versão, não atestado de identidade
binária com todos os patches Debian.

## Reprodução e condição de parada

Use os comandos acima com **novos nomes** de evidência, na mesma VM/Sway existente
e sem calculadora aberta. A fixture recusa adotar/encerrar uma calculadora anterior.
O arquivo é criado exclusivamente. A execução do diagnóstico retorna **0 quando a
coleta negativa termina**, imprimindo NO-GO; isso **não** significa takeover GO.
Retorno 1/PARTIAL indica coleta incompleta e exige verificar o campo `failure`.
Ausência da fixture não é compensada por mock. Não instalar pacotes ou mudar a
sessão para forçar a coleta a passar. O timeout interno de roundtrip/portal é
limitado por subprocesso; as ações reais usam os timeouts AT-SPI existentes.
O JSON versionado agrega os registros dos comandos e não altera os JSONs históricos.
O `base_commit` interno emitido pelo runner M1.3A continua apontando para a base
original desse laboratório; a base desta execução M1.3B é a registrada no nível
raiz da evidência (`4d180f0`).

A condição de parada foi satisfeita: **a fronteira real conjunta não está
fundamentada nesta composição**, portanto não se construiu endpoint de takeover,
nem se substituiu a barreira por flags ou simulação. Não se tentou compensar o
bloqueio com root, mudança de permissão, instalação ou outro desktop.

## Recomendação específica para a próxima etapa do M1.3B

Antes de autorizar um build, revisar um desenho curto de **patch experimental
mínimo executado como compositor aninhado**, isolado do seat físico principal:

1. Definir o ponto de entrega e os recibos observáveis, distinguindo fila do broker,
   fila do compositor, socket do cliente e handler/ação semântica. Flush/IPC reply
   não pode ser declarado automaticamente como recibo de processamento pelo app.
2. Especificar gate comum para todas as rotas relevantes, binding confiável dos
   dispositivos/seat ao principal e mensagens autenticadas com epoch/generation.
   Fechar a admissão antiga antes de resolver held keys/buttons, input methods e foco.
3. Para a única ação conhecida da Calculator, comprovar resolução semântica sem
   novo despacho antigo após confirmação. Se timeout/entrega for desconhecido,
   manter blocked e recusar confirmação, inclusive após desconexão.
4. Só então obter autorização para dependências de build e avaliar o menor patch;
   reproduzir teardown/held-key/foco/concorrência com traços no ponto real de entrega
   e consulta independente na aplicação. Não tocar o compositor global da VM.

Isso é uma proposta de experimento futuro, sem garantir que o patch será pequeno
ou suficiente. Se o desenho não fornecer recibos para **ambos** os canais,
rejeitá-lo antes do build e manter NO-GO para essa alternativa. A escolha definitiva
de compositor/stack ou mudança de decisão aceita exigiria ADR próprio. Nenhuma
etapa seguinte foi iniciada nesta entrega; o trabalho termina em um único PR sem merge.
