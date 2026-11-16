# Instructions for automated contributors

Scope: **LoopEnvironment only** — an independent open-source Linux OS with visual and structured operator interfaces, native LoopBridge and planned LoopTeach.

## Current project phase

M0/M0.5 research and bounded M1.1/M1.2 experiments are recorded (see docs/labs/); neither proves a deployed OS or Bridge. The M1.3 local preflight reported NO-GO for the investigated input/preemption path, and remains unmerged. Re-scope M1.3 against ADR 0008 before further tests. No bootable image, selected compositor, stable API or implemented LoopTeach exists; do not claim otherwise.

## Non-negotiable product boundaries

- LoopEnvironment must be usable independently on physical or virtual machines.
- LoopBridge is part of the OS, open and provider-agnostic.
- Real Linux applications, graphical operation and a structured operator interface are core goals.
- Initial setup establishes a master/responsible owner principal, whether controlled by human, AI or software.
- Agent clients may run outside the guest; authority derives from authentication and grants, not biological labels.
- Owner/delegate takeover requires explicit trusted authorization, not automatic physical pointer motion.
- Native LoopTeach is a planned app-specific teaching tool (preferred configurable Super+click); annotations do not authorize actions.
- Different transports must preserve the same agent-facing conceptual API.
- Deny unauthorized operations; no default remote control or privileged fallback.
- The product does not require a particular proprietary agent, account or cloud service.
- Project-owned code under Apache-2.0; preserve all third-party license obligations.
- Treat saved annotations as untrusted, revisioned semantic data with provenance and ambiguity.

## Before changes

Read README, VISION, PRODUCT_DEFINITION, OPERATOR_MODEL, LOOPTEACH, ARCHITECTURE, LOOPBRIDGE, SECURITY_MODEL, ROADMAP and the ADR index (including ADRs 0008–0009). Distinguish accepted architectural decisions from unresolved technology choices. If a change alters a decision, propose or supersede an ADR.

## Working discipline

- Use **main** as the integration branch. Prefer only one active short-lived feature branch at a time; avoid unnecessary branch proliferation.
- Keep work bounded to one milestone and define a demonstrable result.
- No broad refactors, expensive integration projects or dependency stacks without a verified need.
- Do not perform privileged host/system changes, access external credentials, or expose services publicly without explicit approval.
- State the commands/tests actually executed; don't claim a test passed if it was not run.
- Preserve files and user data, avoid destructive operations and keep external services out of local proofs.
- For documentation changes, validate internal links, consistency, terminology and the distinction between design vs implemented features.

When uncertain, document an open question instead of silently committing the project to a technology.
