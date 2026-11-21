# D4.2C — First cross-UID graphical smoke

The D4.2B handoff reports `READY_FOR_D42C`. The VM retains the installed `af6057c3bbbe83c9058c28dca2fa4abb156202fa` manager. Overall host isolation remains **PARTIAL**.

## Readiness audit

The [D2](TRUSTED_SERVICE_INGRESS_D2.md), [D3](TRUSTED_SERVICE_LIFECYCLE_D3.md), [D4.2A](TRUSTED_SERVICE_BOUNDARY_D42A.md) and [D4.2A.1](TRUSTED_SERVICE_ADMIN_D42A1.md) contracts already cover the manager, per-instance verifiers, relay and presentation. In the installed release, the relay checks kernel `SO_PEERCRED`, has a fixed socket destination, forwards bytes only and reaches a broker listener that refuses the owner principal. The separate private broker socket supports grants. The manager supports explicit offline start and stop, persistent journal retention and fresh identity on replacement. The existing GTK viewer accepts an observer credential and a pinned presentation identity. The installed administrative client only supports authenticated empty-manager readiness.

The checkout's `main` and local `origin/main` reference matched the requested base. The working tree had nine historical untracked entries. The installed release verified against its pinned digest as UID 1000. The unit was running as 980:980 (PID 16793), disabled at boot, with zero restarts. Primary Sway was PID 1617 and UID 1000. The ingress directory ACL allowed traversal only to the named client. UID 1000 received `EACCES` connecting to the private manager, and lacked read/traverse access to the private runtime, service state, root administrative directory and both credential directories. These checks preceded any private graphical session. Authenticated readiness and snapshot provenance come from the D4.2B handoff.

## Execution plan and decision criteria

1. Add a fixed-purpose administrative client for offline start, active-instance listing and explicit stop. Reuse the installed manager and broker RPCs from a separately verified release under the existing dedicated service account. Enroll a fresh observer verifier and hand back only the public pin. Exercise authentication, grant separation, cleanup and lost-reply recovery with local fixtures.
2. Run the UID 1000 client probe and GTK viewer on the existing desktop after approval. Require kernel peer UID 980, observer auth, a pinned frame painted by GTK, an authority event read after a snapshot, and a distinct service compositor with private namespaces.
3. Stop the exact instance while the viewer is connected. Require disconnection, removal of the public route and disposable runtime, retention of persistent state and zero active instances. Compare the primary Sway and manager process identities before and after.
4. Repeat with a fresh verifier and pin after separate approval. Check rejection of the prior credential, forged principal and UID fields, stale pins and administrative requests. Check access denial on the tested private paths as UID 1000 and public ingress denial as UID 65534. Preserve sanitized evidence.

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

The ordinary client generates its own one-instance observer bearer. Only the verifier goes to the administrator. The administrative child generates an independent session owner and delegate, supplies only verifiers to the manager, and keeps the session owner bearer in memory for setup. The offline fixture launches Calculator through the private broker, grants the observer `session.discover` and `desktop.stream` for 180 seconds, and releases the setup lease. The client receives the public ingress address, session ID and epoch. Its event check requires an idle session and reads the actual `control.released` event through authenticated ingress. The replacement probe checks denial of capture, input acquisition, workspace and administrative RPCs. The GTK viewer verifies peer UID 980 before sending the bearer.

The experiment requires a trusted administrator with exclusive use of the manager for its duration and explicit approval to install the additional versioned artifact, start and stop the two disposable offline sessions and issue the UID 65534 denial check. The unit, D4.2B release, boot state, ACL policy and credential source stay in place. The VM operator must confirm the `LoopEnvironment-Pre-D42B` snapshot and have a separate trusted administrative console and a terminal on the existing UID 1000 desktop. Use a reviewed commit, independently confirmed artifact digest, and keep the start, view, probes and stop within the observer grant window.

## Authorized VM procedure

### Before the first authorization

The operator confirms the VM snapshot `LoopEnvironment-Pre-D42B`, a trusted root console, an ordinary graphical terminal at UID 1000 and exclusive use of the manager during both runs. The private workload is the offline Calculator. The existing D4.2B service remains responsible for the private compositor and broker. Only the observer's own bearer is held by the ordinary client. Transfer the public pin, verifier and numeric PIDs when the procedure calls for them. Keep tokens and media out of the evidence.

Use the exact candidate commit and SHA-256 approved from the PR. The install identity is the SHA-256 of the complete `release.json`, which pins the files and helper binaries. A freshly built artifact that differs from the reviewed digest requires review before publication. As UID 1000, from the repository, set `D42C_REV` and `D42C_DIGEST` to those literal values. The candidate can be staged and verified before any VM authorization.

```bash
test "$(id -u)" = 1000
git diff --quiet "$D42C_REV" -- loopbridge tools deploy
D42C_STAGE=$(mktemp -d /tmp/loopbridge-d42c-stage.XXXXXX)
D42C_SOURCE="$D42C_STAGE/$D42C_REV"
/usr/bin/python3 -I -B tools/prepare_loopbridge_release.py build "$D42C_REV" "$D42C_STAGE" &&
  /usr/bin/python3 -I -B tools/prepare_loopbridge_release.py verify "$D42C_SOURCE" "$D42C_DIGEST"
printf 'Revision %s\nSource %s\n' "$D42C_REV" "$D42C_SOURCE"
sha256sum "$D42C_SOURCE/release.json"
```

The installed D4.2B revision is `af6057c3bbbe83c9058c28dca2fa4abb156202fa`. Its manifest SHA-256 is `f393d4d412cc7b2faac417fa58da9c2e8add97590b96d4a5157f06f20efa22b5`.

### Stop 1 — Publish the administrative candidate

**Authorize** a root-controlled quarantine copy, publication of a new directory under `/opt/loopbridge/releases/`, candidate verification and capture of metadata. This stop uses no owner authentication or session RPC. It leaves systemd pointing at the D4.2B install.

Set `D42C_REV`, `D42C_DIGEST` and `D42C_SOURCE` in the trusted root console using the exact reviewed values. Use a dedicated Bash shell. The installation block fails on the first error. Its variables and function definitions are also used in Stops 2 and 3.

```bash
set -e
set -o pipefail
umask 022
D42C_BASE=/opt/loopbridge/releases/af6057c3bbbe83c9058c28dca2fa4abb156202fa
D42C_BASE_DIGEST=f393d4d412cc7b2faac417fa58da9c2e8add97590b96d4a5157f06f20efa22b5
D42C_DEST="/opt/loopbridge/releases/$D42C_REV"
d42c_host_identity() {
  ps -p 1617 -o pid=,uid=,gid=,lstart=,comm=
  systemctl show loopbridge.service -p MainPID -p NRestarts -p ActiveState -p UnitFileState -p ExecStart
}
d42c_host_unchanged() {
  d42c_host_identity > "$D42C_ROOT_EVIDENCE/$1" &&
    diff -u "$D42C_ROOT_EVIDENCE/host-before.txt" "$D42C_ROOT_EVIDENCE/$1"
}
d42c_admin() {
  /usr/bin/python3 -I -B "$D42C_DEST/launcher.py" --manifest-sha256 "$D42C_DIGEST" "$@"
}
test "$(id -u):$(id -g)" = 0:0
test "$(ps -p 1617 -o uid=,comm= | awk '{$1=$1; print}')" = '1000 sway'
D42C_MANAGER_PID=$(systemctl show loopbridge.service -p MainPID --value)
test "$D42C_MANAGER_PID" = 16793
test "$(systemctl show loopbridge.service -p NRestarts --value)" = 0
test "$(systemctl show loopbridge.service -p ActiveState --value)" = active
test "$(systemctl show loopbridge.service -p UnitFileState --value)" = disabled
systemctl show loopbridge.service -p ExecStart --value |
  grep -F "$D42C_BASE/launcher.py --manifest-sha256 $D42C_BASE_DIGEST --client-uid 1000"
/usr/bin/python3 -I -B "$D42C_BASE/launcher.py" --manifest-sha256 "$D42C_BASE_DIGEST" --action verify-installed
[[ "$D42C_REV" =~ ^[a-f0-9]{40}$ && "$D42C_DIGEST" =~ ^[a-f0-9]{64}$ ]]
[[ ! -e "$D42C_DEST" && ! -L "$D42C_DEST" ]]
D42C_ROOT_EVIDENCE=$(mktemp -d /var/tmp/loopbridge-d42c-evidence.XXXXXX)
d42c_host_identity > "$D42C_ROOT_EVIDENCE/host-before.txt"
D42C_QUARANTINE=$(mktemp -d /opt/loopbridge/.d42c-admin.XXXXXX)
cp -R -P --preserve=mode -- "$D42C_SOURCE" "$D42C_QUARANTINE/$D42C_REV"
/usr/bin/python3 -I -B -c '
from pathlib import Path
import runpy, sys
verify = runpy.run_path(sys.argv[1])["verify_release"]
verify(Path(sys.argv[2]), sys.argv[3])
' "$D42C_BASE/launcher.py" "$D42C_QUARANTINE/$D42C_REV" "$D42C_DIGEST"
mv -T --update=none-fail -- "$D42C_QUARANTINE/$D42C_REV" "$D42C_DEST"
d42c_admin --action verify-installed
d42c_host_unchanged host-after-install.txt
printf '%s\n' "$D42C_ROOT_EVIDENCE"
set +e
```

**Pass** when both installed manifests verify and the identity comparison is identical. **Fail** on any digest, owner, path, unit or primary-compositor mismatch. Stop before authenticated administration. **Rollback** keeps the unused candidate and its quarantine inert for inspection. Record which step failed. If publication already happened, no running process references the candidate. A new attempt requires a fresh review of the published path or authorized cleanup of that artifact.

### Stop 2 — First cross-UID session

**Authorize** the root workflow to verify the protected owner credential and hand it to the fixed service-UID child, to start one disposable offline session and to stop that exact instance. This consumes one verifier set and creates service-owned persistent state for that instance. The launch operation through the private broker is the mediated graphical action. The UID 1000 client authenticates as observer, views the result and reads `snapshot` and `events` through ingress. The observer's two grants are `session.discover` and `desktop.stream`. GTK is read-only.

Have both consoles ready. The observer grants last 180 seconds. Review the commands and prepare the evidence directories before invoking start. Use `set -o pipefail` for the pipelines. Any failed command in this stop closes the approval path and leads to explicit cleanup where the ID is known.

In the ordinary graphical terminal, from the reviewed repository checkout:

```bash
set -o pipefail
test "$(id -u)" = 1000
D42C_CLIENT=$(mktemp -d /run/user/1000/loopbridge-d42c.XXXXXX)
D42C_EVIDENCE=$(mktemp -d /tmp/loopbridge-d42c-evidence.XXXXXX)
/usr/bin/python3 -B -m tools.loopbridge_d42c_probe generate --token-file "$D42C_CLIENT/first.token"
```

Paste only the printed verifier into the root console when `read` waits. Confirm the empty list and review credential-mount metadata before starting. The mount and file ownership must match the [D4.2A contract](TRUSTED_SERVICE_BOUNDARY_D42A.md#bootstrap-rotation-and-recovery).

```bash
d42c_manager_empty() {
  local listing
  listing=$(d42c_admin --action admin-smoke-list) || return
  printf '%s\n' "$listing"
  test "$listing" = '{"instances":[]}'
}
d42c_private_sway_pid() {
  ps -p "$(paste -sd, /sys/fs/cgroup/system.slice/loopbridge.service/cgroup.procs)" -o pid=,uid=,comm= |
    awk '$2 == 980 && $3 == "sway" {pid=$1; ++count} END {if (count != 1) exit 1; print pid}'
}
d42c_pin() {
  /usr/bin/python3 -I -B -c '
import json, sys
with open(sys.argv[1]) as pin_file:
    pin = json.load(pin_file)
print(pin["privateId"], pin["epoch"])
' "$1"
}
d42c_namespaces() {
  local ns manager private
  test "$1" != 1617 || return
  for ns in user pid mnt net ipc; do
    manager=$(readlink "/proc/$D42C_MANAGER_PID/ns/$ns") || return
    private=$(readlink "/proc/$1/ns/$ns") || return
    test "$manager" != "$private" || return
    printf '%s %s %s\n' "$ns" "$manager" "$private"
  done
}
d42c_stop() {
  d42c_admin --action admin-smoke-stop --session-id "$1" &&
    d42c_manager_empty &&
    test ! -e "/run/loopbridge-ingress/$1.sock" &&
    test ! -e "/run/loopbridge-private/$1" &&
    test ! -e "/proc/$2" &&
    test -d "/var/lib/loopbridge/sessions/$1/workspace"
}
test "$(systemctl show loopbridge.service -p MainPID --value)" = "$D42C_MANAGER_PID"
nsenter --target "$D42C_MANAGER_PID" --mount -- \
  findmnt -n -o TARGET,OPTIONS --target /run/credentials/loopbridge.service
nsenter --target "$D42C_MANAGER_PID" --mount -- stat -c '%u %g %a %n' \
  /run/credentials/loopbridge.service /run/credentials/loopbridge.service/manager-verifiers.json
nsenter --target "$D42C_MANAGER_PID" --mount -- getfacl -cp \
  /run/credentials/loopbridge.service /run/credentials/loopbridge.service/manager-verifiers.json
getfacl -cp /run/loopbridge-ingress
d42c_manager_empty
read -r D42C_VERIFIER_FIRST
```

Continue only if that preflight passes. If the start pipeline times out, fails or prints an invalid result, use [lost confirmation and recovery](#lost-confirmation-and-recovery) immediately.

```bash
d42c_host_unchanged host-before-first.txt &&
  d42c_admin --action admin-smoke-start --observer-verifier "$D42C_VERIFIER_FIRST" |
    tee "$D42C_ROOT_EVIDENCE/first-start.json"
```

Extract the pin and confirm a distinct UID 980 compositor. Copy only the printed ID and epoch to the ordinary terminal.

```bash
read -r D42C_FIRST_ID D42C_FIRST_EPOCH < <(d42c_pin "$D42C_ROOT_EVIDENCE/first-start.json")
[[ "$D42C_FIRST_ID" =~ ^[a-f0-9]{16}$ && "$D42C_FIRST_EPOCH" =~ ^[a-f0-9]{32}$ ]]
D42C_FIRST_SWAY=$(d42c_private_sway_pid)
d42c_namespaces "$D42C_FIRST_SWAY" > "$D42C_ROOT_EVIDENCE/first-namespaces.txt"
ps -p "$D42C_FIRST_SWAY" -o pid,ppid,uid,gid,lstart,comm
printf '%s %s\n' "$D42C_FIRST_ID" "$D42C_FIRST_EPOCH"
```

In the ordinary graphical terminal:

```bash
read -r D42C_FIRST_ID D42C_FIRST_EPOCH
GDK_BACKEND=wayland /usr/bin/python3 -B -m tools.loopbridge_live_view \
  --socket "/run/loopbridge-ingress/$D42C_FIRST_ID.sock" --peer-uid 980 \
  --token-file "$D42C_CLIENT/first.token" --private-id "$D42C_FIRST_ID" --epoch "$D42C_FIRST_EPOCH" \
  --metrics-file "$D42C_EVIDENCE/first-view.json" &
D42C_FIRST_VIEW_PID=$!
/usr/bin/python3 -B -m tools.loopbridge_d42c_probe live \
  --token-file "$D42C_CLIENT/first.token" --private-id "$D42C_FIRST_ID" --epoch "$D42C_FIRST_EPOCH" |
  tee "$D42C_EVIDENCE/first-probe.json"
```

When Calculator is visible, record the paint and operator confirmation. The helper below is also used for the replacement viewer.

```bash
d42c_view_evidence() {
  /usr/bin/python3 -I -B -c '
import json, sys
with open(sys.argv[1]) as metrics:
    row = json.load(metrics)
if sys.argv[2] == "painted":
    valid = (row["painted"] >= 1 and row["width"] == 800 and row["height"] == 600
             and row["reason"] is None)
else:
    valid = row["state"].startswith("DESCONECTADO") and row["reason"] == "session_ended_or_unreachable"
if not valid:
    raise SystemExit("expected viewer evidence missing")
print(json.dumps(row, sort_keys=True))
' "$1" "$2"
}
d42c_view_evidence "$D42C_EVIDENCE/first-view.json" painted > "$D42C_EVIDENCE/first-painted.json"
printf '%s\n' 'Operator saw Calculator in the read-only window.' > "$D42C_EVIDENCE/first-visual.txt"
```

While the viewer is connected, on the root console run:

```bash
d42c_stop "$D42C_FIRST_ID" "$D42C_FIRST_SWAY" | tee "$D42C_ROOT_EVIDENCE/first-stop.txt"
d42c_host_unchanged host-after-first.txt
```

On the ordinary terminal wait for the disconnection status, capture it, then close the GTK window.

```bash
d42c_view_evidence "$D42C_EVIDENCE/first-view.json" disconnected > "$D42C_EVIDENCE/first-disconnected.json"
/usr/bin/python3 -B -m tools.loopbridge_d42c_probe stopped --private-id "$D42C_FIRST_ID" |
  tee "$D42C_EVIDENCE/first-route-after-stop.json"
```

**Pass** when UID 1000 authenticates to peer UID 980, receives `control.released`, observes Calculator and paints at least one pinned frame. Stop must return `stopped` and `retired:true` for the exact ID, disconnect the viewer before grant expiry, remove the disposable runtime and public route, leave the workspace, and preserve the baseline. **Fail** on any missing confirmation or unexpected access, PID, namespace, session or identity. **Rollback** uses `d42c_stop` for the known test instance and preserves all evidence. An ambiguous outcome follows the recovery procedure below. A successful Stop 2 does not authorize Stop 3.

### Stop 3 — Replacement and negative checks

**Authorize** a second offline session with fresh verifiers, a second controlled stop, negative access checks as UID 1000 and the single `setpriv` check as UID 65534. Start only after Stop 2 passes and the manager again reports an empty list. Keep the first token in its protected ordinary-client directory for the old-bearer denial.

In the ordinary graphical terminal:

```bash
/usr/bin/python3 -B -m tools.loopbridge_d42c_probe generate --token-file "$D42C_CLIENT/second.token"
```

In the root console check readiness, read only the new verifier, then start in a separate block so a failed precondition is visible before any mutation.

```bash
d42c_manager_empty
read -r D42C_VERIFIER_SECOND
test "$D42C_VERIFIER_SECOND" != "$D42C_VERIFIER_FIRST"
```

```bash
d42c_host_unchanged host-before-second.txt &&
  test "$D42C_VERIFIER_SECOND" != "$D42C_VERIFIER_FIRST" &&
  d42c_admin --action admin-smoke-start --observer-verifier "$D42C_VERIFIER_SECOND" |
    tee "$D42C_ROOT_EVIDENCE/second-start.json"
```

Validate the new pin and compositor. In the root console, establish that each live resource exists before counting a permission error against it. Check the delivered credential in the active manager's mount namespace, as in Stop 2. The ordinary client tests direct reachability from its own namespace. Record only metadata.

```bash
read -r D42C_SECOND_ID D42C_SECOND_EPOCH < <(d42c_pin "$D42C_ROOT_EVIDENCE/second-start.json")
[[ "$D42C_SECOND_ID" =~ ^[a-f0-9]{16}$ && "$D42C_SECOND_EPOCH" =~ ^[a-f0-9]{32}$ ]]
test "$D42C_SECOND_ID" != "$D42C_FIRST_ID"
test "$D42C_SECOND_EPOCH" != "$D42C_FIRST_EPOCH"
D42C_SECOND_SWAY=$(d42c_private_sway_pid)
D42C_NSPID=$(awk '/^NSpid:/ {print $NF}' "/proc/$D42C_SECOND_SWAY/status")
d42c_namespaces "$D42C_SECOND_SWAY" > "$D42C_ROOT_EVIDENCE/second-namespaces.txt"
D42C_RUN="/run/loopbridge-private/$D42C_SECOND_ID"
D42C_NS_RUN="/proc/$D42C_SECOND_SWAY/root/private/run"
D42C_INGRESS="/run/loopbridge-ingress/$D42C_SECOND_ID.sock"
test -S "$D42C_INGRESS"
test -S /run/loopbridge-private/manager.sock
test -S "$D42C_RUN/runtime/socket/control.sock"
test -S "$D42C_RUN/runtime/socket/relay.sock"
test -S "$D42C_NS_RUN/wayland-1"
test -S "$D42C_NS_RUN/sway-ipc.980.$D42C_NSPID.sock"
test -S "$D42C_NS_RUN/session-bus"
test -d "/var/lib/loopbridge/sessions/$D42C_SECOND_ID/workspace"
test -f /var/lib/loopbridge/verifiers.json
test -f /var/lib/loopbridge-admin/owner.token
test -f /etc/loopbridge/credentials/manager-verifiers.json
test "$(systemctl show loopbridge.service -p MainPID --value)" = "$D42C_MANAGER_PID" &&
  nsenter --target "$D42C_MANAGER_PID" --mount -- \
    /usr/bin/test -f /run/credentials/loopbridge.service/manager-verifiers.json
test -d "/proc/$D42C_SECOND_SWAY/fd"
test -f "/proc/$D42C_SECOND_SWAY/environ"
getfacl -cp "$D42C_INGRESS" > "$D42C_ROOT_EVIDENCE/second-ingress-acl.txt"
printf '%s %s %s %s\n' "$D42C_SECOND_ID" "$D42C_SECOND_EPOCH" "$D42C_SECOND_SWAY" "$D42C_NSPID"
```

Copy the printed four values to the ordinary terminal. Start the viewer and run the replacement probe.

```bash
read -r D42C_SECOND_ID D42C_SECOND_EPOCH D42C_SECOND_SWAY D42C_NSPID
GDK_BACKEND=wayland /usr/bin/python3 -B -m tools.loopbridge_live_view \
  --socket "/run/loopbridge-ingress/$D42C_SECOND_ID.sock" --peer-uid 980 \
  --token-file "$D42C_CLIENT/second.token" --private-id "$D42C_SECOND_ID" --epoch "$D42C_SECOND_EPOCH" \
  --metrics-file "$D42C_EVIDENCE/second-view.json" &
D42C_SECOND_VIEW_PID=$!
/usr/bin/python3 -B -m tools.loopbridge_d42c_probe replacement \
  --token-file "$D42C_CLIENT/second.token" --previous-token-file "$D42C_CLIENT/first.token" \
  --private-id "$D42C_SECOND_ID" --epoch "$D42C_SECOND_EPOCH" \
  --sway-pid "$D42C_SECOND_SWAY" --sway-namespace-pid "$D42C_NSPID" |
  tee "$D42C_EVIDENCE/second-probe.json"
```

While the same ingress is serving UID 1000, in the root console execute the denial test. The inline program runs with real and effective UID 65534, no supplementary groups and no privilege gain. It has no bearer and sends no data. Expect the live socket's ACL to deny the connection. The unprivileged relay fixture separately exercises kernel-peer rejection after reaching the listener.

```bash
/usr/bin/setpriv --reuid=65534 --regid=65534 --clear-groups --no-new-privs \
  /usr/bin/python3 -I -B -c '
import errno, os, socket, sys
if (os.getuid(), os.geteuid(), os.getgid(), os.getegid(), os.getgroups()) != (65534, 65534, 65534, 65534, []):
    raise SystemExit("unexpected test identity")
with socket.socket(socket.AF_UNIX) as peer:
    peer.settimeout(3)
    try:
        peer.connect(sys.argv[1])
    except PermissionError as error:
        if error.errno not in (errno.EACCES, errno.EPERM):
            raise
        print("uid=65534 ingress denied " + errno.errorcode[error.errno])
    else:
        raise SystemExit("unexpected unlisted UID connect")
' "$D42C_INGRESS" | tee "$D42C_ROOT_EVIDENCE/second-uid-65534.txt"
```

Before stop, the ordinary client records first paint.

```bash
d42c_view_evidence "$D42C_EVIDENCE/second-view.json" painted > "$D42C_EVIDENCE/second-painted.json"
```

On the root console then on the ordinary terminal respectively, verify retirement and disconnection.

```bash
d42c_stop "$D42C_SECOND_ID" "$D42C_SECOND_SWAY" | tee "$D42C_ROOT_EVIDENCE/second-stop.txt"
d42c_host_unchanged host-after-second.txt
```

```bash
d42c_view_evidence "$D42C_EVIDENCE/second-view.json" disconnected > "$D42C_EVIDENCE/second-disconnected.json"
/usr/bin/python3 -B -m tools.loopbridge_d42c_probe stopped --private-id "$D42C_SECOND_ID" |
  tee "$D42C_EVIDENCE/second-route-after-stop.json"
```

Close the test viewer. **Pass** when the fresh bearer works and the first bearer is refused, the ID and epoch differ, the replacement report contains all expected denial flags, and every tested direct resource returns `EACCES` or `EPERM`. UID 65534 must be denied on the reachable ingress. The controlled stop and baseline checks must pass again. **Fail** on any successful unauthorized connection or RPC, any unproven live target, or a missing positive result. **Rollback** is the same exact-ID stop and evidence retention as in Stop 2. A verified unauthorized success is `NO_GO` for the smoke. A missing measurement or ambiguous cleanup is `CONDITIONAL` or `BLOCKED` according to whether operation can be observed safely. Overall host isolation remains **PARTIAL**.

### Lost confirmation and recovery

If a start or stop command returns an error, times out or receives an incomplete reply, close the approval path and preserve its output even if empty. The manager can have accepted the operation. Never resend the start or enroll the same verifier to seek confirmation. The approved start may have consumed the verifier and written a durable session record.

```bash
D42C_RECOVERY=$(mktemp -d "$D42C_ROOT_EVIDENCE/recovery.XXXXXX")
d42c_admin --action admin-smoke-list | tee "$D42C_RECOVERY/active.json"
d42c_host_identity > "$D42C_RECOVERY/host.txt"
```

If the manager reports exactly the known instance or a single new instance from the exclusive window that began empty, identify it by its validated ID and stop it explicitly. An unexpected second instance or an uncertain identity requires a separate recovery decision. Use the known ID or paste the identified ID only.

```bash
read -r D42C_RECOVER_ID
[[ "$D42C_RECOVER_ID" =~ ^[a-f0-9]{16}$ ]] &&
  d42c_admin --action admin-smoke-stop --session-id "$D42C_RECOVER_ID" |
  tee "$D42C_RECOVERY/stop.json"
d42c_admin --action admin-smoke-list | tee "$D42C_RECOVERY/after-stop.json"
```

For a confirmed ID, verify absence of its public route and disposable runtime and retain any existing durable workspace. An empty list by itself cannot prove a controlled shutdown. If the result is already retired, blocked, or the manager is unreachable, keep the records, collect metadata for the known instance and leave the gate incomplete. Preserve the registry, credentials and journals. Any manager stop or restart, package change, credential recovery or snapshot restoration requires separate authorization. A fresh experiment after verified cleanup requires a fresh verifier and an approved test window.

### Procedure files

The [release builder](../../tools/prepare_loopbridge_release.py) creates the candidate artifact. The [verified installed launcher](../../deploy/loopbridge/launcher.py) calls the [fixed administration workflow](../../loopbridge/service_smoke.py). The ordinary terminal uses the [D4.2C probe](../../tools/loopbridge_d42c_probe.py) and the [GTK viewer](../../tools/loopbridge_live_view.py). The smoke uses the existing unit and private session implementation.
