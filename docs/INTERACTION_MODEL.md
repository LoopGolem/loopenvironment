# Visual, structured and delegated interaction model

**Status** — Intended product behavior with bounded evidence for [V0.6 private desktops and PNG capture](LOOPBRIDGE_V0_6.md) and [V0.7 read-only local streaming](LOOPBRIDGE_V0_7.md). The [LoopShell V0.8 design](design/LOOPSHELL_V0_8.md) and verified handoff remain future work.

## Two complementary channels

**Structured channel (preferred for agents):** LoopBridge offers permitted window/session metadata, accessible elements, action descriptions, states, lifecycle and events. Authorized adapters may also expose native system/application operations. JSON can represent this data but does not define the transport.

**Visual channel:** authorized presentation of a rendered Linux desktop. Live viewing, on-demand capture and conventional keyboard/pointer input have separate permissions. Visual fallback remains useful where semantics are missing.

The model is **operator-neutral**: both channels can be used by authenticated principals controlled by people, AI or software outside the OS. Live semantic facts may be enriched by LoopTeach annotations with separate provenance; annotations are not trusted authority or universal semantic coverage. See [LoopTeach](LOOPTEACH.md).

## Discovering and observing sessions

1. A client such as the planned LoopEnvironment Shell authenticates to LoopBridge. The session list includes only sessions and metadata the principal is authorized to discover.
2. The operator selects a session. The client requests presentation access and the presentation service enforces authorization for that session. The client opens an enlarged live view on success and shows connection state and authorized controller or authority metadata.
3. Multiple authorized observers may view the same session. Each observer's connection and permissions are independent. Opening, selecting or focusing a view leaves the current control lease unchanged. A view-only client has no session input path.
4. On observer disconnect, the viewer reports the loss and stops presenting stale frames as live. Reconnection requires revalidating current authorization for the same session. If the session ended or was replaced, the viewer reports it and requires an explicitly selected, authorized session before displaying another desktop. The session and its controller can continue independently of the observer connection.

Sessions may keep rendering and operating headless without a physical monitor or an attached viewer. Continuous capture, encoding and delivery should be idle without authorized demand or an authorized operational need. Policies for thumbnails and individual captures may differ. See [ADR 0011](DECISIONS/0011-session-presentation-and-operator-shell.md) and [architecture](ARCHITECTURE.md#execution-control-and-presentation-planes).

## Observation and actuation mode

An observer can watch the visible effects of native or semantic operations. Attaching or leaving a view does not change the controller's actuation mode. A future observable mode may use authorized pointer movement, keyboard input, scrolling and progressive typing when that makes the action sequence easier to follow. Efficient native and semantic actions remain preferred where appropriate. Both modes follow the same session authority policy and are available according to grants, regardless of who or what operates the principal.

## Unified input mediation

External and locally untrusted clients use authorized LoopBridge capabilities. Physical input is handled through trusted compositor/input components under the **same session arbitration policy**, with a validated binding to the proper principal/session; no per-event synchronous RPC is mandatory.

The system must block direct session access from untrusted clients. The owner/delegate control-plane policy coordinates conventional input and semantic actions. If the input boundary cannot enforce revocation, the system must not claim a completed transfer. See [operator model](OPERATOR_MODEL.md), [ADR 0008](DECISIONS/0008-operator-neutral-authority.md) and [ADR 0007](DECISIONS/0007-unified-input-mediation.md).

## Control arbitration

The initial policy allows **one active controller per session**. Future interactive control requires a separate control grant, a valid lease and the same trusted enforcement as other input paths. A viewer's local pointer and keyboard events stay local unless an authorized interactive path is available and explicitly enabled.

1. Secure installation establishes owner authority; owner delegates operator/session/capability grants.
2. A principal requests an input lease for an authorized session; its current state/target revision is recorded.
3. The principal may send semantic or conventional actions through permitted paths.
4. The owner or a delegated override-capable principal explicitly requests takeover, irrespective of whether either controller is a human or AI.
5. Trusted input/semantic boundaries prevent old queued or in-flight operations from reaching a new focus; acknowledge handoff only after the enforceable barrier.
6. The replacement controller refreshes state and starts acting; previous controller cannot resume without a new lease and refresh.

A physical key press conveys no authority and cannot initiate takeover by itself. Previously completed external effects cannot be undone. Cancellation must distinguish accepted, delivered and outcome-unknown operations. Takeover remains unqualified, including controller disconnect and failure recovery across conventional and semantic dispatch.

## Example workflow (design target)

An owner provisions a VM using an unattended bootstrap key, configures a delegate with limited control over a legacy application and stores credentials outside the agent process. The delegate authenticates remotely, queries structured state, consults permitted LoopTeach annotations, performs a validated UI action and checks its result.

Another authorized principal opens a live view while the delegate continues using structured actions. The observer disconnects and the session continues headless. A later, authorized handoff would require the enforcement boundary to revoke the old lease and fence pending operations before the new controller refreshes state and starts acting.

No application is required to be rewritten, and the OS cannot certify an external business operation solely from a click acknowledgment.

## Accessibility and input expectations

- Accessibility standards are useful but incomplete; return explicit ambiguity/unknown values.
- LoopTeach allows app-scoped, version-aware descriptions and later re-identification, not permanent reuse of runtime target handles.
- Prefer trusted compositor/portal media and input interfaces; reject unsafe bypasses.
- Keep focus, scaling, coordinate space and revisions tied to session/target.
- Sensitive controls and content require redaction and additional permissions.
- A teach-mode shortcut such as **Super+click** must be explicitly authorized, configurable and safely intercepted (no unintended underlying click), with keyboard/structured alternatives.
- Multiple seats/displays, remote interactive takeover and hardening require separate qualification.

## Operator feedback and audit

The planned Shell should show current controller, available grants and any future pending transfer within the principal's metadata scope. Equivalent status should be available through authorized structured clients.

Logs identify requested/accepted/delivered/verified operations and transfer events without raw secrets or unnecessary screenshots by default. Equivalent policy applies to non-visual clients.

## Proof criteria

M1.1/M1.2 provide narrow semantic and isolated-client evidence. Future M1.3 proof must demonstrate a genuine semantic gap, scoped visual fallback, view-only observation, explicit owner/delegate takeover, an enforceable barrier across conventional **and semantic** input, safe refresh/release and zero idle capture/encoding without requests. A remote viewer plus local input is **not** proof of authenticated remote interactive control. The preflight on the present Sway approach reported NO-GO; requirements should be re-scoped to the clarified owner-neutral model before further experiments. See [Roadmap](ROADMAP.md), [operator model](OPERATOR_MODEL.md) and [ADR 0008](DECISIONS/0008-operator-neutral-authority.md).
