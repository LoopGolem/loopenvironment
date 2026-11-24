# LoopShell V0.8-C.1 — Visualização de sessões privadas

**Resultado GO no perfil local ensaiado.** O [PR #29](https://github.com/LoopGolem/loopenvironment/pull/29)
já estava incorporado à `main` em `c732a89`, com branch remota removida.
O desenvolvimento partiu de um worktree limpo.

| Dimensão | Classificação | Evidência |
| --- | --- | --- |
| Interface | GO | Uma janela GTK comum para cada visualização. Duas janelas e um Foot ocuparam a área útil do Sway, com o painel e o console ancorados. |
| Streaming | GO | O leitor e o renderizador V0.7 pintaram quadros 800×600 do desktop privado e acompanharam a mudança real após abrir a Calculadora. |
| Autorização | GO no contrato ensaiado | Descoberta sem `desktop.stream`, credencial de outro principal, epoch incorreto e terceira transmissão foram recusados. Revogar o grant limpou o visualizador afetado. |
| Ciclo de vida | GO | EOF, falta de heartbeat, revogação e fechamento limparam a imagem e os buffers no cliente. A sessão e a Calculadora continuaram após fechar a LoopShell. |
| Isolamento | PARTIAL | O cliente usou somente o socket de cliente do LoopBridge e o display local para desenhar. O ensaio usou um perfil descartável de mesmo UID, sem qualificar isolamento do host ou D5. |

## Fluxo e estados

1. Autentique o console como observador ou delegado. `sessions list` lista
   o que o principal pode descobrir.
2. `session observe <id>` lê o snapshot no console autenticado e seleciona
   o ID lógico, o epoch e o principal. O console pede a credencial de
   observação em um campo mascarado.
3. Uma conexão Unix dedicada verifica o UID e autentica o mesmo principal.
   `presentation.describe` valida o grant `desktop.stream` com alvo `*`,
   devolve o ID privado e é conferido contra a seleção. `presentation.open`
   revalida no broker e precisa devolver a mesma sessão, ID privado, epoch
   e principal, com formato V0.7 e `input=false`. A partir da resposta de
   abertura só o leitor de mídia interpreta bytes nessa conexão.
4. Em uma falha após a abertura, o cliente limpa a imagem antes de tentar
   `presentation.status` em outra conexão autenticada. O segredo fica em
   memória somente para essa tentativa enquanto a visualização está ativa.
   O campo, o histórico e a evidência excluem a credencial. Fechar a janela
   cancela a leitura, descarta os buffers e libera o socket.

A interface distingue conexão em andamento, espera pelo primeiro quadro,
transmissão ativa e imagem estática com heartbeat saudável. Após 2,5 s sem
pacote válido, limpa a imagem e indica transmissão congelada. A
visualização também distingue negativa, revogação ou expiração, identidade
ou epoch divergente, encerramento confirmado e desconexão. EOF enquanto o
status está inacessível aponta perda de conexão. A indicação de nova
autorização pede repetir `session observe <id>` e informar a credencial
novamente. A ação obtém um novo snapshot e cria outra transmissão explícita.

A sessão privada continua independente da interface. O visualizador não
oferece encaminhamento de entrada. Os limites de duas transmissões e a
revogação seguem responsabilidade do broker existente.
[Contrato V0.7](../LOOPBRIDGE_V0_7.md#experimental-rpc-contract)
· [ADR 0011](../DECISIONS/0011-session-presentation-and-operator-shell.md).

## Reprodução

No Debian do laboratório, use a [instância Sway descartável de A.1](LOOPSHELL_V0_8_A_LAYOUT.md#reprodução)
e o [desktop privado descartável de V0.6](../LOOPBRIDGE_V0_6.md#run-locally).
A prova usou Sway 1.10.1, wlroots 0.18.2, GTK 4.18.6, Pixman no compositor
e Cairo no cliente. Os mesmos dois pacotes layer-shell 1.0.4-2 de A.1
foram extraídos em diretório temporário. A LoopShell recebe as bibliotecas
e o typelib somente para o processo dela.

```sh
env LD_LIBRARY_PATH="$lib" GI_TYPELIB_PATH="$lib/girepository-1.0" \
  GDK_BACKEND=wayland GSK_RENDERER=cairo GIO_USE_VFS=local \
  /usr/bin/python3 -B -m loopshell --socket "$endpoint" --config "$lab/layout.json"
```

No cliente administrativo separado, com credencial de laboratório, conceda
ao observador `session.discover` em `desktop` no alvo `*`. Confirme que o
console lista `desktop`, mas a janela de `session observe desktop` fica
vazia e mostra negativa. Conceda `desktop.stream` para o mesmo principal
e alvo. Repita o comando com credencial explícita. Use o procedimento
[V0.7](../LOOPBRIDGE_V0_7.md#run-the-demonstration) para executar um aplicativo
real e observar uma mudança da imagem. Faça a revogação em outro cliente
autorizado e confira a remoção da imagem. Compare `private.status` no
manager antes de abrir e após fechar as janelas.

Para repetir a prova simultânea, conceda descoberta e transmissão a um
segundo principal de laboratório. Na LoopShell, desconecte o console e
autentique com o segundo principal. A primeira janela já autorizada
continua independente. Abra a segunda e confira as duas no Sway
descartável. Uma terceira abertura deve receber o limite do broker.

```sh
/usr/bin/python3 -B -m unittest discover -s tests -p test_visual_session_view.py -v
LOOPSHELL_TEST_GTK=1 GDK_BACKEND=wayland /usr/bin/python3 -B -m unittest discover -s tests
```

## Evidência

O driver acionou o fluxo GTK de seleção e credencial na LoopShell
ancorada, num output 1024×768 em escala 1. A área útil foi 764×588 em
(260, 0). O IPC do Sway descartável confirmou a divisão dessa área entre
Foot e dois visualizadores. A sessão privada estava em outro Sway
headless e seus quadros chegaram pelo transporte do LoopBridge.

A Calculadora foi aberta pelo controlador autorizado de laboratório,
em conexão separada. O visualizador pintou uma nova imagem após a
alteração. A leitura do console permaneceu funcional durante o
streaming. A geração da lease do controlador foi conferida enquanto
as janelas permaneceram abertas. O observador recebeu negativa para
`acquire` e para captura PNG e suas capacidades não incluíram entrada.

A falha de heartbeat foi induzida depois de um quadro real, suspendendo
a entrega ao visualizador. Uma segunda prova interrompeu a conexão
Unix após haver imagem pintada. Ambas verificaram limpeza da imagem.
A checagem de epoch incorreto usou o broker real com uma seleção
deliberadamente desatualizada. Após revogar apenas um grant, o outro
visualizador continuou saudável. O teste de fechamento encerrou a
LoopShell com uma imagem ativa e conferiu buffers vazios, workers
encerrados, instância privada `ready` e Calculadora ainda presente.

A suíte completa aprovou 328 testes com a regressão GTK ativada no
Sway descartável. A CLI original V0.7 também pintou um quadro do mesmo
desktop após o fechamento da LoopShell. Processo, versão, configuração,
saída e workspaces do Sway principal coincidiram antes e depois.

| Medida no ensaio | Observador | Delegado |
| --- | ---: | ---: |
| Quadros recebidos / pintados | 5 / 3 | 2 / 1 |
| Primeiro quadro pintado | 166,68 ms | 173,71 ms |
| Captura até recebimento, mediana | 60,67 ms (5 amostras) | 30,66 ms (2 amostras) |

Numa janela de 1,02 s com duas vistas estáticas, o processo da LoopShell
e do driver usou 9,22% de um CPU lógico e 111,0 MiB de RSS. A amostra
inclui a interface e as bibliotecas GTK. Os dados contêm medidas,
estados e resultados selecionados. [Evidência normalizada](evidence/LOOPSHELL_V0_8_C1_VISUAL_VIEWS.json).

## Limites de C.1 e avanço para C.2

O GO cobre visualização local, real e somente leitura. A amostra de
quadros, latência de captura até o recebimento, primeiro paint, CPU e
RSS descreve este ensaio. Ela não qualifica latência de tela a tela,
throughput sustentado com dois observadores ou uma matriz de cargas.
A V0.8-C.2 pode avançar sobre esse fluxo, com estados e testes próprios
para quaisquer novas vistas ou projeções de eventos. Activity e
Combined pertencem a essa qualificação posterior.

A [limitação GDK em 2→1](LOOPSHELL_V0_8_A_LAYOUT.md#fechamento-a2--escala-121)
continua com reinício como recuperação documentada. [D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5)
e [M1.3B](M1_3B_TRUSTED_INPUT_FEASIBILITY.md) preservam seus gates.
