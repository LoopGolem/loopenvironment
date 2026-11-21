# D4.2C — First cross-UID graphical smoke

## Disposable lab handoff

**Gate 3 result `D42C_GATE3_FUNCTIONAL_PASS`.** The first attempt in the disposable clone ended at `broker_adapter`. After a separately authorized migration, the operator reported that one new offline attempt passed the [functional checks](#gate-3-functional-result). The first failure's exact cause remains inconclusive. Overall host isolation remains **PARTIAL**.

| Role | VirtualBox machine and UUID | Service baseline |
| --- | --- | --- |
| Functional D4.2B reference | `LoopEnvironment-M1-Lab` · `1fdf7e93-4d4b-4ddd-aa72-ddb41d8b16fc` | Release `af6057c3bbbe83c9058c28dca2fa4abb156202fa`. Manager PID `16793`, UID/GID `980:980`, active with zero restarts, unit disabled at boot. Primary Sway PID `1617`, UID `1000`. These process and unit states were also checked by local read-only inspection during this handoff. |
| Disposable D4.2C diagnostic | `LoopEnvironment-D42C-Diagnostic` · `10a1d971-aba2-4d2b-b01e-74b7e85f7c26` | Operator reported PID `3116` for the original clone manager and PID `30622` after migration. At closure the new manager was active with zero restarts, the unit was disabled at boot, and the authenticated instance list was empty. |

The full clone used the cold snapshot `LoopEnvironment-Pre-D42B` (`84cf825d-7036-4356-99b7-acdb80cb098a`) and independent VDI `8a4320d1-88fd-440e-ab7e-02f93ee4299a`. Linux DMI reports `71d9a110-a2ab-2b4d-b01e-74b7e85f7c26`. Decoding the DMI value with `uuid.UUID(bytes_le=...)` yields the clone UUID above. The clone inherited the original hostname. Use the UUID for identity.

The operator confirmed eight disabled virtual NICs, only `lo` in Debian, disabled clipboard, file transfer and drag-and-drop, and no mounted file shares. The clone runs Debian kernel `6.12.117+deb13-amd64`. Sway, Bubblewrap, D-Bus, GTK, PyGObject, PyAT-SPI, Calculator and ACL tooling were present.

Gate 1 ended at `GATE1_VERIFIED_POWERED_OFF`. Gate 2 provisioned revision `76e90edf3c61e5f3b996f9cdec9aa0eaf9f5a2e2`, manifest SHA-256 `1be7c99bbd2ed91a7772fc7d369218bc9ac3d4d9b90b5387f45593d5d15a18e6`. The operator verified the five files on `C:\Projetos\D42C\Gate2\D42C-Diagnostic-v2.iso` on Windows and rechecked the scripts inside the clone.

| ISO file | Approved SHA-256 |
| --- | --- |
| `candidate.tar` | `1b43f057dadee3b28961133db574dee51c0b8b141b1237654c505a38552e6fad` |
| `loopbridge.service` | `bdb53f4f944f26f2d41bafca06e1dc33bb3605a84326db39ba8051498956a977` |
| `client.tar` | `472fc62d1ce0915bb5d26ca880f9618144f79b9090c48d69093b22efea1387cc` |
| `gate2-preflight.sh` | `7f4fe84c1e70dd0b952a45f85ff1ef427472b21dcb7700bdf68643e8cec96697` |
| `gate2-provision.sh` | `860a2d7cf7b9fa7faf09975d18519ee674c57828a7579bf9784a24b604692bad` |

The operator ran `sudo /usr/bin/env -i /bin/bash /mnt/d42c-gate2/gate2-provision.sh --authorize-d42c-gate2-e` exclusively in the clone. The reported sequence was `GATE2_E_PREFLIGHT_OK`, `stage_media`, `publish_release`, `create_account_and_directories`, `bootstrap_once` verified, `install_unit`, `start_manager`, `verify_empty_manager` approved, `publish_client_archive`, then `GATE2_E_PROVISIONED_EMPTY` with `EXIT_CODE=0`. These are operator-reported results. The clone paths `/var/log/loopbridge-d42c-gate2-e/status.log` and `/var/tmp/d42c-client-media.AAavij/client.tar` are the reported evidence and client publication. Recheck both on the clone before use.

Continue review on `codex/trusted-service-d4.2c` in [PR #25](https://github.com/LoopGolem/loopenvironment/pull/25). The original holds the evidence of the earlier D4.2B incident. The clone holds the Gate 3 evidence for its two attempts. The first clone attempt ended with `INVESTIGATION_INCONCLUSIVE` after local diagnosis. The functional pass on the second attempt is a separate result.

Local validation for this handoff covered the archive SHA-256 and byte-for-byte comparison with the pinned Git archive, the Bash and PowerShell syntax and documentation links, plus synthetic UUID, descriptor, diagnostics and viewer-metrics checks. Four identity regressions and 22 smoke fixture tests passed. The clone checkpoint remains operator evidence.

## Gate 3 functional result

The objective was one offline Calculator session in the private desktop, mediated by LoopBridge across client UID `1000` and service UID `980`. The operator reported that `check`, `stage` and `switch` succeeded on the verified offline Debian 13 clone. The active release for the successful attempt was `38e36828d1aad62617de05315df1a20ab7849668`, manifest SHA-256 `c10173b649841d860ca29b256af5497a96f9d2ff6b72baef7b3ec2b3b9367706`. The new manager PID `30622` passed authenticated readiness and returned an empty list before the start. It was reported active after the run with `NRestarts=0` and `UnitFileState=disabled`.

### Operator evidence and criteria

| Criterion | Reported result |
| --- | --- |
| Private graphical session startup | `START_EXIT=0` on the single authorized attempt with the migrated release. |
| Calculator launch and observed output | The operator saw Calculator inside the `LoopBridge · sessão privada ao vivo` window at `800x600`. |
| Observer authorization | The UID `1000` observer authenticated after verifying kernel peer UID `980`. |
| Control release | The authorized probe returned `control.released`. This records release of the setup lease. |
| Frame delivery and paint | The observer received two frames, one unique, and painted one. The human observation confirms the content of that paint. |
| Exact-ID stop | The stop for `9e343bcf3659e680` returned `phase=stopped` and `retired=true`. |
| Retirement and disconnect | The follow-up authenticated list was `{"instances":[]}`. The window displayed disconnection and the observer process was closed separately. |

The operator reported the following values from the viewer metrics after the stop.

| Metric | Value |
| --- | --- |
| `received`, `unique`, `painted`, `presentationFeedback` | `2`, `1`, `1`, `1` |
| `mailboxDropped`, `duplicate` | `0`, `1` |
| `handshakeMs`, `firstPaintMs` | `90.67`, `212.34` |
| Final state and reason | `DESCONECTADO`, `session_ended_or_unreachable` |
| Final FPS | `0.0` after disconnection. The sample does not measure sustained frame rate. |

**Decision `D42C_GATE3_FUNCTIONAL_PASS`.** The reported start, application display, authenticated observer, frame paint, control release, exact stop and empty final list satisfy this functional smoke. The older clone failure remains inconclusive. The smoke leaves sustained streaming performance, interactive agent control, broad host isolation and production qualification open. Replacement credential checks, unauthorized direct-resource and descriptor checks, and the remaining D5 matrix require their own evidence. The final report has no independent measurement of private namespace IDs or post-stop filesystem cleanup.

### Evidence boundaries and retention

- **Operator report.** The clone migration, readiness, start, displayed Calculator, viewer metrics, stop and post-stop state are reported by the operator. The evidence directory is the operator's `$S` in the clone. Expected files include `start.json`, `start.stderr`, `probe.json`, `view.json` and `stop.json`. These files and any screenshots were unavailable for direct inspection during consolidation.
- **Local artifact verification.** The candidate manifest, archive and rendered unit were available locally. The manifest is tied to the committed diagnostic revision. The migration media hashes were rechecked. The original VM's manager PID `16793`, zero restarts and Sway PID `1617` were verified by read-only inspection during consolidation.
- **Automated evidence.** The unprivileged fixture suite for the diagnostic candidate passed 289 tests before clone migration. Tests cover isolated spawn, startup diagnostics, incomplete readiness records and sanitized propagation. Fixture passes do not count as observations from the clone.
- **Technical inference.** The implementation requires a valid start descriptor and checks the peer before observer authentication. The stop implementation validates the exact instance and retirement status. These explain the significance of the reported outcomes. They do not independently attest to clone files or explain why the first attempt reached EOF.

Keep both attempts' evidence in the clone, including the failed attempt's persistent directory, registry and journals. Additional transfer is optional for final review. If needed, use the verified clone console to read the regular, non-symlink evidence files in `$S`, and record the window, file sizes and presence of the expected records. Copy only parsed, allowlisted values for exit status, diagnostic phase/reason, peer UID, observer role, event, numeric viewer metrics, public instance ID and stop/list outcomes. Report the size or absence of `start.stderr` unless a line passes the exact diagnostic parser. Leave descriptors, raw stderr, pixels and authentication material in protected storage. Verify that the sanitized excerpt contains only those fields before transfer.

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
| `/usr/bin/python3 -B -m unittest discover -s tests` with the first D4.2C candidate | 255 passed |
| Focused ingress, relay, bootstrap, release, smoke and presentation suites for the first candidate | 84 passed |
| `git fsck --no-dangling` and the installed launcher `verify-installed` | Passed |
| `setpriv --no-new-privs bwrap --unshare-all … /usr/bin/id` | Started under UID 1000 with a transient namespace |

The fixtures use real local Unix sockets, an actual synthetic ACL layout and the manager and broker RPC contracts. The new smoke fixture simulates the admitted UID and the Calculator operation. Existing fixtures verify rejection of an unlisted kernel peer, no transfer of ancillary FDs, real byte transport, stale verifiers, bounded relay shutdown and media revocation. A lost start reply leaves a session discoverable through protected listing and requires explicit stop. The namespace preflight ran without starting Sway, GTK or a private session. The first repository candidate reached `READY_FOR_VM_TEST` at this stage.

## First cross-UID attempt

The initial D4.2B-based attempt on November 21, 2026 returned the generic launcher error. The trusted root console reported these metadata in the original VM's local time. This predates both Gate 3 attempts in the diagnostic clone.

| Evidence | Observed result |
| --- | --- |
| `first-start.json` | Created at 08:32:06 with zero bytes |
| `4eed830e88a33d68` and its workspace | Created at 08:32:07 |
| `annotations.sqlite3` | Created at 08:32:09, 12,288 bytes |
| `desktop.pending` and `desktop.resolved` | Both absent |
| Private runtime, public route and active instance | Absent |
| Manager and primary Sway | PIDs 16793 and 1617 preserved. Manager active with zero restarts. |
| Root-filtered journal in the incident window | Operator reported `journal_lines=0`, `boundary_matches=0` and `desktop_matches=0`. |

The time and instance directory place the request after manager authentication and verifier reservation. The hardened manager reserves the verifier set before constructing the instance. The missing public descriptor prevents any GTK or observer-event claim for this attempt.

The supervisor launches `inside_service` after it finds the private Wayland and Sway IPC sockets. The SQLite file shows that `inside_service` passed verifier bootstrap and entered `serve` far enough to create its annotation store. The code creates that store before the adapter, broker readiness, private listeners and public relay. Early failure to launch Bubblewrap, enter the D-Bus session or find the private display is inconsistent with this artifact. The artifact cannot establish that the adapter, private listeners or relay were ready. [Supervisor and readiness](../../loopbridge/private_session.py) · [Broker startup order](../../loopbridge/service.py)

`app.launch` journals `desktop.pending` before asking the adapter to send the operation and retains that file even after resolution. Its absence leaves failure in adapter preparation, lease checks or intent publication plausible. A completed Calculator launch through this workflow and subsequent failures in observer grants or control release would have left the marker. The remaining paths include adapter startup, broker or socket readiness, namespace checks, public relay publication, exit around the ready reply, private presentation setup and Calculator preparation. The data does not identify which path failed. An empty active list and absent runtime can result from constructor cleanup, manager reaping or the administrative rollback for a known ID. They do not establish which cleanup path executed. [Dispatch order](../../loopbridge/broker.py) · [Administrative workflow](../../loopbridge/service_smoke.py)

The following optional read-only query is for the trusted root console. It covers the reported window in São Paulo time. It reports counts and discards message text, including multi-line payloads. The ordinary UID could see no entries in this window. The releases used for this attempt redirect the private desktop subprocess stderr to `/dev/null`, so even an empty root result cannot exclude a private startup failure.

```bash
TZ=America/Sao_Paulo /usr/bin/journalctl --unit=loopbridge.service \
  --since '2026-11-21 08:31:55' --until '2026-11-21 08:32:25' \
  --no-pager --quiet --output=cat |
  awk '{
    text = tolower($0)
    if (text ~ /bwrap|namespace|mount|permission denied|read-only file system/) boundary++
    if (text ~ /sway|wayland|dbus|at-spi|adapter|calculator|relay/) desktop++
  }
  END {
    printf "journal_lines=%d boundary_matches=%d desktop_matches=%d\n", NR, boundary, desktop
  }'
```

## Gate 3 attempt — broker adapter startup

The operator reported the first Gate 3 start on `LoopEnvironment-D42C-Diagnostic` (`10a1d971-aba2-4d2b-b01e-74b7e85f7c26`), with manager PID `3116` (`980:980`), primary Sway PID `1567` (UID `1000`), and release `76e90edf3c61e5f3b996f9cdec9aa0eaf9f5a2e2`. The environment was offline and isolated. The start exited `1` with `loopbridge: phase=broker_adapter cleanup=confirmed reason=readiness_eof`. An authenticated follow-up returned `{"instances":[]}`. The Calculator did not start on that attempt. These are operator observations. The clone's filesystem and journal were unavailable for direct inspection during the investigation.

### Boundary established by the record

`serve()` opens the annotation database and initializes the journal before publishing `broker_adapter` and constructing `Adapter`. The next marker, `broker_listeners`, follows successful adapter construction. In the clone, the supervisor had found the private Wayland and Sway IPC sockets and forwarded the broker's `broker_adapter` marker before the readiness pipe reached EOF. That establishes progress through storage and up to adapter construction. Private listeners, relay publication, Calculator and GTK viewer operation are outside the observed boundary. The older incident on the original remains separate. [Broker order](../../loopbridge/service.py) · [Supervisor and readiness](../../loopbridge/private_session.py)

In the earlier release, `Adapter` created a `spawn` child and waited for the worker's first `(True, source)` reply. A failure while importing or constructing the desktop adapter could close that channel before the reply. `worker()` suppressed startup exceptions and `receive()` turned EOF, IPC errors and its timeout into `Unavailable`. When that escaped `serve()`, the broker process closed the supervisor's readiness pipe. The outer Bubblewrap process also routed inherited stderr to `/dev/null`. `readiness_eof` was the supervisor's observation of the broker pipe, with no worker exception or exit code encoded in it. [Earlier worker and handshake](https://github.com/LoopGolem/loopenvironment/blob/76e90edf3c61e5f3b996f9cdec9aa0eaf9f5a2e2/loopbridge/adapter.py)

### Local evidence and assessment

On Python `3.13.5`, `-I -B` preserves interpreter isolation and disables bytecode writes. `isolated_python()` adds only the explicitly mounted `/app` package location. The spawn interpreter starts fresh with the inherited interpreter flags. CPython serializes the parent's `sys.path` in `get_preparation_data()` and applies it in `prepare()` before unpickling the process target. The `-I` startup defaults do not remove that restored entry.

| Local check | Result |
| --- | --- |
| Actual `Adapter('fixture')` child under the isolated command prefix, with the package available only at an explicitly inserted temporary app path | Imported and answered a snapshot over the worker pipe. |
| Same fixture, with only the app entry removed from the serialized spawn preparation data | Failed before worker entry with `ModuleNotFoundError: No module named 'loopbridge'`. |
| Synthetic worker adapter import failure and separate constructor exception, each through a local `serve()` subprocess | Both produced `broker_adapter` and `readiness_eof`, with temporary SQLite present, no private listeners and no injected exception text on the broker's stderr. |
| Imports from the manifest-verified local staged release under `-I -B` in a cleared environment | `Desktop`, PyAT-SPI, `setTimeout` and GLib imported. The check did not use an accessibility or graphical session. |

An earlier unprivileged namespace fixture used a simulated Sway IPC peer and a temporary D-Bus session. It started no compositor or application. The fixture worker passed. Both an intentionally missing Sway socket and an intentionally invalid workspace mode yielded the same broad broker EOF. The non-fault-injected desktop fixture also reached that EOF without exposing the worker exception. Those runs give no direct evidence about the clone's dependency or IPC state. Subsequent reproduction was limited to independent local Python subprocess tests. [Regression tests](../../tests/test_adapter_spawn.py)

The generic hypothesis that `spawn` loses the explicitly inserted app path under `-I -B` is contradicted by the control and CPython's preparation sequence. The unresolved boundary is startup before the adapter handshake. A worker-side import or exception in private Sway IPC, AT-SPI/D-Bus, or workspace/runtime initialization can explain the result. A process creation failure or early worker death can also reach it. The clone record does not distinguish these cases. **Result `INVESTIGATION_INCONCLUSIVE`.**

### Adapter startup diagnostics

The implementation reached `ADAPTER_DIAGNOSTICS_READY_FOR_REVIEW` before the final partial-record regression and candidate build.

The change addresses the loss of detail at the adapter startup boundary. The existing worker pipe carries one bounded byte record for startup. Both ends check the finite set of success tags and failure codes. If the socket becomes readable with an incomplete startup record, the bounded nonblocking read fails closed. It restores blocking mode before ordinary operations. The hardened broker forwards one fixed `broker_adapter` reason to the existing supervisor and manager path. `spawn`, `-I -B` and the mount boundary remain in use. [Worker startup](../../loopbridge/adapter.py) · [Diagnostic allowlist](../../loopbridge/service_diagnostics.py)

| `broker_adapter` reason | Condition |
| --- | --- |
| `adapter_spawn` | The parent could not construct or start the multiprocessing child. |
| `adapter_worker_init` | The worker entered its startup code and failed in `setsid()`. |
| `adapter_import` | An exception occurred while importing the desktop or Calculator adapter in the worker. This covers the import stage and its transitive dependencies. |
| `adapter_construct` | The selected adapter constructor raised after import. Sway IPC, AT-SPI/D-Bus and workspace/runtime initialization are possible causes within this phase. |
| `adapter_startup_channel` | The startup channel could not be created or read, or the readiness record or source was invalid. |
| `adapter_startup_eof` | The worker channel closed before a valid startup record. A failure in the spawn bootstrap before worker entry, abrupt exit or failed diagnostic write can produce this outcome. |
| `adapter_startup_timeout` | The adapter parent's existing worker wait expired. |

The manager and supervisor can reach their earlier deadlines first. In that case the last observed phase and `readiness_timeout` still apply. If the broker cannot send its diagnostic, its supervisor falls back to the last phase with `readiness_eof` or `readiness_timeout`. The code reports observed boundaries and keeps exception strings, paths, tracebacks, environment values and credentials out of the readiness record and manager journal. The exact cause of the completed clone attempt remains inconclusive.

The unprivileged suite (`/usr/bin/python3 -B -m unittest discover -s tests`) passed 288 tests before the partial-record correction and 289 after the open-pipe regression was added. The local subprocess and smoke fixtures cover successful isolated spawn, each startup reason, invalid records, failed diagnostic writes and the phase restriction through manager RPC and the administrative launcher. No installed manager was exercised by these tests. The later functional pass does not establish which, if any, of these changes explains the first Gate 3 failure.

#### Controlled migration to the diagnostic release

The operator reported success for `check`, `stage` and the separately approved `switch` on the existing diagnostic clone. This moved the clone from revision `76e90edf3c61e5f3b996f9cdec9aa0eaf9f5a2e2`, PID `3116`, to `38e36828d1aad62617de05315df1a20ab7849668`, PID `30622`. Both the manager and its private broker then used the diagnostic release. The staged unit differed from the old rendered unit only in the release and manifest pins in `ExecStart`. The migration plan kept both versioned directories and used the provisioned identities and registry. The original D4.2B VM was outside the migration.

| Locally verified migration artifact | SHA-256 |
| --- | --- |
| `release.json` | `c10173b649841d860ca29b256af5497a96f9d2ff6b72baef7b3ec2b3b9367706` |
| `candidate.tar` | `08f0f03f60c2ed8dc27d9ece42445470f37969d94cbac5cc984fbec1831ad9a8` |
| `loopbridge.service` | `71226975df605e9a9353ef72ddf5280ee5f5034b96fa4a4a4eef6b55cc968513` |
| `d42c-migrate.sh` | `1035cc7b77abf962689fdb1167ded1c9b2dbacfc5533cd80c369ff28bda07fd0` |
| `audit-durable-state.py` | `9239fb8933004d0b60bcd7c6e90b7fcf6d01ea06ed2fe0f7790b6de4d7befca9` |

The fresh verifier and the one offline graphical attempt were authorized separately after migration. The [functional result](#gate-3-functional-result) records that attempt. Any further session, migration or rollback requires a new decision.

## Diagnostic candidate and retest plan

The updated administrative launcher returns a nonzero status and one sanitized line on failure. It prints fixed `phase` and `cleanup` values and an optional readiness `reason` on stderr. Successful stdout retains its existing JSON shape. The root parent accepts only an exact allowed record from its verified child. Raw stderr, exception strings, RPC replies, paths, secrets and graphical data are excluded.

| Phase | Meaning |
| --- | --- |
| `state_prepare`, `desktop_startup`, `desktop_display`, `desktop_broker` | State reservation, supervisor start, display sockets or handoff to the private broker process. |
| `broker_bootstrap`, `broker_storage`, `broker_adapter`, `broker_listeners`, `broker_ready` | Last reported stage inside the private broker. The adapter marker follows SQLite and journal initialization. The ready marker follows private socket setup and server startup. |
| `desktop_boundary`, `relay_publication`, `desktop_ready_exited` | Post-ready boundary validation, public relay setup or an exit before the manager returned a ready instance. |
| `manager_start_unclassified` | The manager returned a fault without a supported phase, including `private_session_failed` from the installed D4.2B manager. |
| `start_reply_lost` | The client received no validated start reply. Delivery and cleanup require independent confirmation. |
| `presentation`, `control_acquire`, `calculator`, `grants`, `control_release` | A validated start gave the client an ID. Preparation failed at the reported phase. |
| `cleanup` | An explicit stop did not yield a confirmed stop and retirement receipt. |
| `admin_client_timeout` or `admin_client_failed` | The administrative parent has no validated child diagnostic. For start or stop the effect remains uncertain. |

`cleanup=confirmed` reports successful cleanup of the owned transient resources on manager startup failure, or verified stop and retirement through the administrative rollback. `cleanup=unconfirmed` requires listing and the [lost-confirmation procedure](#lost-confirmation-and-recovery). `cleanup=not_attempted` indicates a failure before a cleanup action. It does not permit reuse of any verifier supplied to a request.

The supervisor forwards allowlisted progress from the private broker on the private readiness pipes. The manager reports the last received phase when the pipe reaches EOF, its deadline expires or a record exceeds its bound. Progress records never satisfy the ready handshake. Bounded reads keep a partial line from blocking past the readiness deadline. The manager's 28-second budget can expire while the broker's adapter is still waiting for its worker. Progress allows classification even when the inner timeout cannot be delivered first. The manager writes one sanitized failure line to its own journal independently of delivering the RPC reply. The phase `broker_adapter` can still cover worker spawn, Sway IPC, AT-SPI initialization or worker timeout. [Readiness protocol](../../loopbridge/private_session.py) · [Broker startup order](../../loopbridge/service.py)

1. Review this commit and stage its versioned release using the builder below. Pin the resulting revision and manifest SHA-256. Any installation follows the Stop 1 quarantine and verification procedure under separate authorization.
2. Qualify the diagnostic manager in the separately authorized environment below when the next attempt must distinguish startup from relay publication.
3. Obtain a fresh authorization for one offline session only after confirming the manager baseline, empty active list and absence of transient paths. Preserve `4eed830e88a33d68` and all prior evidence. Use an independent observer verifier set. Capture the phase/cleanup line separately from the public descriptor. End the one known session explicitly and stop for review. An ambiguous start goes to listing and recovery without another start.

### Retest alternatives

| Alternative | Diagnostic coverage | Risk and effort |
| --- | --- | --- |
| A. Diagnostic administrative client with current D4.2B manager | Classifies transport, presentation, Calculator, grants and cleanup. D4.2B can still collapse private startup and relay publication into `private_session_failed`, reported as `manager_start_unclassified`. | Low setup effort. A start on the working VM adds a verifier reservation and persistent state. This pairing is useful if independent evidence places the incident after a usable instance was returned. |
| B. Instrumented manager in a disposable VM | Adds broker phase and readiness cause. Distinguishes private listeners from the public relay. Retains a sanitized manager diagnostic independently of the RPC reply. | Moderate setup effort. A full clone gives separate disks, kernel, systemd, accounts and state. Check release and platform parity for a relevant comparison. |

Use B for this incident. The observed window includes both private startup and relay publication. The launcher and credential reader require the project's fixed Linux account, `loopbridge.service`, sockets and directories. A second unit in the working guest would require reworking those boundaries. The unprivileged fixtures can exercise the readiness protocol and real local sockets with synthetic identities. They cannot qualify an actual systemd credential store or the cross-UID boundary. The current guest identifies VirtualBox, with neither `VBoxManage` nor `/dev/kvm` visible. Prepare the clone on the hypervisor host.

### Disposable VM — Gate 1, isolated clone

Authorize only creation and offline configuration of a powered-off clone on the hypervisor host. Select a verified clean, cold pre-provisioning snapshot such as `LoopEnvironment-Pre-D42B`. It must precede the D4.2B credentials, registry and sessions, and contain no saved execution state. If the hypervisor cannot make a full clone from that snapshot while the source runs, use a clean Debian/Sway lab base with matching dependencies. Keep the working VM and its existing snapshots in place.

In a Bash terminal on the VirtualBox host, set `SOURCE_UUID` and the verified unique snapshot name `CLEAN_SNAPSHOT`. Inspect these read-only outputs before any clone operation. [Oracle VirtualBox command reference](https://docs.oracle.com/en/virtualization/virtualbox/7.1/user/vboxmanage.html)

```bash
VBoxManage --version
VBoxManage showvminfo "$SOURCE_UUID" --machinereadable
VBoxManage snapshot "$SOURCE_UUID" list --machinereadable
VBoxManage snapshot "$SOURCE_UUID" showvminfo "$CLEAN_SNAPSHOT"
```

After Gate 1 authorization, use a new name and clone the selected snapshot with full disks. Use the new UUID for all further changes. Confirm that the host version supports the options.

```bash
set -e
set -o pipefail
CLONE_NAME=LoopEnvironment-D42C-Diagnostic
if VBoxManage showvminfo "$CLONE_NAME" >/dev/null 2>&1; then exit 1; fi
VBoxManage clonevm "$SOURCE_UUID" --snapshot="$CLEAN_SNAPSHOT" --mode=machine \
  --name="$CLONE_NAME" --register
DIAG_UUID=$(VBoxManage showvminfo "$CLONE_NAME" --machinereadable | awk -F '"' '$1=="UUID=" {print $2}')
[[ "$DIAG_UUID" =~ ^[a-fA-F0-9-]{36}$ && "$DIAG_UUID" != "$SOURCE_UUID" ]]
VBoxManage modifyvm "$DIAG_UUID" --hardware-uuid="$DIAG_UUID" \
  --clipboard-mode=disabled --clipboard-file-transfers=disabled --drag-and-drop=disabled \
  --usb-ohci=off --usb-ehci=off --usb-xhci=off --vrde=off
NICS=$(VBoxManage showvminfo "$DIAG_UUID" --machinereadable | sed -nE 's/^nic([0-9]+)=.*/\1/p')
test -n "$NICS"
for nic in $NICS; do
  VBoxManage modifyvm "$DIAG_UUID" "--nic${nic}=none"
done
VBoxManage showvminfo "$DIAG_UUID" --machinereadable
```

Require `VMState="poweroff"`, every adapter set to `none`, and no shared folders, host-backed serial ports, passthrough devices or raw disks. For each clone disk run `VBoxManage showmediuminfo disk "$CLONE_DISK_UUID"`. Require distinct disk UUIDs and backing files, with no parent disk. Remove inherited per-VM shares from the clone while powered off with `VBoxManage sharedfolder remove "$DIAG_UUID" --name="$SHARE"`. Verify the settings again. Any inherited global share or host channel that cannot be excluded stops the gate. Record host evidence and leave the clone powered off. An incomplete clone stays powered off for review.

### Disposable VM — Gate 2, verify an empty manager

This is the build and provisioning reference. The completed execution is recorded in the [lab handoff](#disposable-lab-handoff).

Obtain separate authorization to boot and provision the verified clone. Stage the approved revision from the repository as UID 1000. Use the standard release builder and the existing systemd unit template.

```bash
set -e
set -o pipefail
REV=$(git rev-parse --verify "$D42C_APPROVED_REV^{commit}")
STAGE=$(mktemp -d /tmp/d42c-release.XXXXXX)
BUNDLE=$(mktemp -d /tmp/d42c-transfer.XXXXXX)
/usr/bin/python3 -I -B tools/prepare_loopbridge_release.py build "$REV" "$STAGE"
DIGEST=$(sha256sum "$STAGE/$REV/release.json" | cut -d ' ' -f 1)
/usr/bin/python3 -I -B tools/prepare_loopbridge_release.py verify "$STAGE/$REV" "$DIGEST"
tar -C "$STAGE" -cf "$BUNDLE/candidate.tar" -- "$REV"
git show "$REV:deploy/loopbridge/loopbridge.service.in" |
  sed -e "s/@REVISION@/$REV/g" -e "s/@MANIFEST_SHA256@/$DIGEST/g" -e 's/@CLIENT_UID@/1000/g' \
  > "$BUNDLE/loopbridge.service"
git archive --format=tar --prefix=source/ "$REV" loopbridge tools > "$BUNDLE/client.tar"
(cd "$BUNDLE" && sha256sum candidate.tar loopbridge.service client.tar)
printf 'revision=%s\nmanifest=%s\ntransfer=%s\n' "$REV" "$DIGEST" "$BUNDLE"
```

Record the manifest and three file hashes independently of the medium. Transfer only those three files to the hypervisor host using an approved offline channel. On a host with an existing ISO tool, for example, run `xorriso -as mkisofs -R -J -V D42C-DIAG -o "$DIAG_ISO" "$BUNDLE"` from the approved bundle copy. Attach the image as a virtual DVD to the verified clone. Set the controller, port and device from the clone's optical drive. [VirtualBox storage commands](https://docs.oracle.com/en/virtualization/virtualbox/7.1/user/vboxmanage.html)

```bash
VBoxManage storageattach "$DIAG_UUID" --storagectl="$DVD_CONTROLLER" --port="$DVD_PORT" \
  --device="$DVD_DEVICE" --type=dvddrive --medium="$DIAG_ISO"
VBoxManage startvm "$DIAG_UUID" --type=gui
```

In the clone, verify the Debian and kernel versions, dependencies and the ordinary UID/GID. Record deviations from the working guest. It uses kernel `6.12.117+deb13-amd64`, systemd `257.13-1~deb13u1`, Bubblewrap `0.12.0-1~deb13u1`, Sway `1.10.1-2`, D-Bus `1.16.2-2` and Python `3.13.5-1`. Calculator, PyGObject, PyAT-SPI and GTK versions also matter. Missing essentials stop the gate pending review of the clean base or a separately approved offline dependency change.

```bash
uname -r
dpkg-query -W bubblewrap sway dbus dbus-daemon systemd python3 python3-gi python3-pyatspi \
  gnome-calculator gir1.2-gtk-4.0 acl
id vboxuser
ip -br link
findmnt -t vboxsf,9p,virtiofs,nfs,nfs4,cifs
```

On the trusted root console **inside the clone**, supply the approved clone `DIAG_UUID` from the host record, along with `REV`, `DIGEST` and the independently recorded `TAR_SHA`, `UNIT_SHA` and `CLIENT_SHA`. Set `DVD_DEVICE` to the clone's guest optical block device such as `/dev/sr0`. Run the guarded block in a dedicated Bash shell. For the observed VirtualBox and Debian pairing, decode the first three DMI UUID fields in little-endian order before comparing with the approved host UUID. A malformed UUID or mismatch aborts before mounting the media. Use fresh root-owned evidence paths. The archive's digest pins every byte before extraction and the installed launcher independently checks its root-controlled inventory before initialization.

```bash
set -e
set -o pipefail
umask 022
test "$(id -u):$(id -g)" = 0:0
GUEST_UUID=$(cat /sys/class/dmi/id/product_uuid)
/usr/bin/python3 -I -B - "$DIAG_UUID" "$GUEST_UUID" <<'PY'
import sys
import uuid

def parse_uuid(text):
    value = uuid.UUID(text)
    if str(value) != text.lower():
        raise ValueError('expected a hyphenated UUID')
    return value

try:
    expected, dmi_uuid = map(parse_uuid, sys.argv[1:])
except ValueError:
    sys.exit('Gate 2: invalid clone or DMI UUID')

normalized = uuid.UUID(bytes_le=dmi_uuid.bytes)
if normalized != expected:
    sys.exit('Gate 2: DMI UUID does not identify the approved clone')
PY
test "$(ip -o link show | awk -F': ' '{print $2}')" = lo
test "$(id -u vboxuser):$(id -g vboxuser)" = 1000:1000
test "$(systemctl show loopbridge.service -p LoadState --value)" = not-found
for path in /etc/systemd/system/loopbridge.service /run/loopbridge-private /run/loopbridge-ingress \
            /var/lib/loopbridge /var/lib/loopbridge-admin /etc/loopbridge/credentials \
            "/opt/loopbridge/releases/$REV"; do
  [[ ! -e "$path" && ! -L "$path" ]]
done
[[ "$REV" =~ ^[a-f0-9]{40}$ && "$DIGEST" =~ ^[a-f0-9]{64}$ ]]
for hash in "$TAR_SHA" "$UNIT_SHA" "$CLIENT_SHA"; do [[ "$hash" =~ ^[a-f0-9]{64}$ ]]; done
if findmnt -n -t vboxsf,9p,virtiofs,nfs,nfs4,cifs; then exit 1; fi
MEDIA=$(mktemp -d /mnt/d42c-optical.XXXXXX)
mount -t iso9660 -o ro,nosuid,nodev,noexec "$DVD_DEVICE" "$MEDIA"
findmnt -n -o OPTIONS --mountpoint "$MEDIA" | grep -Eq '(^|,)ro(,|$)'
printf '%s  %s\n' "$TAR_SHA" "$MEDIA/candidate.tar" "$UNIT_SHA" "$MEDIA/loopbridge.service" \
  "$CLIENT_SHA" "$MEDIA/client.tar" | sha256sum --check --strict

if getent passwd 980 || getent group 980 || getent passwd loopbridge-svc ||
   getent group loopbridge-svc; then exit 1; fi
groupadd --system --gid 980 loopbridge-svc
useradd --system --uid 980 --gid 980 --home-dir /nonexistent --shell /usr/sbin/nologin \
  --no-create-home loopbridge-svc
install -d -m 0755 -o 0 -g 0 /opt/loopbridge /opt/loopbridge/releases /etc/loopbridge
install -d -m 0700 -o 0 -g 0 /var/lib/loopbridge-admin /etc/loopbridge/credentials
install -d -m 0700 -o 980 -g 980 /var/lib/loopbridge /run/loopbridge-ingress
setfacl --set='u::rwx,u:1000:--x,g::---,m::--x,o::---' /run/loopbridge-ingress
getfacl -cp /run/loopbridge-ingress

QUARANTINE=$(mktemp -d /opt/loopbridge/.diagnostic.XXXXXX)
tar -xf "$MEDIA/candidate.tar" -C "$QUARANTINE" --no-same-owner --same-permissions
printf '%s  %s\n' "$DIGEST" "$QUARANTINE/$REV/release.json" | sha256sum --check --strict
DEST="/opt/loopbridge/releases/$REV"
mv -T --update=none-fail -- "$QUARANTINE/$REV" "$DEST"
d42c_admin() {
  /usr/bin/python3 -I -B "$DEST/launcher.py" --manifest-sha256 "$DIGEST" "$@"
}
d42c_admin --action verify-installed
CLIENT_DELIVERY=$(mktemp -d /var/tmp/d42c-client-media.XXXXXX)
install -m 0644 -o 0 -g 0 "$MEDIA/client.tar" "$CLIENT_DELIVERY/client.tar"
chmod 0755 "$CLIENT_DELIVERY"

# Fresh clone only. This generates a different owner, manifest and registry.
d42c_admin --action admin-init
install -m 0644 -o 0 -g 0 "$MEDIA/loopbridge.service" /etc/systemd/system/loopbridge.service
systemd-analyze verify --generators=no --man=no /etc/systemd/system/loopbridge.service
systemctl daemon-reload
systemctl start loopbridge.service
d42c_admin --action admin-ready
LIST=$(d42c_admin --action admin-smoke-list)
test "$LIST" = '{"instances":[]}'
test "$(systemctl show loopbridge.service -p UnitFileState --value)" = disabled
printf '%s\nclient_archive=%s\n' "$LIST" "$CLIENT_DELIVERY/client.tar"
```

The exact name `loopbridge.service` preserves the pinned systemd credential directory. Run these read-only checks in the clone root console. Require UID/GID 980, the manager alone in its cgroup, private runtime and state mode `0700` and the exact named ingress ACL. The delivered credential in the manager mount namespace must be read-only with the [allowed ownership and ACL](TRUSTED_SERVICE_BOUNDARY_D42A.md#bootstrap-rotation-and-recovery).

```bash
CLONE_MANAGER_PID=$(systemctl show loopbridge.service -p MainPID --value)
CGROUP=$(systemctl show loopbridge.service -p ControlGroup --value)
[[ "$CLONE_MANAGER_PID" =~ ^[1-9][0-9]+$ && "$CGROUP" = /system.slice/loopbridge.service ]]
test "$(cat "/sys/fs/cgroup$CGROUP/cgroup.procs")" = "$CLONE_MANAGER_PID"
ps -p "$CLONE_MANAGER_PID" -o pid,uid,gid,lstart,args
stat -c '%u:%g %a %n' /run/loopbridge-private /run/loopbridge-ingress /var/lib/loopbridge
getfacl -cp /run/loopbridge-ingress
CRED=/run/credentials/loopbridge.service
nsenter --target "$CLONE_MANAGER_PID" --mount -- findmnt -n -o TARGET,OPTIONS --target "$CRED"
nsenter --target "$CLONE_MANAGER_PID" --mount -- stat -c '%u:%g %a %n' "$CRED" "$CRED/manager-verifiers.json"
nsenter --target "$CLONE_MANAGER_PID" --mount -- getfacl -cp "$CRED" "$CRED/manager-verifiers.json"
```

Retain the fresh clone credentials with their existing protections. The working VM's paths and logs remain separate. If qualification fails, retain the clone disk and sanitized evidence. An authorized stop targets only the clone's unit after rechecking its DMI UUID. Gate 2 ends with an empty manager.

### Disposable VM — Gate 3, one diagnostic attempt

**Historical procedure for the first clone attempt.** The literals below describe the earlier `76e90edf3c61e5f3b996f9cdec9aa0eaf9f5a2e2` release and PID `3116`, with an initially empty persistent session directory. For the completed second attempt see the [functional result](#gate-3-functional-result). Future use requires explicit GO and newly verified pins, process identities and preserved persistent state. The observer grants last 180 seconds. The published archive from Gate 2 supplies the client tools.

#### Read-only preflight

On the Windows host, inspect the running clone by UUID in VirtualBox. Require all eight NICs disabled, clipboard, transfers and drag-and-drop disabled, and no shares. The original can remain running. A read-only listing is available in PowerShell.

```powershell
$VBox = Join-Path $env:ProgramFiles 'Oracle\VirtualBox\VBoxManage.exe'
& $VBox showvminfo '10a1d971-aba2-4d2b-b01e-74b7e85f7c26' --machinereadable
if ($LASTEXITCODE -ne 0) { throw 'Clone inspection failed' }
```

In a dedicated trusted root Bash shell, load the clone context. The same block can be used to re-establish identity and read evidence if a later command exits the shell.

```bash
set -euo pipefail
set +o history
umask 077
test "$(id -u):$(id -g)" = 0:0
G3_RELEASE=/opt/loopbridge/releases/76e90edf3c61e5f3b996f9cdec9aa0eaf9f5a2e2
G3_DIGEST=1be7c99bbd2ed91a7772fc7d369218bc9ac3d4d9b90b5387f45593d5d15a18e6
G3_E=/var/tmp/loopbridge-d42c-gate3
G3_PID=3116
G3_UNIT=/etc/systemd/system/loopbridge.service
G3_CGROUP=/sys/fs/cgroup/system.slice/loopbridge.service/cgroup.procs
g3_admin() {
  /usr/bin/python3 -I -B "$G3_RELEASE/launcher.py" --manifest-sha256 "$G3_DIGEST" "$@"
}
g3_unit() { systemctl show loopbridge.service -p "$1" --value; }
g3_empty() {
  local result entry
  result=$(g3_admin --action admin-smoke-list) || return
  test "$result" = '{"instances":[]}' || return
  entry=$(find /run/loopbridge-ingress -mindepth 1 -maxdepth 1 -print -quit) || return
  test -z "$entry" || return
  entry=$(find /run/loopbridge-private -mindepth 1 -maxdepth 1 ! -name manager.sock -print -quit) || return
  test -z "$entry"
}
g3_baseline() {
  systemctl show loopbridge.service -p MainPID -p NRestarts -p ActiveState -p UnitFileState || return
  ps -p "$G3_PID,$G3_PRIMARY" -o pid=,uid=,gid=,lstart=,comm=
}
g3_same_baseline() {
  local current
  current=$(g3_baseline) || return
  test "$current" = "$G3_BASELINE"
}
G3_DMI=$(cat /sys/class/dmi/id/product_uuid)
/usr/bin/python3 -I -B - "$G3_DMI" <<'PY'
import sys
import uuid

text = sys.argv[1]
observed = uuid.UUID(text)
if (str(observed) != text.lower()
        or uuid.UUID(bytes_le=observed.bytes) != uuid.UUID('10a1d971-aba2-4d2b-b01e-74b7e85f7c26')):
    raise SystemExit('Gate 3 clone identity mismatch')
PY
test "$(ip -o link show | awk -F': ' '{print $2}')" = lo
G3_MOUNTS=$(findmnt -rn -o FSTYPE)
if grep -Eq '^(vboxsf|9p|virtiofs|nfs|nfs4|cifs|smb3)$' <<< "$G3_MOUNTS"; then exit 1; fi
test "$(g3_unit MainPID)" = "$G3_PID"
```

Run the baseline checks before the experiment. These read the installed unit, release and protected readiness interfaces.

```bash
test "$(g3_unit NRestarts)" = 0
test "$(g3_unit ActiveState)" = active
test "$(g3_unit UnitFileState)" = disabled
test "$(g3_unit FragmentPath)" = "$G3_UNIT"
G3_DROPINS=$(g3_unit DropInPaths)
test -z "$G3_DROPINS"
printf '%s  %s\n' bdb53f4f944f26f2d41bafca06e1dc33bb3605a84326db39ba8051498956a977 "$G3_UNIT" |
  sha256sum --check --strict
test "$(ps -p "$G3_PID" -o uid=,gid= | awk '{print $1 ":" $2}')" = 980:980
test "$(cat "$G3_CGROUP")" = "$G3_PID"
tr '\0' '\n' < "/proc/$G3_PID/cmdline" |
  cmp -s - <(printf '%s\n' /usr/bin/python3 -I -B "$G3_RELEASE/launcher.py" --manifest-sha256 "$G3_DIGEST" --client-uid 1000)
G3_CRED_OPTS=$(nsenter --target "$G3_PID" --mount -- findmnt -rn --target /run/credentials/loopbridge.service -o VFS-OPTIONS)
[[ ",$G3_CRED_OPTS," == *,ro,* ]]
G3_PRIMARY=$(ps -u 1000 -o pid=,comm= | awk '$2 == "sway" {print $1}')
[[ "$G3_PRIMARY" =~ ^[1-9][0-9]*$ ]]
g3_admin --action verify-installed
g3_admin --action admin-ready
g3_empty
G3_DURABLE=$(find /var/lib/loopbridge/sessions -mindepth 1 -maxdepth 1 -print -quit)
test -z "$G3_DURABLE"
[[ ! -e "$G3_E" && ! -L "$G3_E" ]]
G3_BASELINE=$(g3_baseline)
printf '%s\n' "$G3_BASELINE"
```

Use the clone's existing graphical terminal as `vboxuser`. Confirm it belongs to the clone selected on the host. The archive must be root-published and match its independent pin. Import GTK without opening a window. Stop before start if the UID 1000 Wayland session, GTK import, or archive check is missing.

```bash
set -euo pipefail
umask 077
test "$(id -u):$(id -g)" = 1000:1000
G3_DISPLAY=$WAYLAND_DISPLAY
[[ "$G3_DISPLAY" == /* ]] || G3_DISPLAY=$XDG_RUNTIME_DIR/$G3_DISPLAY
test -S "$G3_DISPLAY"
test -S "$SWAYSOCK"
/usr/bin/python3 -I -B -c 'import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk'
G3_ARCHIVE=/var/tmp/d42c-client-media.AAavij/client.tar
[[ -f "$G3_ARCHIVE" && ! -L "$G3_ARCHIVE" ]]
test "$(stat -c '%u:%g:%a' "$G3_ARCHIVE")" = 0:0:644
printf '%s  %s\n' 472fc62d1ce0915bb5d26ca880f9618144f79b9090c48d69093b22efea1387cc "$G3_ARCHIVE" |
  sha256sum --check --strict
```

#### One start and a read-only viewer

After both preflights pass, stage the client as UID 1000 and generate its fresh observer bearer and verifier with the existing probe. Transfer only the printed six-character directory suffix to root. The bearer remains in the UID 1000 directory. This uses a local file inside the clone and needs no host clipboard or file sharing.

```bash
G3_CLIENT=$(mktemp -d /var/tmp/d42c-g3-client.XXXXXX)
tar -xf "$G3_ARCHIVE" -C "$G3_CLIENT"
cd "$G3_CLIENT/source"
/usr/bin/python3 -B -m tools.loopbridge_d42c_probe generate --token-file "$G3_CLIENT/observer.token" \
  > "$G3_CLIENT/verifier.sha256"
printf '%s\n' "${G3_CLIENT##*.}"
```

In the verified root shell, enter that suffix. Read only the verifier as UID 1000. Check the manager again and reserve the per-attempt evidence directory exclusively. Keep the start exit status, descriptor and stderr separate. Run this block once.

```bash
read -r G3_TAG
[[ "$G3_TAG" =~ ^[A-Za-z0-9]{6}$ ]]
G3_VERIFIER=$(timeout 3s /usr/sbin/runuser -u vboxuser -- head -c 65 -- \
  "/var/tmp/d42c-g3-client.$G3_TAG/verifier.sha256")
[[ "$G3_VERIFIER" =~ ^[0-9a-f]{64}$ ]]
g3_same_baseline
g3_empty
mkdir -m 0700 -- "$G3_E"
printf '%s\n' "$G3_BASELINE" > "$G3_E/baseline.txt"
printf '%s\n' "$G3_PRIMARY" > "$G3_E/primary-sway.pid"
date -u '+%F %T UTC' > "$G3_E/since"
G3_RC=0
g3_admin --action admin-smoke-start --observer-verifier "$G3_VERIFIER" \
  > "$G3_E/start.json" 2> "$G3_E/start.stderr" || G3_RC=$?
unset G3_VERIFIER
printf '%s\n' "$G3_RC" | tee "$G3_E/start.exit"
```

The installed action authenticates with the protected clone manager credential and generates separate session owner and delegate credentials. It requests zero HTTPS hosts, launches Calculator through the private broker, grants observation and releases the setup lease. A nonzero exit or invalid descriptor goes to recovery even if no phase was reported. With exit zero, validate and transfer only the ID and epoch to the UID 1000 terminal.

```bash
test "$(cat "$G3_E/start.exit")" = 0
G3_PIN=$(/usr/bin/python3 -I -B - "$G3_E/start.json" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding='ascii') as data:
    pin = json.load(data)
instance = pin['privateId']
epoch = pin['epoch']
if (not re.fullmatch('[a-f0-9]{16}', instance) or not re.fullmatch('[a-f0-9]{32}', epoch)
        or pin['session'] != 'desktop' or pin['ingressSocket'] != f'/run/loopbridge-ingress/{instance}.sock'
        or pin['grantTtlSeconds'] != 180):
    raise SystemExit('Gate 3 descriptor mismatch')
print(instance, epoch)
PY
)
read -r G3_ID G3_EPOCH <<< "$G3_PIN"
G3_PRIVATE=$(ps -p "$(paste -sd, "$G3_CGROUP")" -o pid=,uid=,comm= |
  awk '$2 == 980 && $3 == "sway" {print $1}')
[[ "$G3_PRIVATE" =~ ^[1-9][0-9]*$ && "$G3_PRIVATE" != "$G3_PRIMARY" ]]
for ns in user pid mnt net ipc; do
  manager_ns=$(readlink "/proc/$G3_PID/ns/$ns")
  private_ns=$(readlink "/proc/$G3_PRIVATE/ns/$ns")
  test "$manager_ns" != "$private_ns"
  printf '%s %s %s\n' "$ns" "$manager_ns" "$private_ns"
done > "$G3_E/namespaces.txt"
printf '%s %s\n' "$G3_ID" "$G3_EPOCH"
```

In the UID 1000 graphical terminal enter the two fields. Run the probe before opening the viewer so a failed peer, observer authentication, pin or event check is distinguishable from a GTK failure. If the probe exits nonzero, proceed to cleanup on root. The viewer uses only the authorized ingress.

```bash
read -r G3_ID G3_EPOCH
/usr/bin/python3 -B -m tools.loopbridge_d42c_probe live --token-file "$G3_CLIENT/observer.token" \
  --private-id "$G3_ID" --epoch "$G3_EPOCH" > "$G3_CLIENT/probe.json" 2> "$G3_CLIENT/probe.stderr"
GDK_BACKEND=wayland /usr/bin/python3 -B -m tools.loopbridge_live_view \
  --socket "/run/loopbridge-ingress/$G3_ID.sock" --peer-uid 980 --token-file "$G3_CLIENT/observer.token" \
  --private-id "$G3_ID" --epoch "$G3_EPOCH" --metrics-file "$G3_CLIENT/view.json" \
  > "$G3_CLIENT/view.stdout" 2> "$G3_CLIENT/view.stderr" &
```

When Calculator is visible, record operator confirmation. Save proof of at least one painted frame before closing or stopping. Share only the probe's structured result and the selected numeric metrics.

```bash
cat "$G3_CLIENT/probe.json"
/usr/bin/python3 -I -B -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    row = json.load(stream)
if row["painted"] < 1 or (row["width"], row["height"]) != (800, 600) or row["reason"] is not None:
    raise SystemExit("Gate 3 paint not confirmed")
print(json.dumps({key: row[key] for key in ("width", "height", "painted")}))
' "$G3_CLIENT/view.json" | tee "$G3_CLIENT/painted.json"
```

#### Diagnostics, exact-ID stop and review

Collect the exact allowlisted records from the launcher and unit journal. Collect while the outcome is still known, or promptly after a failed start. The reviewed release's `Diagnostic.from_child` accepts only fixed phase, cleanup and optional reason. A generic launcher line or an empty filtered journal is reported as such.

```bash
g3_diag() {
  /usr/bin/python3 -I -B -c '
import sys
sys.path.insert(0, sys.argv[1])
from loopbridge.service_diagnostics import Diagnostic
for line in sys.stdin.buffer:
    if Diagnostic.from_child(line) is not None:
        sys.stdout.buffer.write(line)
' "$G3_RELEASE"
}
g3_diag < "$G3_E/start.stderr" | tee "$G3_E/admin-phases.txt"
journalctl -u loopbridge.service "_PID=$G3_PID" --since "$(cat "$G3_E/since")" \
  --until "$(date -u '+%F %T UTC')" --no-pager -o cat |
  g3_diag | tee "$G3_E/manager-phases.txt"
find /var/lib/loopbridge/sessions -mindepth 2 -maxdepth 2 \
  \( -name workspace -o -name annotations.sqlite3 -o -name desktop.pending -o -name desktop.resolved \) \
  -printf '%T@ %s %m %U:%G %P\n' > "$G3_E/state-metadata.txt"
```

| Observation | What it can establish |
| --- | --- |
| `admin_bootstrap`, `manager_preflight`, `start_rejected` | Failure before a confirmed private session. Check clone credential delivery, manager access and the fresh verifier. |
| `admin_client_timeout`, `admin_client_failed`, `start_reply_lost` | Start transport or reply uncertainty. Determine actual state by authenticated listing before any cleanup. |
| `state_prepare`, `desktop_startup`, `desktop_display`, `desktop_broker` | Durable preparation, supervisor start, private Wayland/Sway sockets, or broker launch. `desktop_display` is a private compositor/display boundary. |
| `broker_bootstrap`, `broker_storage`, `broker_adapter` | Broker bootstrap, SQLite/journal preparation or adapter startup. The adapter marker follows storage initialization. Adapter failure can cover Sway IPC, AT-SPI or worker readiness. |
| `broker_listeners`, `broker_ready`, `desktop_boundary`, `relay_publication`, `desktop_ready_exited` | Private listener setup, broker readiness, boundary validation, fixed public relay creation or exit before a ready instance could be returned. `readiness_timeout`, `readiness_eof` and `readiness_frame_limit` refine the last reported phase. |
| `presentation`, `control_acquire`, `calculator`, `grants`, `control_release` | The manager returned an instance and setup failed afterward. `calculator` is the mediated application launch, distinct from the UID 1000 GTK viewer. |
| Start descriptor valid, probe fails | Check the exact public route and its ACL metadata. Permission denied is distinct from a missing or refused socket. An unexpected kernel peer or observer denial is a boundary or authorization failure. A wrong pin or missing event is a protocol/authority observation failure. |
| Probe passes, paint missing | Check UID 1000 Wayland/GTK initialization, then the viewer's frame counters. No mapped window, zero received frames, and frames received without a paint are distinct observations. Expired grants cannot establish a stream or rendering defect. |

The supervisor's `stage:...` records travel on private readiness pipes. The two captures above report the manager/client failure boundary when available. A successful descriptor and separate client proof establish that the route was published and usable. A complete journal trace of each successful stage is unavailable in this revision.

On success, keep the viewer connected for the stop and confirm disconnection before grant expiry. On a failed client check, stop the same verified ID promptly and record the observed state. If a guarded command exited the root shell, load only the clone context again and restore `G3_BASELINE` and `G3_PRIMARY` from the saved `baseline.txt` and `primary-sway.pid`. Revalidate the stored descriptor before using its ID. For a lost start response, run `g3_admin --action admin-smoke-list` first. Only when the sole new ready instance can be identified in the exclusive empty-to-start window, enter its exact ID with `read -r G3_ID`. If the list is empty or unexpected, preserve the evidence for review.

```bash
g3_admin --action admin-smoke-list | tee "$G3_E/before-stop.json"
# Continue only with the exact validated ID of the sole ready instance.
[[ "$G3_ID" =~ ^[a-f0-9]{16}$ ]]
test "$(cat "$G3_E/before-stop.json")" = "{\"instances\":[{\"id\":\"$G3_ID\",\"phase\":\"ready\"}]}"
g3_admin --action admin-smoke-stop --session-id "$G3_ID" > "$G3_E/stop.json" 2> "$G3_E/stop.stderr"
test "$(cat "$G3_E/stop.json")" = "{\"id\":\"$G3_ID\",\"phase\":\"stopped\",\"retired\":true}"
g3_empty
test -d "/var/lib/loopbridge/sessions/$G3_ID/workspace"
test "$(cat "$G3_CGROUP")" = "$G3_PID"
g3_same_baseline
```

In the graphical terminal record the viewer disconnection and then close it. Run the existing route-absence probe for the known ID.

```bash
/usr/bin/python3 -I -B -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    row = json.load(stream)
if not row["state"].startswith("DESCONECTADO") or row["reason"] != "session_ended_or_unreachable":
    raise SystemExit("Gate 3 viewer disconnection not confirmed")
print("session_ended_or_unreachable")
' "$G3_CLIENT/view.json" | tee "$G3_CLIENT/disconnected.txt"
/usr/bin/python3 -B -m tools.loopbridge_d42c_probe stopped --private-id "$G3_ID"
```

**Procedure checks** include the distinct UID 980 compositor and namespaces, a validated public descriptor, observer authentication to kernel peer UID 980 with `control.released`, visible Calculator and at least one pinned frame painted. The procedure checks exact-ID retirement, viewer disconnection, removal of transient resources, retained workspace, and the unchanged clone manager and primary Sway baseline. The [functional result](#gate-3-functional-result) states the evidence available from the completed run.

**Diagnostic result** is a concrete phase or unresolved transport classification, with the cleanup outcome and relevant metadata. It closes the single approved attempt. A generic failure without corroboration is inconclusive. An identity, isolation, unexpected active target or unauthorized-access mismatch stops the gate.

Preserve the original VM, the clone's registry, journals and all attempt evidence. After a lost or failed stop, list again for review before any further action. Keep local stderr private. Share only time bounds, exit status, allowlisted diagnostic records, nonsecret instance IDs, metadata, selected metrics and operator observations. Keep credentials, raw outputs, RPC bodies and pixels out of the handoff. A new attempt or recovery requiring a service or installation change needs another explicit decision.

## Administrative workflow

The existing manager and the dedicated administration client use compatible RPCs. Build a separate versioned candidate for its three fixed actions. Keep the unit pointed at the D4.2B release. The installed candidate verifies its own inventory before each invocation. Its root parent reads the existing protected owner bearer, verifies it against the protected manifest and passes it on anonymous stdin to the verified child running as 980:980 with no supplementary groups. The child verifies the kernel peer before sending credentials.

The ordinary client generates its own one-instance observer bearer. Only the verifier goes to the administrator. The administrative child generates an independent session owner and delegate, supplies only verifiers to the manager, and keeps the session owner bearer in memory for setup. The offline fixture launches Calculator through the private broker, grants the observer `session.discover` and `desktop.stream` for 180 seconds, and releases the setup lease. The client receives the public ingress address, session ID and epoch. Its event check requires an idle session and reads the actual `control.released` event through authenticated ingress. The replacement probe checks denial of capture, input acquisition, workspace and administrative RPCs. The GTK viewer verifies peer UID 980 before sending the bearer.

The experiment requires a trusted administrator with exclusive use of the manager for its duration and explicit approval to install the additional versioned artifact, start and stop the two disposable offline sessions and issue the UID 65534 denial check. The unit, D4.2B release, boot state, ACL policy and credential source stay in place. The VM operator must confirm the `LoopEnvironment-Pre-D42B` snapshot and have a separate trusted administrative console and a terminal on the existing UID 1000 desktop. Use a reviewed commit, independently confirmed artifact digest, and keep the start, view, probes and stop within the observer grant window.

## Authorized VM procedure

This is the historical authorization procedure for the D4.2B-based path and its replacement and negative checks. The completed diagnostic-clone smoke is recorded above. Future execution requires its own approvals.

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
