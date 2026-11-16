# M1.1 — Semantic Feasibility no laboratório VirtualBox

**Resultado em 2026-11-16: GO para a prova semântica delimitada na saída virtual
VirtualBox existente.** Não qualifica output headless/sintético wlroots, isolamento,
autorização, eventos ou LoopBridge. O programa é um diagnóstico local confiável,
permitido pelo [ADR 0006](../DECISIONS/0006-mandatory-agent-mediation.md).
As escolhas abaixo são experimentais; nenhuma decisão permanente foi alterada.

## Ambiente e procedência

Execução diretamente na VM Debian, no terminal da sessão Sway existente. Nenhuma
VM adicional, SSH, serviço remoto, instalação de pacote ou alteração administrativa
foi realizada. O operador mantém o snapshot e o GNOME como recuperação.

Versões verificadas por `/etc/os-release`, `uname -r`, `dpkg-query -W`,
`sway --version`, `/usr/bin/python3 --version` e `VBoxClient --version`:

| Componente | Versão observada |
| --- | --- |
| Debian amd64 | 13 trixie, `DEBIAN_VERSION_FULL=13.7` |
| Kernel | `6.12.117+deb13-amd64` |
| Sway | `1.10.1-2` (binário 1.10.1) |
| GNOME Calculator | `1:48.1-2+b1` |
| Python | 3.13.5 |
| python3-pyatspi | `2.46.1-1` |
| at-spi2-core | `2.56.2-1+deb13u2` |
| libgtk-4-1 | `4.18.6+ds-2` |
| VBoxClient | `7.2.22r175245` |

`virtualbox-guest-x11` não foi encontrado pelo dpkg; isso não significa ausência
do VBoxClient, cujo binário respondeu. A versão do hipervisor hospedeiro não foi
verificada. Não houve acesso ao hospedeiro.

O operador relatou `EGL_NOT_INITIALIZED` com a GPU virtual. Não reproduzimos a
falha nem mudamos a configuração para provocá-la. A solução de laboratório é
Pixman. A entrada existente `/usr/share/wayland-sessions/sway-pixman.desktop`
foi lida e contém:

```ini
[Desktop Entry]
Name=Sway (Pixman)
Comment=Sway with software rendering for VirtualBox
Exec=env WLR_RENDERER=pixman /usr/bin/sway
TryExec=/usr/bin/sway
Type=Application
DesktopNames=sway;
```

No GDM, o operador seleciona **Sway (Pixman)**. O arquivo existente de configuração
do Sway contém:

```text
exec VBoxClient --clipboard --session-type wayland --foreground
```

Esse clipboard é uma conveniência do laboratório, não usado pela prova e não é
requisito do produto. Não se adicionou script de configuração VirtualBox à futura
distribuição. Não se mediram desempenho, custo do Pixman ou isolamento do clipboard.

`swaymsg -t get_outputs` respondeu com uma saída ativa `Virtual-1`, make/model
`Unknown`, modo atual 1642×670. Isso identifica a saída gráfica virtual disponível;
**não demonstra** backend headless, output sintético ou sessão sem monitor/viewer.
A proposta M0.5 de output sintético continua sem validação. A configuração adapta
a prova semântica ao laboratório disponibilizado, conforme o escopo desta tarefa.

## Reprodução

Dependências usadas: pacotes Debian `sway`, `gnome-calculator`, `python3`,
`python3-pyatspi`, `at-spi2-core` e suas dependências transitivas. Nenhuma dependência
faltou. Usar `/usr/bin/python3`, que encontra os módulos Debian; não requer pip.

Na sessão Sway de laboratório, fechar manualmente qualquer calculadora existente
antes de começar. O diagnóstico recusa adotar ou encerrar uma instância prévia.
Manter a sessão sem interação humana durante os poucos segundos da prova.

```sh
swaymsg -t get_outputs
/usr/bin/python3 -c 'import pyatspi; print(pyatspi.Registry.getDesktop(0).childCount)'
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 experiments/m1_1/semantic.py --evidence /tmp/M1_1_nova_execucao.json
```

O arquivo de evidências deve ser novo: criação exclusiva impede sobrescrita. O
programa retorna 0 apenas em GO; uma exceção resulta em PARTIAL e retorno 1. O
operador deve avaliar o critério que falhou, sem interpretar PARTIAL como GO.
Os comandos dependem das variáveis da sessão existente (`SWAYSOCK`, barramento
D-Bus e Wayland); não copiar endereços de outras sessões. Não registrar o ambiente
completo ou árvores de outras aplicações.

O sandbox bloqueou inicialmente Sway IPC. A consulta fora dele, com aprovação,
funcionou; o AT-SPI também respondeu fora do sandbox antes dos testes. As execuções
gráficas documentadas foram aprovadas fora do sandbox, com o mesmo usuário da
sessão, sem sudo. Uma restrição da ferramenta não implica falha do compositor.

## Procedimento e critérios

O [protótipo](../../experiments/m1_1/semantic.py) usa `swaymsg -r -t get_tree`
(interface Sway IPC) e pyatspi/libatspi. As interfaces usadas podem ser consultadas
em `man sway-ipc` e nos módulos Debian `pyatspi/action.py`, `text.py` e
`Accessibility.py`; documentação primária: [Sway IPC](https://manpages.debian.org/trixie/sway/sway-ipc.7.en.html)
e [AT-SPI Accessible](https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/class.Accessible.html).

1. Confirmar acesso às duas fontes; recusar calculadora já existente.
2. Iniciar `/usr/bin/gnome-calculator --mode=basic`, guardar o processo filho e
   pidfd, conferir executável e identidade `/proc` (PID, início e UID).
3. Exigir exatamente uma janela com o PID supervisionado, `app_id` esperado e
   `shell=xdg_shell`; exatamente uma aplicação AT-SPI com esse PID e um `frame`.
   Nome/título não bastam. Múltiplas janelas do mesmo processo são ambíguas.
4. Percorrer somente essa árvore (limites de 1500 nós e profundidade 40), exigir
   um botão `7` e exatamente uma ação `click`. Observar campos de papel `text`,
   excluindo rótulos dos botões. Exigir estado inicial vazio ou zero.
5. Antes da ação, conferir novamente processo vivo via pidfd, identidade de
   processo, janela, aplicação, frame, caminho e objeto do botão. Rejeitar
   DEFUNCT, ausência de SENSITIVE ou SHOWING e referência expirada (20 segundos).
6. Executar uma vez `queryAction().doAction(index)`. Não repetir mutações.
7. Consultar novamente as fontes e os textos; exigir o mesmo conjunto de campos
   e exatamente um campo antes vazio/zero passando a `7`. Retorno da ação sozinho
   não satisfaz o teste. Observação por **consulta posterior**, sem assinatura de eventos.
8. Invalidar a referência **antes** de encerrar o próprio processo. Aguardar saída
   e desaparecimento nas duas fontes; iniciar nova instância. Tentar despachar a
   referência anterior: deve retornar `expired_reference` antes de chamar qualquer
   adaptador. Confirmar que a nova instância continua com o texto inicial.
9. Repetir três vezes; após a terceira, encerrar somente o processo criado.

Consultas de prontidão têm prazo de 10 s, confirmação de 5 s e intervalo de 150 ms;
Sway tem timeout de 3 s e AT-SPI é configurado com timeouts de 1/2 s. Chamadas em
andamento podem estender o prazo de polling. Não há fallback por coordenadas,
teclado, screenshot ou clipboard. Não existe endpoint/API pública.

## Evidências e resultados reais

[Primeira tentativa](evidence/M1_1_RUN_01.json): PARTIAL, sem ação executada,
`element_unavailable`. A validação inicialmente exigia ENABLED. Uma única
investigação adicional delimitada, com seis consultas em cerca de três segundos,
mostrou FOCUSABLE, SENSITIVE, SHOWING e VISIBLE, sem ENABLED. O controle não foi
acionado nessa investigação. A validação foi corrigida para os estados exportados;
o resultado real e a ação disponível continuaram obrigatórios.

[Execução completa](evidence/M1_1_RUN_02.json): GO, três inicializações limpas.

| Iteração | PID Sway = PID AT-SPI | Container Sway | Estado antes → depois | Referência anterior |
| --- | --- | --- | --- | --- |
| 1 | 9330 | 10 | vazio → `7` | não se aplica |
| 2 | 9362 | 11 | vazio → `7` | rejeitada antes do adaptador |
| 3 | 9389 | 12 | vazio → `7` | rejeitada antes do adaptador |

O JSON inclui timestamps UTC, início de processo, executável, identidade Sway,
PID AT-SPI, unicidade de frame, caminho/role/nome do botão, ações e textos antes e
depois. Não inclui títulos de outras janelas, árvores completas, credenciais ou
dados pessoais. Nenhuma ação foi dirigida a outra janela na prova observada.

A inspeção exploratória anterior encontrou um objeto com enumeração inconsistente
de ações ao percorrer controles irrelevantes (erro AT-SPI `No action with index 0`).
A implementação consulta ações somente no botão selecionado e falha sem fallback
se essa consulta não funcionar. Avisos transitórios do cache AT-SPI (`GetItems`,
objeto ausente no cache) apareceram na primeira tentativa e investigação; não
foram tratados como confirmação de ação nem ocultados como sucesso.

[Testes automatizados](../../tests/test_m1_1.py): **15 testes passaram**, executados
com o comando acima. Cobrem correlação por PID, ausência e duplicidade de fontes,
identidade incorreta, janela flutuante, controle ausente/duplicado, ação ausente ou
ambígua, falha do retorno, referência invalidada/expirada, PID reutilizado, bloqueio
antes do adaptador, exclusão de rótulos da confirmação e retentativa limitada.
São testes simulados e complementam a execução real, sem substituí-la.
Também executados: `python3 -m py_compile experiments/m1_1/semantic.py`,
`git diff --check` e verificação local dos links Markdown relativos.

## Limites e próximo gate

A correlação é suficiente para esta fixture supervisionada, de um processo e uma
janela. Não resolve aplicações multiprocesso, múltiplas janelas, XWayland, AT-SPI
hostil, troca de sessão ou reconstrução arbitrária de árvore. O pidfd fixa a vida
do processo; os caminhos acessíveis não são identificadores permanentes. A
referência antiga é invalidada localmente e jamais resolvida para a substituta.
Há uma janela de corrida entre validação e chamada AT-SPI: não há transação atômica
entre compositor e aplicação. A prova não certifica segurança contra concorrência
ou aplicações maliciosas. Falhas de encerramento são reportadas, sem escalada ou
kill forçado. Interação humana concorrente pode invalidar a premissa da fixture.

**Recomendação para M1.2:** prosseguir, sob autorização separada, com o experimento
delimitado de autorização e eventos do [roteiro M0.5](../research/M0_5_RECOMMENDATIONS.md#proposed-m1-experiment-sequence).
Reutilizar somente o aprendizado semântico; definir isolamento verificável do
cliente e negação de acesso direto conforme ADR 0006, canal local privado,
identidade/grant restritos, referências expiradas e recuperação explícita de
lacunas de eventos. A demonstração atual não implementa essas garantias, nem
valida mediação física/remota do ADR 0007. Qualificar output sintético separadamente.
Não iniciar imagem, distribuição ou serviço de produção com base neste GO.
