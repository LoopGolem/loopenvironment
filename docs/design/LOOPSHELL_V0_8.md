# LoopShell V0.8 — workspace, command console and session supervision

**Status:** approved architectural intent. The experimental V0.8-A layout has a [PARTIAL lab result](../labs/LOOPSHELL_V0_8_A_LAYOUT.md). The read-only console has bounded GO results in [preview (B.1)](../labs/LOOPSHELL_V0_8_B1_CONSOLE.md) and in the [anchored layout (B.2)](../labs/LOOPSHELL_V0_8_B2_ANCHORED_CONSOLE.md). [Visual (C.1)](../labs/LOOPSHELL_V0_8_C1_VISUAL_VIEWS.md), [Activity (C.2)](../labs/LOOPSHELL_V0_8_C2_ACTIVITY_VIEWS.md) and [Combined (C.3)](../labs/LOOPSHELL_V0_8_C3_COMBINED_VIEWS.md) have bounded functional GO results. Sustained performance, host isolation and human usability remain PARTIAL in C.3.

**Date:** 2026-11-23.  
**Scope:** LoopEnvironment components on existing Linux, with no dependency on any particular AI provider, orchestrator, hypervisor, guest-image manager or external product.

This design refines [ADR 0011](../DECISIONS/0011-session-presentation-and-operator-shell.md) and preserves [ADR 0008](../DECISIONS/0008-operator-neutral-authority.md), [ADR 0007](../DECISIONS/0007-unified-input-mediation.md) and [ADR 0012](../DECISIONS/0012-trusted-service-identity-boundary.md). See [ADR 0013](../DECISIONS/0013-loopshell-layout-and-mission-boundaries.md), [operator model](../OPERATOR_MODEL.md), [architecture](../ARCHITECTURE.md) and [roadmap](../ROADMAP.md).

## Architectural contract

**Operator neutrality:** LoopEnvironment authenticates principals and authorizes their explicitly delegated capabilities, target scopes, leases and revocation. A principal may be controlled by a person, AI, automation or other software, locally or remotely. Source of input (API, virtual or physical keyboard, Shell) is not evidence of identity or owner privilege. Secure unattended and interactive enrollment retain equivalent owner/delegation semantics. "Human" and "agent" describe usage, never security classes. This requirement **already exists** in ADR 0008; V0.8 does not rediscover or supersede it.

**LoopBridge:** the trusted control/authorization/mediation service; enforcement is distributed across trusted compositor/input, Linux and narrow adapters. It owns identity, permissions, operations, audit and session arbitration. It is **not** the graphical shell, a model runtime or a general-purpose root daemon. The Bridge cannot intercept arbitrary Linux syscalls.

**LoopShell:** a **separate unprivileged client** offering navigation, a terminal-*like* structured command console, and session views. It may reuse schemas/parsers, but neither embeds LoopBridge's privileged implementation nor gains authority from display position. It should restart independently without terminating managed sessions. Direct private Wayland socket/compositor IPC, accessibility bus, input device and privileged process shortcuts for untrusted clients remain forbidden.

**Session Supervisor:** logical session/observer/controller lifecycle and arbitration responsibility under Bridge authority, not necessarily another executable.

**External operators:** can use authenticated Bridge interfaces without running LoopShell, an in-guest agent, a particular model, or an orchestration layer. A graphical interface is not an access-control gateway for API clients.

## Three-region spatial model

1. **Navigation rail:** permanent when expanded, **full available display height**, anchored at **left or right**, adjustable bounded width. Shows permitted sessions, missions, agent registrations, state/alerts and authorized actions. User may change side and width through Shell controls; not freely float it or reduce its height.
2. **Bridge command console:** horizontal surface anchored at **top or bottom of the width remaining after the rail**. Bounded adjustable height. When no workspace windows exist it may expand into all remaining space. Never positioned in the middle or over the rail. Displays the prompt, multiline input, command history, scoped event feed and truthful errors.
3. **Workspace:** all remaining area, managed by Sway for ordinary applications and zero/many session views. Adding/resizing views must not obscure or reflow the anchored rail/console.

**Implementation candidate, not proven decision:** GTK4 with Wayland layer-shell / gtk4-layer-shell and exclusive reserved zones for panels; Sway continues to manage ordinary windows. Test shared corner and exclusive-zone ordering, top/bottom or left/right switching, window creation/focus, scale/resize/multi-output and session restore before selection. Compare a bounded fallback using normal windows plus Sway IPC if layer-shell cannot satisfy invariants. Do not patch the parent compositor to force this layout. On small displays, explicitly compact/collapse the console or rail rather than allow overlap; show how full command access is recovered. Persist layout preferences without conferring additional capabilities.

## Typed Bridge command surface

The console is **not Bash, a PTY into host privileges or unrestricted process execution**. It accepts an explicit, versioned, allowlisted Bridge command grammar mapped to authenticated structured API calls; unsupported commands fail closed. The example shows the proposed command surface. The implemented subset is documented below.

```text
bridge> help
bridge> agents list
bridge> sessions list
bridge> session observe <session-id>
bridge> session activity <session-id>
bridge> session combined <session-id>
bridge> mission create --agent <agent-id>
> Describe the objective in free text...
bridge> mission create --orchestrator <agent-id>
> Delegate a bounded objective...
bridge> mission status <mission-id>
bridge> system status
```

`mission` accepts a free-text objective **delegated to a configured eligible agent**, never executed as a shell statement. If no authorized agent exists, return a clear setup/authorization error; agent onboarding must be possible via independently authorized GUI/API flows. Providers may be local or external without vendor coupling. A mission may target one agent or a configured **orchestrator principal** delegated authority to request bounded subordinate sessions and operations.

A default mission context may explain the environment, contract and expected structured response; operators may replace this **instructional** text. Prompt text cannot override authorization, isolation or validation. A candidate JSON response from an agent is an **untrusted operation proposal**, never a grant: validate schema, operation whitelist, target freshness, caller principal, scoped capabilities, lease, limits, argument types, result and audit. Separate request accepted / dispatched / externally verified effect. LoopEnvironment does **not** implement the planning or multi-agent reasoning algorithm.

### V0.8-B.1 implemented subset

The experimental v1 grammar implements local `help`, `clear` and `exit`,
plus `sessions list` and `session status <id>` over the selected Unix
LoopBridge socket. Credentials are entered through a masked field.
`discover` and `snapshot` enforce their existing grants. The console
projects snapshot identity, phase and revision. The [lab report](../labs/LOOPSHELL_V0_8_B1_CONSOLE.md)
documents the broker mappings, limitations and reproduction.

### V0.8-C.1 Visual view

`session observe <id>` selects a permitted session in the console and
prompts for an observation credential. The GTK view uses the V0.7 reader
on a dedicated socket and validates principal, session, private ID,
epoch and the independent `desktop.stream` grant. A closed or stalled
view removes its image. Reopening is explicit and repeats the validation.
The [lab report](../labs/LOOPSHELL_V0_8_C1_VISUAL_VIEWS.md) records the
tested lifecycle and the remaining gates.

### V0.8-C.2 Activity view

`session activity <id>` opens a regular GTK window. It asks for a scoped
credential and verifies the selected console principal and epoch on a
dedicated RPC connection. `snapshot` establishes the current cursor and
`events` follows it on that connection. The Core broker checks
`desktop.observe`. DesktopBroker checks `session.discover` on `*` on
each request. The view displays sequence, event kind, phase and revision.
The stream starts at the snapshot cursor and keeps up to 64 projected
rows in memory. A gap, epoch change, invalid cursor or transport fault
clears the feed and requires explicit reauthentication and a fresh
snapshot. The active media socket and its grant remain independent.
[C.2 lab report](../labs/LOOPSHELL_V0_8_C2_ACTIVITY_VIEWS.md).

### V0.8-C.3 Combined view

`session combined <id>` places the Visual and Activity panes in one
ordinary GTK window. Video preserves its aspect ratio and gets the
larger region. The Activity feed and the outer viewport can scroll at
compact sizes. The three view-opening commands remain independently
available.

The console pins the session and epoch through `snapshot`. If the
broker denies snapshot permission, an authorized `presentation.describe`
can supply the identity for a media-only selection. One explicit masked
credential starts two authentications with the selected observer or
delegate. The media pane owns its V0.7 connection and any bounded status
query. The Activity pane owns its snapshot, cursor and polling connection.
Each grant controls only its pane. The window cancels both panes and
clears their content after a validated identity or epoch mismatch or a
confirmed session end. EOF alone reports unknown session status. Recovery
requires a new command and credential. Closing the window cancels both
workers and their pending GTK callbacks.
[C.3 lab report](../labs/LOOPSHELL_V0_8_C3_COMBINED_VIEWS.md).

## Separate entities and lifecycles

| Concept | Meaning |
| --- | --- |
| **Mission** | Scoped objective with initiator, status, policy and references to work; one mission may involve several sessions |
| **Agent registration** | Configured executor/adapter; registration alone grants no ambient permission |
| **Execution session** | Independent work context, compositor where applicable, applications/resources, stable identity and lifecycle |
| **Controller / control lease** | Principal allowed to issue bounded interactive operations; initial model: one controller per session |
| **Observer / view** | Separately authorized presentation surface; many observers may watch one session |
| **Activity stream** | Scoped structured events and reported activity with freshness, gaps and provenance, not proof of task success |

A session persists when its visual window closes or no observer exists; some sessions are headless and have no meaningful graphical stream. Session views should support **Visual** (genuine live frames), **Activity** (structured event history), and **Combined** (video plus a compact sanitized activity readout), with Combined preferred when real graphics are available. The activity readout is *not* unrestricted terminal access. Selecting/closing a view does not alter a control lease, terminate the session, or require an actuation-mode change.

Present connected, connecting, stalled frame/heartbeat, unauthorized, revoked, session replaced, disconnected, reconnecting and ended states separately. Never paint stale video as "live" or infer mission success from lack of motion. Reconnection revalidates identity/session/grants. Continuous capture/encoding should be idle absent an authorized viewing or operational need; multiple high-frame-rate streams require measured resource budgets.

**Operator-visible behavior:** External clients may prefer efficient, non-graphical native/semantic actions when unseen, or request observable graphical actuation where supported and authorized. A visible session should preferentially display authentic activity; do not simulate actions for show, claim video exists when it does not, or disrupt work merely to animate it. Observation does not automatically switch execution mode; preference belongs to the operator/client, not to an OS-level classifier of "human vs AI".

## Future session-control handoff (not V0.8-A)

An authorized operator of **any nature** can request to pause/preempt the current controller for a particular session, inspect/correct the environment, and explicitly release/return control. No human-only override; no automatic takeover upon clicking a viewer or moving a physical device. Multiple observers may remain attached; conservative interactive control is exclusive.

Distinguish: (a) stopping **new** operations on the old lease, (b) draining or cancelling **in-flight semantic and conventional input** at their trusted dispatch boundaries, (c) already started tasks/processes/network side effects, which are **not automatically frozen or undone**. Claim handoff only after verified enforcement across the actual input and semantic paths; old controller reacquires a fresh lease and refreshed state to resume. If enforcement cannot confirm the barrier, report pending/failed/unknown and do not grant conflicting interactive control.

A host application's "capture keyboard and mouse for VM" is separate from a **session-level authorized takeover**. Exact host-to-guest principal binding and trusted input delivery remain **deliberately deferred** for the later handoff milestone. This is not permission to bypass LoopBridge; see ADRs 0007/0008. Avoid embedding a speculative solution in V0.8-A.

## Delivery sequence and acceptance

| Package | Deliverable | Gate / explicitly excluded |
| --- | --- | --- |
| **V0.8-A — Layout** | Measured GTK4/Sway rail + top/bottom command-console surfaces, adjustable limits, layout restore, flexible windows and safe restart | No agent runtime, handoff, shell execution or new privileged input |
| **V0.8-B — Bridge Shell** | Authenticated typed command interface, sanitized history/events, explicit permission/errors | No Bash passthrough or security-policy bypass |
| **V0.8-C — Session Views** | Authorized discovery and real Visual/Activity/Combined views with multiple observers, reconnect and resource checks | No implicit controller acquisition |
| **V0.8-D — Agent/Mission Foundation** | Provider-neutral registration, bounded mission dispatch/lifecycle and authorized structured operation proposals | No bundled model or intelligent multi-agent orchestrator |

**V0.8-A lab matrix** (disposable existing Debian/Sway VM):
- Left/right rail retains full display height across bounded resize; top/bottom console occupies *only* remaining width, with bounded height.
- 0/1/multiple normal windows, ordinary tiling, floating, focus and resize do not overlap reserved regions.
- Test switching sides, orientations, resolution/scale changes and at least the supported display configurations; document unsupported cases and a recovery path.
- Restart or crash the Shell without terminating private sessions; reconnect and restore layout with identity/grant checks.
- Ensure Shell has no ambient access to private compositor/input sockets or credentials outside its grants; rejected commands and viewer-only clients remain denied control.
- Record setup, reproducible artifacts, cleanup, measured CPU/memory/latency and exact limitations. A failed invariant is NO-GO for that layout implementation, not a reason to weaken security boundaries.

**Current qualification is not upgraded:** V0.7/V0.7.1 local presentation is demonstrated, but unrestricted same-UID host isolation remains **PARTIAL**. D4.2C has a bounded opt-in **functional** smoke on an offline clone; D5 host security qualification remains open. M1.3B observed late AT-SPI effects after revocation; real conventional/semantic preemption remains unqualified. V0.8-A is a UI/layout experiment, not production security certification.

## Explicit deferrals

The exact layer-shell/toolkit backend, command grammar and wire format, agent registry data model, mission execution contract, visual transport internals, multi-agent scheduling, session preemption enforcement, host/guest input path, optional images and hypervisor integration all require separate measured decisions. Preserve portability to existing Linux and third-party clients.
