# LoopEnvironment — Product Definition

**Version:** 0.1
**Status:** Accepted product intent, not an implemented or security-validated system.
**Scope:** The LoopEnvironment operating system and its native LoopBridge subsystem. External clients are unnamed and vendor-independent.

This definition complements accepted ADRs 0001–0007. It records product goals, not selections of Linux base, compositor, RPC protocol, language, image format or implementation.

## 1. Purpose

LoopEnvironment is an independent, complete, open-source Linux operating system designed primarily for AI agents, while remaining operable by humans. It must support normal Linux applications and user-developed programs, subject to actual platform and Linux security constraints. It can run on physical hardware or in a virtual machine, with a visible desktop or an active graphical session that has no viewer.

LoopBridge is an integral OS subsystem for authorized, provider-neutral observation and interaction. It does not contain an LLM, require a particular client or vendor, or replace the kernel or compositor.

## 2. Accepted product principles

- **Full Linux functionality:** Do not impose an intrinsic closed application catalogue, or prohibit ordinary user-developed applications. Applications retain normal Linux behavior and permissions.
- **Agents as native operators:** Prefer structured observation and semantic actions; permit visual observation and pointer/keyboard fallback when necessary.
- **Mandatory interaction mediation:** External AI agents and remote human clients interact with the graphical session only through authorized LoopBridge capabilities. Local physical keyboard and mouse input is also subject to the same OS-defined session control policy.
- **Distributed enforcement:** LoopBridge is the logical policy authority, while trusted compositor, kernel and limited-purpose system services enforce policy at their own boundaries.
- **Honest capability reporting:** Explicitly identify missing, unsupported, ambiguous, stale or redacted observations; do not claim universal visibility or interception.
- **Independent and open:** Core operation requires no proprietary orchestrator, model, account, cloud service, or hypervisor.

## 3. What mandatory input mediation means

The session input policy covers external keyboard/pointer commands, semantic UI actions, focus/window control, remote human control, and local physical keyboard/mouse events directed at the graphical session. Protected OS operations require their own explicit authorization and enforcement.

LoopBridge defines identities, grants, input ownership, revocation and policy. **A trusted compositor/input component may enforce these rules locally**, without making a synchronous Bridge RPC for every mouse movement or key press. No external agent may bypass the authorized interface using raw graphical sockets, accessibility buses, capture/input devices or inherited descriptors.

This requirement is not a claim that the Bridge observes or vetoes all internal syscalls, process computations, network packets, filesystem writes or firmware behavior. Applications can perform indirect operations using their own Linux privileges. Those operations need independent OS-level restrictions if policy must control them.

An administrator must have a documented trusted recovery path. Bridge failure must not silently grant external agents direct session control. The exact local fallback, recovery and fail-closed behavior remains to be designed and tested.

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

**Control:** identities, session scoping, permissions, lease ownership, preemption, invalidation, error categories, diagnostics, security audit and cancellation boundaries.

**Interaction:** keyboard/pointer input, semantic actions, focus, window operations, application launch, and narrowly authorized system operations through adapters.

**Observation:** sessions, outputs, windows, applications, processes, accessible components, approved pixels, and bounded events and resource state.

A single controller per graphical session, with multiple separately authorized observers, is the initial control model. Human takeover must revoke agent control and prevent queued, held or stale input from reaching a new target.

## 6. Structured semantic UI

Clients should be able to request a **machine-readable representation** of the observed session. JSON is a possible textual presentation, not a decision on wire protocol.

The model may contain session/display/window/element handles; application identity; workspace, focus, bounds and scale; element role, name, state, actions and optional geometry; timestamps, revisions and provenance; and explicit unsupported/ambiguous/redacted states.

A compositor window does not necessarily map one-to-one to an accessibility tree. Do not invent a match or permit mutation of an ambiguous target. References must expire on relevant lifecycle/revision changes. Prefer targeted, bounded queries, snapshots and incremental updates with loss detection over exporting entire large trees continually.

The initial schema, APIs, event delivery and error definitions must be refined after feasibility tests.

## 7. API scope

Early **core capabilities** should cover discovery of sessions and windows, inspectable UI elements, semantic actions, keyboard/pointer/focus control, input ownership, events and diagnostics, application discovery/launch, and separately authorized capture and narrow OS operations.

**Optional application adapters** may later provide document, spreadsheet, email, browser or other specialized operations. They must remain provider-neutral, separately permissioned and nonessential to running ordinary Linux applications. No app-specific adapter is guaranteed to exist for arbitrary software.

## 8. Human use and devices

Humans may use the desktop normally. Remote human control must be authorized through the same LoopBridge session authority as external agents, with different identity and grants. Physical keyboard/mouse events are handled by trusted local input components under the same arbitration policy.

Initially, only keyboard and mouse are required as **interactive human input** classes. This does not prohibit graphics, network, storage or other hardware needed by the OS. Future peripheral support requires explicit qualification.

A headless graphical session remains active without a monitor or viewer. Remote view-only is separate from interactive remote takeover, and neither is proof of the other.

## 9. Protected credentials and administrative operations

Do not expose a generic agent API to retrieve raw passwords, reusable tokens or private keys. Where technically possible, protected services should perform authorized authentication without returning secrets to the calling client.

This is not a promise that arbitrary websites, browser extensions, app-level debug tools or already-authenticated sessions cannot reveal data or cause external effects. Sensitive data and application-specific sign-in methods need independent threat modeling, authorization and evidence.

Privileged operations must use narrowly scoped services with OS-enforced authority; an unrestricted root Bridge or transparent privileged fallback is out of scope.

## 10. Future efficiency

Without an observing human, avoid unnecessary continuous capture, video encoding and transmission. The desktop may still render and consume CPU/GPU. Viewer-aware composition, refresh-rate and resource optimizations are deferred until compatibility and functional correctness can be measured.

## 11. Deliberate non-goals and experiments

Do not initially build a new kernel, hypervisor, browser, office suite, AI model, compositor fork or full distribution image. Do not claim universal GUI introspection or universal event veto.

M1.1 remains a bounded semantic proof on an existing Linux session: correlate a real window and its accessibility elements, invoke an action, verify its result and reject stale handles. Subsequent independent experiments must qualify compositor-mediated input arbitration, physical and remote control, agent isolation, failure/recovery, visual fallback, credential boundaries, compatibility and performance.

Build the first LoopEnvironment image **only after** the distinguishing interactions and security boundaries have reproducible evidence. See [Architecture](ARCHITECTURE.md), [LoopBridge](LOOPBRIDGE.md), [Interaction model](INTERACTION_MODEL.md), [Roadmap](ROADMAP.md), and [ADR 0007](DECISIONS/0007-unified-input-mediation.md).

---

**Product principle:** A complete Linux computer with a native, enforceable, semantically rich, vendor-independent interaction authority designed for agents and available to authorized human users.
