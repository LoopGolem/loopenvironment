# Visual, structured and delegated interaction model

**Status:** intended behavior, not implemented behavior.

## Two complementary channels

**Structured channel (preferred for agents):** LoopBridge offers permitted window/session metadata, accessible elements, action descriptions, states, lifecycle and events. Authorized adapters may also expose native system/application operations. JSON can represent this data but does not define the transport.

**Visual channel:** an ordinary rendered Linux desktop for human observation/control plus separately authorized capture and conventional keyboard/pointer fallback. Agents need not see pixels when a sufficient structured operation exists; visual interaction remains useful where semantics are missing.

The model is **operator-neutral**: both channels can be used by authenticated principals controlled by people, AI or software outside the OS. Live semantic facts may be enriched by LoopTeach annotations with separate provenance; annotations are not trusted authority or universal semantic coverage. See [LoopTeach](LOOPTEACH.md).

## Real desktop without an active viewer

A graphical session may remain live without a physical monitor or attached viewer; output/backend support remains subject to testing. Rendering is different from capture/encoding and transmission.

An authorized principal can request view-only access. A principal holding an owner-delegated control capability may also request interactive control. View-only never implies pointer/keyboard input, and no privilege derives from declaring oneself "human".

## Unified input mediation

External and locally untrusted clients use authorized LoopBridge capabilities. Physical input is handled through trusted compositor/input components under the **same session arbitration policy**, with a validated binding to the proper principal/session; no per-event synchronous RPC is mandatory.

The system must block direct session access from untrusted clients. The owner/delegate control-plane policy coordinates conventional input and semantic actions. If the input boundary cannot enforce revocation, the system must not claim a completed transfer. See [operator model](OPERATOR_MODEL.md), [ADR 0008](DECISIONS/0008-operator-neutral-authority.md) and [ADR 0007](DECISIONS/0007-unified-input-mediation.md).

## Control arbitration

Conservative initial design: **one active controller per session**, multiple separately permitted observers. Prefer independent sessions where practical; shared operation remains an explicit policy choice.

1. Secure installation establishes owner authority; owner delegates operator/session/capability grants.
2. A principal requests an input lease for an authorized session; its current state/target revision is recorded.
3. The principal may send semantic or conventional actions through permitted paths.
4. The owner or a delegated override-capable principal explicitly requests takeover, irrespective of whether either controller is a human or AI.
5. Trusted input/semantic boundaries prevent old queued or in-flight operations from reaching a new focus; acknowledge handoff only after the enforceable barrier.
6. The replacement controller refreshes state and starts acting; previous controller cannot resume without a new lease and refresh.

A physical key press is a source event, not a biological credential or automatic takeover request. Previously completed external effects cannot be undone; cancellation must distinguish accepted, delivered and outcome-unknown operations. Recovery and disconnect behavior are unresolved.

## Example workflow (design target)

An owner provisions a VM using an unattended bootstrap key, configures a delegate with limited control over a legacy application and stores credentials outside the agent process. The delegate authenticates remotely, queries structured state, consults permitted LoopTeach annotations, performs a validated UI action and checks its result.

Another authorized principal can view the same session without acquiring input rights. The owner explicitly requests a control transfer; the old operator is blocked at the enforcement boundary and its stale lease invalidated. The new controller refreshes the state before operating.

No application is required to be rewritten, and the OS cannot certify an external business operation solely from a click acknowledgment.

## Accessibility and input expectations

- Accessibility standards are useful but incomplete; return explicit ambiguity/unknown values.
- LoopTeach allows app-scoped, version-aware descriptions and later re-identification, not permanent reuse of runtime target handles.
- Prefer trusted compositor/portal media and input interfaces; reject unsafe bypasses.
- Keep focus, scaling, coordinate space and revisions tied to session/target.
- Sensitive controls and content require redaction and additional permissions.
- A teach-mode shortcut such as **Super+click** must be explicitly authorized, configurable and safely intercepted (no unintended underlying click), with keyboard/structured alternatives.
- Multiple seats/displays, remote interactive takeover and hardening require separate qualification.

## Observable behavior for human clients

A client presenting a human-oriented UI should show current control ownership, available grants and any outstanding transfer. A display/viewer does not grant ownership. An owner/delegate can request override through an authenticated trusted path; another ordinary principal cannot substitute merely by claiming to be human.

Logs identify requested/accepted/delivered/verified operations and transfer events without raw secrets or unnecessary screenshots by default. Equivalent policy applies to non-visual clients.

## Proof criteria

M1.1/M1.2 provide narrow semantic and isolated-client evidence. Future M1.3 proof must demonstrate a genuine semantic gap, scoped visual fallback, view-only observation, explicit owner/delegate takeover, an enforceable barrier across conventional **and semantic** input, safe refresh/release and zero idle capture/encoding without requests. A remote viewer plus local input is **not** proof of authenticated remote interactive control. The preflight on the present Sway approach reported NO-GO; requirements should be re-scoped to the clarified owner-neutral model before further experiments. See [Roadmap](ROADMAP.md), [operator model](OPERATOR_MODEL.md) and [ADR 0008](DECISIONS/0008-operator-neutral-authority.md).
