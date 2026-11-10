# Instructions for automated contributors

Scope: **LoopEnvironment only** — an independent open-source Linux-based operating system with its native agent interface, LoopBridge.

## Current project phase

Documentation-first M0. No buildable OS, distribution image, selected compositor, stable API or deployed bridge exists. Do not invent completed functionality or add placeholder implementation solely to suggest progress.

## Non-negotiable product boundaries

- LoopEnvironment must be usable independently on physical or virtual machines.
- LoopBridge is part of the OS, open and provider-agnostic.
- Existing Linux applications and optional human observation/control are core goals.
- Different transports must preserve the same agent-facing conceptual API.
- Deny unauthorized operations; no default remote control or privileged fallback.
- The product does not require a particular proprietary agent, account or cloud service.
- Project-owned code under Apache-2.0; preserve all third-party license obligations.

## Before changes

Read README, VISION, ARCHITECTURE, LOOPBRIDGE, SECURITY_MODEL, ROADMAP and the ADR index. Distinguish accepted architectural decisions from unresolved technology choices. If a change alters a decision, propose or supersede an ADR.

## Working discipline

- Use **main** as the integration branch. Prefer only one active short-lived feature branch at a time; avoid unnecessary branch proliferation.
- Keep work bounded to one milestone and define a demonstrable result.
- No broad refactors, expensive integration projects or dependency stacks without a verified need.
- Do not perform privileged host/system changes, access external credentials, or expose services publicly without explicit approval.
- State the commands/tests actually executed; don't claim a test passed if it was not run.
- Preserve files and user data, avoid destructive operations and keep external services out of local proofs.
- For documentation changes, validate internal links, consistency, terminology and the distinction between design vs implemented features.

When uncertain, document an open question instead of silently committing the project to a technology.
