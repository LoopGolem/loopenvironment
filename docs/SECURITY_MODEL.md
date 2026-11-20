# Security and trust model

**Status** — Threat model for experimental LoopEnvironment services on existing Linux. [V0.6](LOOPBRIDGE_V0_6.md) and [V0.7](LOOPBRIDGE_V0_7.md) provide bounded lab evidence. V0.7 checks stream authorization and isolation for sandboxed clients. Unrestricted same-UID processes on the host remain inside the trust boundary. Verified takeover remains open.

LoopEnvironment targets both interactive and automated control of graphical workflows, which may touch documents, authenticated websites, messages, and other sensitive resources. **The bridge is a high-value control surface.** The mere fact that an agent is local or that a VM is isolated does not make its actions safe.

## Assets and trust boundaries

Assets include user files, credentials and session cookies, still captures and live frames, accessibility text, application state, browser and email data, input control, event logs, system integrity and network access.

Boundaries:
- Isolated untrusted agent/client ↔ LoopBridge authenticated endpoint, the mandatory path to the graphical session for external agents.
- LoopBridge ↔ user graphical session and accessibility/compositor adapters.
- Presentation clients ↔ authorized presentation services ↔ private session output. The Shell uses these mediated paths and the LoopBridge control plane under scoped grants.
- User session ↔ OS privileges and protected devices.
- Virtual guest ↔ host (network, shared folders, clipboard, devices, secrets).
- Owner/delegate/controller/observer principals ↔ sessions and each other. Observation, input, teaching and override use separate grants.
- Environment package and optional image/update process ↔ upstream package sources and signing keys.

A locally **untrusted client** runs outside the graphical session's trusted execution context; an external AI may instead run on another machine and only connect using authenticated credentials. Principal identity is not equivalent to a Linux UID or a biological human. Owner-level authority must not be inherited indiscriminately by arbitrary processes. [ADR 0006](DECISIONS/0006-mandatory-agent-mediation.md) · [ADR 0008](DECISIONS/0008-operator-neutral-authority.md)

## Threat examples

- Malware connecting to a listening control socket.
- A local process on the same account abusing ambient permissions.
- An agent reading secrets from accessibility trees, screenshots or logs.
- Prompt injection inside a document/webpage asking an agent to exfiltrate data.
- A malicious app spoofing element roles or changing state after inspection.
- Stale target IDs causing actions in the wrong window.
- Unauthenticated or overexposed network forwarding from a VM.
- Remote clients retaining authorization after consent is revoked.
- Clipboard, shared folder, or network escape from an agent workspace.

### Visual presentation threats

- Sensitive documents, credentials or notifications exposed in frames, thumbnails, buffers or diagnostics.
- Unauthorized stream attachment or cross-session leaks through incorrect routing, shared caches or buffers.
- Reused session identifiers or credentials reopening a replaced session, or attaching to a different session after reconnect.
- Continued delivery after revocation, or capture, encoding or streaming started without authorization.
- Viewer focus, controls or input forwarding accidentally granting control or delivering keyboard and pointer events into the session.
- A nested presentation prototype exposing the main Wayland socket or inherited descriptors to untrusted processes, or bridging private sessions through shared compositor or device access.

Presentation services must enforce current principal and session authorization for stream attachment, delivery, reconnect and revocation. Keep live viewing, on-demand capture, semantic inspection, input, administration and transfer grants distinct. View-only clients must have no input forwarding path. Protect frame data from unauthorized disclosure throughout capture and delivery. The media contract, redaction techniques and any trusted nesting path remain open. See [ADR 0011](DECISIONS/0011-session-presentation-and-operator-shell.md) and [architecture](ARCHITECTURE.md).

## Mandatory security principles

1. **No remote listener by default.** Local socket permissions and peer credentials are necessary but not sufficient. An authorized OS user can run untrusted processes.
2. **Explicit principal and session scopes.** Authenticate principal credentials and clients, authorize meaningful capabilities, and bind grants to session/target/duration. No biological classification or trusted client-supplied role label.
3. **Least privilege.** Prefer narrowly scoped services and deny ambient owner authority to arbitrary child processes; no routine unrestricted root Bridge or arbitrary command execution.
4. **Separate observation from control.** Screenshots, element text, keyboard/mouse, file operations and process launch should each have distinct authorization.
5. **Revocation and takeover.** An explicit authenticated owner/delegate override requires revocation of the old lease and a verified barrier against pending and late conventional and semantic effects. The barrier remains unqualified.
6. **Data minimization.** Logs record identities, actions, times, outcomes, and error categories; not raw passwords, full documents or screen recordings by default.
7. **Fail closed.** Invalid authentication, missing permission, expired target, adapter error or broken transport must never result in elevated fallback.
8. **Confidential transport.** Remote use requires encryption and strong authentication; VM loopback binding alone is not a trust policy.
9. **Defense in depth.** OS sandboxing, filesystem permissions, network policy, and VM isolation complement rather than replace Bridge authorization.
10. **Supply-chain transparency.** Verify upstream artifacts, maintain source and license manifests, and plan signed, rollback-capable OS releases.
11. **Mandatory mediation and OS isolation.** Block untrusted agents from direct access to compositor IPC, Wayland or X11, AT-SPI, the session D-Bus, and input and capture interfaces or devices, including access inherited from another process. Enforce this separation independently of Bridge socket authentication and deny agent access to the session where the separation cannot be enforced. The isolation mechanism and its effectiveness remain to be validated.

## Operator authorization and owner authority

An authenticated principal's grants—not a task instruction or assertion that a client is human—determine authorization. The initial owner may be controlled by a person, AI or other automation; the OS cannot prevent an intentionally authorized owner from changing its own policy.

Sensitive operations (payments, sending messages, credential entry, destructive changes) may require explicit **owner-defined higher-level policy**, approval, scope or confirmation. These rules apply regardless of the type of controller. Prompt injection and malicious stored LoopTeach annotations are untrusted input, not instructions to grant authority. A local process using stolen owner credentials is a compromise of owner identity, not evidence that an AI bypassed biological detection.

## Virtual deployment caveats

Private host↔guest communication must be authenticated. Host shared folders can undermine guest isolation; clipboard sync, USB passthrough, host networking, and credential forwarding should start disabled or narrowly scoped. Guest snapshots do not roll back effects on cloud services or the host.

## Required verification before broad exposure

- Authentication and authorization negative tests, including same-user unauthorized clients.
- Direct-access denial from the isolated agent context, including with a valid Bridge grant. Check compositor and display sockets, accessibility and session buses, input and capture paths and inherited access.
- Session isolation, securely bootstrapped owner authority, delegated administration and concurrent-observer/control-lease tests.
- Presentation tests for unauthorized and cross-session attachment, stale identifiers or credentials, revocation during delivery, disconnect/reconnect, session replacement, frame confidentiality and idle behavior without authorized demand.
- View-only clients must reject or lack input forwarding. Any future nested presentation path must demonstrate host Wayland socket protection and isolation from sibling sessions and protected devices.
- Stale-element, race-condition, focus-stealing and disconnect handling.
- Screenshot/accessibility and LoopTeach annotation redaction, provenance, poisoning, mismatching and logging tests.
- Remote exposure, TLS/identity, pairing and revocation tests before enabling remote mode.
- Separate tests for view-only and interactive control. Verify that takeover requires authenticated owner/delegate authority and preempts all previous conventional and semantic input. A remote viewer plus local input proves neither remote authenticated takeover nor general operator identification.
- Dependency, update, boot-image integrity, and reproducibility checks.
- Threat-model review for actual Wayland/portal/accessibility implementations.

No assertion of production-grade security is appropriate until these mechanisms exist and pass tests.
