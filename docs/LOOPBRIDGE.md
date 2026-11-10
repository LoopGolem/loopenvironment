# LoopBridge: native agent interface

**Status:** architecture contract and exploratory protocol design; there is no implemented API.

LoopBridge belongs to LoopEnvironment. An external agent should work with the OS through LoopBridge whether the OS runs on physical hardware or inside a virtual machine. A graphical client and an agent are both clients; they receive only permissions granted to their identities.

## Responsibilities

1. Authenticate clients and identify the requested OS user and graphical session.
2. Authorize operations by **capability, target, and session**.
3. Expose a best-effort semantic desktop model.
4. Broker permitted input and focus control.
5. Emit structured events, lifecycle changes and errors.
6. Provide optional visual capture/streaming with separate authorization.
7. Record security-relevant actions without recording secrets by default.

Non-responsibilities: reasoning, task planning, mandatory LLM integration, hypervisor management, unrestricted process execution, bypassing application security or browser authentication, and pretending third-party apps expose complete semantic state.

## Proposed contract domains

| Domain | Illustrative operations | Caution |
| --- | --- | --- |
| Discovery | GetServerInfo, ListSessions, ListCapabilities | Versions and grants must be visible. |
| Desktop | ListWindows, GetFocusedWindow, GetDisplays | Window scope must be session-limited. |
| Accessibility | GetElementTree, GetElement, GetSupportedActions | Null/unknown is meaningful; never fabricate controls. |
| Input | InvokeElement, Focus, TypeText, SendKey, PointerAction | Requires explicit input capability and ownership. |
| Events | Subscribe, Ack/Resume, GetSnapshot | Reconnect and overflow must be detectable. |
| Media | CaptureFrame, StartStream, StopStream | Sensitive pixels, separately authorized. |
| Control | RequestControl, ReleaseControl, RevokeClient | Human policy can preempt agent input. |
| Diagnostics | GetHealth, GetAdapterCapabilities | Must not leak unapproved system details. |

Operation names are **illustrative**, not stable endpoints. The initial API definition, error model and client SDKs require an ADR after the first technical spike.

## Semantic desktop model

A client may observe a hierarchy such as:

    Session -> Display -> Window -> AccessibleElement

Each exposed object may provide an opaque ID, generation/revision, role, title or label (where permitted), state (enabled, focused, selected, visible), bounds, available actions, and source/quality of evidence.

- An ID is a handle, not permanent identity. Window closing or accessibility tree rebuilding invalidates it.
- Elements may contain sensitive content; policy must support redaction of text and labels.
- Semantics must identify provenance: accessibility tree, native integration, inferred visual result, or unknown.
- The client must be able to discover when an action cannot be performed.
- Logical coordinates, display scaling, virtual desktops, focus and timeouts require explicit rules.

## Events and consistency

Event delivery is best-effort and versioned, not an oracle of complete application state.

- Assign event sequences within a session stream; define ordering and concurrency.
- Surface stream overflow/gap and recommend a fresh snapshot on loss.
- Include lifecycle events for windows, focus, element changes, permissions, and control ownership.
- Define cancellation and command completion separately; an input command being accepted does not prove an external business operation succeeded.
- Bound queue sizes, timeouts, memory use, and subscription lifetimes.

## Transport independence

**Local default:** a Unix-domain socket scoped to the current OS user/session, with kernel peer-credential checks plus application-level authorization. An example development path is /run/user/UID/loopenvironment/bridge.sock; the final pathname is not specified.

**Virtual guest:** a private host/guest channel or a carefully bound network proxy reaches the same service contract. No hypervisor-specific dependency belongs in the public semantics. A port forwarded to 127.0.0.1 on the host is not itself authenticated.

**Remote opt-in:** encrypted, mutually authenticated access with explicit pairing and revocation, disabled by default. Never bind an unauthenticated bridge to all network interfaces.

gRPC/Protocol Buffers is a candidate for typed requests and event streaming; Unix sockets, an authenticated network transport, and a future guest channel are candidate carriers. **No protocol, port, or RPC framework has been finalized.** Video may be delivered on a separate authorized media channel.

## Authorization outline

Suggested initial grants:

| Grant | Allows | Does not imply |
| --- | --- | --- |
| desktop.observe | Window metadata, redacted accessible state | Screenshots, secrets, control |
| desktop.control | Approved UI actions for specified session | File system/root access |
| desktop.capture | Approved frame/stream observation | Input control |
| process.launch | Explicit allowlisted or policy-approved launch | Arbitrary elevated commands |
| files.access | Scoped file operation via dedicated service, if ever implemented | Entire home directory |
| audit.read | Permitted security/audit events | Secret-bearing raw logs |

Capabilities are preliminary and must be backed by real enforcement. Access to email, financial services, authentication prompts, and credential material should require additional application-level safeguards where practical.

## Fail-closed behavior

- Deny by default without an authorized identity and scoped grant.
- Refuse an action if the target expired, a session changed owners, or a human took control.
- Report unsupported semantics rather than silently switching to a more privileged channel.
- Never interpret API presence as authorization to bypass OS or application permissions.
- Treat network or client disconnection as a reason to release control leases safely.

## Initial proof

An authorized client connects locally, reads one real window's accessible controls, invokes an allowed action, receives an event, and observes a denied action. A human viewer can connect independently and reclaim control. Test a deliberately low-semantic UI to demonstrate an explicit fallback path rather than misleadingly complete trees.

All of this is still **planned**, not shipped.
