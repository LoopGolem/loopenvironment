# Operator identity, ownership and session authority

**Status:** accepted product requirements; implementation, credential format and UI remain unselected. See [ADR 0008](DECISIONS/0008-operator-neutral-authority.md).

## Core distinction

LoopEnvironment does not identify the biological nature of an operator. A person, AI system, script, service or orchestration tool may act behind an authenticated principal. Claims such as "human", "AI", "bot" or "automation" are optional metadata for UX and audit, **not** a trustworthy security boundary.

- **Principal / identity:** independently authenticated subject recognized by LoopEnvironment.
- **Owner (master/responsible):** initially provisioned principal holding ultimate administrative authority for this installation. It is not necessarily a person, a Linux root login, or a specific process.
- **Operator:** principal currently requesting access to a session or resource, with explicitly granted capabilities.
- **Client:** an implementation connecting to LoopBridge. One principal may use multiple clients, from inside or outside the machine.
- **Session:** a graphical and operational context with stable scoped identity and its own control/observation policy. A session is not identical to a principal.
- **Control lease:** revocable, time-bounded authorization for one principal to deliver specified operations in one session.

The owner may delegate administration, create principals, authorize or revoke capabilities, configure which sessions can be controlled, and assume control where the owner's administrative authority permits. The owner may themselves be operated by an AI. No CAPTCHA or biological classifier is required. Merely labeling a connection as an owner or a human does not authenticate it.

## Bootstrap and recovery

- Every new installation MUST establish an initial owner through a secure bootstrap flow, with no hardcoded shared master secret.
- Interactive install (for example, bootable media) and automated provisioning (for example, a VM created by an external orchestrator) must lead to equivalent owner authority and policy semantics.
- Bootstrap must bind credentials to the owner through an authenticated or otherwise protected setup channel. Avoid embedding reusable secrets into public images, logs, command lines, or sample configuration.
- Bootstrap completion, owner credential recovery, additional administrative principals and credential rotation need explicit audited designs and tests. Do not expose an unauthenticated recovery backdoor.
- A VM manager or external provisioning tool is optional and MUST NOT be a required dependency of core LoopEnvironment.

## Default policy and delegation

The proposed initial policy is deny-by-default for additional principals. Owner control is an administrative authority, not unrestricted ambient access by every process running in the owner's desktop.

Permissions have a subject, capability, scope (session, target and data), duration, and revocation rules. Observation, semantic inspection, frame capture, conventional input, application launch, file access, privileged administration, teaching/annotation and exporting profiles are distinct capabilities. No permission implies another unless policy explicitly grants it.

An owner may knowingly delegate broad or even administrative capability; the system cannot protect against an owner intentionally changing its own policies or transferring control of its credentials. Least-privilege defaults and confirmation for sensitive actions are UX/security mechanisms, not restrictions based on whether the controller is an AI.

Local Linux UID/GID, namespaces, MAC, sockets and process credentials may help enforce principal boundaries. **Operator identity is not a synonym for a Linux UID**, and one Unix user account need not be created for each remote operator. An authorized principal must not be confused with an arbitrary local process capable of speaking to a socket.

## Sessions, observation and takeover

Prefer independently controllable sessions as a product direction, without requiring that every operator always receive a separate session. Principals can be granted view-only, control, or administrative authority over each session. Multiple observers are allowed; an initial conservative input model permits one active controller per session.

Takeover is an **explicit authenticated operation** by the owner or another principal holding a delegated override capability. It is not triggered merely because a physical pointer moved or someone appeared at a viewer. There is no privileged "human" class and no automatic right for one ordinary operator to replace another.

For any control handoff, the target session must:
1. Validate that the requesting principal has override/control authority.
2. Block new actions under the old lease and coordinate in-flight semantic and conventional input at the actual enforcement boundary.
3. Discard or account for pending input before confirming transfer; already completed external effects cannot be undone.
4. Invalidate stale targets, publish the ownership transition, and allow the new controller to refresh state before acting.
5. Require an explicit new lease and current state before a previous controller can resume.

Physical input needs a trusted binding to a principal/session and trusted compositor/input enforcement; physical device events alone do **not** prove operator identity. Remote observers and remote interactive controllers remain separate grants. The exact binding, preemption barrier, compositor strategy and recovery path are unresolved.

## Boundaries and limitations

LoopBridge knows which **authenticated principal** requested a Bridge operation. It does not classify the intention or origin of every Linux syscall. Processes with unrestricted session, root or kernel authority can bypass API-level policy; avoid giving untrusted software ambient owner authority. Confinement of locally executing untrusted code and protected resources is required independent of Bridge authentication. Trusted applications and administrators keep their documented trust boundaries.

When privilege is legitimately delegated, consequences are attributed to the principal and its grants; do not claim guarantees against a malicious or compromised owner. An operator-neutral model does not make authorization optional.

See [product definition](PRODUCT_DEFINITION.md), [interaction model](INTERACTION_MODEL.md), [security model](SECURITY_MODEL.md) and [LoopBridge](LOOPBRIDGE.md).

## Bounded authority contract for M1

See [Session Authority V1](design/SESSION_AUTHORITY_V1.md) for precise control-plane invariants, the real enforcement barrier, acceptance tests and boundaries for M1.3A/B/C. Its operation names and state model are exploratory and do not replace the accepted product requirements above.
