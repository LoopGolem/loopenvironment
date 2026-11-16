# M1.2 — Authorization and Events

**Resultado em 2026-11-16: GO para a fixture local delimitada.** Um cliente
explicitamente provisionado, isolado pelo Bubblewrap, operou a calculadora pelo
socket local; o cliente sem credencial foi negado. As sondas reais de bypass
falharam também com grant válido. Expiração, desconexão, lacuna de histórico e
recuperação por snapshot foram demonstradas. Isto é um protótipo experimental,
sem API estável ou LoopBridge completo, e não certifica segurança de produção.

## Revisão prévia e ambiente

Antes da implementação foram lidos AGENTS, README, VISION, ARCHITECTURE, ROADMAP,
SECURITY_MODEL, LOOPBRIDGE, PRODUCT_DEFINITION, o índice de ADRs, ADRs 0006/0007,
as recomendações M0.5 e o [relatório M1.1](M1_1_VIRTUALBOX.md). A arquitetura,
isolamento, dependências, testes e condições de falha foram apresentados ao
operador antes da implementação. Nenhuma operação administrativa foi necessária.

`git fetch origin` confirmou `main` limpa e atualizada em `e67ffae`, merge do M1.1.
A árvore da antiga branch M1.1 foi comparada com main e era idêntica; a branch
local concluída foi removida antes de criar `codex/m1.2-authorization-events`.
A referência remota histórica M1.1 foi preservada. Nenhum merge foi realizado.

A execução ocorreu na própria VM Debian 13, sessão Sway/Pixman, saída VirtualBox
existente. Codex é ferramenta confiável de desenvolvimento; **o isolamento sob
teste é explicitamente criado pelo lançador Bubblewrap**, sem depender do sandbox
da ferramenta. Não foram criados usuários, alterados sysctls/permissões globais,
instalados pacotes ou modificadas as configurações do Sway/GDM/VirtualBox.

Versões novamente verificadas: kernel `6.12.117+deb13-amd64`, Python `3.13.5`,
Bubblewrap `0.12.0-1~deb13u1`, Sway `1.10.1-2`, GNOME Calculator `1:48.1-2+b1`,
python3-pyatspi `2.46.1-1`, at-spi2-core `2.56.2-1+deb13u2`, GTK `4.18.6+ds-2`.
Os sysctls consultados permitiam user namespaces (`unprivileged_userns_clone=1`,
`max_user_namespaces=15394`). Não foram alterados. A solução Pixman e as limitações
do output VirtualBox continuam as registradas no M1.1; headless não foi testado.

## Arquitetura mínima e reutilização

O [runner confiável](../../experiments/m1_2/run.py) confirma os endpoints reais,
inicia somente sua calculadora, mantém o [broker](../../experiments/m1_2/broker.py)
na sessão e lança dois clientes isolados, um sem credencial e outro provisionado.
Ao final encerra seu processo da calculadora e remove apenas o diretório temporário
que criou. Uma calculadora prévia provoca recusa, sem adoção ou encerramento.

Reutiliza do M1.1 as funções de descoberta Sway/AT-SPI, correlação por PID único,
identidade de processo, referência semântica, validação e ação `click` no botão
`7`. O código M1.1 permaneceu inalterado. Para evitar travessias amplas repetidas,
a leitura resolve novamente os caminhos dos campos `text` conhecidos e chama
`getText` no estado real; não usa rótulos de botões para confirmar o resultado.
A referência do botão continua sendo validada independentemente antes da ação.

O broker aceita apenas autenticação, snapshot/assinatura, ação fixa `invoke7` e
consulta de eventos. Nenhum argumento permite escolher executável, PID, caminho
D-Bus, comando Sway, ação arbitrária ou socket da sessão. Há uma única fixture,
um broker e um cliente atendido por vez; a operação não depende de foco ou input
sintético. Não há listener TCP, captura, streaming visual ou controle humano.

### Isolamento escolhido e alternativa

O [perfil Bubblewrap](../../experiments/m1_2/isolation.py) foi testado sem root:

- Novos namespaces de usuário, montagem, PID, rede e IPC; `/proc` privado.
- `/usr` e `/app` somente leitura, `/tmp` privado e `/dev` mínimo do Bubblewrap.
  Não expõe home, `/sys`, `/run` da sessão, X11 ou dispositivos físicos.
- Compartilha somente o diretório novo do socket experimental, somente leitura.
  No lado confiável: diretório 0700 e socket 0600. Não modifica sockets existentes.
- Ambiente limpo, nova sessão de terminal, capabilities removidas, NoNewPrivs=1
  e criação adicional de user namespaces desabilitada. A combinação testada exige
  `--unshare-user` explícito junto a `--unshare-all` para `--disable-userns`.
- `close_fds=True`, stdin de provisionamento e stdout/stderr em pipes privados.
  Nenhum descritor da sessão é intencionalmente herdado pelo cliente.

Um usuário Linux separado daria uma fronteira DAC adicional, mas exigiria criação
administrativa de conta e uma política de acesso ao endpoint. **Não foi criado nem
testado.** Permissões de socket sozinhas não distinguem processos do mesmo UID.
Namespaces permitem o experimento atual sem essa mudança administrativa.
A política de montagem e os descritores são parte essencial da fronteira, conforme
[a documentação primária do Bubblewrap](https://github.com/containers/bubblewrap/blob/main/README.md).
Não foi aplicado perfil seccomp próprio ou limite de recursos por cgroup.

### Protocolo e autorização experimentais

| Opção | Vantagem | Custo/limite neste laboratório |
| --- | --- | --- |
| gRPC/Protobuf | Contrato gerado, tipos e streaming | Módulos Python `grpc` e `google.protobuf` ausentes; precisaria qualificar credenciais do peer no runtime escolhido e adicionar dependências |
| JSON-RPC local | Biblioteca padrão permite obter `SO_PEERCRED` diretamente e testar o gate com poucas dependências | Schema, framing, limites, eventos e recuperação precisam ser definidos explicitamente |

Foi usada a alternativa JSON-RPC do [estudo M0.5](../research/M0_5_RECOMMENDATIONS.md),
sem selecionar protocolo definitivo. gRPC não foi instalado nem medido. Pacotes
opcionais para uma avaliação futura: `python3-grpcio`, `python3-protobuf` e, se
houver geração local, `protobuf-compiler`. gRPC oferece credenciais locais, mas
isso não estabelece sozinho as identidades e grants do produto; consultar a
[documentação Python primária](https://grpc.github.io/grpc/python/_modules/grpc.html).

O [framing](../../experiments/m1_2/protocol.py) usa JSON UTF-8 terminado por newline,
limite de 8192 bytes, envelopes JSON-RPC 2.0 com ID inteiro e parâmetros objeto.
Não aceita notificações ou batches. Método desconhecido não chama o adaptador.
Não é um protocolo de produção, nem foi submetido a fuzzing ou teste de carga.

O lançador gera uma credencial aleatória de 256 bits e entrega-a ao cliente
autorizado somente pelo stdin privado. Não persiste token em argv, ambiente,
arquivo, auditoria ou evidência. O broker exige UID do peer obtido por `SO_PEERCRED`
e comparação da credencial; UID isoladamente não basta. O grant tem duração de
180 s, permite somente ler a fixture, inserir `7` e consultar seus eventos.
É conferido em cada operação e novamente após validação do alvo antes da ação.
Não é provisionamento geral, pairing ou autenticação entre usuários.

Referências são opacas, ligadas à conexão e ao alvo validado, com TTL de 10 s.
Snapshot substitui a referência anterior. Expiração é conferida antes e depois da
validação; desconexão e falha de reautenticação invalidam a referência. Não há fila
de mutações nem repetição automática de ação. Falha de adaptação/resultado produz
indisponível ou resultado desconhecido, sem fallback.

## Eventos e recuperação

Snapshot fornece estado, época aleatória do broker e watermark da sequência;
também estabelece a assinatura da conexão. `events` consulta mudanças a partir
do cursor. A fonte é explicitamente **`atspi_query`**, não eventos nativos AT-SPI:
consultas são feitas em snapshot, ação confirmada e leitura de eventos. Não há
thread que monitore continuamente a aplicação.

O histórico mantém os dois eventos mais recentes. Cada mudança observada recebe
sequência crescente na época atual. Cursor anterior ao histórico retorna
`gap_snapshot_required`; época diferente retorna `epoch_changed_snapshot_required`.
A recuperação é um novo snapshot com estado atual e watermark. Após desconexão,
a conexão nova precisa autenticar e obter novo snapshot/assinatura; referências
da conexão antiga não operam. Repetir uma leitura não repete a mutação.

O teste provoca lacuna **real no histórico do broker**: três ações semânticas
confirmadas excedem a retenção de dois eventos, mantendo o cursor antigo. Não
fabrica eventos ou resultado visual. Depois do snapshot de recuperação, uma ação
após reconexão confirma o próximo número de sequência e o texto `7777`.

Este mecanismo detecta perda no histórico entregue pelo broker. **Não detecta
transições transitórias que ocorram inteiramente entre consultas AT-SPI**. Não
promete consistência global, totalidade dos eventos upstream ou snapshot atômico
com interação humana concorrente. A fixture deve ficar sem outros operadores.
Mudança inesperada de identidade/ciclo de vida encerra a prova; não há rebind
silencioso para outra aplicação. Reinício real do broker não foi demonstrado;
a rejeição de época incompatível foi testada no canal e nos testes unitários.

## Reprodução e testes independentes

Dependências efetivamente usadas: `/usr/bin/python3`, `python3-pyatspi` e GI/Gio
já disponíveis no laboratório M1.1, Sway, GNOME Calculator, Bubblewrap e `unshare`
do util-linux. Nenhum pacote adicional foi necessário. Num ambiente que não tenha
`bubblewrap`, a prova deve parar e informar a dependência; não executar o cliente
sem isolamento nem instalar com sudo automaticamente.

Na raiz do repositório, dentro da sessão existente e sem calculadora prévia:

```sh
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 -m py_compile experiments/m1_2/*.py tests/test_m1_2.py
/usr/bin/python3 -m experiments.m1_2.run --evidence /tmp/M1_2_nova_execucao.json
```

O arquivo precisa ser novo (criação exclusiva). Retorno 0 significa GO; exceção
registra PARTIAL e retorno 1. Um bypass observado deve ser classificado NO-GO,
mesmo que outros passos funcionem. Não interpretar testes simulados como prova
real. O programa não é um servidor persistente e termina após os dois clientes.

O [probe independente](../../experiments/m1_2/probe.py) usa sockets e operações de
filesystem diretamente, sem importar o broker. Compara namespace interno com os
identificadores do lançador; tenta os endpoints reais que o processo confiável
conseguiu alcançar, caminhos via `/proc/1/root`, dispositivos presentes no host e
`/dev/uinput`, e tenta criar outro user namespace. A rede separada também é testada
com um socket AF_UNIX abstrato canário criado pelo lançador. Esse canário testa a
fronteira de rede; não é um serviço gráfico real.

O lançador deixa deliberadamente um socket Sway real marcado herdável no pai;
`close_fds=True` deve eliminá-lo no cliente. O probe verifica zero sockets herdados
e zero descritores inesperados além de stdin/stdout/stderr e, depois da autenticação,
do próprio socket do broker. Testa antes da autenticação nos dois clientes e
repete com grant válido. Dispositivos de entrada/DRM existentes são tentados
somente no namespace do cliente, onde não estão montados. Ausência de hardware
real de câmera não qualifica uma câmera específica. O portal de captura fica
inacessível pela negação do barramento da sessão; não se tentou capturar frames.

Limites de execução: timeout de socket cliente 20 s; conexão do broker até 90 s e
32 pedidos; orçamento externo por cliente 120 s. Chamadas em andamento podem
estender esses prazos. O perfil não foi qualificado contra DoS ou clientes que
façam fork/flood; limites de cgroup e resistência a clientes arbitrários permanecem
pendentes. AT-SPI e Sway conservam os timeouts limitados do experimento anterior.

## Evidências e resultado observado

[RUN_08_GO](evidence/M1_2_RUN_08_GO.json) é a prova com o código final:

| Critério | Resultado real |
| --- | --- |
| Correlação | PID Sway = PID AT-SPI = 13710; container 21; executável e início registrados |
| Cliente sem grant | Autenticação, leitura, escrita e eventos negados; aplicação permaneceu intacta |
| Cliente com grant | Quatro ações semânticas confirmadas: vazio → 7 → 77 → 777 → 7777 |
| Acesso direto | Sway, Wayland, D-Bus sessão, AT-SPI, X11, PipeWire e barramento de sistema conectáveis no baseline; inacessíveis aos clientes |
| Namespaces/dispositivos | Cinco namespaces distintos, capabilities zero, NoNewPrivs=1, userns aninhado negado, zero dispositivos expostos |
| Herança de descritores | Zero sockets herdados e zero descritores inesperados, inclusive com grant válido |
| Referência expirada/fora de escopo | Rejeitada; snapshot confirmou estado inicial preservado |
| Evento | Sequência 1 com texto 7 e origem atspi_query |
| Lacuna e recuperação | Cursor antigo rejeitado; snapshot recuperou texto 777 no watermark 3 |
| Desconexão | Referência antiga e assinatura anterior rejeitadas na nova conexão |
| Retomada | Evento 4 confirmou texto 7777 após novo snapshot |

A [RUN_04_PARTIAL](evidence/M1_2_RUN_04_PARTIAL.json) foi preservada: negação e
isolamento passaram, mas a conexão autorizada foi encerrada antes de concluir o
fluxo de eventos. A auditoria registra uma ação confirmada; não é GO. A leitura
ampla da árvore foi reduzida aos campos necessários e os prazos foram ajustados.
Medições de duração no JSON são diagnósticas, não benchmark de desempenho.

Houve outras tentativas de desenvolvimento: RUN_01/02 pararam na prontidão da
fixture (o motivo detalhado não foi preservado); uma chamada diagnóstica encontrou
serialização de endereço AF_UNIX abstrato em bytes, corrigida para texto; RUN_03
teve negação bem-sucedida e falha posterior no cliente autorizado; RUN_05 registrou
`unexpected_executable` na inicialização, antes de clientes. A identidade esperada
passou a ser aguardada com prazo limitado, sem aceitar um executável alternativo.
RUN_06 e RUN_07 passaram; a prova final RUN_08 acrescenta conferência de todos os
descritores inesperados. Só os registros parcial representativo e final são
incluídos aqui; nenhum arquivo parcial foi convertido em GO.

**31 testes automatizados passaram** (15 M1.1 + 16 M1.2), incluindo framing
fragmentado, limites/mensagens inválidas, credencial/UID, expiração de grant,
reautenticação, referências por conexão, expiração durante validação, métodos e
parâmetros fora do escopo, ordem, retenção, cursor e época. Esses testes e as
sondas reais se complementam. Também foram executados compilação Python,
`git diff --check`, verificação de links internos e revisão dos arquivos/evidências.

Os JSON contêm apenas categorias das sondas, errno, números de processo/UID,
campos controlados da calculadora, época/sequência e auditoria sem argumentos.
Não contêm credenciais, endereços privados de endpoints, árvores alheias, títulos
ou screenshots. Não registrar o stdin de provisionamento ou o ambiente completo.

## Limites, condições de parada e pendências

GO vale para uma sessão de laboratório confiável, um processo/janela de
calculadora e clientes lançados pelo perfil fixo. Falha de montagem, isolamento,
baseline, correlação, confirmação, rejeição de referência ou recuperação impede GO.
O programa retorna PARTIAL em falhas; um bypass exige NO-GO na avaliação do gate.

O perfil não resiste a kernel comprometido, root ou processos não isolados do
mesmo UID no contexto confiável. Não confere automaticamente o sandbox de um peer
externo: o lançador é parte da confiança. Não foi qualificado isolamento entre
usuários ou sessões simultâneas, autorização dinâmica, persistência/revogação de
identidades, reinício real do broker, controle físico/remoto ou semântica de outras
aplicações. Há uma corrida residual entre validação e dispatch AT-SPI; não há
transação atômica entre fontes. Não foi construído contrato público ou segurança
de produção, nem selecionados definitivamente compositor, protocolo ou isolamento.

A revisão do mantenedor deve avaliar essas fronteiras e a limitação do polling.
Qualificar eventos upstream, sessão/multiusuário e recursos exigirá trabalho
separado. Não iniciar captura, takeover, M1.3, imagem ou distribuição neste PR.
As exigências dos [ADRs 0006](../DECISIONS/0006-mandatory-agent-mediation.md) e
[0007](../DECISIONS/0007-unified-input-mediation.md) continuam em vigor; o segundo
não foi implementado por este experimento. Nenhuma decisão aceita foi alterada.
