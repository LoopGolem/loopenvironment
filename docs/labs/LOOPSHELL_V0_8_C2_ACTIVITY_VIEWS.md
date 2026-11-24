# LoopShell V0.8-C.2 — Activity Session View

**GO no perfil local ensaiado.** O [PR #30](https://github.com/LoopGolem/loopenvironment/pull/30)
já estava na `main` em `abe87ca`, com a branch remota de C.1 removida.
A branch C.2 partiu de um worktree limpo.

| Dimensão | Classificação | Evidência |
| --- | --- | --- |
| Interface | GO | Painel e console ancorados com Activity, Foot e Visual em três janelas comuns dentro da mesma área útil. |
| Autorização | GO | Negativa sem grant e para credencial de outro principal. O observador não conseguiu adquirir controle nem ler o workspace. O grant de vídeo teve ciclo independente. |
| Consistência do histórico | GO | Dois eventos reais e consecutivos apareceram em ordem. O cliente iniciou no cursor do snapshot, projetou campos tipados e recusou respostas malformadas. |
| Recuperação | GO | Lacuna real, revogação, expiração e interrupção induzida do socket limparam as linhas. A nova sincronização exigiu novo comando e credencial. Epoch, cursor inválido, snapshot obrigatório e timeout foram exercitados deterministicamente. |
| Ciclo de vida | GO | Fechar a Activity ou a LoopShell liberou conexões, workers e linhas. O desktop privado permaneceu `ready`, com o mesmo processo e snapshot acessível. |
| Isolamento | PARTIAL | A Activity usou o socket de cliente do LoopBridge e o display local. O ensaio de mesmo UID verifica as negativas do broker e a independência de sessão. A qualificação de isolamento no host permanece em D5. |

## Contrato observado

`session activity <id>` seleciona a sessão no console autenticado e pede
novamente a credencial em um campo mascarado. Um socket dedicado verifica
o UID do serviço e autentica o mesmo observador ou delegado. O snapshot
nessa conexão valida a sessão, o epoch e o cursor inicial. A partir
desse cursor, `events` segue na mesma conexão. Console, Activity e
mídia binária da Visual têm sockets distintos.

No Core, `snapshot` e `events` exigem `desktop.observe`. No
DesktopBroker, ambos exigem `session.discover` para o alvo `*`.
O broker reavalia o grant a cada pedido. A Visual exige seu próprio
`desktop.stream`. A janela Activity apresenta sequência, tipo
reconhecido, fase e revisão. A origem de cada registro deve ser
`authority`. Estado arbitrário, conteúdo da sessão, identificadores de
grants e objetos de auditoria ficam fora da projeção.

| Limite | Core | DesktopBroker |
| --- | ---: | ---: |
| Ociosidade / idade máxima da conexão | 30 / 180 s | 60 / 300 s |
| Solicitações por conexão | 64 | 160 |
| Eventos retidos por sessão | 8 | 8 |

O cliente consulta de imediato e, depois, a cada dois segundos após
cada resposta. O orçamento é de 60 consultas, até 62 pedidos incluindo
autenticação e snapshot, e nenhum polling novo a partir de 170 s.
Cada leitura tem timeout de 3 s. O frame RPC tem limite de 8192 bytes.
A janela guarda até 64 linhas em memória e começa no cursor atual,
sem replay anterior ao snapshot. Uma consulta vazia atualiza o estado
visível para “sem novos eventos”. Isso descreve o feed durante o
intervalo observado.

Lacuna, cursor inválido, snapshot obrigatório, mudança de epoch, perda
de permissão ou interrupção encerram a consulta e limpam os registros.
A recuperação usa outro `session activity <id>` e uma credencial
explícita; o novo snapshot estabelece outro ponto de partida. O erro
`grant_denied` pode representar revogação, expiração ou sessão
indisponível. EOF deixa o estado da sessão desconhecido. A credencial
da Activity fica em memória até concluir a abertura inicial do feed
e é descartada antes das consultas `events`.
[ADR 0008](../DECISIONS/0008-operator-neutral-authority.md) ·
[ADR 0011](../DECISIONS/0011-session-presentation-and-operator-shell.md).

## Reprodução

Use o [Sway descartável de A.1](LOOPSHELL_V0_8_A_LAYOUT.md#reprodução)
com saída 1024×768 em escala 1, painel esquerdo de 260 px, console
inferior de 180 px e só um Foot. O ensaio usou Debian 13.7, Sway 1.10.1,
wlroots 0.18.2, GTK 4.18.6, Foot 1.21.0 e Bubblewrap 0.12.0.
Sway rodou com Pixman e GTK com Cairo. Os dois pacotes layer-shell
1.0.4-2 vieram do repositório Debian configurado e foram extraídos
em diretório temporário após verificação dos hashes de A.1 e das
dependências de execução.

Suba um [desktop privado descartável](../LOOPBRIDGE_V0_6.md#run-locally).
Use o socket da instância em `endpoint` e o layout JSON de A.1.
Dentro do Sway descartável, execute:

```sh
env LD_LIBRARY_PATH="$lib" GI_TYPELIB_PATH="$lib/girepository-1.0" \
  GDK_BACKEND=wayland GSK_RENDERER=cairo GIO_USE_VFS=local \
  /usr/bin/python3 -B -m loopshell --socket "$endpoint" --config "$lab/layout.json"
```

1. Autentique o console como observador de laboratório. Confira que
   `session activity desktop` recebe negativa antes de existir o grant.
2. Numa conexão de proprietário separada ao socket da instância, use
   `delegate` para conceder `session.discover` com alvo `*`. Repita o
   comando e preencha o campo mascarado com a credencial de observador.
   Em outra abertura, use a credencial de delegado para conferir a
   negativa por divergência do principal.
3. Com a Activity autorizada, use a conexão do proprietário para
   `acquire` e `release`, passando à liberação o ID da lease em
   `lease`, sua geração e seu epoch. Confira `control.changed` e
   `control.released` em sequência. Repita cinco ciclos entre duas
   consultas para ultrapassar a retenção. Na nova abertura, confira
   a indicação de consulta vazia até induzir outro evento.
4. Conceda separadamente `desktop.stream` para `*` e abra
   `session observe desktop` com a credencial de observador. No IPC
   do Sway descartável, confira a área útil e as três janelas com
   `swaymsg -t get_workspaces` e `swaymsg -t get_tree`.
5. Revogue o grant de descoberta com `revoke`. Confira o esvaziamento
   da Activity e a continuidade da Visual. Para repetir a expiração,
   conceda descoberta com TTL curto e aguarde a consulta seguinte.
   Restabeleça o grant para abrir outra Activity. Compare `private.status`
   antes de abrir, após fechar a Activity e após fechar a LoopShell.

```sh
/usr/bin/python3 -B -m unittest discover -s tests -p test_activity_view.py -v
LOOPSHELL_TEST_GTK=1 GDK_BACKEND=wayland /usr/bin/python3 -B -m unittest discover -s tests
```

## Medidas e limites

O IPC registrou uma área útil de 764×588 em (260, 0). Foot, Activity e
Visual ocuparam 255, 255 e 254 px de largura, sem sobreposição. A Visual
pintou um quadro do desktop privado. Em 6,20 s de Activity sem novos
eventos, o cliente enviou três consultas (0,484/s) e usou 3,77% de
um CPU lógico. O RSS foi de 77,59 a 77,60 MiB. O driver contou pedidos
no cliente, mediu tempo de CPU do processo e leu `VmRSS` em
`/proc/self/status`. A medição inclui GTK e o driver e foi feita
antes de abrir a Visual.
A suíte completa aprovou 338 testes, com regressões GTK ativadas.
O processo, a versão, o arquivo de configuração, as saídas e os
workspaces do Sway principal foram comparados antes e depois.
[Evidência normalizada](evidence/LOOPSHELL_V0_8_C2_ACTIVITY_VIEWS.json).

O avanço para C.3 depende de validar que vídeo e atividade mantêm
autorizações, atualidade e falhas independentes dentro da janela
Combined. Sessões mais longas, vários observadores e custo sustentado
ainda pedem ensaio. A [limitação GTK 2→1](LOOPSHELL_V0_8_A_LAYOUT.md#fechamento-a2--escala-121),
[D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5)
e [M1.3B](M1_3B_TRUSTED_INPUT_FEASIBILITY.md) seguem independentes.
