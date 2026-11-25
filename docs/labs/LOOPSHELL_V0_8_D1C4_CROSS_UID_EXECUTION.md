# V0.8-D.1C.4 — Qualificação cross-UID do Registry

**Resultado: GO experimental.** No clone descartável Debian 13, o
Registry funcionou entre UIDs Linux distintos. A prova inclui 18 negativas
de acesso direto, revogação, rotação de credenciais, persistência,
recuperação após reinício e remoção verificada da fixture. O aceite do
objetivo registra o recebimento pelo executor. A fase de execução de um
objetivo pertence à [proposta D.2A](../design/LOOPSHELL_V0_8_D2A_EXECUTOR_PROPOSAL.md).

As observações vieram de saídas de terminal fornecidas pelo operador,
complementadas pela confirmação final de limpeza (`CLEANUP GO`). A
[evidência sanitizada](evidence/LOOPSHELL_V0_8_D1C4_CROSS_UID_EXECUTION.json)
é uma consolidação desses resultados com procedência
`operator_supplied_terminal_output`. O registro depende da transcrição do
operador. Esta revisão documental não executou a prova nem coletou logs
persistentes.

## Identificação e fronteira da fixture

| Item | Valor informado |
| --- | --- |
| Ambiente | Clone VirtualBox `looplab-d1c3`, Debian 13, com snapshot prévio |
| Commit do ensaio | `2917d1a35f0e9898c47656557c7a3e5ef067ecd6` (D.1C.3, PR #38) |
| SHA-256 do TAR | `6e7034c4d029aeca7afa86eba86dd59c97e375419439b3de35e876ba7aed6da6` |
| Run ID | `5f0c4c9f006e04ed` |
| Raiz temporária | `/run/loop-registry-d1c3-5f0c4c9f006e04ed`, `0755`, `0:0` |
| Cliente desktop | `vboxuser`, UID/GID `1000:1000` |
| Serviço experimental | `loopbridge-svc`, UID/GID `980:980` |
| Diretório privado | `0700`, `980:980` |
| Diretório de ingresso | `0710`, `980:980`, ACL `user:1000:--x` |
| Socket RPC | `0620`, com admissão do UID 1000 |
| SQLite e manifesto | Ambos `0600`, UID 980 |
| Unidade instalada no preflight | `loopbridge.service`, `ActiveState=inactive`, `UnitFileState=disabled` |

O [procedimento D.1C.3](LOOPSHELL_V0_8_D1C3_CROSS_UID_PREFLIGHT.md) e o
[driver](../../tools/registry_cross_uid.py) exercitam o perfil
[D.1C.2](../design/LOOPSHELL_V0_8_D1C2_OPERATIONAL_REGISTRY.md), a
[admissão D2](../design/TRUSTED_SERVICE_INGRESS_D2.md) e o
[ciclo D3](../design/TRUSTED_SERVICE_LIFECYCLE_D3.md), sob a direção da
[ADR 0012](../DECISIONS/0012-trusted-service-identity-boundary.md).
O socket e o descritor privados da prova eram sentinelas sintéticas.

## Resultados por fase

1. **Inicial — GO.** Broker sob UID 980, PID `5588`, e cliente sob UID
   1000. O cliente verificou a identidade do broker via `SO_PEERCRED`.
   Passaram a autenticação individual, o registro do executor, a
   confirmação do vínculo, a criação e a oferta do objetivo e o aceite.
   A credencial inválida e a operação do principal sem grant foram recusadas.
2. **Revogação e rotação — GO.** O broker publicou a geração `2` da
   política. O grant do emissor foi efetivamente revogado. A credencial
   anterior do executor foi recusada, a rotacionada foi aceita e a
   operação do principal sem grant continuou recusada.
3. **Reinício e recuperação — GO.** O primeiro broker encerrou
   ordenadamente e removeu seus sockets. O segundo iniciou sob UID 980,
   PID `5833`. O `DatabasePin` permaneceu `24:2231:24:2234`. O objetivo
   continuou aceito e o recibo original foi reconciliado pelo mesmo
   `request_id`, na revisão `3`. A credencial antiga continuou recusada
   e o grant do emissor permaneceu revogado. O segundo broker também
   encerrou ordenadamente e removeu seus sockets.

As respostas RPC observadas nas três fases não trouxeram dados auxiliares
ou descritores. Cada fase repetiu as mesmas seis sondagens sob UID 1000.

| Acesso direto tentado | Inicial | Revogação e rotação | Após reinício |
| --- | --- | --- | --- |
| Travessia do diretório privado | `EACCES` | `EACCES` | `EACCES` |
| Listagem do diretório privado | `EACCES` | `EACCES` | `EACCES` |
| Leitura do SQLite | `EACCES` | `EACCES` | `EACCES` |
| Leitura do manifesto | `EACCES` | `EACCES` | `EACCES` |
| Conexão ao socket sentinela privado | `EACCES` | `EACCES` | `EACCES` |
| Abertura do descritor sentinela em `/proc/<pid>/fd/<n>` | `EACCES` | `EACCES` | `EACCES` |

Total de **18 negativas**, todas com `errno 13` (`EACCES`).

## Auditoria e limpeza

Antes da remoção, o operador confirmou o hostname `looplab-d1c3`,
UID administrativo 0, raiz da fixture `0755` e `0:0`, ausência dos PIDs
`5588` e `5833`, ausência dos dois sockets experimentais e ausência de
montagens internas. O SQLite e o manifesto ainda pertenciam ao UID 980,
em modo `0600`. O operador executou `rm -r --one-file-system` somente
no diretório aprovado. A verificação posterior retornou `CLEANUP GO`.
A unidade instalada permaneceu `ActiveState=inactive` e
`UnitFileState=disabled`.

## Matriz de aceitação

| Dimensão | Resultado | Alcance da evidência |
| --- | --- | --- |
| Registry cross-UID funcional | **GO** | UIDs reais distintos, peer verificado, fluxo autenticado até o aceite, negativas de credencial inválida e de principal sem grant. |
| Isolamento direto na fixture | **GO** | 18 negativas `EACCES` e nenhuma transferência auxiliar observada no RPC. |
| Revogação e rotação | **GO** | Geração 2 aplicada, grant do emissor revogado e troca efetiva da credencial do executor. |
| Persistência e recuperação | **GO** | Novo processo, mesmo `DatabasePin`, estado aceito e recibo original, revisão 3. A revogação e a recusa da credencial antiga persistiram. |
| Cleanup da fixture | **GO** | Operador confirmou a remoção no clone e o estado inativo e desabilitado da unidade instalada. |
| Terceiro UID não admitido | **NOT RUN** | Teste opcional do procedimento D.1C.3. |
| Sobrescrita no mesmo inode por ator privilegiado | **FORA DO ESCOPO** | O pin identifica o diretório e o arquivo por dispositivo e inode. |
| Reativação após perda definitiva do SQLite ativo | **NÃO QUALIFICADA** | A recuperação demonstrada reabriu o banco ativo preservado. |
| Isolamento de sockets gráficos privados reais | **NOT RUN** | As sondagens usaram sentinelas, sem instâncias privadas de Wayland, Sway IPC ou D-Bus. |
| D5 completo | **NÃO QUALIFICADO (PARTIAL)** | A [matriz D5](../design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5) exige prova do perfil endurecido com recursos reais. |
| M1.3B | **INDEPENDENTE, NÃO QUALIFICADO POR ESTA PROVA** | O [gate de preempção e takeover](../ROADMAP.md#m13b--trusted-input--enforcement-feasibility) exige barreiras reais de despacho de entrada e semântica. |
