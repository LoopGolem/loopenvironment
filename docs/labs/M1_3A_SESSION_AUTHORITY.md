# M1.3A — Identity, Grants & Session Authority

**Resultado em 2026-11-16: GO somente para M1.3A.** O núcleo experimental
executável autentica identidades, delega/revoga grants e arbitra leases por
sessão. Um delegado isolado inseriu `7` na GNOME Calculator mediante autorização;
o observador leu o resultado sem controle. Revogação e replay foram recusados,
sem novos dígitos. **Takeover foi demonstrado apenas como política simulada em
testes unitários.** Não há preempção real, LoopBridge de produção ou GO do M1.3
completo.

## Base, diagnóstico e limites de trabalho

Foram lidos integralmente AGENTS, README, VISION, PRODUCT_DEFINITION,
OPERATOR_MODEL, SESSION_AUTHORITY_V1, ARCHITECTURE, LOOPBRIDGE, INTERACTION_MODEL,
SECURITY_MODEL, ROADMAP, LOOPTEACH, índice de ADRs e ADRs 0006–0009, além do código,
testes e laboratório M1.2 e do adaptador M1.1. Nenhuma decisão aceita foi alterada;
[Session Authority V1](../design/SESSION_AUTHORITY_V1.md) é o contrato experimental.

`git status --short --branch`, `git branch -avv`, `git remote -v`, `git log -8
--oneline`, `git fetch origin` e `git rev-parse HEAD origin/main` confirmaram árvore
limpa e base `76d5504af535d17e94030b7471ca89c18fcff09c`. Ela contém o PR #5
(`338dac4`, contrato) e o PR #6 (preservação do preflight histórico NO-GO).
`git diff main codex/m1.3-fallback-human-control --stat` não encontrou diferença;
o commit único da branch anterior estava preservado pelo squash do PR #6.
Só essa branch local concluída foi removida; foi criada
`codex/m1.3a-session-authority`. Nenhuma branch remota foi excluída.

Plano executado: núcleo independente; testes progressivos; integração da fixture
existente; revisão adversarial; qualificação delimitada do código final; evidência e PR.
Não houve instalação de pacotes, sudo, nova VM, usuário Linux, mudança global,
listener de rede, captura ou implementação de outro marco. O sandbox da ferramenta
negou escritas em `.git` e operações de socket; os comandos Git e de qualificação
necessários foram executados com aprovação fora desse sandbox. **O isolamento sob
teste foi sempre o Bubblewrap explícito**, não o sandbox da ferramenta.

## Ambiente efetivamente usado

VM Debian 13.7 existente, sessão Sway e saída VirtualBox já utilizadas por M1.1/M1.2:

| Componente | Versão consultada |
| --- | --- |
| Kernel | `6.12.117+deb13-amd64` |
| Python | `3.13.5` |
| Sway | `1.10.1-2` (`sway --version`: 1.10.1) |
| Bubblewrap | `0.12.0-1~deb13u1` |
| GNOME Calculator | `1:48.1-2+b1` |
| python3-pyatspi | `2.46.1-1` |
| at-spi2-core | `2.56.2-1+deb13u2` |
| GTK 4 | `4.18.6+ds-2` |

Comandos de diagnóstico: `cat /etc/os-release`, `uname -r`, `python3 --version`,
`sway --version` e `dpkg-query -W` para os pacotes acima. A evidência registra
versões, base e SHA-256 dos fontes/testes efetivamente qualificados.

## Implementação e fronteiras

O novo [módulo experimental](../../experiments/m1_3a/broker.py) reutiliza partes
pequenas do M1.2 sem alterar seus fontes ou testes:

- [identity.py](../../experiments/m1_3a/identity.py): provisionamento **efêmero de
  laboratório**, três credenciais aleatórias distintas de 256 bits, comparação
  de digests e falha uniforme. `unenrolled` recebe nenhuma identidade registrada.
  Não é bootstrap de instalação, rotação ou recuperação de produção.
- [authority.py](../../experiments/m1_3a/authority.py): grants, escopo exato de sessão
  e alvo, expiração monotônica injetável, revisões, epoch, lease exclusivo e fases.
  Capacidades não operacionais são apenas representáveis, sem endpoints próprios.
- [broker.py](../../experiments/m1_3a/broker.py): conexão autenticada via credencial
  **e** UID de `SO_PEERCRED`, autorização no servidor, snapshot, ação fixa `invoke7`,
  eventos, administração limitada, liberação e reinício lógico da sessão.
  Não há método de takeover real, shell, D-Bus genérico ou input arbitrário.
- [protocol.py](../../experiments/m1_3a/protocol.py): reaproveita envelope/encoding
  do M1.2; acrescenta rejeição de chaves JSON duplicadas e prazo absoluto do frame.
- [adapter.py](../../experiments/m1_3a/adapter.py): reaproveita `Fixture`, correlação
  e validação M1.1; separa preparação, despacho e confirmação por texto da aplicação.
- [client.py](../../experiments/m1_3a/client.py), [run.py](../../experiments/m1_3a/run.py)
  e [qualify.py](../../experiments/m1_3a/qualify.py): clientes idênticos por pipes
  privados, prova real limitada e agregação de testes/evidência sanitizada.

### Autenticação e grants

Uma conexão começa sem autoridade. O servidor determina o principal a partir da
credencial efetiva, nunca de `principal_id`, `role`, `human` ou `agent`. Parâmetros
extras são rejeitados. Mesmo UID não autentica um operador. Toda reautenticação,
inclusive bem-sucedida, elimina referências, assinatura e lease anteriores.
Credenciais de principal podem intencionalmente autenticar mais de uma conexão;
**leases e handles não podem ser emprestados entre elas**, mesmo para o mesmo
principal. Reconexão exige autenticação, lease e snapshot novos.

O owner recebe grants explícitos da fixture por 180 s em cada sessão de teste,
incluindo administração e override; isso não concede autoridade aos demais
processos do UID. A fixture cadastra apenas três principais e não oferece cadastro
público. Cada grant possui beneficiário, capacidade, alvo, emissor, expiração,
revisão e estado de revogação; a sessão que o contém é parte do escopo. Só são
aceitos alvo `calculator.digit7` ou `*`, dentro de uma sessão conhecida. Não há
matching de alvos arbitrários ou herança de janelas.

Delegação exige **identity.admin e a capacidade delegada**, com escopo e validade
suficientes para toda a duração solicitada. O owner pode delegar administração
explicitamente; controle sozinho não administra nem faz override. Administração
restrita não revoga grants mais amplos. Revogação é por grant, sem cascata implícita:
se houver outro grant válido para a mesma capacidade/escopo, ele continua valendo.
Leases podem ter deadline posterior a um grant, mas cada operação consulta grants
vivos novamente; o lease não estende sua autoridade.

As credenciais só existem na memória confiável e no stdin privado do respectivo
cliente. O broker retém digests; não há credencial em argv, ambiente, arquivos ou
logs. Auditoria usa métodos conhecidos e categorias fixas, sem parâmetros ou
exceções brutas. Antes da gravação, o runner procura as credenciais provisionadas
na evidência; se encontrar uma, substitui todo o relatório por uma falha sanitizada.
Esse scan é complementar à seleção restrita dos campos, não um detector geral de
segredos de produção.

### Sessão, concorrência e despacho

A sessão tem ID, epoch aleatória, revisão de estado/política, geração, controlador,
lease e fase. Novas aquisições incrementam a geração. Lease é vinculado ao principal,
conexão, sessão, epoch e deadline. Dois clientes não obtêm controle simultâneo.
Revogação, expiração e desconexão impedem novas operações. Reinício lógico muda a
epoch e invalida leases/handles; não é reinício de desktop ou processo do broker.

Cada snapshot cria um handle opaco, válido por até 10 s, para aquela conexão,
epoch, geração, revisão e alvo real. Novo snapshot substitui o anterior. Após
adquirir controle é necessário atualizar o snapshot. Cada tentativa admitida de
operação consome o handle, inclusive se a preparação falhar. Replay não repete a
mutação e timeout não provoca retry automático.

Um lock por sessão serializa política, grants e leases. Chamadas de descoberta e
preparação AT-SPI/Sway ocorrem fora dele, sob um lock separado de acesso ao adaptador.
Depois delas o broker verifica novamente conexão, grants, lease, geração, epoch,
revisão, deadline e handle. A checagem final e a única chamada `doAction` são
serializadas com revogação pelo lock **daquela sessão**. Não há lock global mantido
durante chamadas externas. A fixture configura timeouts AT-SPI de 1000/2000 ms;
Sway conserva timeout de 3 s. O lock do adaptador também serializa confirmação e
observação da fixture, sem bloquear administração de política durante essa espera.

Uma operação reservada permanece pendente até resolver. Liberação/revogação ou
desconexão nesse intervalo invalidam o lease, mas impedem nova aquisição enquanto
houver resultado pendente. Uma operação já despachada pode ser confirmada após
revogação/expiração: isso registra o efeito anterior, **não cancela eventos físicos**.
Falha após tentativa de despacho gera `outcome_unknown`, invalida o lease e deixa
`blocked`; um simples reinício lógico não remove esse bloqueio. Recuperação real
exigiria verificação da fronteira e não está implementada.

Ainda há uma corrida entre a última validação da aplicação e mudanças externas à
fixture. Não existe transação atômica entre Sway, aplicação e AT-SPI. O teste exige
uma calculadora nova supervisionada, sem outros operadores; não comprova arbitragem
de ações AT-SPI em andamento nem cancelamento no compositor.

### Eventos e limites de recursos

Eventos ordenados por sessão registram mudanças de grant, controle, resultado e
reinício. Snapshot traz watermark, epoch e revisões. Retenção: oito eventos;
gap/epoch incompatível invalida a assinatura e exige snapshot. Eventos dependem
de operações/consultas, não de subscrição nativa AT-SPI nem monitoramento contínuo.
A revisão é a do estado do broker; não promete capturar toda transição da aplicação.
A observação sempre é reautorizada, inclusive após consultas externas.

Limites: 8192 bytes/frame, envelope estrito, ID inteiro crescente por conexão
(replay de ID encerra o canal), até 64 pedidos e 180 s/conexão; espera de frame no
máximo 30 s, limitada pela vida restante da conexão. Até oito peers simultâneos,
128 entradas de auditoria e 128 grants por sessão (incluindo revogados). Timeouts
não interrompem magicamente uma chamada externa já iniciada; não há servidor de
produção, fila ilimitada ou mecanismo de recuperação de chamadas travadas.

## Isolamento e prova Linux real

O runner usa o [perfil Bubblewrap M1.2](../../experiments/m1_2/isolation.py)
inalterado, trocando apenas o entrypoint e adicionando o fonte do novo cliente
somente leitura. Cada cliente possui namespaces separados, `/proc` privado,
ambiente limpo, capabilities zero, NoNewPrivs e userns adicional desabilitado.
O diretório compartilhado contém somente o socket experimental (diretório 0700,
socket 0600), montado somente leitura. Segredos chegam por stdin, não pelo mount.

As [sondas M1.2](../../experiments/m1_2/probe.py) foram executadas antes e após
autenticação para owner/delegate/observer/unenrolled. O baseline confiável conectou
Sway, Wayland, D-Bus de sessão, AT-SPI, X11, PipeWire, barramento de sistema e canário
AF_UNIX abstrato. Todos foram inacessíveis nos clientes, também via `/proc/1/root`.
Dispositivos de entrada/DRM e `/dev/uinput` foram negados, cinco namespaces eram
privados e não havia descritores inesperados ou sockets herdados. O launcher
marcou deliberadamente um socket Sway herdável; `close_fds=True` o eliminou.
Não foi exposto AT-SPI/Wayland/Sway ao cliente autorizado.

Na qualificação final, PID Sway = PID AT-SPI = **44002**, container **27**,
executável `/usr/bin/gnome-calculator`, início de processo registrado na evidência:

1. Owner autenticou, delegou observe/control ao delegate e apenas observe ao observer.
2. Clientes independentes autenticaram; unenrolled teve leitura/escrita negadas.
3. Observer não adquiriu controle; delegate não emitiu grants administrativos nem
   ganhou autoridade com `role: owner`/`human: true`.
4. Delegate obteve snapshot, lease e snapshot atualizado, e invocou `invoke7`.
5. Consulta independente, com nova descoberta e `texts(frame)` fora da confirmação
   do adaptador, encontrou `7`. O snapshot do observer confirmou o mesmo texto.
6. Observer não escreveu e replay do handle não repetiu o dígito.
7. Owner revogou desktop.control. Nova ação e aquisição do delegate foram negadas.
8. Observe continuou válido. Consulta independente confirmou texto ainda em `7`.

O runner só encerra a calculadora que iniciou. Uma calculadora pré-existente
provoca recusa, sem adoção, encerramento ou alteração da sessão global.

## Testes automatizados e evidências

[Qualificação final sanitizada](evidence/M1_3A_QUALIFICATION_01_GO.json):
**96 testes passaram; zero falhas, erros ou skips** — 15 M1.1, 16 M1.2 e 65 M1.3A.
O JSON contém os IDs completos dos testes, hashes dos fontes/testes, ambiente,
sondas, auditoria sem parâmetros e estados reais da calculadora. Não contém
credenciais, leases, handles, endereços privados, screenshots ou dados de outros apps.

| Evidência unitária/determinística | Casos observados |
| --- | --- |
| Autenticação | Credencial ausente/incorreta, mesmo UID, UID errado, spoofing, reauth inválida/válida, credencial reutilizada intencionalmente em conexão distinta sem empréstimo de lease |
| Política | Deny by default, observer sem controle, control sem observe/admin/override, admin limitado, sessão/alvo incorretos, validade finita, grant expirado/revogado, leitura reautorizada após consulta |
| Frescor/replay | Handle substituído/consumido/expirado, snapshot anterior à aquisição, reconexão, epoch nova, geração antiga e empréstimo entre identidades/conexões |
| Concorrência | Aquisição simultânea com um vencedor, revogação versus aquisição, grants concorrentes sem perda de revisão, duas ações com um despacho, release versus aquisição, política de outra sessão durante adaptador lento |
| Despacho | Revogação/expiração/desconexão durante preparação sem despacho, EOF detectável antes do despacho, expiração depois do envio sem falso cancelamento, pendência durante revogação, resultado desconhecido bloqueado |
| Protocolo/recursos | Frame grande/inválido, envelope inválido, JSON duplicado, IDs repetidos, métodos desconhecidos, deadline absoluto contra trickle, timeout ocioso, orçamento de pedidos, retenção real da auditoria, gap/ressincronização |
| Takeover **simulado** | Operação marcada pendente, fencing imediato da geração antiga, resolução/cancelamento simulado antes do avanço da geração, refresh obrigatório, override delegado, requester diferente recusado, barreira desconhecida sem sucesso |

Os testes usam um adaptador gravador para observar número de despachos/dígitos,
relógio injetável para expiração, threads/barreiras/Event para corridas e sockets
Unix reais para framing/autenticação. Não duplicam a política no cliente. Casos
de ambiguidade/ciclo de vida reais continuam cobertos pelos testes M1.1 de
correlação/elementos e pela validação da fixture. Não houve fuzzing ou benchmark.
A carga máxima de oito peers é limitada no código, sem qualificação de DoS.

O takeover abstrato usa métodos explicitamente `*_simulated_takeover`, sem
endpoint no broker e sem ligação com Sway ou o adaptador real. A resolução da
barreira é um resultado **fornecido pela simulação**; não é observação do compositor.
Os testes verificam que o modelo não avança a geração antes desse resultado e
permanece bloqueado quando ele é desconhecido. Isso não prova cancelamento de
nenhuma chamada AT-SPI/Wayland real.

### Execuções efetivas

- Primeira suíte no sandbox da ferramenta: 87 testes, dois erros de expectativa
  nos novos testes e dez erros de socket devido às restrições do sandbox. Não foi
  tratada como aprovação. Foram corrigidas expectativas de erro por escopo e a
  seleção do último evento de geração, sem relaxar política.
- `python3 -m unittest discover -s tests -v`, fora desse sandbox: **87/87 passaram**.
- `/usr/bin/python3 -m experiments.m1_3a.run --evidence /tmp/M1_3A_RUN_01.json`:
  GO real inicial. Esse registro transitório não é a evidência do código final.
- Revisão adversarial: acrescentados prazo absoluto, parser estrito, bloqueio de
  reinício após outcome desconhecido, vínculo do solicitante na simulação e testes
  de regressão. Nenhum bypass de isolamento foi observado.
- `python3 -m py_compile experiments/m1_3a/*.py tests/test_m1_3a.py`: passou.
- `/usr/bin/python3 -m experiments.m1_3a.qualify --evidence /tmp/M1_3A_QUALIFICATION_02.json`:
  **96/96 testes e prova real GO**, agregados no JSON versionado. O comando invoca
  discovery unittest no mesmo processo e depois executa uma única fixture real.
  A qualificação 01 também passou em 96 testes e na aplicação; foi renovada após
  remover uma linha em branco final, para que os hashes do registro versionado
  correspondam exatamente aos arquivos entregues. A execução 02 emitiu um aviso
  AT-SPI de cache inexistente durante descoberta; a correlação e as consultas
  independentes posteriores passaram. O aviso não foi suprimido nem tratado como
  prova de sucesso.
- `git diff --check`, conferência dos links internos, hashes da evidência,
  terminologia, campos sanitizados e preservação dos fontes/evidências M1.1/M1.2
  integram a revisão final registrada no PR.

### Reprodução

Na raiz do repositório, com as dependências acima já instaladas, dentro da sessão
Sway existente e sem calculadora aberta:

```sh
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 -m py_compile experiments/m1_3a/*.py tests/test_m1_3a.py
/usr/bin/python3 -m experiments.m1_3a.qualify --evidence /tmp/M1_3A_nova_qualificacao.json
```

O último comando já inclui a suíte completa; não é necessário executar ambos os
comandos de teste para uma reprodução. Para somente a aplicação real:

```sh
/usr/bin/python3 -m experiments.m1_3a.run --evidence /tmp/M1_3A_nova_aplicacao.json
```

O caminho da evidência precisa ser novo; criação exclusiva impede sobrescrita.
Retorno 0 indica GO delimitado; retorno 1 indica PARTIAL/NO-GO, conforme JSON.
Ausência de sessão/fixture/dependência gera PARTIAL, sem fallback não isolado.
Falha de invariantes/sondas impede GO. Sem fixture real, execute os unitários e
não declare GO completo. Não instalar pacotes ou alterar o desktop para contornar
uma falha. Os testes usam prazos finitos; não executar baterias indefinidamente.

## Limites e próximos gates

GO é para o controle de autoridade de **uma fixture em uma sessão real**, com
segunda sessão apenas em testes unitários. Não foram demonstrados desktops
independentes simultâneos, isolamento entre usuários, broker reiniciado como
processo, clientes remotos, credenciais de produção, onboarding, recuperação,
resistência a DoS/fork/flood, kernel/root comprometido ou proteção contra processos
não isolados no contexto confiável do mesmo UID. Referências são conservadoras:
qualquer revisão de autoridade exige novo snapshot para agir.

M1.3B permanece pendente: binding confiável de input físico ao principal/sessão;
fronteira real para input convencional; barreira coordenada entre compositor e
operações semânticas; resolução verificável de efeitos pendentes/desconhecidos;
takeover real confirmado somente após essa barreira. O histórico
[preflight NO-GO](M1_3_FALLBACK_HUMAN_CONTROL.md) permanece inalterado.

Captura, streaming, observador gráfico remoto, M1.3C, imagem/instalação do SO,
LoopTeach e segurança de produção não foram implementados ou qualificados.
Nenhum próximo marco foi iniciado; a entrega termina em PR para revisão humana,
sem merge.
