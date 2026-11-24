# V0.8-D.1 — Proposta de registro e delegação de objetivos

**Proposta para revisão.** O primeiro experimento registra um executor já
associado a um principal e entrega um objetivo a um cliente autenticado
que decide aceitá-lo ou recusá-lo. O resultado demonstrável é o estado
dessa entrega e sua autoria.

## Contratos de partida

O principal autenticado é o sujeito das permissões. Humano, agente e
serviço descrevem quem opera o cliente. O owner possui autoridade
administrativa explicitamente provisionada. Os grants atuais vinculam
um principal, uma capacidade, um alvo, uma sessão e uma expiração.
O broker também mantém epoch de sessão e geração da lease. A prova local
usa papéis de laboratório com credenciais distintas. Um registro de
executor precisa referenciar uma identidade com ciclo de vida próprio.
[Modelo de operador](../OPERATOR_MODEL.md) ·
[ADR 0008](../DECISIONS/0008-operator-neutral-authority.md).

## Experimento mínimo

1. Um administrador autenticado registra um ID opaco de executor, um
   nome de apresentação e o vínculo com um principal. O executor
   confirma o vínculo com sua própria credencial. O registro guarda
   o estado e a revisão usados para validar novas entregas.
2. Um emissor com escopo explícito para aquele executor deposita um
   objetivo textual limitado, com ID, revisionamento, autoria e
   expiração. O conteúdo é tratado como dado inerte. A primeira prova
   pode usar um objetivo sem sessão associada.
3. Um cliente de laboratório autenticado consulta seus objetivos e pode
   aceitar ou recusar um ID e revisão atuais. O emissor pode retirar
   a oferta. O cliente recebe o resultado dessa transição. Submissões
   repetidas retornam o mesmo resultado sob a mesma autorização.
4. O ensaio verifica recusa de credencial alheia, vínculo pendente,
   revisão antiga, escopo insuficiente, expiração e revogação antes
   da aceitação. A ação observável de aceitar limita-se a registrar o
   aceite. Controle, mídia, workspace e lease seguem as autorizações
   do contrato de sessão.
   [ADR 0011](../DECISIONS/0011-session-presentation-and-operator-shell.md) ·
   [ADR 0013](../DECISIONS/0013-loopshell-layout-and-mission-boundaries.md).

## Decisões para aprovação arquitetural

- Provisionamento, prova de posse, rotação e revogação de credenciais
  individuais. Definir como o vínculo de executor é confirmado e
  suspenso, inclusive para clientes remotos.
- Sujeitos autorizados a registrar, aceitar vínculos, oferecer e retirar
  objetivos. Definir os alvos específicos e a revalidação na transição.
  Os grants atuais de sessão continuam aplicados no seu próprio escopo.
- Revisões e idempotência em disputa entre aceite, retirada e revogação.
  Definir quais registros e metadados podem aparecer no histórico.
- Limites de tamanho, expiração, retenção e armazenamento. Definir
  a projeção de auditoria e o tratamento de objetivos sensíveis antes
  de escolher os endpoints e o formato definitivo.
