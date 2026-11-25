# V0.8-D.2A — Proposta de primeiro executor funcional

**Proposta para revisão.** O objetivo é demonstrar uma execução sintética
real, autorizada e auditável após a entrega de um objetivo pelo Registry.
Na [D.1C.4](../labs/LOOPSHELL_V0_8_D1C4_CROSS_UID_EXECUTION.md), o aceite
registrou o recebimento e sobreviveu ao reinício. A D.2A propõe um ciclo de
execução separado, que referencia o objetivo aceito e sua revisão.

## Fluxo mínimo

1. O executor se autentica com credencial individual, confirma o vínculo ao
   principal lógico e recebe e aceita uma oferta pelo Registry. O UID
   serve à admissão do transporte local. Credenciais e grants do principal
   determinam a autoridade, independentemente de quem o opera.
   [Contrato do Registry](LOOPSHELL_V0_8_D1C2_OPERATIONAL_REGISTRY.md) ·
   [ADR 0008](../DECISIONS/0008-operator-neutral-authority.md).
2. Um principal com grant explícito de autorização solicita ao LoopBridge
   a execução da operação tipada, com escopo exato de executor, objetivo e
   revisão. O LoopBridge verifica também o grant de execução do principal
   vinculado ao executor. A autorização explícita do LoopBridge vale para
   uma tentativa, com prazo limitado pela validade da autoridade e pelo
   prazo do objetivo. Os grants do Registry cobrem apenas o seu próprio
   ciclo de entrega.
3. A única operação candidata soma em memória duas constantes fixas (`2 + 3`)
   e devolve o inteiro `5`. O seletor da operação é um campo tipado da
   solicitação separada de execução. O texto do objetivo permanece dado
   inerte no Registry, mesmo quando contém algo que se parece com um comando.
   A operação tem como único efeito observável o resultado auditado. O
   perfil exclui shell, navegador, comandos derivados do texto, rede,
   acesso a workspace, mídia, interfaces de sessão e entrada gráfica.
4. O LoopBridge revalida identidade, vínculo, autorização e prazo no ponto
   de início, registra esse início e só então libera a operação sintética.
   O registro de execução identifica a tentativa, o objetivo e sua revisão,
   o executor, o principal que autorizou, o principal vinculado, a operação
   e os instantes e estados de início e desfecho. O LoopBridge registra
   resultado verificado ou falha sanitizada. Credenciais e texto do
   objetivo ficam fora da auditoria, cuja leitura exige grant próprio.

## Encerramento e repetição

Cancelamento por principal com grant específico, revogação da autoridade
ou do vínculo e expiração impedem o início quando entram em vigor antes
dele. Se uma dessas condições vencer a disputa durante a tentativa, ela
impede a publicação de sucesso e gera um desfecho auditável com o motivo.
O LoopBridge revalida a autorização antes de publicar o resultado e
ordena essa publicação com os encerramentos concorrentes. Um desfecho já
registrado permanece no histórico.

Uma repetição da mesma solicitação reconcilia a tentativa existente sob
autorização vigente. Se houver interrupção após o início, o estado
recuperado deve permitir identificar a tentativa e registrar a falha ou
o desfecho incerto. A retomada de execução exige nova autorização. O
protocolo e a persistência da auditoria, incluindo a atomicidade entre
estado e evento, ficam para revisão antes da implementação.

O experimento se restringe ao Registry e à operação em memória. Operações
com recursos privados reais e preempção de entrada ou semântica continuam
sujeitas à [matriz D5](TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5)
e ao [gate M1.3B](../ROADMAP.md#m13b--trusted-input--enforcement-feasibility).

## Critérios de qualificação

| Resultado | Critérios |
| --- | --- |
| **GO** | Executor vinculado recebe e aceita a oferta. O aceite isolado e pedidos com identidade inválida, vínculo incorreto, grant ausente, alvo fora do escopo ou operação desconhecida são incapazes de iniciar trabalho. Uma autorização explícita produz uma única tentativa, resultado verificável `5` e trilha auditável. Uma falha induzida gera registro sanitizado. Cancelamento, revogação e expiração são exercitados antes do início e antes da publicação, com desfecho coerente e sem sucesso tardio. Repetição e interrupção são reconciliadas sem nova execução. Texto com aparência de comando permanece inerte. |
| **PARTIAL** | Falta evidência de qualquer critério obrigatório, ou o fluxo autorizado apresenta falha funcional, sem violação de autoridade observada. |
| **NO-GO** | Há início ou publicação de sucesso indevidos, execução derivada do texto, efeito fora da operação aprovada, duplicação da tentativa, aceite de auditoria forjada ou caminho que contorna D5 ou M1.3B. |
