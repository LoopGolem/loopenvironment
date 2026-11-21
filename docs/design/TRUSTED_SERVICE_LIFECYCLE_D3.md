# D3 — Unprivileged Ingress Lifecycle and Failure Contract

**Status:** D3 implementation under review. The V0.7.1 unrestricted same-UID host-isolation gate remains **PARTIAL**. No dedicated Linux service identity, public cross-UID socket, systemd service or privileged host configuration is deployed here.

## Purpose

Extend the [D2 admission contract](TRUSTED_SERVICE_INGRESS_D2.md) with a real, explicitly enabled Unix socket listener lifecycle that reuses the existing LoopBridge `Broker`, `Server`, authenticated RPC and durable journal, while preserving the V0.7.1 default behavior. D3 uses same-UID temporary fixture paths only.

## Implementation

- `managed_ingress_listener(layout)` requires a **pre-existing** service-owned ingress parent directory with exact mode `0700`, a non-symlink final parent, and a disjoint resolved private root. It rejects oversized Unix paths and never automatically deletes a preexisting path, including sockets and symlinks.
- When the listener successfully binds, its socket is mode `0600`. It is closed at shutdown and its path is unlinked only when the path still refers to **that same socket inode**. Replaced files and directories are not deleted.
- `serve(..., ingress_layout=..., ingress_policy=...)` is an **opt-in** integration. Both options must be present; their types, private-root match and configured service UID are validated before startup. It uses the existing private-root lock, journal, adapter, broker and connection handling.
- In opt-in mode, the service exposes only the new ingress endpoint; any existing legacy endpoint under `private_root/socket/control.sock` causes a startup failure. There is **no silent fallback** to the legacy socket.
- Without these options, `serve()` retains the existing V0.7/V0.7.1 listener location, peer admission and semantics, including the ordinary fixture lifecycle.
- The broker still obtains `SO_PEERCRED` from the actual Unix peer. OS admission does **not** authenticate a principal; valid credentials and grants remain mandatory.

## D3 local test plan

Run the usual regression suite in CI. The new `tests/test_service_ingress_d3.py` exercises a temporary fixture listener over **real AF_UNIX sockets**:

| Area | Expected outcome |
| --- | --- |
| Startup/shutdown | Correct socket `0600`, authenticated RPC, cleanup of own endpoint, private state preserved |
| Authorization | An unadmitted kernel peer with valid bearer denied; invalid/unauthed peer denied; authorized observer requires grant |
| Competing processes | Second service cannot acquire same private runtime or displace current ingress |
| Occupied ingress path | Existing socket is not unlinked, replaced or silently recovered |
| Unsafe path | Missing parent, symlink parent or permissive directory refused |
| Split config | Missing policy/layout, mismatched UID and mismatched private-root mapping refused |
| Legacy state | A legacy endpoint blocks new ingress rather than leaving two front doors |
| Credential lifecycle | Restart with new verifiers rejects prior credentials; persistent state retained |
| Teardown race | Replacement regular file at former socket path is not deleted on shutdown |
| Backward compatibility | Legacy `serve()` can still operate when the new ingress is not requested |

The tests are intentionally unprivileged. They do not create other OS users, change file ownership, install packages or start private graphical sessions.

## Ownership and deployment decisions for D4

This prototype keeps the ingress parent `0700` and its socket `0600` so only the **current UID** can connect. Therefore **it cannot yet support an operator with a different Linux UID**. A D4 configuration must explicitly decide and test how the public ingress endpoint is reachable by a designated operator identity without allowing the operator to traverse the private service runtime. Candidate designs include a managed directory group/ACL (with restrictive membership), or narrowly scoped systemd socket activation with verified socket ownership. This choice is **not** made or automatically applied by D3.

Recommended D4 design inputs:

1. Distinct dedicated service UID and the ordinary desktop/operator UID; no routine root broker.
2. Service-owned private runtime and durable state with explicit ownership and mode checks, plus a separate operator-facing ingress path.
3. Authenticated principal enrollment, token distribution and rotation rules. Do not put owner credentials in files readable by the ordinary untrusted desktop account without a considered trust model.
4. Single authoritative ingress path, lifecycle-managed failures, no downgrade to shared-UID mode when hardened setup fails.
5. A disposable VM snapshot and operator-approved changes, including exact rollback instructions.

Whether a static service UID or systemd `DynamicUser=` best fits durable workspaces and upgrade/rollback is still a **decision gate**, not a claim of completed provisioning. D4 should select and document one tested option.

## Review acceptance / remaining gates

- [ ] GitHub CI confirms the full Python suite, including D3's local socket tests, is green.
- [ ] No changes to existing private Sway startup, live presentation media, captured frames or operator grant model.
- [ ] Opt-in failure cases are fail-closed, do not unlink unrelated paths, and retain durable journal/workspace state.
- [ ] D4 design and provisioning actions remain separately approved; no privileged configuration is changed by the D3 PR.

**PARTIAL remains the correct qualification:** neither ordinary-user direct private Wayland/Sway IPC/D-Bus denial nor a working cross-UID authorized viewer has been demonstrated by D3. Those require the D4 lab environment and D5 qualification matrix in [Trusted Service Boundary V1](TRUSTED_SERVICE_BOUNDARY_V1.md).
