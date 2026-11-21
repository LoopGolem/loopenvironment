# D4.2A.1 — Dedicated service administrative bootstrap

**Status:** unprivileged repository implementation and fixture validation, pending review and real D4.2B deployment. The host boundary remains **PARTIAL**. This is a narrow complement to [D4.2A](TRUSTED_SERVICE_BOUNDARY_D42A.md), prompted by the D4.2B preflight finding that the manager lacked an integrated, reviewed administration workflow.

## Scope and authorization

The installed launcher now provides three explicit operations in addition to its unchanged default service mode: `verify-installed`, `admin-init`, and `admin-ready`. A fixed internal `ready-client` action is used by the readiness parent. There is no sudo policy, new setuid binary, general administrative RPC proxy, automatic install or systemd activation. The administrator must already have independently authorized root access in a trusted context. Do not authorize arbitrary programs or commands to run as the dedicated service account from the ordinary desktop.

All actions require the root-controlled, approved installed versioned release and pinned manifest digest; they are rejected when run from a checkout or staging tree. The administrative initializer and readiness parent require real/effective UID and GID 0. The readiness child requires the configured non-root service UID/GID and no supplementary groups. The service's normal `--client-uid` argument remains mandatory in service mode and is rejected with administrative actions.

## D4.2B sequence (not executed by D4.2A.1)

Verify the operator's snapshot and confirm the service is stopped and has never been initialized. Synchronize the merged Git revision and build again from that revision; the old digest is not the digest of this release. Transfer and verify the reviewed tree in root-controlled staging, checking its provenance before executing any code as root. Install only the approved tree in the documented root-controlled location, then use the read-only action to check the installed digest.

Under explicit operator approval, provision the static `loopbridge-svc` account and group, and prepare the following **empty** directories with no extended access/default ACLs:

| Directory | Ownership | Mode |
| --- | --- | --- |
| `/var/lib/loopbridge-admin` | root:root | 0700 |
| `/etc/loopbridge/credentials` | root:root | 0700 |
| `/var/lib/loopbridge` | loopbridge-svc:loopbridge-svc | 0700 |

The outer directories and installed release ancestry must be trusted, root-owned and not group/other-writable. Keep `/run/loopbridge-private` absent until normal systemd activation; the initializer refuses any existing runtime, even if empty. Provision the separate ingress directory and its exact nominal ACL according to D4.2A and the approved D4.2B plan. This tool does not create that directory or set up boot-time provisioning.

Example command contract, **not authorization to run**. Set REVISION and DIGEST to externally reviewed literal values. Run from the trusted console; never grant a general-purpose escalation path or pipe a bearer through an ordinary desktop shell.

```sh
/usr/bin/python3 -I -B "/opt/loopbridge/releases/$REVISION/launcher.py" \
  --manifest-sha256 "$DIGEST" --action verify-installed
# Following separate approval; execute in the trusted root context:
/usr/bin/python3 -I -B "/opt/loopbridge/releases/$REVISION/launcher.py" \
  --manifest-sha256 "$DIGEST" --action admin-init
# Following separately approved installation/start of the unit, with no sessions:
/usr/bin/python3 -I -B "/opt/loopbridge/releases/$REVISION/launcher.py" \
  --manifest-sha256 "$DIGEST" --action admin-ready
```

Success messages are fixed and do not include credential values or private session data. Confirm the actual systemd handoff and unit identity independently. Do not run these examples as privileged scripts from the checkout.

## Fresh bootstrap and recovery

The initializer validates exact owners/modes, rejects symlinks, access/default ACLs and overlapping directory identities, locks the three directory inodes, and refuses nonempty directories. Each output uses an exclusive temporary file, file sync, a no-replace hard-link publication and directory sync. The output is three files:

- `/var/lib/loopbridge-admin/owner.token`: root:root 0600, manager owner bearer. Only the root administrative workflow reads it.
- `/etc/loopbridge/credentials/manager-verifiers.json`: root:root 0600, version 1 manifest with three independent verifiers for the manager. Unused manager delegate and observer bearers are not retained.
- `/var/lib/loopbridge/verifiers.json`: service UID/GID, 0600, version 1 fresh empty registry, published last.

This is **not a multi-file atomic transaction**. An interrupted operation may leave one or more files. The admin initializer refuses retries on any nonempty target directory. It does not delete or overwrite previously published output or seed an existing installation. Stop and review partial state, preserve evidence, and seek explicit approval for recovery or restoration of the preinstallation snapshot. Never overwrite a previously used registry, or roll back an enrolled registry to the fresh seed.

## Authenticated readiness

The root parent validates the protected owner file and manifest and checks that the bearer matches the owner verifier. It starts only the verified installed launcher in the dedicated non-root account with its primary group and no supplementary groups, passing the bearer over an anonymous stdin pipe. No shell, bearer in argv/environment, inherited extra file descriptors, or payload logs. Both credential-holding processes disable core dumps and set non-dumpable before reading credential data. The child closes bootstrap stdin after consumption, checks the fixed private manager endpoint's ownership/mode and kernel peer UID, and calls only `auth` and `private.list`. Success requires owner authentication and an empty instance list. Output and errors from the child are discarded; timeout or any mismatch fails readiness.

This is deliberately a **fresh-deployment** check, not a general client or health endpoint for active sessions. It does not create a graphical session, delegate a grant, stream media, rotate credentials, or expose owner authority on the ordinary ingress. Subsequent D4.2C administrative orchestration and observer enrollment require a separately reviewed and authorized workflow. The actual root-to-service credential handoff, deployment ACL, systemd credential mount and process identity still need validation in the target VM. Unprivileged tests exercise temporary directories, synthetic credentials, mocked privilege handoff and actual local Unix RPCs; they are not evidence of real cross-UID isolation.

## Gates

- D4.2A.1: implementation and CI regression evidence; PR review before merge.
- D4.2B: confirmed snapshot, approved release/install, exact ownership, initial registry, actual systemd credential delivery and authenticated empty manager readiness.
- D4.2C: real private graphical session and authorized GTK viewer, separately approved.
- D5: original T01–T10 matrix; no GO inferred from any preceding stage.
