# LoopShell V0.8-B.1 — Console de leitura

**Resultado GO** para o console de leitura sobre o socket Unix existente,
com credenciais de laboratório. O ensaio cobre a interface GTK4 em prévia,
o protocolo real e um desktop privado descartável. A qualificação da V0.8
completa, o isolamento do host e a transferência de controle têm gates
próprios. Veja o [design V0.8](../design/LOOPSHELL_V0_8.md).

## Comandos e grants

A gramática local v1 aceita uma linha ASCII por vez, até 256 caracteres.
Identificadores têm até 32 caracteres e usam letras, dígitos, ponto,
hífen e sublinhado, começando por letra ou dígito. Os IDs lógicos atuais
incluem `desktop` e `calculator`. A gramática e a versão 0.6 do
protocolo LoopBridge têm ciclos de versão independentes.

| Entrada | Comportamento | Autorização existente |
| --- | --- | --- |
| `help` | Mostra a gramática e os comandos disponíveis. | Local. |
| `clear` | Limpa o histórico em memória. | Local. |
| `exit` | Fecha a LoopShell e encerra sua conexão. | Local. |
| `sessions list` | Chama `discover` e exibe `{"sessions":[…]}`. | `session.discover` para as sessões retornadas. O perfil desktop concede esse grant com alvo `*`. |
| `session status <id>` | Chama `snapshot` e exibe `session`, `phase` e `revision` em JSON. | `session.discover` com alvo `*` no DesktopBroker. No Core/fixture, o snapshot exige `desktop.observe` no alvo autorizado. |
| `system status`, agentes, missões, observação visual ou controle | Operação indisponível no console. | O console utiliza apenas as duas consultas da tabela. |

O diagnóstico administrativo existente tem seu próprio contrato de
autorização. Nenhum endpoint novo foi necessário. A listagem reflete
somente o broker selecionado. No perfil privado, o socket de um desktop
expõe seu ID lógico `desktop`.

## Autenticação e falhas

Informe o caminho absoluto do socket de cliente LoopBridge com `--socket`.
A LoopShell compara o UID do peer obtido pelo kernel com o UID local por
padrão. Em um perfil com identidade Linux dedicada, informe o UID esperado
por `--peer-uid`. Use o endpoint provisionado para o cliente, em um caminho
de confiança. A verificação de UID não comprova isolamento entre processos
que já compartilham a mesma identidade Linux.

Em **Conectar**, insira a credencial individual de 43 caracteres do
observador ou delegado no campo mascarado e pressione Enter. O cliente usa
`auth`, limpa o campo antes da chamada e guarda a identidade retornada e o
socket, sem guardar o bearer para reconectar. Uma resposta `owner` fecha a
conexão antes de qualquer consulta. A entrada da CLI protege o processo com
o mecanismo local usado pelo viewer. Histórico e erros exibem nomes
canônicos, campos validados ou mensagens fixas. Texto digitado, exceções
remotas, dados dos erros e referências de snapshot ficam fora do histórico.

O console distingue desconexão, UID divergente, autenticação recusada,
permissão insuficiente, recurso explicitamente indisponível, resposta
inválida, tempo esgotado e operação indisponível. `grant_denied` cobre
tanto falta de grant quanto sessão inexistente ou fora de visibilidade.
A mensagem preserva essa ambiguidade para que o console não exponha
existência de sessões além do contrato. `target_unavailable`, quando
retornado pelo Core, indica recurso indisponível. EOF, inclusive após
encerramento do broker, indica perda de conexão. O socket sozinho não
distingue encerramento da sessão de outra causa de perda da conexão.

As chamadas de I/O ocorrem fora da thread GTK, com uma chamada em curso e prazo de três
segundos por etapa de transporte. Após timeout, resposta inválida ou perda
do transporte, uma nova tentativa exige **Conectar** e a credencial.
A conexão autenticada permanece sujeita aos grants atuais em cada chamada.
Uma desconexão ocorrida em repouso é observada na próxima consulta.

## Reprodução

Na raiz do repositório, execute a regressão focada e a suíte completa.

```sh
/usr/bin/python3 -B -m unittest discover -s tests -p test_loopshell_console.py -v
/usr/bin/python3 -B -m unittest discover -s tests
```

O teste `BrokerIntegration` inicia o broker real com o adapter fixture,
gera credenciais individuais em memória, verifica grants e revogação e
testa uma negativa de controle pelo protocolo. Para repetir manualmente
o fluxo na interface, inicie um fixture descartável.

```sh
lab=$(mktemp -d /tmp/loopshell-b1.XXXXXX)
/usr/bin/python3 -B -m loopbridge provision "$lab/credentials"
/usr/bin/python3 -B -m loopbridge serve --mode fixture --runtime "$lab/runtime" \
  --credentials "$lab/credentials/service.json" &
broker=$!
trap 'kill "$broker" 2>/dev/null; wait "$broker" 2>/dev/null' EXIT
endpoint="$lab/runtime/socket/control.sock"
```

Depois de o broker reportar `ready`, abra a LoopShell em prévia. Use a
credencial de laboratório de `observer.token` no campo mascarado.
`sessions list` retorna permissão insuficiente até a concessão do grant.

```sh
/usr/bin/python3 -B -m loopshell --preview --socket "$endpoint" \
  --config "$lab/layout.json" &
```

Em um cliente de administração separado, conceda somente os escopos de
leitura ao observador do fixture.

```sh
/usr/bin/python3 -B -m loopbridge client --socket "$endpoint" \
  --token-file "$lab/credentials/owner.token" <<'RPC'
{"method":"delegate","params":{"session":"calculator","principal":"observer","capability":"session.discover","target":"*","ttl":180}}
{"method":"delegate","params":{"session":"calculator","principal":"observer","capability":"desktop.observe","target":"*","ttl":180}}
RPC
```

No console, teste `sessions list` e `session status calculator`.
`session status missing` produz a negativa de visibilidade. `acquire calculator`
e `system status` ficam indisponíveis. `exit` deixa o fixture ativo.
Os arquivos descartáveis pertencem ao diretório criado acima.

Para repetir com um desktop privado, siga o [procedimento local V0.6](../LOOPBRIDGE_V0_6.md#run-locally)
com credenciais e runtime descartáveis. Informe à LoopShell o socket de
cliente publicado pela instância. No cliente de administração separado,
conceda o grant de descoberta a `desktop` com alvo `*`. Consulte
`session status desktop` e compare `private.status` no manager antes e
depois de `exit` para verificar a continuidade.

## Evidência

- A suíte focada aprovou 16 testes. Cobriu a gramática, limite de entrada,
  desligamento, credencial inválida, peer UID divergente, negativa de grant,
  timeout, EOF, quadros e resultados inválidos e descarte de texto remoto.
  A integração com o broker auditou somente `auth`, `discover` e
  `snapshot` para os comandos do observador. A mesma credencial recebeu
  `grant_denied` ao pedir `acquire` pelo cliente de teste separado.
- No Debian com GTK 4.18.6 e Sway 1.10.1, um ensaio adicional abriu o console
  em uma prévia GTK4 sobre Sway headless isolado. O broker da sessão privada
  real executou em outro Sway descartável. O ensaio usou o campo GTK
  mascarado, verificou falha de credencial e negativa até a concessão do
  grant, recebeu `{"sessions":["desktop"]}` e o status `idle`, verificou
  as respostas locais e confirmou continuidade da instância `ready` após
  `exit`. A auditoria registrou apenas autenticação e as duas consultas
  para o console. A prova separada de aquisição retornou `grant_denied`.
  [Dados do ensaio](evidence/LOOPSHELL_V0_8_B1_CONSOLE.json).
- A suíte completa aprovou 317 testes. O ensaio gráfico cobriu a prévia,
  e os testes determinísticos de geometria da V0.8-A continuaram aprovados.
  O perfil D4.2C cross-UID e a geometria ancorada com o novo console ficam
  fora desse ensaio gráfico. [D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5)
  e [M1.3B](M1_3B_TRUSTED_INPUT_FEASIBILITY.md) preservam seus gates.
