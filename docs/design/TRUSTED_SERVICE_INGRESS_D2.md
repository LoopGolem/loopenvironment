# D2 — Trusted Service Ingress Contract (unprivileged prototype)

**Status:** D2 implementation proposal, not a deployed cross-UID service. **Overall private-session isolation: PARTIAL.** This is the second delivery under [Trusted Service Boundary V1](TRUSTED_SERVICE_BOUNDARY_V1.md) and [ADR 0012](../DECISIONS/0012-trusted-service-identity-boundary.md).

## Boundary being modeled

The hardened installation will have two *different* OS identities: an ordinary operator account (for clients such as Codex, the Shell and viewers), and a dedicated unprivileged account that owns the private-session runtime. LoopBridge principal names (\`owner\`, \`delegate\`, \`observer\`) are **not** OS accounts.

1. **OS admission:** read the connecting peer's identity from the Unix-domain socket using the kernel-provided \`SO_PEERCRED\`, not a JSON field or claimed process name; consult an explicit configured UID allowlist.
2. **Principal authentication:** even an admitted UID must authenticate with a valid bearer credential; the client cannot set its own role.
3. **Authorization:** capabilities, session scope, leases, revocation and viewer/capture separation continue to be enforced by the existing broker.
4. **Private runtime isolation:** the intentionally client-reachable Bridge ingress socket must be separate from the service-owned private compositor and D-Bus runtime paths. A public ingress socket conveys no authority to receive raw private compositor descriptors.

No external agent or ordinary host client should receive a private Wayland, Sway IPC, session D-Bus, input or capture file descriptor. Normal trusted execution-plane components and applications inside the private session continue to use the necessary internal compositor interfaces.

### Proposed path layout (not provisioned)

| Function | Illustrative path | Intended owner/access |
| --- | --- | --- |
| Authenticated local ingress | \`/run/loopbridge-ingress/control.sock\` | Service-managed listener reachable by specifically admitted local clients; final group/ACL/ownership pending D3/D4 |
| Service-owned private runtime | \`/run/loopbridge-private/\` | Dedicated service UID; not traversable by ordinary operator UID |
| Durable state / workspace | \`/var/lib/loopbridge/private/\` | Service-owned; exact layout and persistence require D3/D4 review |
| Viewer and Shell | Ordinary desktop session | Connect to ingress and authenticate as a scoped Bridge principal |

**Important:** these paths are illustrative design contracts. The current V0.7.1 private sockets and service lifecycle have **not** moved to them. \`IngressLayout\` checks only absolute, disjoint lexical locations; it does *not* resolve symlinks, set permissions, create sockets or guarantee directory ownership.

## D2 implementation

- \`loopbridge/service_ingress.py\` defines immutable \`PeerAdmission(service_uid, allowed_uids)\` and \`IngressLayout(public_socket, private_root)\`. Both validate explicit inputs and reject invalid configurations.
- \`loopbridge/broker.py\` accepts an optional \`ingress_policy\`. With no supplied policy it constructs \`PeerAdmission.local_only(uid)\` and **retains existing single-UID behavior**. If an explicit policy is provided, its \`service_uid\` must match the broker's configured UID.
- Both initial authentication and later requests check the configured peer admission **in addition to** existing principal authentication, scopes and session/lease checks. Invalid reauthentication still removes existing authority.
- \`tests/test_service_ingress_d2.py\` uses synthetic \`Connection\` objects to verify explicit UID admission, rejection of unlisted UIDs even with a valid token, mandatory bearer auth, absence of implicit observer grants, invalid-policy rejection, and ingress/private path separation.

The existing Unix-domain server already obtains \`SO_PEERCRED\` for connections. **D2 does not yet change \`serve()\` or private manager startup to pass a cross-UID policy**, and it does not create a separate public listener. This is intentional: exposure and ownership of a new cross-UID socket must be designed and qualified in D3/D4 rather than introduced with incomplete host privileges.

## D2 acceptance and non-goals

| Gate | D2 evidence / required behavior |
| --- | --- |
| Existing default behavior | Without explicit peer policy, only the configured service UID is admitted; existing tests remain green |
| Peer admission not equal to authorization | Whitelisted UID alone cannot authenticate, discover, capture or control |
| Credential and scope enforcement | Wrong bearer denied; valid observer without grants denied; reauthentication failure clears identity |
| Explicit roster | Invalid, empty or mismatched peer policies rejected; no implicit UID role promotion |
| Ingress/private path separation | Disjoint absolute layouts accepted; nested/relative/traversal forms rejected lexically |
| Existing V0.7 stream | No changes to media transport, compositor startup or presentation grants |
| Host safety | No user creation, systemd installation, root action, chmod of live sockets or host config modifications |

**Remaining PARTIAL:** tests use synthetic UIDs, not two actual Linux OS users. They do not demonstrate kernel-enforced denial of direct private display and D-Bus access. A path shape check is not a substitute for filesystem ownership validation. Owner-token security and actual cross-UID socket placement remain outside D2.

## Next deliveries

**D3:** decide the ingress listener's real path ownership and lifecycle, model credential provisioning and failure recovery, and add unprivileged integration tests on transient local sockets. Ensure the hardened profile never silently falls back to a same-UID profile. No privileged changes.

**D4:** only after explicit operator authorization, provision the separate Linux service identity in the disposable VM and validate that legitimately authorized Shell/viewer clients still work.

**D5:** execute the scoped denial and positive functionality matrix from [Trusted Service Boundary V1](TRUSTED_SERVICE_BOUNDARY_V1.md), independently review the evidence, and lift the **particular host-identity gate** to GO only if all mandatory checks pass. Other product security and takeover gates remain independent.
