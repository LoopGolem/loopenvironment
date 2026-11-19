# LoopBridge: native structured operator interface

**Status:** architecture contract with bounded experimental implementations; there is no stable or production-ready public API.

LoopBridge is the **central service of LoopEnvironment on existing Linux**. It is the vendor-neutral structured interface for **authenticated operator principals** and their clients, whether controlled by people, AI or services, local or external. The owner and delegates determine capabilities and session scope; the environment does not infer a controller's biological identity. Physical input requires trusted session/principal binding and compositor enforcement, not necessarily per-event RPC. See [operator model](OPERATOR_MODEL.md), [product definition](PRODUCT_DEFINITION.md), [ADR 0008](DECISIONS/0008-operator-neutral-authority.md) and [ADR 0007](DECISIONS/0007-unified-input-mediation.md).

## Structured-first operation and backend reuse

LoopBridge is a trusted authority and integration boundary, not an AI planner, kernel or requirement to reimplement every desktop backend. Prefer supported Linux, application and semantic APIs to visual actions; preserve desktop capture and input for permitted observation/fallback. Cua Driver's exact-target decisions, structured results, permissions and compositor integrations are **research candidates**, not adopted dependencies. Any external adapter must remain behind Bridge grants and trusted input/semantic enforcement, with no direct untrusted-client bypass.

LoopBridge must be usable on an existing Linux host without requiring a dedicated ISO or VM image.

## Untrusted client isolation

Untrusted or externally controlled clients may run in an isolated local execution context or **entirely outside LoopEnvironment**. An agent is not required to be an in-guest Linux process. The important distinction is the trust boundary, not the controller's nature.

Locally untrusted code must not gain unmediated access to protected compositor IPC, Wayland/X11, AT-SPI, session buses, input/capture devices or inherited descriptors. Bridge authentication does not authorize those bypasses. The trusted compositor, applications and limited administrative services have separate boundaries. An owner may legitimately delegate broad authority, but ordinary processes in the owner's session must not inherit administrative privileges automatically.

Historical ADR 0006 remains mandatory for untrusted client access; [ADR 0008](DECISIONS/0008-operator-neutral-authority.md) clarifies terminology. Exact isolation mechanisms remain experimental.

## Responsibilities

1. Authenticate principals and bind clients to the correct installation, session and resources.
2. Implement owner-defined delegation, capability grants, scope and revocation.
3. Offer a machine-readable best-effort model of current graphical sessions, windows, accessible elements and actions.
4. Resolve authorized LoopTeach profile annotations against **new live elements** with provenance and ambiguity reporting.
5. Mediate permitted semantic/visual/keyboard/pointer actions and trusted session handoffs.
6. Supply event streams, snapshots, lifecycle changes, honest outcomes and errors.
7. Separately authorize visual capture, teaching/profile changes, file/process operations and administrative actions.
8. Audit security-relevant transitions without recording secrets by default.

Non-responsibilities: AI reasoning/planning, biological verification, mandatory model hosting, hypervisor management, bypassing application security or observing/vetoing every Linux syscall.

## Proposed contract domains

| Domain | Illustrative operations | Caution |
| --- | --- | --- |
| Discovery | GetServerInfo, ListSessions, ListCapabilities | Versions and grants must be visible. |
| Desktop | ListWindows, GetFocusedWindow, GetDisplays | Window scope must be session-limited. |
| Accessibility | GetElementTree, GetElement, GetSupportedActions | Null/unknown is meaningful; never fabricate controls. |
| Input | InvokeElement, Focus, TypeText, SendKey, PointerAction | Requires explicit input capability and ownership. |
| Events | Subscribe, Ack/Resume, GetSnapshot | Reconnect and overflow must be detectable. |
| Media | CaptureFrame, StartStream, StopStream | Sensitive pixels, separately authorized. |
| Control | RequestControl, ReleaseControl, RevokeClient | Owner/delegate authority governs control transfers. |
| Diagnostics | GetHealth, GetAdapterCapabilities | Must not leak unapproved system details. |
| Teaching | IdentifyElement, AnnotateElement, GetProfile, ReviewMatch | Future LoopTeach scope; annotation is not input authorization. |
| Ownership | GetPrincipal, ListGrants, Delegate, RevokeGrant | Requires administrative capabilities; names are illustrative. |

Operation names are **illustrative**, not stable endpoints. The initial API definition, error model and client SDKs require an ADR after the first technical spike.

## Semantic desktop model

A client may observe a hierarchy such as:

    Installation -> Session -> Display -> Window -> LiveElement

Each exposed target may carry a runtime handle, generation/revision, role, state, bounds, available actions, app identity/context, freshness and observation provenance. An opaque handle identifies a **current** element, not a persistent semantic concept.

LoopTeach may add **application-scoped saved annotations** (purpose, expected effect, usage notes) to a matching live element. A stored profile must be re-evaluated after every app restart/version/layout change and must return ambiguous/unresolved when evidence is insufficient. Native accessibility, operator descriptions, visual inference and tested bundled profiles must remain distinguishable. No description authorizes an action by itself.

Application pixels do not guarantee accessible semantics. Redact sensitive data; handle missing matches, inaccessible controls and stale references explicitly. Prefer bounded reads and explicit error conditions. See [LoopTeach](LOOPTEACH.md).

## Events and consistency

Event delivery is best-effort and versioned, not an oracle of complete application state.

- Assign event sequences within a session stream; define ordering and concurrency.
- Surface stream overflow/gap and recommend a fresh snapshot on loss.
- Include lifecycle events for windows, focus, element changes, permissions, and control ownership.
- Define cancellation and command completion separately; an input command being accepted does not prove an external business operation succeeded.
- Bound queue sizes, timeouts, memory use, and subscription lifetimes.

## Transport independence

**Local default proposal:** authenticated Unix-domain endpoint with OS peer identity plus application-level principal grants. A Linux UID alone is not an operator principal.

**Virtual guest:** a private guest/host path or authenticated proxy should carry the same conceptual API. An external orchestration service may hold an owner credential established at unattended bootstrap, but no orchestration vendor is required.

**Remote opt-in:** use protected, mutually authenticated transport, pairing/rotation and explicit revocation; remote listeners are disabled by default.

gRPC/Protocol Buffers, JSON-RPC and local/guest channels remain candidates, not final protocol decisions. View-only, input control and teaching are separate capabilities. Remote transport never implies a "human" or owner identity.

Authorized owner/delegate takeover must be verified against actual input and in-flight semantic action paths; client revocation alone is insufficient. See [interaction model](INTERACTION_MODEL.md#control-arbitration).

## Authorization outline

Capabilities below are illustrative and must be backed by OS-enforced scopes and principal authentication:

| Grant | Allows | Does not imply |
| --- | --- | --- |
| desktop.observe | Permitted window/element state, including allowed annotations | Pixel capture or input |
| desktop.capture | Scoped frame/stream access | Control or teaching |
| desktop.control | Authorized semantic/conventional input with lease | Root/files/admin authority |
| desktop.clipboard | Specifically approved clipboard operations | Clipboard access by other grants |
| app.teach | Annotate approved app/element via LoopTeach | Invoking that element or distributing profiles |
| app.profile.read | Read allowed saved annotations | Modify/approve/import them |
| app.profile.manage | Manage allowed app profiles | Administrative ownership |
| session.override | Explicitly request control transfer for allowed sessions | Automatic rights on all sessions |
| identity.admin | Create/delegate/revoke principals within scope | Kernel/root authority in general |
| process.launch | Approved process creation via narrow service | Arbitrary privileged commands |
| files.access | Scoped file operations via authorized service | Unrestricted filesystem |
| audit.read | Read approved audit events | Raw secrets or unsanitized logs |

The initial owner holds ultimate configured administrative authority but should not automatically expose its credentials/capabilities to arbitrary descendant processes. Identity and grant lifetimes, handoff barriers, local device binding and high-risk actions need dedicated designs. See [operator model](OPERATOR_MODEL.md).

## Fail-closed behavior

- Reject unknown principals, denied scope, expired/revoked leases and ambiguous/stale targets.
- Treat annotations as untrusted data: do not auto-execute their commands or elevate privileges.
- An authorized owner/delegate takeover must prevent old pending operations from affecting the new target **before** confirmation; otherwise report failure/unknown, not successful handoff.
- Do not silently fall back from inaccessible semantics to a more privileged input or capture path.
- On disconnect, release control appropriately and require fresh state before reacquisition.
- Administrative recovery must not create an unmediated channel for unauthorized clients.

## Initial proof

**Experimental evidence:** M1.1 showed a bounded GNOME Calculator semantic action; M1.2 added a fixture-specific isolated client, local authorization and query-derived events. Neither is a completed LoopBridge service or proof of universal security.

The M1.3 preflight for a conventional input/preemption path reported NO-GO in the local lab; its [historical report](labs/M1_3_FALLBACK_HUMAN_CONTROL.md) is preserved in this repository. Its outcome motivates reviewing **owner/delegate control semantics** and the enforcement boundary, not abandoning the design. LoopTeach and persistent profile matching remain unimplemented. [Roadmap](ROADMAP.md#m1--agent-native-desktop-proof).

## Experimental service V0.2

The `desktop` service mode exposes one local Sway session, a catalog of supervised applications, bounded AT-SPI queries and a private workspace. See the [V0.2 contract and qualification](LOOPBRIDGE_V0_2.md). The [V0.1 Calculator procedure](LOOPBRIDGE_CORE_V0_1.md) remains available with explicit `--mode calculator`.

## Experimental service V0.3

The [V0.3 and LoopTeach V0.1 contract](LOOPBRIDGE_V0_3.md) describes native operation policies, multi-document workspace operation and scoped persistent teaching.
