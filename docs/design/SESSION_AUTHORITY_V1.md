# Session Authority V1 — minimal identity and control contract

**Status:** proposed implementation contract for the next bounded M1 experiment; **not a deployed feature, final public API, or new product ADR**. This refines [operator identity](../OPERATOR_MODEL.md), the [LoopBridge design](../LOOPBRIDGE.md), [interaction model](../INTERACTION_MODEL.md), and accepted [ADR 0008](../DECISIONS/0008-operator-neutral-authority.md) / [ADR 0007](../DECISIONS/0007-unified-input-mediation.md). Those accepted decisions take precedence if any wording here conflicts.

## 1. Goal and scope

Specify the **smallest testable contract** for owner/assigned-principal authority over a graphical session, independently of the identity of the controller as a person, AI, service or script. A principal might connect from outside LoopEnvironment. We are **not** detecting whether a caller is human.

V1 must separate:
1. **Authentication:** which principal made a request.
2. **Authorization:** which capabilities, session and target that principal may access.
3. **Arbitration:** who currently holds the session's control lease.
4. **Enforcement:** which trusted boundary actually prevents a disallowed operation from reaching an app.
5. **Observation:** what session state and changes a principal can read, independently of control.

**M1.3A** can prove (1)–(3) and a narrow, controlled operation without pretending to have proven (4) for all UI paths. **M1.3B** must demonstrate enforceable takeover across both semantic and conventional input before claiming handoff GO. **M1.3C** separately validates visual fallback/observation.

V1 deliberately does **not** select Sway, compositor forks, transport, IAM backend, persistence format, install UI, RPC framework or public wire schema. The experimental M1.2 JSON-RPC channel is only a laboratory starting point.

## 2. Entities and terms

| Term | V1 meaning |
| --- | --- |
| **Installation** | The administrative domain of one LoopEnvironment installation/guest, with an initial owner principal. |
| **Principal** | Authenticated subject; its ID is not a Linux UID, a specific AI model, or a claim of being human. |
| **Owner (master/responsible)** | Initial ultimate administrative principal provisioned at installation. Can delegate or change policy. No biological predicate. |
| **Delegate** | Principal granted particular capabilities by owner or a properly authorized administrator. |
| **Client connection** | Authenticated transport channel acting on behalf of a principal; clients are not automatically principals. |
| **Session** | Operational/graphical context with an ID, lifecycle epoch and distinct access policy; it can have multiple observers. |
| **Grant** | Revocable authorization tuple: principal, capability, resource scope, expiry and policy revision. |
| **Control lease** | One active principal/session input authority at a time, with opaque lease identifier, generation and expiry. |
| **Override** | Explicit owner/delegate request to replace a session's current controller. |
| **Enforcement boundary** | Trusted compositor/input path for conventional events and trusted broker/adapter for semantic actions. |
| **Live target handle** | Versioned reference to a current app/window/element; not a persisted LoopTeach annotation. |

A natural-language label such as `human`, `agent`, `admin` or `operator` MUST NOT itself grant authority. A physical keyboard event MUST NOT be interpreted as owner authentication.

## 3. Installation bootstrap and delegation (product requirement; not implemented in M1.3A)

- A fresh installation starts in **unowned/unconfigured** mode with **no operational grants** to outside clients. Secure bootstrap establishes exactly one initial owner authority before ordinary delegated control becomes available.
- Interactive install and automated provisioning MUST produce equivalent owner privileges, even when an external AI/VM orchestrator performs setup. No universal, preinstalled or logged master credential is permitted.
- The final proof must cover protected credential delivery, rotation, recovery and audit. **M1.3A may use ephemeral test-only identities and deterministic fixtures**; it MUST NOT represent this as secure OS bootstrap or use real user credentials.
- Owner may create principals, delegate bounded capabilities and revoke them. Privilege delegation MUST be explicitly authorized and recorded. Non-owner clients MUST NOT mint administrative powers or grant more than the authority delegated to them.
- A principal may intentionally possess multiple grants. Owner may deliberately delegate full administration; the OS does not promise to constrain an owner who consciously changes policy.
- Ambient owner access from arbitrary processes in the owner's desktop MUST NOT be assumed; Linux UID alone is insufficient authentication.

## 4. Capability and scope model

The following are **conceptual capability IDs**, not a frozen public ABI:

| Capability | Authorizes | Does not imply |
| --- | --- | --- |
| `session.discover` | Discover permitted session metadata | Full UI state, capture or input |
| `desktop.observe` | Read permitted structured UI state | Input or pixels |
| `desktop.capture` | Observe separately scoped frames | Control or clipboard |
| `desktop.control` | Request an input lease and perform allowed semantic/conventional UI actions | Administrative override |
| `session.override` | Request explicit replacement of a controller in an allowed session | Linux root or arbitrary session access |
| `identity.admin` | Delegation/revocation within authorized administrative scope | Unlimited system operations by every process |
| `app.teach` | Store/modify permitted application annotations | Execute the annotated action |
| `app.profile.read` | Query permitted LoopTeach profile data | Edit, approve or invoke the control |

A grant has at least: `principal_id`, `capability`, `scope` (installation/session/window/target as applicable), `expires_at`, `grant_revision`, `issuer`, `revoked`. Actual encoding remains open.

**Invariants:**
- Deny by default; every meaningful request must be checked against the live authenticated principal and current scope.
- Capture, clipboard, teaching, observation, administration, ordinary input and override are independent.
- A granted capability does not bypass application/OS permission boundaries.
- Owner administrative status is **not** a bearer token inherited by every child process; requests still need authenticated principal proof.
- Invalid/expired scope, stale target, revoked grant or unknown authorization state MUST fail closed.

## 5. Session control model

For the first proof, prefer independent sessions as a deployment option but qualify **one real session**; do not require creating a Linux account or separate desktop per principal.

State per session (conceptual): `session_epoch`, `control_generation`, `controller_principal_id | null`, `active_lease | null`, `policy_revision`, `state_revision`, `phase`.

Phases:

| Phase | Permitted behavior |
| --- | --- |
| `idle` | No control lease. A permitted principal may request control. Authorized observation remains possible. |
| `controlled` | Exactly one valid control lease; actions require matching principal, lease/generation, scope and fresh target. Observers are independent. |
| `handoff_pending` | Override/release is being reconciled. **Reject new old-generation actions**, wait for an enforceable dispatch barrier, and do not yet assert successful takeover. |
| `blocked` | Boundary is unavailable/uncertain. Deny further input and refuse takeover success until recovery/verification; authorized diagnostics may remain available. |

Initial session input state is `idle`. Every new lease or completed handoff advances `control_generation` monotonically for the current `session_epoch`. A restart changes `session_epoch` and invalidates earlier leases and live handles. The same principal controlling a session from two connections does not create two independent leases.

A lease expires at a bounded deadline. On explicit release, expiry, revocation, crash or disconnect, stop allowing new operations under it; decide safe recovery and pending-action resolution before assigning new control. Observers do not automatically become controllers. No pointer movement or viewer attachment constitutes takeover.

## 6. Handoff and acknowledgement barrier

**Takeover protocol (desired product property):**

1. Requester authenticates as principal P with live `session.override` on session S (or an equivalent explicit owner grant). Check the session epoch/policy revision.
2. Atomically enter `handoff_pending`, fence the current `control_generation`, and reject all **new** operations for the old lease.
3. Coordinate with **every actual dispatch path** that can mutate S: conventional keyboard/pointer and semantic actions (including accessibility or application adapters), not just the public RPC queue.
4. Before acknowledging handoff, prove that every accepted old-generation operation has either completed delivery **before the barrier** or is guaranteed not to be delivered **after the barrier**. Resolve held keys/buttons and focus/target changes as appropriate. A command with unknown delivery status cannot be silently classified as cancelled.
5. Advance the generation and make P's new lease active only if the boundary proves it can prevent old-generation delivery; emit an ordered `control.changed` event. P MUST refresh target/state before action.
6. If the boundary fails, times out or reports unknown delivery, enter `blocked` and return an explicit **handoff_not_confirmed** error. Never claim successful preemption based only on a broker flag or a test mock.

**Precise guarantee:** Once a takeover response reports `confirmed`, the trusted OS must not newly deliver an old-generation UI action to the session. Earlier delivered effects (including external network/payment/email effects) are not reversible and are not promised to be.

Atomicity between a compositor and an independent application's semantic action is **not yet established**. If the current Linux stack cannot prove the barrier, the real-compositor handoff test is **NO-GO/PARTIAL**, not a reason to weaken the requirement.

## 7. Observation, freshness and events

- Observation is separately authorized, with redaction/scope. Structured snapshots should expose an epoch, revision, control phase, controller identity **only where permitted**, and the set of capabilities available to the caller.
- Live target handles are bound to session epoch and app/window/element lifetime. Stale/ambiguous handles cannot be used to mutate a newly focused target.
- Control transitions, grant changes, lease expiry, gaps and disconnections produce bounded, ordered events where observable. A stream gap or epoch change requires explicit snapshot/resynchronization.
- Request acceptance, OS-level dispatch and outcome verification are distinct. A timeout after dispatch may have an **unknown** outcome; do not automatically repeat mutating actions.
- LoopTeach metadata is app-specific, attributed and untrusted descriptive data. It is never a lease, capability, persistent live handle or authority to execute a command.
- Capture must be opt-in and independently granted. No observer means no implied continuous screenshot/encoding, though rendering can continue.

## 8. Illustrative operations (not stable endpoints)

```text
Authenticate() -> principal_id, connection_id
GetCapabilities(session_id) -> caller-scoped grants
GetSessionSnapshot(session_id) -> epoch, revisions, phase, permitted state
Delegate(principal_id, capability, scope, expiry) -> grant_id [owner/admin]
RevokeGrant(grant_id) -> policy_revision [owner/admin]
RequestControl(session_id) -> lease, generation [desktop.control]
ReleaseControl(session_id, lease) -> updated state
RequestTakeover(session_id, expected_epoch) -> confirmed lease OR handoff_not_confirmed [session.override]
InvokeElement(session_id, lease, target_handle, action) -> confirmed | unknown | denied
SendInput(session_id, lease, input_action) -> dispatched | unknown | denied
ObserveEvents(session_id, cursor) -> ordered events | gap_snapshot_required
```

Each request MUST derive `principal_id` from the authenticated connection—not from a user-editable payload. In particular, `RequestTakeover` never asks the caller to declare `human: true`.

These operation names and result shapes are **contract sketches**, not an API freeze or commitment to JSON-RPC/gRPC.

## 9. M1.3A acceptance — bounded laboratory proof

**Scope:** prove identity, grants and **control-plane arbitration** on one local fixture. Reuse the M1.2 isolated-client pattern only where it reduces risk. Do not build an OS account manager or real remote service.

Mandatory positive/negative cases:
1. Provision ephemeral `owner`, `delegate`, `observer` and `unenrolled` identities with private test credentials; evidence never includes them.
2. Authenticate independently with distinct connections; prove spoofed `principal_id` or `human` metadata does not change identity.
3. Owner grants delegate `desktop.observe` / `desktop.control` for session S; observer gets `desktop.observe` only.
4. Delegate can request the initial lease and issue the **one already-supported** Calculator semantic operation; result independently verified as in M1.2.
5. Observer reads permitted state but cannot mutate or claim input. Unenrolled connection cannot discover protected data.
6. Delegate cannot override another controller or mint owner-only grants; wrong-session and expired/revoked grants fail.
7. Owner revokes grant; newly submitted delegate actions are rejected. Verify stale lease/reference denial.
8. Exercise an **abstract policy-only takeover** with deterministic pending requests to prove fencing and transitions. Clearly label this as *simulation*, not real compositor preemption.
9. Confirm M1.1/M1.2 automated tests still pass. Preserve negative isolation checks if the trusted-session fixture is invoked.
10. Produce sanitized evidence, run instructions, a documented limitation and **GO only for M1.3A control-plane proof**, not for M1.3B or M1.3 overall.

**Stop conditions:** if identity is derived only from client-supplied strings, if an observer can mutate, if the grant/lease revocation is bypassed, if a local untrusted client reaches protected session APIs, or if a simulation is presented as a real takeover, classify NO-GO and stop.

## 10. Gates that remain after M1.3A

**M1.3B — trusted input and semantic dispatch:** find/implement an enforceable compositor/input path; bind physical local input to the authorized principal/session, and prove that conventional plus semantic pending operations are fenced across a real owner/delegate takeover. If no tested path meets the barrier, record NO-GO for that approach; do not accept API-only preemption.

**M1.3C — visual fallback and observer:** real missing-semantic UI, separately permissioned capture and conventional input, read-only observer, denied clipboard bypass, idle capture/encoding measurements (30 seconds before/after attachment), and real session-state verification. Never infer control capability from a viewer.

**M1.4:** independent compatibility and reproduction. **LoopTeach** remains a native future product capability with its own bounded proof of persistent app-specific annotation after relaunch. **M2** is gated on the whole validated interaction and security boundary, not merely M1.3A.

## 11. Outstanding design decisions

- Cryptographic bootstrap, key storage, owner recovery, multiple owners and credential rotation.
- Effective authorization/revocation semantics across independent session processes and transport reconnect.
- Proven local physical-device-to-principal binding, graphical seat and multi-session ownership.
- Compositor/adapters' generation fencing and semantic in-flight cancellation; crash recovery.
- Maximum lease duration, quotas, fairness, event format and public schema.
- Distinguishing an operational principal from Linux user/resource credentials without leaking ambient privileges.
- Scope inheritance and audit retention. No external or production identity integration in M1.3A.

**This document defines test obligations; it does not assert that the current Debian/Sway experiment satisfies them.**
