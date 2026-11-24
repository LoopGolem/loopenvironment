# LoopShell V0.8-B.2 — Console autenticado em layout ancorado

**Resultado GO no perfil local ensaiado.** Em 2026-11-24, a prova integrou o
layout layer-shell da V0.8-A com o console de leitura da V0.8-B.1 em uma
instância Sway descartável. O broker e sua sessão privada rodaram em outro
Sway descartável. O ensaio usou Debian 13.7 amd64, GTK 4.18.6, Sway 1.10.1,
Pixman e o protocolo layer-shell v4.

O [PR #28](https://github.com/LoopGolem/loopenvironment/pull/28) já estava
incorporado à `main` em `1382757` e sua branch remota tinha sido removida.
O trabalho partiu de um worktree limpo. Os pacotes Debian
`libgtk4-layer-shell0` e `gir1.2-gtk4layershell-1.0` 1.0.4-2 foram
extraídos em diretório temporário. Seus SHA-256 coincidiram com os de A.1,
e as dependências de execução já estavam disponíveis. A instalação do
sistema dispensou alterações.
[Layout V0.8-A](LOOPSHELL_V0_8_A_LAYOUT.md) · [Console V0.8-B.1](LOOPSHELL_V0_8_B1_CONSOLE.md).

## Geometria e foco

Na saída 1024×768, o teste usou GDK para medir as superfícies mapeadas e
IPC do Sway para medir a área útil e as duas janelas Foot. As duas janelas
preencheram o retângulo útil em cada combinação. A troca de preferência
aconteceu com **Aplicar layout**, mantendo a LoopShell em execução.

| Painel / console | Zonas em px | Painel | Console | Área útil em px |
| --- | ---: | ---: | ---: | --- |
| Esquerda / inferior | 260 / 180 | 260×768 | 764×180 | 764×588 em (260, 0) |
| Esquerda / superior | 200 / 120 | 200×768 | 824×120 | 824×648 em (200, 120) |
| Direita / inferior | 410 / 240 | 410×768 | 614×240 | 614×528 em (0, 0) |
| Direita / superior | 480 / 400 | 480×768 | 544×400 | 544×368 em (0, 400) |

Antes da correção, o Sway reservava 120 px e o console media 134 px.
A barra vertical do histórico contribuía com 46 px para a altura mínima
do scroller, e o console ultrapassava a reserva em 14 px. Reduzir a altura
mínima do indicador de rolagem apenas no console preservou a rolagem e
permitiu ao GTK respeitar a zona de 120 px. A regressão GTK opt-in mede o
console conectado com histórico preenchido na largura mínima de 320 px.

O ensaio alternou o foco por clique de Foot A para o console e então para
Foot B, usando dispositivos virtuais confinados ao Sway descartável. O
teclado Wayland digitou os dois comandos no console de 120 px. A entrada
agora fica somente leitura durante I/O e recusa nova submissão enquanto
há uma operação pendente. A autenticação devolve o foco ao botão antes
de ocultar o campo de credencial. A reexecução passou sem os avisos
`GtkText` de perda de foco observados na primeira rodada.

## Autenticação, falhas e encerramento

| Prova no console ancorado | Resultado |
| --- | --- |
| Autenticação e descobrimento | A credencial inválida foi recusada. O observador autenticado recebeu negativa até obter `session.discover` no alvo `*`. Após o grant, `sessions list` retornou `desktop` e `session status desktop` retornou a fase `idle`. |
| Revogação e controle | Revogar o grant de descoberta bloqueou o status na conexão aberta. Uma chamada de teste separada com a mesma credencial recebeu `grant_denied` em `acquire`. |
| Tratamento de credenciais | O campo estava mascarado e foi limpo. A inspeção de histórico, erros, auditoria do broker e logs do processo que fechou durante a consulta confirmou ausência dos valores usados. A evidência guarda dimensões, estados, métodos e resultados reduzidos. |
| Desconectar | A sessão privada conservou sua identidade, processo e estado `ready`. |
| Timeout | Com a resposta de `discover` retida, o console exibiu timeout, reabilitou a edição e aceitou `help`. O foco continuou na janela Foot durante a conclusão. |
| Queda da conexão | O console mostrou desconexão, reabilitou a entrada e voltou a oferecer **Conectar**. A sessão privada continuou ativa. |
| Fechar com leitura em curso | O botão **Fechar LoopShell** encerrou o processo antes do timeout e liberou seu socket e ambas as zonas. A mesma instância privada permaneceu `ready` e seu snapshot continuou `idle`. |

Um relay temporário do ensaio encaminhou as chamadas ao broker real. Ele
reteve uma resposta de `discover`, fechou a conexão em outra execução e
confirmou que a consulta estava em curso antes do fechamento da interface
na terceira. O relay encaminhou somente uma autenticação e uma leitura por
caso. O processo que fechou durante a leitura entrou pela CLI normal da
LoopShell, com credencial de laboratório entregue por pipe anônimo ao
driver de teste. [Medições e resultados](evidence/LOOPSHELL_V0_8_B2_ANCHORED_CONSOLE.json).

## Eventos existentes para uma etapa posterior

O broker expõe a consulta `events` por `session`, `epoch` e `cursor`. O
cliente obtém o cursor e a época com `snapshot` na mesma conexão.
O DesktopBroker exige `session.discover` no alvo `*`. O Core exige
`desktop.observe`. Há um histórico limitado e a consulta retorna lacuna
ou exige nova captura quando perde o cursor válido. Uma reconexão também
requer novo snapshot.

No desktop descartável, o observador recebeu `snapshot_required` antes
do primeiro snapshot, recebeu `grant.changed` após um grant de leitura e
obteve `grant_denied` após revogação. Uma próxima interface pode projetar
somente campos tipados como tipo de evento, sequência e revisão, filtrar
valores no cliente e tratar epoch, lacuna e reconexão. Isso pode usar o
endpoint atual com autorização existente. A LoopShell B.2 continua com
`discover` e `snapshot` como suas operações de leitura.
[Despacho do broker](../../loopbridge/broker.py) · [Histórico](../../loopbridge/protocol.py).

## Reprodução e limites

Use o [Sway descartável e a extração de A.1](LOOPSHELL_V0_8_A_LAYOUT.md#reprodução)
e o [procedimento de sessão privada de B.1](LOOPSHELL_V0_8_B1_CONSOLE.md#reprodução).
Com o display Wayland de teste selecionado, inicie a LoopShell com os
caminhos de biblioteca e typelib de A.1 e o socket de cliente do broker privado.

```bash
env LD_LIBRARY_PATH="$lib" GI_TYPELIB_PATH="$lib/girepository-1.0" \
  GDK_BACKEND=wayland GSK_RENDERER=cairo GIO_USE_VFS=local \
  /usr/bin/python3 -B -m loopshell --socket "$endpoint" --config "$lab/layout.json"
```

Confira as duas janelas Foot com `swaymsg -r -t get_tree` e o retângulo
útil com `swaymsg -r -t get_workspaces` no Sway descartável. Aplique
**Esquerda + Topo**, largura 200 e altura 120. Use **Conectar** com a
credencial de laboratório do observador e execute as consultas. Em cliente
administrativo separado, confira o mesmo ID privado em `private.status`
após desconectar ou fechar.

No mesmo Sway descartável, a regressão de altura é ativada junto da suíte.

```sh
LOOPSHELL_TEST_GTK=1 GDK_BACKEND=wayland \
  /usr/bin/python3 -B -m unittest discover -s tests
```

A suíte com a regressão GTK ativada aprovou 318 testes. Processo, versão,
configuração, saída e workspaces do Sway principal coincidiram antes e depois.
O resultado gráfico é local e em escala 1. O [limite GDK na escala 2→1](LOOPSHELL_V0_8_A_LAYOUT.md#fechamento-a2--escala-121)
mantém o reinício como recuperação documentada. [D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5)
e [M1.3B](M1_3B_TRUSTED_INPUT_FEASIBILITY.md) permanecem trabalhos independentes.
