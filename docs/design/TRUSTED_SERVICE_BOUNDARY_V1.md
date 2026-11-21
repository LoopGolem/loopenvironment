# Trusted Service Boundary V1 — Five Deliveries

**Status:** D1 accepted (PR #20), D2 merged (PR #21), D3 merged (PR #22), and [D4.2A repository preparation](TRUSTED_SERVICE_BOUNDARY_D42A.md) provides a candidate profile, with [D4.2A.1 administrative bootstrap](TRUSTED_SERVICE_ADMIN_D42A1.md) prepared for review. **Current host isolation gate:** PARTIAL (V0.7.1); no privileged VM changes are authorized by this document.

## Goal and precise acceptance claim

Keep existing Linux and LoopBridge's principal-neutral, scoped authority. Qualify a bounded Debian 13/VirtualBox runtime where a non-sandboxed client running as the **ordinary desktop user** can access private Sway, Wayland, D-Bus, input/capture and session-sensitive resources **only through authorized Bridge interfaces**. Retain a working authorized viewer, independent sessions, revoke/expiry and lifecycle. Do not treat a local Linux UID or physical person as a LoopBridge principal.

The word **GO** would qualify **only this host-client/private-session boundary** on the tested profile; it would not certify the whole product, trusted applications inside the private desktop, root/kernel threats, stolen owner credentials or remote deployment.

### Existing evidence and non-goals

- V0.7.1's user-reported full Debian demonstration: streaming, performance, sandboxed-client authorization and human observation **GO**; unrestricted same-UID host isolation **PARTIAL**.
- Direct private Wayland registry, screencopy and advertised virtual-input interfaces, Sway IPC and D-Bus were still reachable from the ordinary host UID.
- Verifier-per-instance mode is opt-in (`private --scoped-credentials`) in V0.7.1, and selected `PR_SET_DUMPABLE=0` hardening did not eliminate all access paths.
- Continue to run untrusted agents in explicit sandboxes where supported; host-account hardening is **additional** defense, not permission to stop isolation.
- No changes to the main Sway compositor, root login, system-installed packages or OS accounts occur during D1–D3.

## Proposed target structure

| Component | Host OS identity | Authorized interface | Should **not** have |
| --- | --- | --- | --- |
| Existing operator desktop, Codex, future Shell and GUI viewer | Ordinary desktop account (e.g. `vboxuser`) | Local authenticated Bridge control/presentation socket | Direct access to service-owned private Wayland, Sway IPC, D-Bus, credentials or capture/input FDs |
| LoopBridge trusted manager and private-session supervision | Distinct unprivileged service account | Explicit Bridge ingress; service-owned private runtime | Routine root privileges, arbitrary remote listener |
| Private Sway, session-bus and trusted in-session adapters | Service-controlled execution context and namespaces | In-session trusted IPC and narrowly scoped adapters | Export of private IPC into ordinary host desktop by accident |
| Isolated untrusted agent clients | Explicit confined identity/view | Scope-limited Bridge endpoint | Direct private compositor/OS devices |
| Authorized owner/delegate/observer principal | **Logical**, not an OS account | Bearer/verification and current grants | Authority inferred from UID, process name or a human label |

**Boundary design note:** Do not expose a parent directory allowing desktop-account traversal to private resources merely to make the Bridge socket reachable. Use a deliberately separate ingress path. The public ingress and private runtime have different ownership, discovery and mount rules. The IPC contract and actual filesystem/unit layout are reserved for D2.

## Five small, reviewable deliveries

| Delivery | Scope | Acceptance for the delivery | Explicit exclusions |
| --- | --- | --- | --- |
| **D1 — Threat model + identity contract** | Proposed ADR 0012; runtime ownership/roles; negative and positive gate matrix; constraints and unresolved questions | Accurate, reviewable design linked from roadmap/security docs; no runtime changes; PR approved before merge | No unit installation, users, privileged commands or GO claim |
| **D2 — Minimal authenticated ingress contract** | Define operator-facing socket, peer admissibility, principal authorization and separation of public/private path ownership; implement a narrowly scoped unprivileged prototype or mocks ([D2 contract](TRUSTED_SERVICE_INGRESS_D2.md)) | Unit tests reject unauthorized operations and do not leak raw private handles; legacy behavior still explicit | No privileged setup or actual cross-UID deployment |
| **D3 — Launch/cleanup integration tests** | Add unprivileged fixtures for ownership/configuration, startup/shutdown, credential lifecycle, multiple instances and failure/recovery ([D3 lifecycle](TRUSTED_SERVICE_LIFECYCLE_D3.md)); reserve concrete OS service templates for separately authorized D4 | Repeatable tests and CI green; no insecure fallback in hardened profile; systemd vs alternative decision documented | No modifying host accounts, /etc, compositor, or package state |
| **D4 — Authorized disposable-VM qualification setup** | Prepare the profile and release in [D4.2A](TRUSTED_SERVICE_BOUNDARY_D42A.md). With separate operator authorization, provision the service profile on a VM snapshot in D4.2B and run the first cross-UID smoke in D4.2C | Reproducible install/rollback and confirmed normal Bridge/GTK/Sway function; no impact on primary desktop | No assumption that provisioning implies security GO; no production deployment |
| **D5 — Scoped security qualification** | Re-run documented host boundary checks, retained sandboxed-client checks, UI/streaming/regression and credential/permission lifecycle on that profile | Required denials and positive checks all observed with reproducible evidence and independent review; otherwise PARTIAL or NO-GO | No universal security/agent-safety claims, no automatic merge |

**Development discipline:** keep `main` plus at most one short-lived implementation branch, PR per reviewed delivery, squash/cleanup after explicit approval. If a delivery needs more than one code change, use small, testable commits within the same PR, not simultaneous branches. Escalate only the specific privileged or destructive operation for approval.

## Acceptance matrix for eventual D5

| ID | Required check | Expected outcome | Evidence |
| --- | --- | --- | --- |
| T01 | Ordinary desktop UID, no Bridge authentication: direct private Wayland / Sway IPC / D-Bus reachability | **Denied**, independently of session and token names | Bounded synthetic VM checks; no screen or secret payloads in report |
| T02 | Ordinary desktop UID: private compositor paths, owned state and sensitive process interfaces | **Denied** except intentionally public metadata | Owner/mode/runtime and process-isolation observation |
| T03 | Untrusted host client: inherited sockets and capture/input descriptors | **None** outside the authorized Bridge protocol | Restricted fixture with explicit descriptor inventory |
| T04 | Bridge endpoint with missing, wrong, expired or out-of-scope principal credential | **Denied** with no successful operation or media | RPC negative tests; sanitized result only |
| T05 | Authorized distinct principals: scoped observation, capture, input and grants | **Allowed only with correct grant**, no accidental privilege widening | Existing core tests and VM integration |
| T06 | Session A credential/verifier against session B and replacement session | **Denied**; old sessions cannot be reattached by stale identity | Scoped verifier tests and lifecycle regression |
| T07 | Authorized viewer/stream: real Sway frames, revocation, expiry, exit, reopen, stop | Existing gates remain **GO** without raw private endpoint disclosure | GUI demo plus automated integration |
| T08 | Performance (existing 800×600 Debian fixture) | >=28 unique motion FPS and p95 app-to-presentation <=100 ms, measured; no fabricated values | Frame metrics from full demo |
| T09 | Service crash, cleanup, reinstall/rollback and credentials | No unexpected privilege exposure, stale private sockets or automatic weak-mode fallback | Explicitly reviewed VM lifecycle evidence |
| T10 | Owner bootstrap and storage under distinct OS identities | No ambient owner bearer credential granted to ordinary unrelated desktop processes; exact protected enrollment documented | Separate credential-lifecycle review |

**Decision rule:** T01–T10 must be supported by evidence relevant to the actual hardened profile, with no known contradictory successful direct-access observation. Any failed or unexecuted mandatory check retains **PARTIAL**; a demonstrated unsafe regression can be **NO-GO**. An honest partial result is a useful deliverable, not a reason to discard the stage.

## D1 completion checklist

- [x] Specify the threat actors, assets, intended privileged boundary and exclusions.
- [x] Propose a dedicated OS service account distinct from the operator account, without committing to static versus dynamic UID yet.
- [x] Keep Bridge principal authorization independent from OS identity.
- [x] Record legacy/scoped credential compatibility and owner-token-storage caveat.
- [x] Define five independent acceptance gates and a reproducible D5 matrix.
- [x] Architectural direction approved and merged as PR #20; D2 work now proceeds separately.

## References

- [ADR 0012 accepted direction](../DECISIONS/0012-trusted-service-identity-boundary.md)
- [D2 ingress contract](TRUSTED_SERVICE_INGRESS_D2.md)
- [D3 opt-in lifecycle and D4 ownership decisions](TRUSTED_SERVICE_LIFECYCLE_D3.md)
- [Current security model](../SECURITY_MODEL.md)
- [V0.7.1 qualification](../LOOPBRIDGE_V0_7_1.md)
- [ADR 0011](../DECISIONS/0011-session-presentation-and-operator-shell.md)
