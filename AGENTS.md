# Instructions for automated contributors

Scope: **LoopEnvironment only** — an open-source environment for existing Linux, centered on LoopBridge, with visual and structured operator interfaces and experimental LoopTeach.

## Current project phase

[ADR 0010](docs/DECISIONS/0010-linux-environment-not-os.md) defines the existing-Linux product scope. [LoopBridge V0.6](docs/LOOPBRIDGE_V0_6.md) adds managed private Sway desktops and a GTK4 viewer using authorized PNG captures. [ADR 0011](docs/DECISIONS/0011-session-presentation-and-operator-shell.md) separates execution, control and presentation. The [roadmap](docs/ROADMAP.md#loopbridge-release-track) starts fluent presentation with local streaming in V0.7 and plans an ordinary graphical Shell in V0.8. Nested presentation remains an open hypothesis.

M1.1–M1.3B.2 remain historical experiments. The unmodified Sway/AT-SPI path has no verified preemption barrier, and M1.3B.2 remains PARTIAL. See the [lab records](docs/labs/) and [Session Authority V1](docs/design/SESSION_AUTHORITY_V1.md).

## Non-negotiable product boundaries

- LoopEnvironment runs on existing Linux on physical or virtual machines.
- LoopBridge is the central service, open and provider-agnostic.
- Real Linux applications, graphical operation and a structured operator interface are core goals.
- Independent private sessions are preferred. Viewing, capture, semantic inspection, control, administration and handoff require separate authorization. Opening a view leaves the active controller and actuation mode unchanged.
- Initial setup establishes a master/responsible owner principal, whether controlled by human, AI or software.
- Agent clients may run outside the guest; authority derives from authentication and grants, not biological labels.
- Owner/delegate takeover requires explicit trusted authorization, not automatic physical pointer motion.
- Native LoopTeach supports app-specific teaching through GTK and a structured CLI (configurable Super+click remains a design target); annotations do not authorize actions.
- Different transports must preserve the same agent-facing conceptual API.
- Deny unauthorized operations; no default remote control or privileged fallback.
- The product does not require a particular proprietary agent, account or cloud service.
- Project-owned code under Apache-2.0; preserve all third-party license obligations.
- Treat saved annotations as untrusted, revisioned semantic data with provenance and ambiguity.

## Before changes

Read README, VISION, PRODUCT_DEFINITION, OPERATOR_MODEL, LOOPTEACH, ARCHITECTURE, LOOPBRIDGE, SECURITY_MODEL, ROADMAP and the ADR index (including ADRs 0008–0011). Distinguish accepted architectural decisions from unresolved technology choices. If a change alters a decision, propose or supersede an ADR.

## Working discipline

- Use **main** as the integration branch. Prefer only one active short-lived feature branch at a time; avoid unnecessary branch proliferation.
- Keep work bounded to one milestone and define a demonstrable result.
- No broad refactors, expensive integration projects or dependency stacks without a verified need.
- Do not perform privileged host/system changes, access external credentials, or expose services publicly without explicit approval.
- State the commands/tests actually executed; don't claim a test passed if it was not run.
- Preserve files and user data, avoid destructive operations and keep external services out of local proofs.
- For documentation changes, validate internal links, consistency, terminology and the distinction between design vs implemented features.

When uncertain, document an open question instead of silently committing the project to a technology.
