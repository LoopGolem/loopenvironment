# ADR 0013 — LoopShell layout and mission/session interface boundaries

**Status:** Accepted architectural direction; implementation and enforcement unqualified.  
**Date:** 2026-11-23

## Context

[ADR 0008](0008-operator-neutral-authority.md) already specifies principal-neutral authority. [ADR 0011](0011-session-presentation-and-operator-shell.md) separates execution, control and presentation, and introduces a graphical observer Shell. After V0.7 live viewing and the partial V0.7.1/D4.2C security work, the project needs a coherent workspace UX for supervised operator activity without importing a particular model, orchestration engine or VM product.

## Decision

1. **Separation of authority and UI.** Name the graphical client **LoopShell**. It is distinct from LoopBridge, remains subject to authenticated principal capabilities, and may restart independently. A terminal-looking widget parses allowlisted Bridge commands; it is not Bash, a privileged shell or the implementation of Bridge policy. Session Supervisor is a logical authority/lifecycle role, not necessarily an extra process.
2. **Layout contract.** A full-height, bounded-width navigation rail is left or right. A height-adjustable Bridge command console is top/bottom over the **remaining** width. Sway manages all other windows in the remaining rectangle. Both panels are repositioned through UI controls rather than freely floating. Evaluate Wayland layer-shell/exclusive zones with GTK4 first as a **prototype candidate**, not a proven toolkit choice; test fallback and restore.
3. **Mission and orchestration boundary.** A typed `mission` command may delegate free-text objectives to an enrolled, explicitly authorized local/remote agent. An optional orchestrator is only an externally provided agent with limited delegated capabilities. Customizable prompt templates cannot modify security policy; agent-produced JSON always requires schema, principal, scope, lease and target validation before action. LoopEnvironment contains no mandatory multi-agent planning algorithm.
4. **Separate lifecycles.** A mission, executor registration, execution session, control lease, observer view and activity stream are distinct. Sessions may run headlessly without observers; many authorized observers may watch one session; one active interactive controller per session is the conservative policy. Views should combine authentic live frames with scoped activity when available, but viewing alone never grants input or switches actuation mode.
5. **Neutral takeover semantics.** Authorized principals may later request a pause/preemption and transfer of a session's controller, without biological classification or host-device priority. Existing work may outlive a lease; verified semantic/conventional dispatch barriers are prerequisites for declaring a handoff complete. How host keyboard/mouse input maps to a guest principal is **deferred** while mandatory mediation under ADRs 0007/0008 remains binding.
6. **Incremental development.** V0.8-A layout, V0.8-B typed Bridge Shell, V0.8-C session views, V0.8-D minimal agent/mission foundation. Do not fold unreconciled D5 or takeover gates into a GUI milestone.

## Consequences

LoopShell is a useful graphical client, not a universal access gateway; independent API consumers must retain supported authorized paths. Visibility is an operator strategy and UX concern, never identity evidence. A GUI prototype cannot claim a production-grade security boundary. V0.7.1 unrestricted-host isolation is PARTIAL; the D5 matrix and trusted input handoff gate remain open. No requirement for a specific provider, Linux image or external product is added.

This ADR refines ADR 0011 and preserves ADRs 0007, 0008, 0010 and 0012.

## Open questions

Layer-shell geometry on Sway, toolkit choice, compact display UX, command grammar and RPC mapping, agent registry and mission lifecycle, stream cost/provenance, accessibility, future trusted host/guest input binding and session preemption.

See [V0.8 design](../design/LOOPSHELL_V0_8.md) and [roadmap](../ROADMAP.md).
