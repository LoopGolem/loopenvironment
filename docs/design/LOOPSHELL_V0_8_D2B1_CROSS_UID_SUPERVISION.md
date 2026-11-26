# V0.8-D.2B.1 — Fronteira cross-UID da supervisão

**Perfil experimental preparado para qualificação.** O único plano é
`add_in_two_stages`, com resultado inteiro `5`. A supervisão, a auditoria e
a recuperação seguem a [D.2B](LOOPSHELL_V0_8_D2B_SUPERVISED_EXECUTION.md).
A [D.1C.4](../labs/LOOPSHELL_V0_8_D1C4_CROSS_UID_EXECUTION.md) oferece
evidência cross-UID para o Registry. A execução supervisionada exige
a prova própria descrita no [runbook D.2B.1](../labs/LOOPSHELL_V0_8_D2B1_CROSS_UID_PREFLIGHT.md).

## Fronteiras

| Componente | Evidência ou mecanismo reutilizado | Decisão D.2B.1 |
| --- | --- | --- |
| Ingresso Linux | `CrossUIDIngress`, `PeerAdmission` e `SO_PEERCRED` do [ingresso D2](TRUSTED_SERVICE_INGRESS_D2.md). | `supervised.sock` em diretório de ingresso separado. Serviço com UID não root e um UID desktop distinto e explícito. Diretório `0710` e socket `0620` com ACL nominal exata. |
| Ciclo do listener | `bound_listener` e `Server`, seguindo o [ciclo D3](TRUSTED_SERVICE_LIFECYCLE_D3.md). | A configuração é verificada antes de escutar. O encerramento libera os workers e remove somente o inode do socket criado pela instância. |
| Identidade lógica | Verificadores individuais e manifesto pinado da [D.1C.2](LOOPSHELL_V0_8_D1C2_OPERATIONAL_REGISTRY.md). | `registry/1` e `execution/2` no mesmo ingresso restrito, com a autenticação e os grants de cada domínio. |
| Banco | `DatabasePin`, diretório privado, abertura sem seguir links e checagens antes e durante a transação. | `supervised.sqlite3` com schema D.2B, pin de dispositivo e inode do diretório e arquivo, locks existentes e piso temporal compartilhado. |
| Controle da execução | Grants e trilha D.2B. | O harness concede e revoga grants voláteis por código confiável em processo. Identidade Linux e posse de um ID de tentativa não concedem autoridade lógica. |

O serviço verifica o UID admitido do peer a partir do kernel. O cliente
do ensaio compara **PID, UID e GID** retornados por `SO_PEERCRED` com a
identidade fornecida pela sessão administrativa que iniciou o broker.
O cliente de referência mantém a comparação same-UID por padrão. Os
três argumentos `--service-pid`, `--service-uid` e `--service-gid` ativam
uma comparação explícita com a mesma fonte do kernel. Uma divergência
encerra a conexão antes de solicitar credenciais. O perfil operacional
rejeita ingresso same-UID. Uma falha de configuração encerra a partida.

O modelo considera um cliente de desktop autenticado ou anônimo e
capaz de usar o sistema de arquivos do desktop. A proteção de recursos
privados depende da identidade de serviço separada. Root, kernel,
código sob o UID de serviço e o supervisor administrativo fazem parte
da base confiável da fixture. O ensaio usa sentinelas privadas para testar
travessia, leitura e acesso a descritores. O leitor do driver recusa
dados auxiliares e fecha qualquer descritor recebido. As evidências
sobre isolamento de recursos gráficos reais permanecem NOT RUN.
A [matriz D5](TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5)
segue PARTIAL. [M1.3B](../ROADMAP.md#m13b--trusted-input--enforcement-feasibility)
continua independente.

## Política e reabertura

A inicialização explícita usa criação exclusiva em diretório privado
`0700`, arquivo `0600` e pin original. Na reabertura o supervisor
apresenta esse pin. Banco ausente, substituído, com modos inválidos
ou com schema histórico é recusado. O pin protege a identidade do
arquivo e diretório, com confiança no dispositivo e no sistema de
arquivos. Registry e Execution passam pela mesma verificação do
armazenamento ao abrir a conexão e antes do commit. Execution repete
a verificação após preparar o commit e antes de entrar na região
de confirmação ambígua. A ordem dos locks e as verificações de
autoridade e do piso temporal continuam válidas. Uma falha nesse
ponto retorna `storage_unavailable`, aborta a transação e impede
recibo ou efeito decorrente de autorização ainda não confirmada.
Na recuperação, a mesma falha antecede a publicação do listener.

O check é pontual. Uma troca por root ou por código confiável entre
a revalidação e o commit, sobrescrita no mesmo inode e rollback
integral da VM ficam fora da garantia. A troca reproduzida na revisão
foi feita pelo harness sob o UID dono da fixture. A capacidade de
um desktop separado substituir o banco privado continua NOT RUN.

O manifesto `policy.json` contém verificadores individuais e grants
de **entrega** do Registry. A implementação reutiliza a validação de
`PolicyPin`, a proteção do manifesto `0600` e o controle confiável em
processo. O driver fixa a geração 1 à configuração sintética derivada
da semente descartável e do run ID. Bearers e semente ficam em memória.
Os grants de execução e supervisão continuam voláteis. Na reabertura,
o driver tenta auditoria e passo antes de reemitir qualquer grant.
O comando administrativo `reissue` reemite auditoria e permissão para
reconciliar um recibo histórico de passo. A trilha confirma progresso,
resultado, motivos de expiração e recuperação de despacho pendente.

Os perfis históricos Registry operacional, `execution/1` e
`execution/2` local conservam as versões e schemas. O novo perfil usa
o schema D.2B e recusa abertura de bancos incompatíveis. O módulo de
supervisão operacional recebe apenas configuração explícita de
ingresso, manifesto e banco. O driver liga o harness em processo para
os casos de qualificação.

## Controle do ensaio

O modo `plan` é somente leitura. Os modos `broker` e `desktop` exigem
aprovação de root em uma raiz exclusiva de `/run`. A aprovação vincula
perfil, run ID, boot, hostname, machine ID, pares UID/GID e janela.
Os papéis validam IDs reais e efetivos, grupos, privilégios, ambiente
gráfico e inventário de descritores. A janela real usa prazos absolutos UTC e monotônico do
boot aprovado, inclusive ao trocar a instância do broker. No driver, ela limita o ingresso, a computação, os commits
e a espera pelo controle. A perda do pipe ou o vencimento da janela
encerra o broker.

O passo `arm` resolve, no SQLite confiável, as tentativas pausadas do
emissor previstas no ensaio. Os grants novos fixam o escopo e os IDs
resolvidos pelo serviço. O pipe só aceita liberações por caso, em ordem
fixa. Cada liberação espera a barreira do worker correspondente.
O cliente usa apenas RPCs existentes para ler progresso ou pedir
controle. O harness conta cada chamada ao cálculo em memória,
inclusive quando não encontra uma tentativa armada. Essa contagem
cobre a instância de recuperação antes de qualquer `arm`. Timeout,
perda do pipe ou contagem faltante deixam a prova PARTIAL. Admissões
duplicadas ou despachos indevidos efetivamente observados resultam
em NO-GO. Ao encerrar o broker com despacho pendente, o
harness descarta o retorno dessa chamada antes de confirmar uma
conclusão. A instância seguinte registra `uncertain`.

O relógio sintético de teste avança apenas por comandos fixos do
harness. Ele produz a expiração de `continue` e a expiração da tentativa
com ordenação determinística. Os prazos da aprovação do operador são
medidos separadamente com os relógios reais. A prova não depende de
alteração do relógio da VM. Os JSON de evidência contêm resultados
fixos, contadores, revisões, referências opacas do ensaio e o hash
das trilhas confirmadas. O runbook define a separação dos canais,
a prova real de kernel e os critérios de parada.

O mesmo harness conhece as credenciais sintéticas que usa para
representar cada principal. A prova verifica a separação lógica por
credencial apresentada. Ela não qualifica custódia independente de
credenciais entre processos do mesmo usuário do desktop.
