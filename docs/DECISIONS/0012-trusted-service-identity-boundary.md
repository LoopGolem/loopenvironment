# ADR 0012 — Trusted Linux Service Identity for Private Sessions

**Status:** Proposed — architecture under review, not an implemented or accepted security guarantee

**Date:** 2026-11-21

## Context

LoopBridge V0.7.1 demonstrates opt-in instance-scoped credential verifiers, selected process-local protections and a working low-latency presentation path. Its [qualification](../LOOPBRIDGE_V0_7_1.md) remains **PARTIAL** for unrestricted same-UID host processes. In the Debian lab, a process under the ordinary desktop account could reach private Wayland, Sway IPC and D-Bus endpoints directly. It was also able to inspect some host-visible process information. Sandboxed clients with distinct namespace views passed their separate authorization gates.

The current private manager creates a Bubblewrap instance from its own OS UID. Private compositor/session resources consequently share a relevant host identity with the desktop account, despite namespaced views and authenticated Bridge RPC. File modes, opaque paths, bearer separation and `PR_SET_DUMPABLE=0` are useful layers but do not independently establish an OS principal boundary for an unrestricted same-UID process.

The accepted product constraints remain: LoopEnvironment runs on **existing Linux**, principals are neutral as to human/AI origin, operator authority derives from grants rather than physical-device origin, and direct private-session access must be mediated for untrusted external clients. See [ADRs 0006](0006-mandatory-agent-mediation.md), [0008](0008-operator-neutral-authority.md), [0010](0010-linux-environment-not-os.md) and [0011](0011-session-presentation-and-operator-shell.md).

## Proposed decision

### D1 — Separate OS identity from the ordinary operator account

For the future hardened deployment, run trusted private-session services, compositor supervision and private runtime ownership under a **dedicated Linux service UID distinct from the user's desktop UID**. The dedicated account is not an owner principal and is not an agent: it is a host OS security boundary. Service components must not routinely execute as root. A one-time, explicitly authorized provisioning action may be required to establish identities and filesystem/service ownership.

The service-owned runtime and private display/IPC paths are unavailable to the ordinary desktop UID except through the explicitly exposed Bridge front door. Do not treat UID separation alone as proof that every socket or inherited descriptor is protected.

### D2 — Explicit trusted ingress; no raw private socket exposure

Expose a narrowly scoped, authenticated LoopBridge Unix-domain endpoint for approved local clients. Treat the OS peer identity as an admission signal, not as authority to observe, control, capture or administer a session. Continue enforcing principal credentials, exact session origin, capability grants, leases, expiry and revocation. The presentation viewer, Shell and remote-client adapters use the same mediated authority model and do not receive private Wayland, Sway IPC, session-bus or input/capture descriptors.

Private compositor, accessibility and D-Bus access remains accessible to **trusted execution-plane components inside the managed session** as needed for normal applications. This proposal concerns untrusted external host clients, not a promise to eliminate normal application-to-compositor traffic.

### D3 — Distinct runtime paths and controlled lifecycle

Keep private socket directories, workspaces, credentials, journal state and temporary resources under service-controlled ownership and mounts. Use explicit, reproducible startup/shutdown and cleanup, including a safe failure path that does not fall back to a weaker ambient same-UID deployment. For hardened mode, require instance-scoped verifier enrollment instead of silently accepting legacy credential sharing.

Any systemd system-unit, static service user or `DynamicUser=` design remains a **candidate** until portability, persistent state, restart semantics and least privilege have been evaluated. A user-level unit running under the operator UID by itself cannot meet D1.

### D4 — Credential authority and limits

The Bridge service should consume credential verifiers without unnecessarily receiving persistent bearer-token files. A compromised ordinary desktop account may expose credentials accessible to that same account; protecting the owner's client-side authentication material is a separate, explicit enrollment and storage requirement. No GO claim may imply safety after an owner credential is stolen. The hardened profile must document how legitimate owner clients authenticate without making persistent owner authority ambient to all processes of the desktop account.

Operator/owner principal semantics are unchanged: a human, model or automation can operate an authorized principal. A dedicated service UID does not grant a biological human special privilege.

### D5 — Qualification determines GO, not implementation alone

The new OS service identity is a **design hypothesis**. The former V0.7.1 same-UID gate may become **GO (bounded Debian VM profile)** only after a reproducible authorized test demonstrates both:
1. Direct private compositor, IPC, display, accessibility and sensitive runtime/credential paths are not accessible to an **untrusted unrestricted process under the ordinary desktop UID**, including unintentional inherited access.
2. Normal authorized LoopBridge clients retain correct operation, separation of grants, revocation, live viewing, lifecycle, cleanup and the previously measured performance threshold.

Do not widen that result to root, kernel compromise, an attacker controlling an authorized service identity, trusted in-session applications, stolen owner credentials, remote deployments or production security in general. Historical M1.3B takeover/preemption gates remain separate.

## Consequences

- A small deployment/provisioning surface will need explicit operator permission and a reviewable rollback plan; it must not silently change the Debian VM or its primary Sway session.
- Communication and resource ownership boundaries must be explicit in code and tests rather than inferred from `os.getuid()` equality.
- Legacy experimental mode can remain for compatibility but must be clearly marked as **not qualified for unrestricted same-UID isolation**; no automatic insecure fallback.
- The initial V0.8 Shell can continue as a normal authenticated observer client while this security qualification remains pending.

## Delivery sequence and decision gates

The [trusted-service boundary plan](../design/TRUSTED_SERVICE_BOUNDARY_V1.md) defines five short, separately reviewed deliveries. This ADR contains the **proposed architecture**, not authority to install units, create users, modify privileged system settings or claim a GO.

## Open questions

- Should the service UID be static or assigned dynamically, considering persistent session journals/workspaces and upgrades?
- What is the smallest host-authorized installation interface and its rollback behavior?
- How will the Bridge-facing endpoint allow authorized operators without broadening private runtime traversal?
- What are the trusted and untrusted boundaries for in-session applications and remote clients?
- How can owner enrollment and credential storage remain defensible against untrusted host-account processes?
- Which display, session-bus, process-inspection and file ownership mechanisms need independent host verification on Debian 13 and other Linux distributions?

## References

- [Current V0.7.1 evidence and open gate](../LOOPBRIDGE_V0_7_1.md)
- [LoopEnvironment security model](../SECURITY_MODEL.md)
- [Linux Unix-domain sockets (unix(7))](https://man7.org/linux/man-pages/man7/unix.7.html)
- [systemd service identity and credentials](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
