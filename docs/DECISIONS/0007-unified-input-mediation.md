# ADR 0007 — Unified input mediation and distributed enforcement

**Status:** Accepted
**Date:** 2026-11-10

## Context

ADRs [0002](0002-native-loopbridge.md), [0004](0004-desktop-and-human-observation.md), and [0006](0006-mandatory-agent-mediation.md) establish a native, provider-neutral Bridge, human observation, and mandatory mediation for external agents. The product additionally requires a common authority over remote human input and the physical keyboard/mouse input of a controlled graphical session, without replacing the Linux kernel or requiring a single all-powerful daemon.

## Decision

- LoopBridge defines client identities, capabilities, ownership, revocation and session input policy.
- External AI agents and remote human controllers use the authorized LoopBridge contract to operate the graphical session.
- Local physical keyboard and mouse input is subject to the same session-level policy, enforced by trusted compositor/input integration.
- Low-level input delivery may enforce cached policy locally rather than invoke a Bridge RPC for every event.
- The kernel and narrowly privileged services retain their own enforcement authority. This is not a universal interception or veto of all internal application/kernel activity.
- Normal Linux applications and user-written programs remain supported, without a mandatory closed application catalogue.
- Trusted administration and recovery must not expose an alternate, unmediated path for agents.

## Consequences

Compositor selection must demonstrate input policy enforcement, not only window discovery. External access must fail closed if mediation or isolation is unavailable. Physical/remote control, in-flight input cancellation, trusted recovery, and app-level indirect side effects all require explicit tests. Bridge must not become an unrestricted root daemon.

## Open questions

Compositor and integration strategy, physical-seat enforcement, recovery design, local input policy distribution, privilege separation, API schema, and the exact validation matrix remain experimental. See [Product definition](../PRODUCT_DEFINITION.md) and [Roadmap](../ROADMAP.md).
