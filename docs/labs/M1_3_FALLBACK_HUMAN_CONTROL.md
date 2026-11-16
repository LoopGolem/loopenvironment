# M1.3 — Fallback and Human Control

**Resultado: NO-GO para prosseguir com esta abordagem na sessão Sway existente.**
A avaliação foi encerrada no preflight: não foi qualificado um caminho de entrada
vinculado ao alvo com preempção segura na fronteira do compositor. A alternativa
limitada de portal RemoteDesktop/EIS na mesma sessão também não está disponível.
Isso não prova impossibilidade em toda configuração Sway, nem registra um bypass
observado. Significa que não há evidência suficiente para habilitar controle com
as garantias obrigatórias deste experimento. Não é GO parcial.

O [inventário real](evidence/M1_3_PREFLIGHT_01.json) registra PARTIAL porque cobre
somente o preflight. A [avaliação do gate](evidence/M1_3_ASSESSMENT.json) registra
NO-GO e o estado de cada um dos 17 passos exigidos. Não houve implementação de
broker M1.3, nova API, observador, captura, entrada convencional ou takeover.

## Nota posterior de preservação e autoridade

Este relatório descreve o experimento histórico anterior ao esclarecimento de
identidade e autoridade da [ADR 0008](../DECISIONS/0008-operator-neutral-authority.md)
e ao contrato proposto [Session Authority V1](../design/SESSION_AUTHORITY_V1.md),
incorporado à main pelo PR #5. No entendimento atual, takeover exige autoridade
explícita de um principal autenticado owner/delegate; natureza humana/artificial
ou origem física da entrada não concedem privilégios. A terminologia histórica
abaixo foi preservada, sem reinterpretar observações como prova desse contrato.

Esta publicação encerra e preserva o preflight anterior. O código e os dois JSONs
históricos permanecem inalterados; o NO-GO continua restrito à abordagem
investigada, sem declarar inviabilidade do LoopEnvironment. Captura, observador,
takeover e medições de 30 segundos não foram executados. Nenhum experimento
M1.3A/B/C ou LoopTeach foi iniciado nesta publicação.

## Preparação e ambiente

Foram lidos AGENTS, README, ROADMAP, ARCHITECTURE, LOOPBRIDGE, INTERACTION_MODEL,
SECURITY_MODEL, PRODUCT_DEFINITION, recomendações M0.5, ADRs 0004/0006/0007 e os
relatórios M1.1/M1.2; o protótipo e testes existentes foram inspecionados.

`git fetch origin` encontrou o squash M1.2 em
`6237b54cf10c70a72dca09d7dc3563d6fa28a79e`. A árvore da branch local M1.2 foi
comparada com origin/main e, novamente, com main após fast-forward: ambas as
comparações foram idênticas, sem alterações exclusivas ou arquivos locais a
preservar. Só então a branch antiga foi removida localmente. Sua referência remota
foi preservada. O novo trabalho usa `codex/m1.3-fallback-human-control`, a única
branch temporária local. Não houve merge de implementação, commit ou publicação.

O Codex é a ferramenta confiável do laboratório; não é o cliente sob teste.
O preflight ocorreu diretamente na VM Debian 13/Sway Pixman, sem SSH ou nova VM.
A configuração de renderização e saída VirtualBox segue o
[relatório M1.1](M1_1_VIRTUALBOX.md); não se demonstrou output headless.

Versões consultadas por dpkg e comandos locais:

| Componente | Versão |
| --- | --- |
| Kernel / Python | 6.12.117+deb13-amd64 / 3.13.5 |
| Sway / wlroots | 1.10.1-2 / 0.18.2-3 |
| Foot | 1.21.0-2 |
| libwayland-client | 1.23.1-3 |
| Bubblewrap | 0.12.0-1~deb13u1 |
| python3-pyatspi / python3-gi | 2.46.1-1 / 3.50.0-4+b1 |
| xdg-desktop-portal | 1.20.3+ds-1 |
| Portal GNOME / GTK | 48.0-2 / 1.15.3-1 |
| VBoxClient | 7.2.22r175245 |

`wayland-info`, `grim`, `wayvnc`, `wtype`, `wl-copy` e `wl-paste` não foram
localizados no PATH. `xdg-desktop-portal-wlr` não consta como instalado. Não se
instalou nada. Pacotes correspondentes para eventual avaliação autorizada seriam
`wayland-utils`, `grim`, `wayvnc`, `wtype` e `wl-clipboard`. Instalar essas ferramentas
não resolve, por si só, o bloqueio de política de entrada.

## A — Captura

A enumeração real do registry Wayland encontrou:

- `zwlr_screencopy_manager_v1` versão 3.
- `zwlr_export_dmabuf_manager_v1` versão 1.
- `wl_shm` versão 2 e `wl_output` versão 4.

O [diagnóstico](../../experiments/m1_3/preflight.py) usa libwayland-client por ctypes
apenas para obter o registry e fazer roundtrip, sem bind dos managers de captura,
entrada ou clipboard. O worker tem timeout externo de 8 s. Não foi necessário
instalar uma ferramenta para enumerar interfaces.

Screencopy é candidato a captura pontual realizada pelo broker, sem conceder o
socket Wayland ao cliente isolado. O protocolo expõe output inteiro ou região de
output; uma região não identifica uma janela nem impede sobreposição por conteúdo
alheio. A presença do global não comprova autorização, sucesso de captura ou
privacidade do alvo. Referência primária:
[XML screencopy](https://github.com/swaywm/wlr-protocols/blob/master/unstable/wlr-screencopy-unstable-v1.xml).

Seria necessário qualificar uma fonte explicitamente autorizada, sua revisão e
ciclo de vida antes de distribuir pixels. Nenhum frame foi solicitado ou salvo.
Não existe encoder M1.3 em execução. As janelas de 30 s antes/depois do observador
**não foram medidas**: assinaturas e frames codificados são `null` na avaliação,
sem contadores fictícios ou alegação de custo zero. A sessão continuou funcionando;
isso não é medição de renderização, captura ou codificação.

## B — Entrada e componente de aplicação da política

Foram anunciados `zwp_virtual_keyboard_manager_v1` v1 e
`zwlr_virtual_pointer_manager_v1` v2. A enumeração não precisou de root; criação de
dispositivos virtuais e envio de eventos **não foram tentados**, portanto não se
confirma neste teste a permissão efetiva de injeção.

O teclado virtual é associado a um seat; o ponteiro usa coordenadas globais e
pode sugerir seat/output. Esses contratos não transportam uma referência de
janela, revisão esperada, identidade/grant do broker ou epoch de controle. Não foi
identificada neles uma operação que confirme cancelamento de comandos já enviados
antes de trocar o foco. Destruir um objeto não equivale a retirar eventos já
processados. Fontes primárias:
[teclado virtual v1](https://github.com/swaywm/wlroots/blob/master/protocol/virtual-keyboard-unstable-v1.xml)
e [ponteiro virtual v2](https://github.com/swaywm/wlr-protocols/blob/master/unstable/wlr-virtual-pointer-unstable-v1.xml).

A revisão do [caminho de teclado Sway 1.10.1](https://github.com/swaywm/sway/blob/1.10.1/sway/input/keyboard.c)
mostra despacho pelo seat/foco do compositor. A manpage instalada `sway-input(5)`
documenta configuração de dispositivos, seats, cursor, inibição de atalhos e
`input ... events`. Esses controles não constituem, isoladamente, uma integração
qualificada com leases do broker. Não se alterou nenhum deles. Registry também
anuncia transient seat, session lock e security context; presença desses nomes
não prova arbitragem de ownership ou cancelamento. Nenhum foi ativado como atalho
para assumir controle da sessão.

A distinção obrigatória permanece:

| Propriedade | Quem teria de aplicar | Estado M1.3 |
| --- | --- | --- |
| Revogação na API | Broker e grants/epoch | Não implementada |
| Descarte de comandos ainda na fila do broker | Executor serializado e caminho independente de revogação | Não demonstrado |
| Alvo/foco, eventos em trânsito, teclas pressionadas e barreira de handoff | Integração do compositor/input com o broker | Não qualificado |
| Política sobre teclado/mouse físicos | Compositor/input confiável | ADR 0007 não demonstrada |

Consultar foco e depois enviar input deixa uma corrida. Cancelar uma fila Python
pode impedir comandos ainda não despachados, mas isso não demonstraria sozinho a
barreira de input exigida. Não foi criada uma simulação de takeover com flags.
O NO-GO é da abordagem ainda não qualificada, não uma alegação de que todo uso de
input virtual é inseguro ou de que um bypass foi observado.

## C — Takeover e única investigação alternativa

Um caminho humano candidato seria um processo local confiável separado do cliente
isolado, com endpoint independente e capacidade de revogar o lease. O isolamento
M1.2 pode ocultar esse endpoint do agente, mas o mecanismo não foi implementado
nem autenticado neste marco. Acionamento físico real e ação humana posterior
**não ocorreram**. O broker M1.2 não contém integração de política de entrada
física com o Sway. Não se declara mediação integral da ADR 0007.

A única alternativa delimitada investigada foi RemoteDesktop/EIS via portal e
disponibilidade dos serviços Mutter **na sessão atual**. A introspecção D-Bus real
mostrou ausência de `org.freedesktop.portal.RemoteDesktop` e
`org.freedesktop.portal.ScreenCast`. `ListNames` mostrou que
`org.gnome.Mutter.RemoteDesktop` e `org.gnome.Mutter.ScreenCast` não têm proprietário.
Logo, não havia nesse caminho uma sessão RemoteDesktop à qual conectar EIS.
Não se chamou ConnectToEIS, não se ativou GNOME Remote Desktop nem se criou outro
desktop ou serviço de rede. Ter pacotes do portal GNOME instalados não demonstra
que essas interfaces estejam disponíveis na sessão Sway.

Essa consulta é um diagnóstico de disponibilidade; não é uma comparação prática
com outra sessão GNOME/Mutter. Iniciar essa sessão e qualificar sua preempção
exigiria um experimento posterior aprovado. Não se multiplicaram alternativas.

## D — Lacuna semântica real

Foi aberto o Foot instalado, sem modificar a aplicação, com app_id de fixture e
um processo Python que imprime somente texto de teste fixo. Não se injetou tecla,
não se removeu árvore acessível nem se desligou AT-SPI para fabricar a lacuna.
A janela Sway real foi identificada por PID **16658**, container **23**,
`app_id=org.loopenvironment.M13Gap`, executável `/usr/bin/foot`.

Em oito consultas, durante **5469 ms**, nenhuma aplicação AT-SPI tinha o PID dessa
janela. Em todas as mesmas amostras, a calculadora de controle positivo (PID 16617)
foi encontrada uma vez e seus campos de texto responderam a nova leitura. Nenhuma
ação semântica foi executada nela. Os dois processos gráficos criados foram
encerrados; não se adotaram janelas prévias do operador.

A lacuna observada é ausência de aplicação/árvore AT-SPI atribuível ao PID do Foot
no intervalo amostrado: o diagnóstico não dispõe de texto/células/ações do terminal
por essa árvore. Não se prova ausência de qualquer outra interface do Foot, nem
cobertura universal de versões. Aviso transitório do cache AT-SPI foi observado;
o controle positivo continuou respondendo e os dados de amostragem foram salvos.

## E — Clipboard e isolamento

O registry anuncia `wl_data_device_manager` v3, seleção primária v1 e
`zwlr_data_control_manager_v1` v2. A configuração conhecida de autostart
`exec VBoxClient --clipboard --session-type wayland --foreground` foi confirmada,
assim como um processo VBoxClient com esses flags. Essa integração já existia;
não foi iniciada, encerrada ou alterada. Nenhum conteúdo de clipboard, inclusive
do hospedeiro, foi lido ou escrito.

O preflight reutilizou exatamente a montagem/namespaces do M1.2, substituindo
somente o payload por seu probe independente. Wayland, X11, Sway IPC, AT-SPI,
D-Bus da sessão, barramento de sistema e PipeWire aceitaram conexão no baseline
confiável e falharam com ENOENT no cliente isolado, inclusive via `/proc/1/root`.
Havia cinco namespaces distintos, CapEff zero, NoNewPrivs=1, userns aninhado negado,
zero sockets herdados e zero descritores inesperados. Um socket Sway real foi
marcado herdável no pai para testar a exclusão por `close_fds=True`.

Isso verifica bloqueio dos caminhos de transporte relevantes ao clipboard; não
é teste de transferência de conteúdo. O cliente deste preflight não autenticou um
grant: o M1.2 já contém evidências históricas com grant válido, mas essa parte não
foi repetida aqui. Nenhum bypass foi observado nessas sondas. Não foi implementada
uma API de clipboard, nem testada negação de grants de captura/input do M1.3.

## Procedimento e verificações executadas

Na raiz do repositório, na sessão existente, sem calculadora prévia:

```sh
/usr/bin/python3 -m experiments.m1_3.preflight --evidence /tmp/M1_3_nova_execucao.json
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 -m py_compile experiments/m1_3/preflight.py
```

O arquivo de evidências deve ser novo. O comando de preflight retorna 0 quando
conclui **o inventário**, mesmo mantendo resultado PARTIAL; retorno 0 não significa
GO do M1.3. Falha de coleta retorna 1 e o tipo do erro, sem argumentos sensíveis.
O worker de registry é limitado a 8 s, portal a 2 s por chamada, probe isolado a
8 s, prontidão da janela Foot a 5 s e amostragem a oito consultas. O script depende
das mesmas permissões de sessão e bibliotecas já disponíveis; não usa sudo.

Também executados: `git diff --check`, verificação de links relativos/âncoras e
revisão das evidências. **31 testes anteriores passaram**, sem alteração do código
M1.1/M1.2 ou seus testes. Essas regressões não comprovam os cenários M1.3 não
implementados. A evidência nova é o preflight real, não testes de flags de leases.

## Arquitetura proposta, dependências e pendências

Se o bloqueio for resolvido em trabalho aprovado, a arquitetura mínima permanece:
cliente Bubblewrap → broker local → adaptadores confiáveis de captura/input;
observador com grant somente de leitura e caminho humano local independente.
Captura, observação, entrada convencional, controle temporário e revogação precisam
de capacidades separadas, limitadas à identidade, sessão, alvo e revisão. O
observador não deve receber sockets de input ou clipboard. Esse desenho não foi
implementado; o inventário não anuncia essas capacidades como disponíveis.

Antes de nova tentativa, é preciso demonstrar um backend com alvo/seat qualificado,
barreira verificável de preempção, liberação de estado pressionado e ordem entre
cancelamento e troca de foco. Fonte de pixels autorizada e seus contadores reais
também precisam de qualificação. Não basta instalar grim/wtype ou alterar permissões.
Nenhuma mudança administrativa foi necessária para o que foi executado; nenhuma
instalação ou reconfiguração foi solicitada como solução especulativa.

**M1.4 permanece bloqueado para o cenário completo enquanto M1.3 não passar.**
Recomenda-se ao mantenedor revisar a fronteira de input e aprovar separadamente
uma comparação de backend/sessão com o mesmo caso de preempção. Não se selecionou
outro compositor ou stack, nem se mudou um ADR. M2 não deve começar com base neste
resultado. Não se iniciou M1.4, M2, imagem, controle remoto ou streaming.
