# LoopShell V0.8-C.3 — Combined Session Views

**Resultado funcional GO no perfil local ensaiado.** O [PR #31](https://github.com/LoopGolem/loopenvironment/pull/31)
foi incorporado à `main` em `b8d76bb`, com a branch remota de C.2
removida. A C.3 partiu de um worktree limpo. O conteúdo qualificado no
commit `8f73e6f` já estava na `main`.

## Arquitetura e uso

`session combined <id>` abre uma janela GTK4 comum com vídeo
proporcional acima da atividade estruturada. A divisão é ajustável.
Em tamanhos compactos, a janela e o histórico permitem rolagem.
O console mantém `session observe <id>`, `session activity <id>`,
`sessions list`, `session status <id>`, `help`, `clear` e `exit`.
A escolha de modo acontece na abertura. Cada comando inicia somente
os recursos da vista pedida.

A Combined usa o mesmo widget de vídeo da vista Visual e o mesmo
widget de Activity da vista independente. A seleção fixa sessão,
principal e epoch. O console usa o snapshot quando autorizado.
Se o broker negar o snapshot, o console pode usar
`presentation.describe` com um grant de mídia existente. Nesse caso
também fixa o ID privado, e a conexão de mídia o revalida na abertura.

O operador digita uma credencial de observador ou delegado no campo
mascarado. Cada componente autentica o principal selecionado no seu
socket, com validação de UID. Vídeo exige `desktop.stream` no alvo `*`
e verifica sessão, ID privado, epoch e `input=false`. A Activity
consulta `snapshot` e `events` no mesmo socket RPC e exige
`session.discover` no DesktopBroker ou `desktop.observe` no Core.
Ela preserva a projeção, os cursores e os limites de C.2. O poll
tem intervalo de dois segundos e orçamento de 60 consultas.
A janela guarda até 64 eventos em memória.

O widget de vídeo possui o worker, o buffer de quadro mais recente,
o timer, o callback de desenho e a eventual consulta de diagnóstico.
O token de mídia em memória dura até o diagnóstico ou cancelamento.
O token de Activity é descartado após autenticação e snapshot. O
widget de Activity possui o worker, o socket RPC, as linhas e
o callback de atualização GTK. Fechar a janela cancela ambos com
interrupção de sockets e limpa os dados visíveis. Uma falha local
limpa apenas o componente afetado. Um erro validado de identidade
ou epoch, ou um `presentation.status` que confirma encerramento
para o mesmo stream, invalida a seleção inteira. EOF indica perda
de conexão com o estado da sessão desconhecido. Reabrir exige repetir
o comando e informar a credencial.
[Design V0.8](../design/LOOPSHELL_V0_8.md#v08-c3-combined-view) ·
[Contrato V0.7](../LOOPBRIDGE_V0_7.md#experimental-rpc-contract) ·
[Dados permitidos em C.2](LOOPSHELL_V0_8_C2_ACTIVITY_VIEWS.md#contrato-observado).

## Integração gráfica

O ensaio usou dois compositores Sway headless separados, um para a
LoopShell e Foot e outro gerenciado pelo LoopBridge para o desktop
privado. A Calculadora aberta pelo controlador autorizado alterou o
quadro real. A Activity exibiu `control.changed`,
`operation.confirmed` e `control.released` em sequência. O observador
recebeu negativas para adquirir controle e ler o workspace.

| Saída em escala 1 | Zonas painel / console | Área útil em (260, 0) | Janelas lado a lado |
| --- | --- | --- | --- |
| 1280×800 | 260 / 180 px | 1020×620 | Foot, Combined, Visual com 340 px cada |
| 1024×768 | 260 / 180 px | 764×588 | Foot, Combined, Visual com 255, 255 e 254 px |

O driver verificou os três retângulos pelo IPC do Sway descartável.
No GTK, ambas as regiões mantiveram área visível e o vídeo usou
`ContentFit.CONTAIN`. A revisão examinou rótulos, estados, rolagem e
limpeza ao fechar. Em largura estreita, o histórico ganhou barra
de rolagem visível e sequência compacta. O fechamento passou sem
críticos do GTK após substituir a rolagem automática animada por
um ajuste imediato. O ensaio técnico usou automação GTK; usabilidade
com participantes permanece por avaliar. Os prefixos de IDs privados
foram retirados da captura durante a coleta.
[Captura sanitizada](evidence/LOOPSHELL_V0_8_C3_COMBINED.png).

A matriz de falhas rodou com vídeo apenas, atividade apenas e com
ambos autorizados. Revogar um grant preservou o outro fluxo; revogar
os dois esvaziou os dois painéis. Interromper os sockets um de cada
vez confirmou que uma perda de transporte independe da outra.
Suspender o helper descartável de captura produziu falta de heartbeat.
Um burst de dez eventos ultrapassou os oito retidos e a Activity
sinalizou lacuna. Uma nova abertura começou no snapshot atual.
O broker real rejeitou um epoch antigo. A confirmação de encerramento
com `presentation.status` e a invalidação dos dois painéis com conteúdo
foram verificadas por fixtures determinísticas.

Dois principais puderam manter duas Combined simultâneas. Visual
e Combined também pintaram a alteração real do dígito 7.
Uma terceira abertura recebeu negativa
no vídeo pelo limite de streams e manteve Activity. Desconectar
o console e fechar uma vista não interrompeu as demais. Fechar a
LoopShell limpou buffers e callbacks, interrompeu os workers e liberou
os helpers, com a mesma sessão privada ainda `ready` e a Calculadora
presente.

## Reprodução

Use Debian 13.7 amd64 com Sway 1.10.1, wlroots 0.18.2, GTK 4.18.6,
Foot 1.21.0, Bubblewrap 0.12.0 e os binários de laboratório usados
por V0.7, incluindo Firefox ESR 153.7.0esr e a Calculadora do GNOME. Em um
`dbus-run-session -- bash`, use um caminho temporário curto, como
`/tmp/lsc3.XXXXXX`, e siga [a extração e a inicialização de A.1](LOOPSHELL_V0_8_A_LAYOUT.md#reprodução).
Use saída inicial 1280×800 em escala 1, Pixman e um único
`HEADLESS-1`. O runtime e o socket Sway devem ficar em um
subdiretório exclusivo de `$lab`. Os pacotes layer-shell 1.0.4-2
foram extraídos com os hashes de A.1.

Com `SWAYSOCK`, `WAYLAND_DISPLAY` e `XDG_RUNTIME_DIR` apontando
para o compositor descartável, rode da raiz do repositório:

```sh
export LD_LIBRARY_PATH="$lib" GI_TYPELIB_PATH="$lib/girepository-1.0"
export GDK_BACKEND=wayland GSK_RENDERER=cairo GTK_A11Y=none GIO_USE_VFS=local
G_DEBUG=fatal-criticals /usr/bin/python3 -B -m tools.loopshell_combined_lab \
  --root "$lab" --evidence "$lab/integration.json"
G_DEBUG=fatal-criticals /usr/bin/python3 -B -m tools.loopshell_combined_lab \
  --root "$lab" --performance --evidence "$lab/performance.json"
LOOPSHELL_TEST_GTK=1 /usr/bin/python3 -B -m unittest discover -s tests
```

O driver provisiona credenciais em memória, cria uma sessão privada
e uma janela Foot, e fecha os recursos criados ao terminar. Reinicie
apenas o Sway descartável em 1280×800 para repetir a prova de
integração, que muda a saída para 1024×768. A reprodução de desempenho
pode usar um Sway descartável recém-iniciado para evitar competição
com outras provas. O driver compara os recursos antes e depois e
exporta somente medidas, geometria e resultados selecionados.
[Driver de laboratório](../../tools/loopshell_combined_lab.py).

## Desempenho sustentado

A rodada reproduziu a cena estática da Calculadora e a página offline
`motion` do Firefox usada por V0.7. O ensaio de movimento produziu
eventos de autoridade por leases curtas de um controlador de
laboratório em outra conexão. O driver registrou as amostras no fim
de cada intervalo. A partida da Calculadora antes do Firefox tornou
a sequência de inicialização a mesma do ensaio V0.7.

| Cena | Intervalo | Consultas events / eventos por vista | Recebidos / únicos / sobrescritos / pintados | FPS pintado |
| --- | ---: | --- | --- | ---: |
| Estática, uma Combined | 60,01 s | 30 / 0 | 0 / 0 / 0 / 0 após primeiro quadro, heartbeat saudável | 0,00 |
| Movimento, uma Combined | 30,05 s | 15 / 12 | 385 / 385 / 230 / 155 | 5,16 |
| Movimento, duas Combined, observador | 30,55 s | 15 / 12 | 319 / 319 / 248 / 71 | 2,32 |
| Movimento, duas Combined, delegado | 30,55 s | 15 / 12 | 295 / 295 / 228 / 67 | 2,19 |

| Vista em movimento | Captura a recebimento, mediana / p95 | Firefox a paint, mediana / p95 | Firefox a feedback do Sway, mediana / p95 |
| --- | ---: | ---: | ---: |
| Uma Combined | 42,27 / 154,87 ms | 284,20 / 467,60 ms | 288,44 / 478,03 ms (154 amostras) |
| Duas Combined, observador | 65,35 / 181,99 ms | 324,54 / 570,83 ms | 455,10 / 680,99 ms (71 amostras) |
| Duas Combined, delegado | 72,84 / 189,06 ms | 363,55 / 504,52 ms | 380,46 / 532,40 ms (67 amostras) |

CPU é percentual de um CPU lógico. RSS inclui páginas compartilhadas.
O processo da Shell com driver usou 2,17% e terminou em 89,79 MiB
na cena estática, 48,49% e 100,61 MiB com um vídeo em movimento, e
49,13% e 114,98 MiB com dois. Nessas janelas, a variação de RSS foi
−0,05, +1,93 e +0,07 MiB. O Bridge usou 1,30%, 8,65% e 14,30%
e o Sway privado usou 0,02%, 6,36% e 7,14%. Cada processo de captura
ficou entre 3,37 e 3,41 MiB ao fim das amostras. O JSON detalha CPU,
RSS inicial e final e contadores por fluxo.

Os helpers de captura saíram em 447,44 ms após fechar as duas vistas.
Durante 8,01 s com o Firefox ainda aberto e sem observadores, a Shell
ficou em 1,25% e 102,41 MiB e o Bridge em 0,62%. Um terceiro leitor
foi recusado no ensaio de integração. Um leitor autorizado que parou
de consumir a mídia foi encerrado pelo broker como `slow_viewer`.
A amostra estima recursos do caminho de observação. A latência de
apresentação termina no feedback do Sway headless.

O ensaio histórico V0.7 registrou 56,26 FPS e p95 de 43,86 ms
até o feedback do compositor principal em 8,30 s. C.3 ficou aquém
do alvo de 28 FPS e 100 ms de p95 naquele protocolo de qualificação.
Tentamos a referência de 30 s no Sway descartável com o visualizador
V0.7 deste trabalho e com uma cópia de `main` anterior a C.3.
As duas tentativas pintaram o primeiro quadro. A primeira interrompeu
na mudança da Calculadora e a segunda na leitura dos marcadores de
movimento. As amostras comparáveis ficaram pendentes. A causa da
diferença de desempenho entre os ambientes ainda requer medição.
[Relatório V0.7](../LOOPBRIDGE_V0_7.md#benchmark-methodology).

A amostra de custo precedeu o ajuste final da guarda de rolagem ao
redimensionar o feed. A integração gráfica e a regressão completa foram
repetidas com esse ajuste. Os 349 testes passaram com GTK ativado.
O PID e a hora de início, a versão, o hash da configuração, as saídas
e os workspaces do Sway principal coincidiram. Os arquivos instalados
do Debian permaneceram sem os dois pacotes layer-shell experimentais.
[Evidência JSON](evidence/LOOPSHELL_V0_8_C3_COMBINED_VIEWS.json).

## Matriz de qualificação

| Dimensão | Resultado | Evidência |
| --- | --- | --- |
| Interface Combined | GO | Uma janela GTK4 com proporção preservada, histórico rolável e divisória ajustável. Tiling verificado em duas resoluções. |
| Streaming real | GO | Quadros 800×600 do desktop privado, mudança real da Calculadora, Firefox offline e heartbeat estático. |
| Atividade estruturada | GO | Eventos consecutivos, projeção C.2, cursor e indicação de lacuna em broker real. |
| Autorização independente | GO | Cada grant autorizado isoladamente. Credencial mascarada e verificação de identidade em dois sockets. Controle e leitura de workspace recusados ao observador. |
| Revogação e recuperação | GO no contrato ensaiado | Revogações separadas e simultâneas, EOF, freeze, lacuna, ressincronização e epoch antigo. O encerramento confirmado foi exercitado com resposta de status determinística. |
| Ciclo de vida | GO | Fechamento repetido, cancelamento em I/O, remoção de caches de mídia e eventos e encerramento da interface com sessão privada ativa. |
| Múltiplos observadores | GO no limite existente | Dois principais na Combined, Combined com Visual e negativa para terceira mídia. |
| Desempenho sustentado | PARTIAL | Ver amostras e limites da metodologia abaixo. |
| Isolamento do host | PARTIAL | Prova funcional em ambiente local de mesmo UID. A qualificação de isolamento continua em D5. |
| Usabilidade | PARTIAL | Revisão técnica e evidência gráfica em dois tamanhos. Avaliação com operadores permanece aberta. |

A recomendação é incorporar C.3 como incremento experimental da
V0.8-C após revisão do PR, preservando a qualificação parcial nos
itens pendentes. [D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5),
[M1.3B](M1_3B_TRUSTED_INPUT_FEASIBILITY.md) e a
[limitação GTK 2→1](LOOPSHELL_V0_8_A_LAYOUT.md#fechamento-a2--escala-121)
mantêm seus critérios próprios.
