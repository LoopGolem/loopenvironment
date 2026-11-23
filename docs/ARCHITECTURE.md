# Environment architecture

**Status:** conceptual Linux environment architecture with bounded prototypes; no stable or production-secure Bridge runtime has been released.

## Boundaries

LoopEnvironment is a set of installable services and integrations for **existing Linux**, centered on LoopBridge. Real sessions and supported resources should be operable through structured, permissioned interfaces. A **principal** may be controlled by a person, AI or script inside or outside the host; no LLM, special kernel or standalone distribution is mandatory.

Secure interactive or unattended provisioning binds an initial owner principal who manages delegates and sessions. LoopBridge provides the native API and governs authority. The experimental LoopTeach GTK and structured workflows supply application-scoped annotations as semantic data. Grants continue to govern actions. See [operator model](OPERATOR_MODEL.md) and [LoopTeach](LOOPTEACH.md).

## Execution, control and presentation planes

| Plane | Responsibility |
| --- | --- |
| **Execution plane** | Run independent private graphical sessions, their compositors, applications and workspaces on existing Linux. Trusted compositor, input and accessibility components enforce their respective session boundaries. |
| **LoopBridge control plane** | Authenticate principals, authorize discovery and operations, govern grants and leases, and report structured state, events and audit records. It governs access to presentation and delegates protected work to narrowly scoped adapters. |
| **Presentation plane** | Deliver and display authorized session output locally or remotely. It enforces the presentation access derived from the control plane and can evolve independently of the structured operation interface. |

These planes describe logical responsibilities. Implementations may colocate them where the trust boundaries allow. The planned **LoopShell** (LoopEnvironment Shell) is an ordinary, **unprivileged graphical client**, not the LoopBridge enforcement service. It uses authorized control-plane services for typed commands, discovery, metadata and authority state, and authorized presentation services for session views. The intended layout has a full-height left/right navigation rail, a top/bottom terminal-like Bridge console over the remaining width, and a Sway-managed workspace. The console accepts allowlisted, structured Bridge commands—not a general OS shell. Mission, session, observer surface and controller lease have separate authority/lifecycle semantics. Privileged compositor IPC, private Wayland sockets and direct capture or input interfaces stay behind trusted boundaries. See [ADR 0011](DECISIONS/0011-session-presentation-and-operator-shell.md), [ADR 0013](DECISIONS/0013-loopshell-layout-and-mission-boundaries.md) and the [V0.8 design](design/LOOPSHELL_V0_8.md).

| Term | Meaning |
| --- | --- |
| Graphical session | An independently managed environment for running graphical applications with its own lifecycle, workspace and authority scope. |
| Compositor | The session component that manages surfaces, composes output and participates in trusted input enforcement. |
| Operator / principal | An authenticated identity acting on a session with scoped grants. A person, AI, service or other software can act behind it. |
| Client | Software that connects on behalf of a principal, such as an MCP host, viewer or the planned Shell. |
| Observer | A principal authorized to view a session. Session control requires separate authority. |
| Controller | A principal holding the active control lease and relevant action grants for the session. |
| Graphical transport | The mechanism that carries visual output to authorized clients, locally or between machines. |
| Presentation backend | The implementation that makes session output available for display, such as a capture and streaming pipeline or a candidate nested compositor path. |

[V0.6](LOOPBRIDGE_V0_6.md) demonstrated private headless Sway sessions and a GTK4 viewer using periodic authorized PNG captures. Low-latency streaming is the initial presentation direction. Nested Wayland presentation remains an unqualified hypothesis for local use. Changing a running session's presentation backend may require recreating it. Prefer structured native actions where reliable, with separately authorized conventional input available as a fallback. Technologies such as Cua Driver remain research candidates.

## Core components

### Linux base and graphical session

- Reuse an existing Linux distribution's boot, kernel, packages and session lifecycle; add only qualified environment services.
- Real graphical session, compatible with conventional Linux applications.
- Run headless without a physical display or observer. Capture, encoding and delivery should be active only for authorized demand or operational needs.
- Preserve trusted local operation/recovery even if the Bridge client endpoint fails, without granting unmediated access to external agents. Exact input-policy failure and recovery behavior requires qualification.
- Treat application rendering, capture, encoding, and video delivery as distinct costs.

### LoopBridge

- Runs in the appropriate user/session security context where possible.
- Discovers and normalizes accessible UI data but does **not** pretend missing semantic metadata exists.
- Brokers authorized input and visual observation through narrowly scoped adapters.
- Owns the public API, event stream, identity, permission and audit interfaces.
- Must never expose arbitrary privileged OS internals directly to clients.

### Adapter boundary

Adapters encapsulate compositor, accessibility bus, portals, and app-specific integrations. They announce supported capabilities and errors. No single adapter is assumed universal. A screenshot/input fallback can work when semantic controls are unavailable, subject to policy.

### Distribution and lifecycle

Installable environment components need documented provenance, upgrade/rollback guidance, software supply-chain tracking and physical/virtual host compatibility. An optional preconfigured VM image may simplify onboarding later, but is not a prerequisite or evidence of better capability.

## Deployment neutrality

Debian in VirtualBox is the current lab. Physical or virtual deployments may use other Linux distributions, hypervisors and input, display or graphics devices, subject to qualification. The client contract remains independent of agent implementation, LLM and provider.

**Physical machine:** a local agent may connect to an authenticated per-user Unix-domain socket. Remote control may be enabled explicitly using authenticated, encrypted transport.

**Virtual guest:** the exact same LoopBridge protocol can be reached through a private virtual network or a guest/host transport with a host-side adapter. The guest does not need to know which VM manager starts it. Localhost forwarding is only a reachability mechanism; it does not provide identity or authorization.

The structured client contract preserves the same semantics across transports. Graphical transport has its own latency, disconnection and media characteristics. Local presentation may use IPC. Remote presentation requires explicit authorization and protected transport.

## Session and control model

- Principals are authenticated subjects, not synonyms for a Linux UID/process, human body or AI model.
- Owner bootstrap occurs once per installation through an interactive or unattended protected flow.
- Session and target identifiers are scoped; live references must be revalidated.
- Independent sessions are preferred. Several principals may access a session according to their grants, with multiple authorized observers and one active controller under the initial policy.
- Live viewing, on-demand capture, semantic inspection, semantic action, conventional input, teaching, process/file access, administration and control transfer have distinct authorization.
- Takeover requires an explicit authenticated owner/delegate request. Physical pointer motion conveys no authority.
- A handoff requires a verified barrier against stale or in-flight operations across conventional and semantic paths. The barrier remains unqualified.
- Untrusted clients cannot directly bypass protected compositor/session interfaces. Bridge cannot itself intercept every syscall.
- Learned application semantics cannot grant new input privileges.

See [operator model](OPERATOR_MODEL.md), [interaction model](INTERACTION_MODEL.md) and [ADR 0008](DECISIONS/0008-operator-neutral-authority.md).

## Expected data flow

1. Environment bootstrap securely establishes an initial master/responsible owner.
2. Owner creates/delegates principals, permissions and session policies.
3. A local or remote client authenticates to LoopBridge as a principal.
4. Client receives a permitted structured snapshot, including reliably matched LoopTeach annotations with distinct provenance.
5. A permitted semantic or conventional operation is validated against current target/lease; trusted OS components enforce protected paths.
6. Bridge reports an outcome with known/unknown status; events and snapshots repair stream gaps.
7. An authorized observer uses the presentation service to view a selected session. The controller's lease and actuation mode are independent of observer attachment.
8. Future owner/delegate handoff requires a verified revocation barrier before refreshing state and granting a replacement control lease.

This flow includes planned presentation and handoff behavior. The V0.6 qualification describes the implemented subset.

## Constraints and risks

- Accessibility metadata may be missing, stale, or inconsistent.
- Wayland security boundaries restrict global input and capture; use documented compositor/portal mechanisms, not unsafe bypasses.
- Browser DOM and app-specific models are separate from the OS accessibility tree; expose richer adapters only with explicit permissions.
- Network/storage/hardware isolation depends on deployment and is not automatically guaranteed by LoopBridge.
- Host↔guest shared folders, clipboard, networking and credential injection require threat modeling.
- Graphics performance and virtual GPU compatibility must be measured, not assumed.

## Architecture quality gates

The full M1 proof still requires authorization, semantic inspection of a real application, event consistency, denial of unauthorized access, separate authorized observation and verified owner/delegate interruption. The staged presentation work has its own gates and leaves the full M1 gate open.

See [LoopBridge](LOOPBRIDGE.md), [Interaction](INTERACTION_MODEL.md), [Security](SECURITY_MODEL.md) and [Roadmap](ROADMAP.md).
