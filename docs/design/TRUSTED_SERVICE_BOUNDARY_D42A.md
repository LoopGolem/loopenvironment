# D4.2A — Preparing the dedicated Linux service boundary

**Status:** repository implementation and unprivileged fixture evidence. Host isolation remains **PARTIAL**. D4.2B provisioning, D4.2C integrated smoke and D5 qualification require separate operator decisions. [ADR 0012](../DECISIONS/0012-trusted-service-identity-boundary.md) · [D5 qualification matrix](TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5).

## Integration with D3

The checkout and remote `main` matched D3 at `2e699c83a8f6776e53d77edf37bf2f0bdfcf39fe`. The D4.1 `CONDITIONAL` outcome was supplied in the task. The repository had no tracked D4.1 report to compare line by line.

D3's reusable `serve()` ingress is a same-UID listener. The private manager still launched Bubblewrap as its own Linux UID, and its Bridge published `runtime/socket/control.sock` inside a private runtime bind mount. Manager and Bridge checked `SO_PEERCRED` independently. The manager held its verifier history in memory and piped the selected manifest to the private session. The old instance directory held temporary resources alongside the workspace and journal, and startup attempted to compile the Wayland input/capture and stream helpers. Those legacy entry points remain available under their existing policy. The explicitly selected candidate uses the [installed launcher](../../deploy/loopbridge/launcher.py).

## Ingress and principal authority

The candidate launcher verifies the static service account and primary group `loopbridge-svc` and accepts one explicitly configured, existing client UID. The client UID is nonzero and distinct from the service UID. The service publishes one filesystem Unix socket per random instance ID in a dedicated directory. The private manager returns `ingressSocket` to authenticated administrators after the Bridge reports ready and its isolated namespace checks pass. Administrators can distribute this path and the presentation identity to an authorized operator. The UID merely admits a connection. Normal RPC authentication, grants, leases and epoch checks still occur in the destination Bridge.

| Path | Candidate ownership and effective access |
| --- | --- |
| `/opt/loopbridge/releases/<commit>/` | Root-owned versioned tree. Service reads code and executes the approved helpers. |
| `/run/loopbridge-private/` | Service UID and primary GID, mode `0700`. Contains `manager.sock`, disposable instance runtime and both per-instance Bridge listeners. |
| `/run/loopbridge-ingress/` | Service-owned. Owner `rwx`, named client UID `--x`, mask `--x`, group and other empty. No default ACL. |
| `/run/loopbridge-ingress/<id>.sock` | Service-owned. Owner `rw-`, named client UID `-w-`, mask `-w-`, group and other empty. |
| `/var/lib/loopbridge/` | Service UID and primary GID, mode `0700`. Stores the verifier registry and per-instance durable state. |
| `/etc/loopbridge/credentials/` | Root-only provisioning source for the systemd credential. Owner bearer storage is separate and restricted to the administrative workflow. |

The ingress checks the directory UID, GID, canonical paths, exact access ACL and absence of a default ACL. It installs the socket's nominal access ACL via the Linux POSIX ACL xattr and reads it back before `listen()`. With an extended ACL, the group mode bits represent the ACL mask. Mode `0710` or `0620` by itself does not establish the required admission policy. Occupied paths fail startup. Cleanup checks the socket inode before unlinking. [Linux POSIX ACL tags](https://github.com/torvalds/linux/blob/master/include/uapi/linux/posix_acl.h) · [Linux ACL xattr format](https://github.com/torvalds/linux/blob/master/include/uapi/linux/posix_acl_xattr.h).

The manager and the session's administrative Bridge socket are private. The latter and the relay destination use the same session Broker, grants, lease and presentation state. The Broker rejects the logical `owner` on the relay destination, including during reauthentication. Admission is local to the relay's front socket. The private Broker sees a service-UID peer on the backend and independently validates the bearer and role.

## Relay and presentation

The manager registers the destination `runtime/socket/relay.sock` once per instance. The relay checks the inbound kernel `SO_PEERCRED`, pins the expected destination socket inode, and verifies the connected backend's kernel UID. Request data cannot change the destination. The relay copies bytes in both directions, including the JSON reply to `presentation.open` and the subsequent media stream on the same connection. Uses of `presentation.status`, including the viewer's separate status connection, still go to the same Broker. A viewer's disconnect, grant expiry and grant revocation end capture through the existing presentation lifecycle.

The relay has eight concurrent connections per instance, a one-second backend connection timeout and a 30-second bidirectional inactivity limit. The limit resets on useful byte transfer or EOF progression. Each direction has at most 64 KiB of data queued in userspace, plus bounded kernel socket queues. The relay pauses reads when a direction fills and resumes on writable progress. A half-close drains that direction before propagating EOF. A fully closed Bridge can drain its final bytes to a connected client for up to two seconds. Transport errors, viewer close and session stop terminate copying, with session stop cancelling and joining relay workers before stopping the private process. The relay uses byte reads and writes, so Linux discards ancillary file descriptors at the read boundary. There is no payload, token or frame logging.

Like the pre-existing transport, a broker revocation cannot retract bytes already queued for an authorized stream. At the drain deadline the relay drops remaining userspace data. Bytes already in the client's kernel queue can still arrive. The Bridge stops new capture for the revoked grant and constrains actuation separately. The relay has no grant state or RPC parser. Measure buffered-media drain, revocation timing and performance on the target deployment during D5.

## Bootstrap, rotation and recovery

- The manager accepts `manager-verifiers.json` only via `LoadCredential=` and the expected `CREDENTIALS_DIRECTORY=/run/credentials/loopbridge.service`. It checks trusted ancestors, rejects symlinks at the store and credential, and requires a read-only credential mount. It accepts either root ownership with the exact named service-UID ACL (directory `0550`, file `0440`) or a service-owned directory `0500` and file `0400` on that read-only mount. These are candidate layouts for systemd 257. The actual delivery on the target unit is part of deployment validation. [systemd 257 credential implementation](https://github.com/systemd/systemd/blob/v257/src/core/exec-credential.c).
- The credential is a version 1 verifier manifest with distinct SHA-256 verifier digests for `owner`, `delegate` and `observer`. Provision independently generated, high-entropy bearers out of band. A hardened `private.start` uses the existing `credentialVerifiers` RPC field to enroll an independent set. The manager sends only the resulting manifest through a private bootstrap pipe to the session. The Bridge replaces its bootstrap stdin after reading it. The service's start command, persistent environment and logs carry no bearers.
- The state directory is locked on the manager's lifetime. The registry `verifiers.json` is service-owned mode `0600`. The operator seeds it exactly once for a fresh deployment. The manager rejects missing, invalid or unsafe data. It reserves every session digest before attempting launch and never releases a reservation after a failed or stopped instance. Atomic file replacement follows file sync and is followed by directory sync. A failed write prevents further enrollment in that process. A restart reads only the published record. A manager manifest can be reused unchanged on restart. Rotation requires a completely fresh set and retires the old one permanently.
- No session or grant is replayed on restart. A replacement gets a new instance ID, workspace, Broker epoch and verifier set. The old session's bearer stops authenticating when its Bridge is stopped and cannot be enrolled again. Grant TTL governs grant authority and media independently from bearer validity. To retire a compromised session bearer, stop the affected instance and use fresh credentials for a replacement.
- The hardened runtime and socket tree are disposable. Each `state/sessions/<id>/` retains the workspace, annotations and intent/receipt journal. An archived instance can be queried by ID using private `private.status`; an unresolved intent remains blocked. There is no automatic repair, replay, reassignment of the workspace or claim of cancellation. Resolve uncertainty through independently verified state and the operator-approved recovery process before reuse of affected data.

## Release and systemd contract

Build an approved revision using existing tooling and a new temporary staging directory. The build reads tracked files from `git archive`, compiles both x86-64 helpers before activation and creates a versioned file inventory with SHA-256 hashes. Record the commit and manifest digest through the approved release process before transferring the artifact. Use that recorded digest to verify the staging tree and pin the digest in the unit. The local build is the source of the binary artifacts. The checksums rely on the review of the commit and build environment for provenance. [Staging tool](../../tools/prepare_loopbridge_release.py).

```sh
/usr/bin/python3 -I -B tools/prepare_loopbridge_release.py build <commit> <existing-staging-parent>
/usr/bin/python3 -I -B tools/prepare_loopbridge_release.py verify <staged-release-dir> <approved-manifest-sha256>
```

The launcher requires a versioned installed path, root ownership and non-writable ancestry for group and other. It checks the file inventory and helper type, permissions and executable mount. It explicitly adds the verified release to the isolated Python import path. The private supervisor and Bridge add the read-only package bind at `/app` inside Bubblewrap. The installed profile performs no C compilation. The private supervisor checks both helper paths again inside the namespace before starting Sway.

The [candidate unit](../../deploy/loopbridge/loopbridge.service.in) selects a static account to retain ownership of durable state over restarts. `Type=exec` confirms program execution. Confirm that the private manager responds to an authenticated RPC before treating it as ready. `RuntimeDirectory=` manages the private runtime and `StateDirectory=` manages the persistent service state. A separately provisioned ingress directory retains the nominal ACL and is exempted from `ProtectSystem=strict` through `ReadWritePaths=`. `ProtectHome=yes` keeps the service independent of the ordinary user's home. `NoNewPrivileges=yes` and the empty capability bounding set require unprivileged Bubblewrap with functioning user and mount namespaces. Leave namespace restrictions compatible with Bubblewrap, including the nested browser sandbox. Check the release source and in-namespace binds for executable mounts and the helpers' dynamic libraries. The Python service owns dynamic listener creation and verification. Treat socket activation as a separate design requiring an explicit inherited-FD and lifecycle contract. [systemd execution settings](https://www.freedesktop.org/software/systemd/man/257/systemd.exec.html) · [Bubblewrap namespace model](https://github.com/containers/bubblewrap/blob/main/README.md).

## Evidence from D4.2A

| Command or fixture | Observed result |
| --- | --- |
| `python3 -B -m unittest discover -s tests` at D3 | 198 passed |
| `python3 -B -m unittest discover -s tests` with D4.2A | 233 passed, 35 added |
| `systemd-analyze verify --generators=no --man=no <local-rendered-unit>` | Exit 0 on systemd 257 using synthetic unit substitutions |
| `prepare_loopbridge_release.py build` and `verify` under `python3 -I -B` | Built both helpers and verified a staged release from the implementation commit. The isolated import check resolved the staged package in the presence of a synthetic `PYTHONPATH`. |
| `setpriv --no-new-privs bwrap --unshare-all …` with a local Unix socket fixture | Unprivileged Bubblewrap started a distinct user namespace and the connected Unix peer retained the current UID. The fixture used the same real Linux UID on both sides. |

The tests use actual filesystem ACLs and Unix sockets with synthetic data. They verify rejection of the real unlisted peer and simulate positive distinct-UID admission. They also run a synthetic capture subprocess through the existing viewer protocol to exercise upgrade, frame layout, status, revocation, expiry and viewer exit. The principal verifier and journal tests cover restart, replacement and incomplete or uncertain storage. The package test rejects a staged or checkout invocation of the installed launcher.

## D4.2B checklist for separate operator approval

1. Review the implementation and release digest. Snapshot the disposable VM, identify the ordinary UID, and record the primary Sway baseline.
2. Review creation of a dedicated static account and group with no login. Confirm the approved administrative workflow can run a narrowly authorized client with the service UID. Keep all owner bearers in restricted administrative storage or protected process input. Review token enrollment and distribution for the observer and delegate separately.
3. Review root ownership and verified artifact transfer to the versioned path. Confirm executable mounts, system package dependencies and unprivileged Bubblewrap. Set the resolved revision, digest and client UID in the reviewed unit.
4. Prepare separate runtime, state and ingress ownership. Decide and review how to recreate the ingress directory and exact ACL at boot before the unit starts. Confirm the target filesystem accepts named ACLs on both directories and sockets. Seed a fresh `verifiers.json` with `{"version":1,"manager":null,"used":[]}`, service ownership and mode `0600`. Preserve existing registry state on any upgrade or restart.
5. Prepare the restricted systemd credential source from a fresh versioned verifier manifest. Inspect the delivered mount, ownership and effective ACL in the service context. Verify the rendered unit, establish authenticated access to the private manager and review the service cgroup without affecting the primary graphical session. Arrange the separate D4.2C run before enrolling live clients.

## Stop and rollback proposal

Stop the reviewed unit and confirm that its cgroup has ended and ingress no longer accepts connections. Inspect any abandoned socket against its recorded instance and only remove a confirmed stale deployment artifact under explicit approval. Keep the verifier registry, retired workspace and journals. Disable or remove only the unit, ingress setup, credential source and account changes made by the approved provisioning. An approved earlier compatible release must use the current durable registry. If compatibility or state integrity is uncertain, leave the hardened service stopped pending review. Never restore an older registry to retire the deployment, resume old grants or enable a legacy endpoint as a fallback.

## D4.2C and D5 checks

- D4.2C must use the real service and ordinary UIDs to verify socket ACL reachability, rejection of unlisted UIDs, real `SO_PEERCRED` through the relay, credential mount properties, namespaces and helper binds in the unit. Exercise the authorized GTK viewer, real frame delivery, stop and replacement, and verify that the primary Sway session is unaffected.
- D5 must independently verify direct private Wayland, Sway IPC, accessibility and D-Bus denial, process and credential isolation, descriptor boundaries, owner storage, authorized operation and control separation, crash and rollback behavior, and the existing streaming performance thresholds. The unprivileged fixture suite leaves the host isolation gate at **PARTIAL**.
