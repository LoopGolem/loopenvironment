# LoopEnvironment — Product Definition

**Version:** 0.2
**Status:** Accepted product intent, not an implemented or security-validated system.
**Scope:** LoopEnvironment OS, native LoopBridge, owner/operator identity model and planned LoopTeach. External controllers are provider-neutral.

This definition incorporates accepted clarifications ADR 0008–0009 while preserving ADRs 0001–0007 as historical records. It records product goals, not selections of Linux base, compositor, RPC protocol, language, image format or implementation.

## 1. Purpose

LoopEnvironment is a complete open-source Linux OS with **dual native operation**: a real graphical environment and a structured machine-readable model of that environment. A principal operating it may be controlled by a person, AI, program or remote service; it need not run an agent inside the OS. Conventional Linux apps and user programs remain supported.

LoopBridge provides authenticated, scoped and vendor-neutral operations. LoopTeach will be a native tool for recording and later retrieving application-specific semantic annotations through LoopBridge. Installation may be physical or virtual, interactive or unattended; the latter can establish an owner without a biological-human operator.

## 2. Accepted product principles

- **Normal Linux:** do not enforce a closed application catalog or specific AI provider.
- **Principal-neutral:** security is based on authenticated identity, grants and session scope, never biology or client implementation.
- **Responsible owner:** initial setup creates an ultimate master/responsible owner which may delegate, revoke and administer sessions, whether controlled by a person or AI.
- **Dual views:** visual rendering and permissioned structured observation/action for the same real session, with explicit semantic gaps.
- **Native LoopTeach:** operator-authored app-specific annotations may inform future sessions only when re-identified safely.
- **Mandatory mediation:** untrusted local and external clients must use authorized Bridge capabilities for graphical operation.
- **Distributed OS enforcement:** trusted compositor/input, kernel and narrow services apply policy; no universal syscall interception.
- **Separated capabilities:** observation, capture, teaching, input and administration are not interchangeable.

See [operator model](OPERATOR_MODEL.md), [LoopTeach](LOOPTEACH.md), [ADR 0008](DECISIONS/0008-operator-neutral-authority.md) and [ADR 0009](DECISIONS/0009-native-loopteach.md).

## 3. What mandatory input mediation means

Graphical session policy governs semantic actions, input, focus, observation and control transfer. A trusted compositor may enforce input using locally cached policy; no synchronous Bridge call per physical event is required.

The OS must block untrusted clients from bypassing authorized Bridge operations through compositor IPC, Wayland/X11, accessibility/session buses, input devices or inherited descriptors. Local clients may be isolated by OS mechanisms; remote clients do not need to be processes inside the OS.

The owner or delegated principal may explicitly request takeover. **No physical keyboard event or claim of being human confers owner privileges**. All takeover paths need authenticated principal binding and tested enforcement against in-flight and stale actions.

Bridge does not inspect every Linux syscall. Kernel/services enforce access to files, network and devices. A deliberate or compromised ultimate owner may change the system's administrative policy; non-owner processes must not inherit that authority automatically.

## 4. Authority model

| Component | Responsibility |
| --- | --- |
| LoopBridge control plane | Identity, client authentication, authorization, control leases, arbitration, revocation, command validation, audit |
| Trusted compositor and input integration | Apply session input/focus policy, process approved physical and synthetic input, expose windows and displays |
| Linux kernel and security facilities | Enforce process, file, device, memory and IPC boundaries; isolate external agents from protected session resources |
| Narrowly scoped trusted services | Carry out particular authorized privileged operations without making LoopBridge an unrestricted root daemon |
| Applications and semantic adapters | Run normal Linux functionality and expose the accessible/application data they actually support |

These are **logical responsibilities**, not a mandate for a particular number of processes. Sway/wlroots, AT-SPI, D-Bus, gRPC, Debian and other technologies are candidates, not approved implementation dependencies.

## 5. LoopBridge responsibility planes

**Authority:** initial owner binding, principals, delegation, grants, sessions, leases, revocation and audit.

**Interaction:** permitted semantic actions, conventional input, focus, window management and narrowly authorized OS operations.

**Observation:** session/window/element state, available actions, events and separately authorized pixels.

**Teaching:** LoopTeach manages separately permissioned annotations; Bridge may resolve them against live elements with explicit provenance and confidence. Annotation never grants input rights.

Initial conservative model: one active input controller per session, multiple separately authorized observers. Takeover belongs to an owner/delegated principal, not a biological-human role. The enforcement boundary must coordinate pending input and semantic actions before confirming handoff; that guarantee remains unvalidated.

## 6. Structured semantic UI

Every graphical session should expose its **observable** structure and state through a permissioned machine-readable representation; JSON is an illustrative presentation, not a protocol decision. Include session/window/element identities, app/version/context, roles, states, actions, geometry, freshness, provenance and explicit unsupported/ambiguous/redacted values.

A compositor's window may not map unambiguously to an accessibility tree; refuse actions if correlation is unsafe. Live references expire when their target or context changes. Prefer bounded queries/snapshots/events with gap detection.

Distinguish native accessible data, trusted application integrations, operator-provided LoopTeach descriptions, tested bundled app profiles and visual inference. Saved profiles are **not live target handles**: re-identify on each launch, reject ambiguity and never treat annotations as authorization. See [LoopTeach](LOOPTEACH.md).

## 7. API scope

Core capabilities cover principal/session discovery, observation, accessible elements, semantic and conventional input, leases/ownership, events, diagnostics, permitted frames and narrow system operations. Transport and JSON/RPC details remain open.

Native LoopTeach will support authorized element selection (preferably configurable Super+click), annotation, profile storage and future Bridge lookup. Annotation read, edit, approval and sharing are separately authorized. Application-specific richer adapters remain optional, and ordinary apps still work without profiles.

## 8. Human use and devices

The desktop remains usable by people, but **a human is not an authorization class**. Physical keyboard and mouse are input sources, not proof of principal authority; trusted local binding to a session/principal is required. Authenticated owner/delegates can explicitly assume control according to policy; ordinary operators cannot arbitrarily preempt each other.

Independent sessions are the preferred default product direction, with shared-session operation/viewing where authorized. A remote owner may be human or automated. Remote viewing and interactive control remain separate permissions. Headless operation and hardware compatibility require qualification.

## 9. Protected credentials and administrative operations

Do not expose a generic agent API to retrieve raw passwords, reusable tokens or private keys. Where technically possible, protected services should perform authorized authentication without returning secrets to the calling client.

This is not a promise that arbitrary websites, browser extensions, app-level debug tools or already-authenticated sessions cannot reveal data or cause external effects. Sensitive data and application-specific sign-in methods need independent threat modeling, authorization and evidence.

Privileged operations must use narrowly scoped services with OS-enforced authority; an unrestricted root Bridge or transparent privileged fallback is out of scope.

## 10. Future efficiency

Without an observing human, avoid unnecessary continuous capture, video encoding and transmission. The desktop may still render and consume CPU/GPU. Viewer-aware composition, refresh-rate and resource optimizations are deferred until compatibility and functional correctness can be measured.

## 11. Deliberate non-goals and experiments

Do not initially build a new kernel, hypervisor, bespoke browser, office suite or full distribution. No decision mandates a compositor fork, universal GUI introspection, perfect annotation matching or classification of all syscalls.

M1.1 and M1.2 have bounded GO evidence, not shipping OS guarantees. The M1.3 preflight reported NO-GO for its attempted input preemption path; it remains local/unmerged and must be reconciled with the clarified operator-neutral authority model before more testing. LoopTeach is a native future product capability, not an implemented M1 feature.

A custom image follows reproducible evidence of the security and interaction properties; see [architecture](ARCHITECTURE.md), [operator model](OPERATOR_MODEL.md), [LoopTeach](LOOPTEACH.md) and [roadmap](ROADMAP.md).
