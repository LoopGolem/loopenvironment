# D4.2C — First cross-UID graphical smoke

The D4.2B handoff reports `READY_FOR_D42C`. The VM retains the installed `af6057c3bbbe83c9058c28dca2fa4abb156202fa` manager. Overall host isolation remains **PARTIAL**.

## Readiness audit

The [D2](TRUSTED_SERVICE_INGRESS_D2.md), [D3](TRUSTED_SERVICE_LIFECYCLE_D3.md), [D4.2A](TRUSTED_SERVICE_BOUNDARY_D42A.md) and [D4.2A.1](TRUSTED_SERVICE_ADMIN_D42A1.md) contracts already cover the manager, per-instance verifiers, relay and presentation. In the installed release, the relay checks kernel `SO_PEERCRED`, has a fixed socket destination, forwards bytes only and reaches a broker listener that refuses the owner principal. The separate private broker socket supports grants. The manager supports explicit offline start and stop, persistent journal retention and fresh identity on replacement. The existing GTK viewer accepts an observer credential and a pinned presentation identity. The installed administrative client only supports authenticated empty-manager readiness.

The checkout's `main` and local `origin/main` reference matched the requested base. The working tree had nine historical untracked entries. The installed release verified against its pinned digest as UID 1000. The unit was running as 980:980 (PID 16793), disabled at boot, with zero restarts. Primary Sway was PID 1617 and UID 1000. The ingress directory ACL allowed traversal only to the named client. UID 1000 received `EACCES` connecting to the private manager, and lacked read/traverse access to the private runtime, service state, root administrative directory and both credential directories. These checks preceded any private graphical session. Authenticated readiness and snapshot provenance come from the D4.2B handoff.

## Execution plan and decision criteria

1. Add a fixed-purpose administrative client for offline start, active-instance listing and explicit stop. Reuse the installed manager and broker RPCs from a separately verified release under the existing dedicated service account. Enroll a fresh observer verifier and hand back only the public pin. Exercise authentication, grant separation, cleanup and lost-reply recovery with local fixtures.
2. Run the UID 1000 client probe and GTK viewer on the existing desktop after approval. Require the kernel peer UID 980 at the public ingress, observer auth, a pinned frame painted by GTK, and an actual authority event read after a snapshot. Require rejection of administrative requests, invalid credentials and stale pins.
3. Confirm that the private compositor is a distinct service process with private namespaces. Verify that the tested private sockets, files and process resource paths fail access as UID 1000. Compare the primary Sway process identity before and after.
4. Stop the exact instance while the viewer is connected. Require disconnection, removal of the public route and disposable runtime, retention of persistent state and zero active instances. Repeat with a fresh verifier and pin to test explicit replacement and denial of the prior credential. Preserve sanitized evidence.

`READY_FOR_VM_TEST` means the code, fixture tests and procedure are ready for the separately authorized experiment. `CONDITIONAL` describes incomplete operational evidence. `BLOCKED` applies if start, viewing, events or cleanup cannot be demonstrated. A successful unauthorized access, unexpected descriptor or change to the primary Sway is `NO_GO` for this smoke.

## Unprivileged evidence

| Check | Result |
| --- | --- |
| `/usr/bin/python3 -B -m unittest discover -s tests` on the base | 249 passed |
| `/usr/bin/python3 -B -m unittest discover -s tests` with D4.2C | 255 passed |
| Focused ingress, relay, bootstrap, release, smoke and presentation suites | 84 passed |
| `git fsck --no-dangling` and the installed launcher `verify-installed` | Passed |
| `setpriv --no-new-privs bwrap --unshare-all … /usr/bin/id` | Started under UID 1000 with a transient namespace |

The fixtures use real local Unix sockets, an actual synthetic ACL layout and the manager and broker RPC contracts. The new smoke fixture simulates the admitted UID and the Calculator operation. Existing fixtures verify rejection of an unlisted kernel peer, no transfer of ancillary FDs, real byte transport, stale verifiers, bounded relay shutdown and media revocation. A lost start reply leaves a session discoverable through protected listing and requires explicit stop. The namespace preflight ran without starting Sway, GTK or a private session. The result for the repository candidate is **READY_FOR_VM_TEST**.

## Administrative workflow

The existing manager and the dedicated administration client use compatible RPCs. Build a separate versioned candidate for its three fixed actions. Keep the unit pointed at the D4.2B release. The installed candidate verifies its own inventory before each invocation. Its root parent reads the existing protected owner bearer, verifies it against the protected manifest and passes it on anonymous stdin to the verified child running as 980:980 with no supplementary groups. The child verifies the kernel peer before sending credentials.

The ordinary client generates its own one-instance observer bearer. Only the verifier goes to the administrator. The administrative child generates an independent session owner and delegate, supplies only verifiers to the manager, and keeps the session owner bearer in memory for setup. The off-line fixture launches Calculator through the private broker, grants the observer `session.discover` and `desktop.stream` for 180 seconds, and releases the setup lease. The client receives the public ingress address, session ID and epoch. Its event check reads the actual `control.released` event through the authenticated ingress. It requires the session to be idle and denies capture, input acquisition, workspace and administrative RPCs. The GTK viewer verifies peer UID 980 before sending the bearer.

The experiment requires a trusted administrator with exclusive use of the manager for its duration and explicit approval to install the additional versioned artifact, start and stop the two disposable offline sessions and issue the UID 65534 denial check. The unit, D4.2B release, boot state, ACL policy and credential source stay in place. The VM operator must confirm the `LoopEnvironment-Pre-D42B` snapshot and have a separate trusted administrative console and a terminal on the existing UID 1000 desktop. Use a reviewed commit, independently confirmed artifact digest, and keep the start, view, probes and stop within the observer grant window.

## Authorized VM procedure

### 1. Stage as UID 1000

Run in the repository. Use the reviewed D4.2C commit as `D42C_REV`.

```bash
D42C_REV=$(git rev-parse HEAD)
D42C_STAGE=$(mktemp -d /tmp/loopbridge-d42c-stage.XXXXXX)
/usr/bin/python3 -I -B tools/prepare_loopbridge_release.py build "$D42C_REV" "$D42C_STAGE"
D42C_DIGEST=$(sha256sum "$D42C_STAGE/$D42C_REV/release.json" | cut -d ' ' -f 1)
/usr/bin/python3 -I -B tools/prepare_loopbridge_release.py verify \
  "$D42C_STAGE/$D42C_REV" "$D42C_DIGEST"
printf '%s\n' "$D42C_REV" "$D42C_STAGE/$D42C_REV" "$D42C_DIGEST"
```

### 2. Verify and publish from the trusted root console

Supply the independently reviewed `D42C_REV`, `D42C_DIGEST` and `D42C_SOURCE` (the complete staged release path). The installed D4.2B verifier checks the root-controlled quarantine copy before any candidate code is executed. Then publish the verified artifact alongside the active release. Run in a dedicated Bash shell and stop on command failure.

```bash
set -e
umask 022
BASE=/opt/loopbridge/releases/af6057c3bbbe83c9058c28dca2fa4abb156202fa
BASE_DIGEST=f393d4d412cc7b2faac417fa58da9c2e8add97590b96d4a5157f06f20efa22b5
/usr/bin/python3 -I -B "$BASE/launcher.py" --manifest-sha256 "$BASE_DIGEST" --action verify-installed
[[ "$D42C_REV" =~ ^[a-f0-9]{40}$ && "$D42C_DIGEST" =~ ^[a-f0-9]{64}$ ]]
D42C_DEST="/opt/loopbridge/releases/$D42C_REV"
[[ ! -e "$D42C_DEST" && ! -L "$D42C_DEST" ]]
D42C_QUARANTINE=$(mktemp -d /opt/loopbridge/.d42c-admin.XXXXXX)
cp -R -P --preserve=mode -- "$D42C_SOURCE" "$D42C_QUARANTINE/$D42C_REV"
/usr/bin/python3 -I -B -c '
from pathlib import Path
import runpy, sys
verify = runpy.run_path(sys.argv[1])["verify_release"]
verify(Path(sys.argv[2]), sys.argv[3])
' "$BASE/launcher.py" "$D42C_QUARANTINE/$D42C_REV" "$D42C_DIGEST"
mv -T --update=none-fail -- "$D42C_QUARANTINE/$D42C_REV" "$D42C_DEST"
/usr/bin/python3 -I -B "$D42C_DEST/launcher.py" --manifest-sha256 "$D42C_DIGEST" --action verify-installed
d42c_admin() {
  /usr/bin/python3 -I -B "$D42C_DEST/launcher.py" --manifest-sha256 "$D42C_DIGEST" "$@"
}
d42c_admin --action admin-smoke-list
```

Expect `{"instances":[]}`. Preserve before/after copies of the following metadata in the evidence folder. The primary Sway PID and start time, service PID, restart count and ExecStart must match. The delivered credential mount must be read-only with the properties allowed by the [D4.2A profile](TRUSTED_SERVICE_BOUNDARY_D42A.md#bootstrap-rotation-and-recovery).

```bash
ps -p 1617 -o pid,uid,gid,lstart,args
systemctl show loopbridge.service -p MainPID -p NRestarts -p ActiveState -p UnitFileState -p ExecStart
D42C_MANAGER_PID=$(systemctl show loopbridge.service -p MainPID --value)
nsenter --target "$D42C_MANAGER_PID" --mount -- \
  findmnt -n -o TARGET,OPTIONS --target /run/credentials/loopbridge.service
nsenter --target "$D42C_MANAGER_PID" --mount -- stat -c '%u %g %a %n' \
  /run/credentials/loopbridge.service /run/credentials/loopbridge.service/manager-verifiers.json
getfacl -cp /run/loopbridge-ingress
```

### 3. Enroll and start the first session

In the UID 1000 graphical terminal, obtain the verifier. Keep the bearer in the protected client directory and record evidence separately.

```bash
D42C_CLIENT=$(mktemp -d /run/user/1000/loopbridge-d42c.XXXXXX)
D42C_EVIDENCE=$(mktemp -d /tmp/loopbridge-d42c-evidence.XXXXXX)
/usr/bin/python3 -B -m tools.loopbridge_d42c_probe generate --token-file "$D42C_CLIENT/first.token"
```

Copy only the printed verifier into `D42C_VERIFIER` on the root console. The following starts one offline session and returns the public descriptor. From the JSON set `D42C_ID` to `privateId` and `D42C_EPOCH` to `epoch`. Share the public descriptor with UID 1000.

```bash
d42c_admin --action admin-smoke-start --observer-verifier "$D42C_VERIFIER"
ps -o pid,ppid,uid,gid,comm -p "$(paste -sd, /sys/fs/cgroup/system.slice/loopbridge.service/cgroup.procs)"
```

Set `D42C_SWAY_PID` to the distinct UID 980 Sway PID in that cgroup. The namespace PID and existence checks prevent a permission denial on a nonexistent path from counting as evidence. Record process metadata and pass only the two numeric PIDs and public session pin to the client.

```bash
test "$D42C_SWAY_PID" != 1617
D42C_NSPID=$(awk '/^NSpid:/ {print $NF}' "/proc/$D42C_SWAY_PID/status")
ps -p "$D42C_SWAY_PID" -o pid,ppid,uid,gid,lstart,comm
D42C_RUN="/run/loopbridge-private/$D42C_ID"
D42C_NS_RUN="/proc/$D42C_SWAY_PID/root/private/run"
test -S /run/loopbridge-private/manager.sock
test -S "$D42C_RUN/runtime/socket/control.sock"
test -S "$D42C_RUN/runtime/socket/relay.sock"
test -S "$D42C_NS_RUN/wayland-1"
test -S "$D42C_NS_RUN/sway-ipc.980.$D42C_NSPID.sock"
test -S "$D42C_NS_RUN/session-bus"
test -d "/var/lib/loopbridge/sessions/$D42C_ID/workspace"
test -f /var/lib/loopbridge/verifiers.json
test -f /var/lib/loopbridge-admin/owner.token
test -f /etc/loopbridge/credentials/manager-verifiers.json
test -f /run/credentials/loopbridge.service/manager-verifiers.json
nsenter --target "$D42C_MANAGER_PID" --mount -- \
  test -f /run/credentials/loopbridge.service/manager-verifiers.json
test -d "/proc/$D42C_SWAY_PID/fd"
test -f "/proc/$D42C_SWAY_PID/environ"
getfacl -cp "/run/loopbridge-ingress/$D42C_ID.sock"
/usr/bin/setpriv --reuid=65534 --regid=65534 --clear-groups --no-new-privs \
  /usr/bin/python3 -I -B -c '
import errno, os, socket, sys
if os.getuid() != 65534:
    raise SystemExit("unexpected UID")
with socket.socket(socket.AF_UNIX) as peer:
    peer.settimeout(3)
    try:
        peer.connect(sys.argv[1])
    except PermissionError as error:
        if error.errno not in (errno.EACCES, errno.EPERM):
            raise
        print("unlisted UID denied")
    else:
        raise SystemExit("unexpected unlisted UID connect")
' "/run/loopbridge-ingress/$D42C_ID.sock"
```

The UID 65534 check is expected to fail at the ACL. The local relay fixture independently checks that a real unlisted kernel peer is rejected when it can reach the listener.

### 4. Verify GTK, events and isolation as UID 1000

Set `D42C_ID`, `D42C_EPOCH`, `D42C_SWAY_PID` and `D42C_NSPID` from the administrative console. Start the viewer on the existing desktop.

```bash
GDK_BACKEND=wayland /usr/bin/python3 -B -m tools.loopbridge_live_view \
  --socket "/run/loopbridge-ingress/$D42C_ID.sock" --peer-uid 980 \
  --token-file "$D42C_CLIENT/first.token" --private-id "$D42C_ID" --epoch "$D42C_EPOCH" \
  --metrics-file "$D42C_EVIDENCE/view-first.json" &
D42C_VIEW_PID=$!
/usr/bin/python3 -B -m tools.loopbridge_d42c_probe live \
  --token-file "$D42C_CLIENT/first.token" --private-id "$D42C_ID" --epoch "$D42C_EPOCH" \
  --sway-pid "$D42C_SWAY_PID" --sway-namespace-pid "$D42C_NSPID" \
  > "$D42C_EVIDENCE/probe-first.json"
```

Require visible Calculator in the read-only GTK window, at least one frame painted, the `control.released` authority event and the explicit denials in the probe report. Read the metrics after first paint and preserve them before they are updated. Record operator confirmation as text and keep screenshots, pixels and tokens out of the evidence bundle. Denials apply to the specific paths tested. The probe requires `EACCES` or `EPERM` for live private resources.

### 5. Stop, check evidence and test replacement

While the viewer is still connected, invoke this on the root console.

```bash
d42c_admin --action admin-smoke-stop --session-id "$D42C_ID"
d42c_admin --action admin-smoke-list
test ! -e "/run/loopbridge-private/$D42C_ID"
test -d "/var/lib/loopbridge/sessions/$D42C_ID/workspace"
```

Expect the exact ID in state `stopped`, `retired:true`, an empty list and persistent workspace. Verify the old compositor exited, and record the GTK metrics when they show disconnection. Close that viewer. Run the UID 1000 stopped check and preserve the result.

```bash
/usr/bin/python3 -B -m tools.loopbridge_d42c_probe stopped --private-id "$D42C_ID" \
  > "$D42C_EVIDENCE/stopped-first.json"
```

Repeat steps 3–5 with a new bearer at `$D42C_CLIENT/second.token`, new evidence names and the new session's public pin and PIDs. Confirm the new ID and epoch differ. Add `--previous-token-file "$D42C_CLIENT/first.token"` to the second live probe. Require `priorBearerDenied:true`. Compare both baseline processes and the service properties using step 2. Preserve the two sanitized descriptors, operational outcomes, ACL/mount metadata, probe reports, GTK metrics and relevant trusted journal excerpts.

## Failure and rollback

- Installation writes only a new root-controlled candidate directory and its quarantine. A verification failure stops before candidate execution. Quarantine and an unused candidate can remain for review. The running service continues using the pinned D4.2B artifact.
- Starting a session consumes the supplied verifier and creates durable state even if subsequent setup fails. If setup fails after the client learned the instance ID, the client attempts to stop that exact instance. If start or stop is unconfirmed, run `d42c_admin --action admin-smoke-list`. Identify the instance from the exclusive test window and use `d42c_admin --action admin-smoke-stop --session-id "$D42C_ID"` only for a confirmed test instance. Keep the journal, durable registry and workspace. Treat a blocked or already retired result after a lost reply as incomplete evidence of controlled stop.
- If cleanup cannot be confirmed, keep the evidence and pause for a separate recovery decision. The protocol never resumes a previous session. A retry after confirmed cleanup uses a fresh observer verifier. Any service stop or restart, credential recovery or snapshot restoration needs separate authorization.
- Real namespace behavior under systemd, helper execution, GTK paint, direct private path denial and cross-UID media delivery remain to be measured. Grant expiry fences observer access and does not retire the instance. Observe and stop within the grant window to distinguish grant expiry from controlled shutdown.
