# Security and trust model

**Status:** initial threat model; implementation and independent review are still required.

LoopEnvironment targets AI-controlled graphical workflows, which may touch documents, authenticated websites, messages, and other sensitive resources. **The bridge is a high-value control surface.** The mere fact that an agent is local or that a VM is isolated does not make its actions safe.

## Assets and trust boundaries

Assets: user files, credentials/session cookies, screenshots, accessibility text, application state, browser/email data, authorized input control, event logs, system integrity, and network access.

Boundaries:
- Isolated untrusted agent/client ↔ LoopBridge authenticated endpoint, the mandatory path to the graphical session for external agents.
- LoopBridge ↔ user graphical session and accessibility/compositor adapters.
- User session ↔ OS privileges and protected devices.
- Virtual guest ↔ host (network, shared folders, clipboard, devices, secrets).
- Human observer ↔ agent-controlled session and other observers. View-only access and remote interactive takeover have separate grants.
- Software image/update process ↔ upstream package sources and signing keys.

An external agent runs outside the graphical session's trusted execution context, even when it runs on the same machine. Administrative processes, trusted session applications and local human control have separate trust boundaries. [ADR 0006](DECISIONS/0006-mandatory-agent-mediation.md)

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
- Screen streaming exposing unrelated application content.

## Mandatory security principles

1. **No remote listener by default.** Local socket permissions and peer credentials are necessary but not sufficient. An authorized OS user can run untrusted processes.
2. **Explicit identity and session scopes.** Authenticate clients, authorize every meaningful capability, and bind grants to a user/session/target when possible.
3. **Least privilege.** Prefer a per-user bridge; no routine root/administrator bridge, global input bypass, or unrestricted arbitrary command execution.
4. **Separate observation from control.** Screenshots, element text, keyboard/mouse, file operations and process launch should each have distinct authorization.
5. **Revocation and takeover.** Human intervention must preempt agent input and expire stale leases.
6. **Data minimization.** Logs record identities, actions, times, outcomes, and error categories; not raw passwords, full documents or screen recordings by default.
7. **Fail closed.** Invalid authentication, missing permission, expired target, adapter error or broken transport must never result in elevated fallback.
8. **Confidential transport.** Remote use requires encryption and strong authentication; VM loopback binding alone is not a trust policy.
9. **Defense in depth.** OS sandboxing, filesystem permissions, network policy, and VM isolation complement rather than replace Bridge authorization.
10. **Supply-chain transparency.** Verify upstream artifacts, maintain source and license manifests, and plan signed, rollback-capable OS releases.
11. **Mandatory mediation and OS isolation.** Block untrusted agents from direct access to compositor IPC, Wayland or X11, AT-SPI, the session D-Bus, and input and capture interfaces or devices, including access inherited from another process. Enforce this separation independently of Bridge socket authentication and deny agent access to the session where the separation cannot be enforced. The isolation mechanism and its effectiveness remain to be validated.

## Agent permissions are not human consent

A task instruction alone does not justify every possible operation. Sensitive workflows—payments, sending messages, credential entry, destructive file changes—need explicit higher-level policy/approval, especially for unattended operation. Prompt injection cannot be fixed by a transport encryption setting.

## Virtual deployment caveats

Private host↔guest communication must be authenticated. Host shared folders can undermine guest isolation; clipboard sync, USB passthrough, host networking, and credential forwarding should start disabled or narrowly scoped. Guest snapshots do not roll back effects on cloud services or the host.

## Required verification before broad exposure

- Authentication and authorization negative tests, including same-user unauthorized clients.
- Direct-access denial from the isolated agent context, including with a valid Bridge grant. Check compositor and display sockets, accessibility and session buses, input and capture paths and inherited access.
- Session isolation and concurrent-observer/control-lease tests.
- Stale-element, race-condition, focus-stealing and disconnect handling.
- Screenshot/accessibility redaction and logging tests.
- Remote exposure, TLS/identity, pairing and revocation tests before enabling remote mode.
- Separate tests for remote view-only access and interactive remote takeover. Verify that takeover requires its own grant and preempts agent input in the same session. A remote viewer plus local human takeover provides evidence for viewing and local takeover only.
- Dependency, update, boot-image integrity, and reproducibility checks.
- Threat-model review for actual Wayland/portal/accessibility implementations.

No assertion of production-grade security is appropriate until these mechanisms exist and pass tests.
