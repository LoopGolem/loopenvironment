# ADR 0011 — Independent Session Presentation and Operator Supervision

**Status:** Accepted — architectural direction

**Date:** 2026-11-20

## Context

LoopEnvironment runs on existing Linux and uses LoopBridge as the central service for authority and operation. [LoopBridge V0.6](../LOOPBRIDGE_V0_6.md) demonstrated managed private Sway sessions, separately authorized capture and a GTK4 viewer that displayed one pinned private desktop. Periodic PNG captures established visual delivery in the lab. The product goal is for authorized operators to discover, select and observe sessions with fluidity comparable to an ordinary desktop. That target and its resource costs remain to be measured.

This decision develops the observation direction of [ADR 0004](0004-desktop-and-human-observation.md) under the mediation, principal-neutral authority and existing-Linux requirements of [ADRs 0006](0006-mandatory-agent-mediation.md), [0007](0007-unified-input-mediation.md), [0008](0008-operator-neutral-authority.md) and [0010](0010-linux-environment-not-os.md).

## Decision

### D1 — Independent graphical sessions

Prefer private, independently controllable sessions for graphical applications. Session boundaries are independent of agent and operator identities. One operator may access several sessions with the corresponding grants, and one session may be available to several operators. A single shared compositor is outside the preferred execution architecture.

### D2 — Execution, control and presentation

The **execution plane** runs sessions, private compositors, applications and workspaces. The **LoopBridge control plane** governs identities, grants, leases, operations, events and audit. The **presentation plane** provides authorized access to visual streams and presents them locally or remotely. These are logical responsibilities that implementations can distribute across processes or services as needed.

### D3 — Low-latency graphical streaming (Alternative A)

Use low-latency graphical streaming for the first live presentation implementation, starting with local delivery in V0.7. Streaming can use local IPC and can also support delivery between machines through an explicitly authorized remote transport. TCP/IP and an external network are optional. Codec, protocol and media stack selection require experiments. WayVNC, PipeWire and other appropriate capture or transport mechanisms are candidates for evaluation.

### D4 — Nested Wayland presentation (Alternative B)

Keep nested Wayland presentation as a future hypothesis for local use. A private compositor could present its output inside another compositor's graphical environment. This path is technically plausible and remains unqualified under the LoopEnvironment isolation model.

Study access to the host compositor, Wayland socket protection, process and device isolation, input mediation, compatibility with private sessions, presentation of multiple sessions, composition and memory costs, and effects on session authority. Keep the main Wayland socket out of reach of untrusted clients and processes. Any performance advantage requires measurement. Nesting presents output locally. Cross-machine presentation still calls for a streaming transport.

### D5 — LoopEnvironment Shell

Start the LoopEnvironment Shell as an ordinary Linux graphical application and authorized client of control and presentation services. It should discover permitted sessions, show allowed metadata and state, select a session for observation, display an enlarged view, and show the current controller and authority state when permitted. It should report connection, unavailability and recovery states. Authorized administrative operations and control transfer may follow in later milestones.

The initial Shell can run on an existing desktop without a custom Wayland compositor, full desktop shell, distribution or login manager. Evolving it into a compositor requires a separate decision and justification.

### D6 — Operator-neutral authority

Preserve [ADR 0008](0008-operator-neutral-authority.md). An operator is an authenticated principal that may be controlled by a person, AI, service or other software. Grants determine authority. The Shell holds only the authority granted to its authenticated principal.

### D7 — Observation and control

A session may have multiple authorized observers and, under the initial policy, one active controller. Authorize live viewing, on-demand capture, semantic inspection, control, administration and control transfer separately. Selecting or opening a view leaves control authority unchanged. An effective handoff requires explicit authorization, revocation and a verified barrier across conventional and semantic dispatch. That barrier remains unqualified.

### D8 — Observation and actuation mode

Observer connections leave actuation mode unchanged. Prefer efficient native and semantic actions where appropriate. A future observable mode may use pointer movement, keyboard input, scrolling and progressive typing to make actions visually comprehensible where technically viable and authorized. The mode describes behavior and conveys no information about the operator's identity.

### D9 — Headless operation and resource use

Private sessions continue running without observers or a physical display. Keep continuous capture, encoding and transmission idle unless an authorized observer or an authorized operational need calls for them. Thumbnails, live views and on-demand capture may follow separate policies. Measure resource consumption and qualify limits experimentally.

## Consequences

The three planes can evolve independently. The visual transport model should accommodate new transports and presentation backends. Changing a running session's backend may be unsupported. In particular, moving between headless and nested operation may require recreating the session. Live switching remains unqualified.

The [architecture](../ARCHITECTURE.md) describes the boundaries, and the [roadmap](../ROADMAP.md#loopbridge-release-track) sequences the implementation and qualification work.

## Open questions

- Minimal media contract and authorization boundaries for stream setup, delivery and revocation.
- Local and remote transports, update rate and latency targets, GPU and software rendering compatibility.
- Redaction and protection of sensitive content in frames and buffers.
- Concurrent observers, reconnect and recovery, authorized discovery and session lifecycle.
- Shell toolkit and integration.
- Feasibility and security of nested presentation, including socket and input boundaries.
- Authorized remote interactive control and its enforcement.
- Isolation strategies and CPU, memory and other resource limits.
