# V0.8-D.2C.2 cross-UID workspace preflight

**PREPARED / NOT EXECUTED.** The nonprivileged rehearsal uses authenticated Unix RPC, the real creation adapter, pinned SQLite, actual hard links, and exact-process SIGKILL. Its Linux cross-UID denials, real peer admission and operational cleanup are **NOT RUN**. The operator needs a fresh authorization for the actual experiment. The [acceptance matrix](../design/LOOPSHELL_V0_8_D2C2_ACCEPTANCE.md) controls qualification.

D.1C.4 retains experimental GO for the Registry. D.2A and D.2B retain experimental local GO. D.2B.2 retains experimental GO for A–D, cleanup GO and global PARTIAL. D.2C.1 retains experimental GO for its disposable same-UID profile. D.2C.2 and real private graphical resources remain NOT RUN. D5 remains PARTIAL. M1.3B has independent preemption gates.

The driver uses the [D.2C.1 contract](../design/LOOPSHELL_V0_8_D2C1_MEDIATED_WORKSPACE.md) and the [D.2B.1 operational preflight](LOOPSHELL_V0_8_D2B1_CROSS_UID_PREFLIGHT.md) as references. Use one disposable Debian Lab clone with the expected existing `loopbridge-svc` (980:980) and `vboxuser` (1000:1000) accounts, a private root console, and a preapproved snapshot. The driver proposes the existing Debian `nobody:nogroup` (65534:65534) for the peer challenge. Preparation verifies the passwd mappings and that `nobody` has a disabled login shell and no supplementary memberships. All workers get cleared groups, no new privileges, zero effective, permitted, inheritable and ambient capabilities, a fresh environment and isolated credential pipes. The root console owns the separate broker administrative pipe. The UID 1000 executor receives only its synthetic executor bearer and uses authenticated RPC for preparation, publication and receipt replay. Separate hardened helpers hold the Registry registration, issuer, controller, status and audit bearers. Root verifies the actual files and ledger independently.

## Before the approval window

### 1. Verify the clone and transfer the approved revision

At the hypervisor, record the approved snapshot ID, source DMI UUID, new clone DMI UUID, and provenance of the full clone. Independently verify the clone hostname, machine ID and current boot ID. Use a fresh clone with dedicated synthetic desktop state. Verify the reviewer-approved Git commit and archive checksum over an independent channel. PR #44 was reviewed at `39275ca4d748c31894b86e093f54fe4e7a1571da` and squash-merged as `0672027b223b8155bee257e43844420b98ec509d` with identical tree `3811d8a2c26366686ab03a9ff62fd9fd48aa85c8`. For this run use the later **full commit that contains the reviewed D.2C.2 driver and runbook**.

On the trusted source system:

```bash
set -euo pipefail
[[ "${D2C2_REVISION:?full reviewed D.2C.2 commit}" =~ ^[0-9a-f]{40}$ ]]
test "$(git rev-parse --verify "$D2C2_REVISION^{commit}")" = "$D2C2_REVISION"
test ! -e "${D2C2_EXPORT:?new destination for Git TAR}"
git -c tar.umask=0022 archive --format=tar --output="$D2C2_EXPORT" "$D2C2_REVISION"
test "$(git get-tar-commit-id < "$D2C2_EXPORT")" = "$D2C2_REVISION"
sha256sum -- "$D2C2_EXPORT"
```

Transfer through approved read-only media, or inherit the archive from the trusted source through a full clone. For inheritance, record the matching SHA-256 of the newly exported TAR, the stored origin TAR before cloning and the clone TAR. A digest bundled with the TAR needs an independently verified source. The clone can stay offline.

In an independently authorized **root console** in the clone, populate the expected environment variables from the approval record. Set `D2C2_INPUT` to the approved TAR on media or the verified inherited copy. Keep this console open for the later blocks. Use a display-independent root console. Keep command tracing off.

```bash
set +x
set -euo pipefail
umask 022
test "$(id -u):$(id -g)" = 0:0
test "$(hostname)" = "${D2C2_HOSTNAME:?authorized clone hostname}"
test "$(cat /etc/machine-id)" = "${D2C2_MACHINE_ID:?authorized unique machine ID}"
test "$(cat /proc/sys/kernel/random/boot_id)" = "${D2C2_BOOT_ID:?authorized current boot ID}"
test "$(tr 'A-F' 'a-f' < /sys/class/dmi/id/product_uuid)" = "${D2C2_CLONE_DMI:?authorized clone UUID}"
test "$D2C2_CLONE_DMI" != "${D2C2_SOURCE_DMI:?source UUID from hypervisor}"
: "${D2C2_SNAPSHOT:?verified snapshot reference}"
test "$(id -u loopbridge-svc):$(id -g loopbridge-svc)" = 980:980
test "$(id -u vboxuser):$(id -g vboxuser)" = 1000:1000
test "$(id -u nobody):$(id -g nobody)" = 65534:65534
test "$(id -G nobody)" = 65534
getent passwd loopbridge-svc vboxuser nobody
getent group 980 1000 65534
for d2c2_tool in git tar sha256sum setpriv systemctl python3; do
  command -v "$d2c2_tool" >/dev/null
done
[[ "${D2C2_REVISION:?reviewed revision}" =~ ^[0-9a-f]{40}$ ]]
[[ "${D2C2_ARCHIVE_SHA:?independently verified SHA-256}" =~ ^[0-9a-f]{64}$ ]]
test -f "${D2C2_INPUT:?approved TAR}" && test ! -L "$D2C2_INPUT"
d2c2_run=$(/usr/bin/python3 -c 'from secrets import token_hex; print(token_hex(8))')
d2c2_root="/run/loop-d2c2-$d2c2_run"
d2c2_source="/opt/loop-d2c2-$D2C2_REVISION"
d2c2_records="/var/tmp/loop-d2c2-evidence-$d2c2_run"
test ! -e "$d2c2_root" && test ! -e "$d2c2_source"
mkdir -m 0700 -- "$d2c2_records"
d2c2_archive="$d2c2_records/source.tar"
install -o 0 -g 0 -m 0444 -- "$D2C2_INPUT" "$d2c2_archive"
printf '%s  %s\n' "$D2C2_ARCHIVE_SHA" "$d2c2_archive" | sha256sum -c -
test "$(git get-tar-commit-id < "$d2c2_archive")" = "$D2C2_REVISION"
mkdir -m 0755 -- "$d2c2_source"
tar --no-same-owner --no-same-permissions -xf "$d2c2_archive" -C "$d2c2_source"
d2c2_bad=$(find -P "$d2c2_source" \( ! -user root -o ! -group root -o -perm /022 -o \( ! -type f -a ! -type d \) \) -print -quit)
test -z "$d2c2_bad"
test -f "$d2c2_source/tools/sway_baseline.py"
d2c2() {
  (cd -- "$d2c2_source" && /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
    /usr/bin/python3 -B -m tools.workspace_cross_uid --run-id "$d2c2_run" "$@")
}
d2c2 plan | tee "$d2c2_records/plan.json"
```

### 2. Capture the Sway baseline and prepare

In the existing UID 1000 Sway session, positively identify that session's PID and IPC socket. Use the same pair and the same source revision at every checkpoint. Declare expected dynamic changes before provisioning and record how the operator will achieve stable checkpoints. This protocol declares **no expected changes**. Use the preexisting shell for capture, keep focus and output state stable, and run administrative commands from the independent console. Record any interaction that could affect workspaces, focus, containers, or outputs, with its checkpoint and observed effect. If a separately reviewed protocol predeclares a dynamic difference, the operator must corroborate it with timestamped observations and the before/after component hashes. The collector's `--expect-dynamic` switch alone supplies no corroboration.

In the **desktop shell**, set `D2C2_REVISION` and `D2C2_SWAY_PID` from the trusted record. Keep this shell open for all checkpoints.

```bash
set -euo pipefail
umask 077
test "$(id -u):$(id -g)" = 1000:1000
[[ "${D2C2_REVISION:?reviewed revision}" =~ ^[0-9a-f]{40}$ ]]
[[ "${D2C2_SWAY_PID:?confirmed Sway PID}" =~ ^[1-9][0-9]+$ ]]
d2c2_sway_source="/opt/loop-d2c2-$D2C2_REVISION"
d2c2_sway_socket="${SWAYSOCK:?confirmed Sway IPC socket}"
d2c2_sway_dir=$(mktemp -d /tmp/loop-d2c2-sway.XXXXXXXX)
printf '%s\n' "$d2c2_sway_dir"
printf '%s\n' 'Expected dynamic changes: none. Log all relevant interactions and checkpoints.' \
  > "$d2c2_sway_dir/operator-log.txt"
d2c2_capture() {
  case "$1" in before|prepared|before-cleanup|after-cleanup) ;; *) return 2 ;; esac
  test ! -e "$d2c2_sway_dir/$1.json"
  (cd -- "$d2c2_sway_source" && /usr/bin/python3 -B -m tools.sway_baseline capture \
    --pid "$D2C2_SWAY_PID" --socket "$d2c2_sway_socket") > "$d2c2_sway_dir/$1.json"
  printf '%s %s\n' "$(date -u +%FT%TZ)" "$1" >> "$d2c2_sway_dir/operator-log.txt"
}
d2c2_capture before
```

In the **root console** set `D2C2_SWAY_DIR` to the absolute directory produced by the desktop block. The driver checks for a complete component-wise snapshot, verifies the archive and deployed tree byte-for-byte, checks the disabled/inactive installed unit and provisions the fixture. The fixture contains root-owned metadata, `private/` (980:980, `0700`), `ingress/` (980:980 with UID 1000 search only) and a separate `challenge/` (980:980 with UID 65534 search only). The nominal socket grants only UID 1000 connect permission. The briefly opened challenge socket grants only UID 65534 connect permission and uses the same broker peer allowlist to prove application rejection with a valid ungranted bearer. The nominal directory and endpoint ACLs stay fixed.

```bash
[[ "${D2C2_SWAY_DIR:?absolute directory from desktop}" =~ ^/tmp/loop-d2c2-sway\.[a-zA-Z0-9]{8}$ ]]
test -f "$D2C2_SWAY_DIR/before.json" && test ! -L "$D2C2_SWAY_DIR/before.json"
install -m 0600 -- "$D2C2_SWAY_DIR/before.json" "$d2c2_records/sway-before.json"
d2c2 prepare --archive "$d2c2_archive" --revision "$D2C2_REVISION" \
  --archive-sha256 "$D2C2_ARCHIVE_SHA" --hostname "$D2C2_HOSTNAME" --machine-id "$D2C2_MACHINE_ID" \
  --boot-id "$D2C2_BOOT_ID" --clone-dmi "$D2C2_CLONE_DMI" --source-dmi "$D2C2_SOURCE_DMI" \
  --snapshot "$D2C2_SNAPSHOT" --sway-before "$d2c2_records/sway-before.json" \
  | tee "$d2c2_records/prepared.json"
```

At a stable point in the **desktop shell**, run `d2c2_capture prepared`. In the **root console**, verify the checkpoint before opening the window:

```bash
install -m 0600 -- "$D2C2_SWAY_DIR/prepared.json" "$d2c2_records/sway-prepared.json"
(cd -- "$d2c2_source" && /usr/bin/python3 -B -m tools.sway_baseline compare \
  "$d2c2_records/sway-before.json" "$d2c2_records/sway-prepared.json") \
  | tee "$d2c2_records/sway-compare-prepared.json"
```

## Execute only after independent operator authorization

In the **root console**, review the prepared manifest, clone/snapshot provenance and predeclared Sway expectations. Approve explicitly by typing the run ID. The root-owned `0444` approval binds the approved revision and archive, clone/machine/boot, fixture device and inode pins, identities and wall-clock and monotonic bounds. A start requires freshness within 60 seconds. The controller consumes the approval once by creating a separate exclusive execution marker. Use one bounded block for A–D. The example opens a 300-second window, with a hard maximum of 900 seconds. Interrupted or expired runs retain their evidence and use a fresh fixture for any future approved experiment.

```bash
printf 'Type %s to authorize actual cross-UID A–D execution on this reviewed clone: ' "$d2c2_run"
read -r d2c2_authorized
test "$d2c2_authorized" = "$d2c2_run"
d2c2 approve --confirm-run "$d2c2_authorized" --snapshot "$D2C2_SNAPSHOT" --seconds 300 \
  | tee "$d2c2_records/approval-summary.json"
d2c2_rc=0
d2c2 execute --archive "$d2c2_archive" > "$d2c2_records/execution-summary.json" || d2c2_rc=$?
cat "$d2c2_records/execution-summary.json"
printf 'Driver exit code: %d\n' "$d2c2_rc"
```

The controller uses bounded pipe/RPC exchanges and deterministic barriers. An execution-window timeout stops new RPC and gate releases. In-flight requests may finish the bounded kernel operation they already entered. Gates are outside the production authority mutex. The **before** gate is after durable dispatch intent and staged-byte validation, before the final pinned storage/resource and authorization checks. The final virtual UTC sample follows those checks and must be strictly before each capability deadline. The instrumentation checks the actual approval immediately before entering the real hard link. The sample and syscall occupy the same policy mutex. Linux may deschedule between userspace and syscall entry and may return or make the link visible later than the decision. The run requires a responsive local filesystem and authority at the sampled decision. A stronger requirement for an absolute wall-clock bound on kernel entry, visibility or completion is a **qualification blocker** for this design. A timeout or unexplained late effect is PARTIAL, or NO-GO when evidence shows an unauthorized effect.

After-link gates occur after the actual link and before inspection/confirmation, outside the mutex. Virtual capability expiry is an explicit clock advance at a gate. It uses a separate synthetic epoch and leaves both real approval bounds intact. Gates time out after at most eight seconds, and a failed check stops the run and retains evidence. An unexplained crash or unverified process exit requires operator inspection. There is no unattended retry or approval renewal.

D1, D2 and D3 use separate resources. At each gate the controller opens pinned SQLite read-only and checks durable dispatch. It uses a pidfd for the exact broker, checks PID/start ticks and identity, sends SIGKILL, waits for the observed exit and records the executor's transport loss. Before restarting, it revalidates the fixture, checks the recorded stale socket inode, type, owner, mode and ACL, checks that the path is absent from `/proc/net/unix`, and requires `ECONNREFUSED` from a connect to that exact path. It unlinks just that endpoint and starts a different PID with the original database, policy and resource pins. D3 deliberately removes only the recorded staging link after broker exit while preserving the final file's inode and bytes. Its missing attribution must yield uncertainty. A restart requires the original approval window to remain open.

## Review and restricted cleanup

In the **desktop shell**, capture `d2c2_capture before-cleanup` at a stable point. Preserve the interaction log and note deviations. In the **root console** preserve and inspect the run while all data still exists:

```bash
test -f "$d2c2_root/evidence.jsonl" && test ! -L "$d2c2_root/evidence.jsonl"
install -m 0600 -- "$d2c2_root/evidence.jsonl" "$d2c2_records/evidence.jsonl"
install -m 0600 -- "$D2C2_SWAY_DIR/before-cleanup.json" "$d2c2_records/sway-before-cleanup.json"
d2c2 inspect | tee "$d2c2_records/inspection-summary.json"
install -m 0600 -- "$d2c2_root/inspection.json" "$d2c2_records/inspection.json"
sha256sum -- "$d2c2_records/evidence.jsonl" "$d2c2_records/inspection.json"
```

Inspection requires observed exits for all identified workers, empty ingress directories, no visible live endpoint under the fixture, no fixture mount, exact inventory, resource and fixture pins, and the unchanged installed unit baseline. The process startup records and traced lifecycles account for inherited pipes, the broker's known private descriptor and the accepted connections. Unexpected paths, ownership, mounts, descriptors, or incomplete lifecycles block cleanup. Retain the clone/fixture for review if inspection fails. For an unexpected stale socket, retain it pending proof of the exact endpoint and terminated owner. The automated stale removal is limited to the planned SIGKILL/restart transitions. Avoid generic process matching and recursive fixture removal.

After reviewing the JSONL and the inspection manifest, independently authorize cleanup of just that manifest. Type its independently reviewed SHA-256. Cleanup checks the manifest against the current fixture, including installed service state, and checks the retained evidence digest. It requires its own decision after the execution has finished and uses no execution authorization.

```bash
printf 'Type the reviewed inspection SHA-256 to authorize exact fixture cleanup: '
read -r d2c2_inspection_approved
d2c2 cleanup --confirm-run "$d2c2_run" --inspection-sha256 "$d2c2_inspection_approved" \
  --retained-evidence "$d2c2_records/evidence.jsonl" | tee "$d2c2_records/cleanup.json"
```

In the **desktop shell**, run `d2c2_capture after-cleanup` at a stable point. In the **root console**, preserve per-component hashes and all comparison outputs. The source and evidence directories stay available to the reviewer until the clone is disposed of under a separate decision.

```bash
install -m 0600 -- "$D2C2_SWAY_DIR/after-cleanup.json" "$d2c2_records/sway-after-cleanup.json"
install -m 0600 -- "$D2C2_SWAY_DIR/operator-log.txt" "$d2c2_records/sway-operator-log.txt"
for d2c2_checkpoint in prepared before-cleanup after-cleanup; do
  d2c2_sway_rc=0
  (cd -- "$d2c2_source" && /usr/bin/python3 -B -m tools.sway_baseline compare \
    "$d2c2_records/sway-before.json" "$d2c2_records/sway-$d2c2_checkpoint.json") \
    > "$d2c2_records/sway-compare-$d2c2_checkpoint.json" || d2c2_sway_rc=$?
  printf '%s comparison exit code: %d\n' "$d2c2_checkpoint" "$d2c2_sway_rc"
  cat "$d2c2_records/sway-compare-$d2c2_checkpoint.json"
done
```

Structural evidence includes the compositor and IPC identities, version, configuration file identity and content, loaded configuration and output identity. Dynamic evidence includes workspaces, focus, containers/visual state, output modes/geometry and output state. All components must be present. Structural changes or unexplained dynamic divergences make this gate inconclusive even if a later snapshot matches. Stable checkpoints provide evidence about the captured state. They cannot establish continuous graphical isolation.

## Evidence and acceptance

The controller emits UTF-8 JSON Lines with schema `workspace-cross-uid/1`. Each row has `mode` (`actual` or `rehearsal`), `run_id`, a contiguous `sequence`, real `wall_unix_ns` and `monotonic_ns` samples, and an `event`. The driver enforces event field sets. Case/resource/operation IDs correlate status, counters, file metadata and ledger receipts. Certificate-like file observations include only device, inode, UID/GID, mode, link count, size and SHA-256. Virtual timestamps are identified separately and supplement the controller's real samples. Preserve the approved metadata and snapshots, JSONL, lifecycle/inspection summary, cleanup and installed-unit comparisons. Export only the scoped sanitized evidence. The policy, raw SQLite file, staging links, document bytes and bearer credentials stay in the fixture or the private process channels.

| Acceptance gate | Driver events and required evidence |
| --- | --- |
| A1 Linux identities and ingress | `process_started` for actual service and client IDs, start ticks, empty groups, NNP and capability checks. `kernel_ingress` shows expected bidirectional `SO_PEERCRED`, valid bearer, invalid bearer denial and no ancillary FDs, including the fresh PIDs. `non_admitted_peer` records UID 65534 and nominal kernel denial plus a denied valid-bearer RPC through the challenge socket. `rpc_denied` covers an authenticated ungranted principal. |
| A2 Direct resource denial | `direct_access` reports the executor PID, attempted operations and kernel EACCES/EPERM. Staged checkpoint covers private root/resource traversal and listing, database, policy, staging, final create and `/proc` descriptor. Published checkpoint adds final read, nontruncating write open and additional create. `broker_ready` and `independent_filesystem` give trusted positive controls for actual private files, descriptor and document. ENOENT/timeout are inconclusive. Unexpected success stops the proof. |
| B1 Exact authority | `registry_rpc` records registration, confirmation, offer and acceptance. `rpc_denied` and `exact_grant_profile` cover acceptance alone, mismatched performer/principal/resource/revision/attempt/capability/payload, a granted stale revision, and separate status, audit and control. C cases show fencing for removal, replacement and expiry. |
| B2 Authorized real effect | `receipt` and `status` show paused admission and explicit executor steps. `independent_filesystem` gives empty, staged-only, then real published observations and checks both names against the durable stage pin. `audit_verified` matches authenticated audit to independent SQLite rows with the exact scope/operation and durable observation and confirmation. A2 must still pass after publication. |
| C Fence and supervision | `gate` identifies durable dispatch revision and concrete before/after edge. `authority_change`, `rpc_denied`, and `receipt` order decisions. Check absent final names for pre-pause/cancel/revoke/replace/expiry and later publication only via a new pre-pause advance. Check retained inodes after post-pause/cancel/revoke/expiry. The concurrent pair must reach both gates, then preserve the winning inode/digest and report occupied destination. `transport_reply_discarded` plus receipt replay and conflict prove lost-reply behavior. Check `publication_counters` per operation, zero untracked and no duplication. |
| D1 Interrupt and recover (mission D1–D3) | `broker_interrupted`, `process_exited` and `stale_endpoint_removed` identify the exact SIGKILL and cleanup. Compare all `broker_ready` pins and distinct PIDs. D1 retains the original inode/digest and reaches durable `reconciled`. D2 remains uncertain with absent final. D3 records `attribution_observation_removed`, preserves final inode/digest and remains uncertain. Recovery counters must show zero actual adapter calls/links. |
| D2 Reissue (mission D4) | `rpc_denied` before reissuance plus `exact_grant_profile`, `status`, `audit_verified` and `receipt` show minimal individual status/audit/receipt authority. New work requires exact new grants and fresh attempt/request IDs. `direct_access` repeats the staged and post-publication probes after restart. |
| E1 Cleanup and installed service | Preserve process lifecycles and inspection manifest. Review socket, mount, inode, ownership and mode checks; retain evidence hash and separately approved cleanup result. Match installed-unit digest before execution, at inspection and after removal. |
| E2 Sway preservation | Preserve all four `sway-baseline/1` snapshots with individual hashes, exact same compositor/socket, recorded predeclaration and interaction log, comparison outputs and corroboration for any agreed dynamic change. Missing or unexplained evidence is inconclusive. |

Use **experimental GO** only after independent review of every mandatory observation from an actual cross-UID execution. The driver's successful actual result is `pending_operator_review`. Use **PARTIAL** for an incomplete, interrupted or inconclusive actual qualification and **NO-GO** for an observed unauthorized access/effect, overwrite, duplicated publication, identity violation or false successful confirmation. The nonprivileged rehearsal cannot establish a cross-UID outcome. D5 and real private graphical isolation remain outside this qualification.

The local commands are `python3 -B -m tools.workspace_cross_uid plan`, `python3 -B -m tools.workspace_cross_uid rehearse` and `python3 -B -m unittest discover -s tests -p 'test_workspace_cross_uid.py'`. Rehearsal uses a disposable temporary directory, separate same-UID processes, the actual adapter and SQLite. It labels peer and direct Linux probes NOT RUN and cannot invoke provisioning or cross-UID paths.
