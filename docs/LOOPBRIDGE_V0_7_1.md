# LoopBridge V0.7.1 — Scoped Credentials and Process Hardening

**Status: experimental; PARTIAL overall.** This milestone consolidates incremental hardening on top of [V0.7](LOOPBRIDGE_V0_7.md). It is **not** a same-UID isolation fix, a security certification, or a production deployment claim.

## Scope and delivered changes

- The lab `provision` command writes a versioned `service.json` manifest containing SHA-256 credential verifiers, with separate owner/delegate/observer bearer-token files (`0600`). The service can load the verifier manifest; the legacy bearer manifest remains an explicitly allowed compatibility path in existing service/manager modes.
- The private-session manager supports opt-in `--scoped-credentials`. In that mode each `private.start` requires a distinct, validated `credentialVerifiers` map. The manager rejects missing and reused verifiers, including reuse after an instance stops within the current manager lifetime. The manager's bootstrap identity and each private desktop have different credentials.
- Private instances receive verifier manifests rather than raw bearer-token maps during bootstrap. The experimental GTK viewers also support `--token-stdin`, so the scoped demonstration need not create persistent per-viewer token files.
- Selected trusted Python processes and the C capture helper use `PR_SET_DUMPABLE=0` as defense in depth. Bootstrap stdin is closed/rebound in relevant service/viewer paths; some subprocesses explicitly use `close_fds=True`.
- The scoped presentation demonstration exercises credential independence, stale-session rejection, viewer exit, revocation, bounded delivery, isolated clients and process-access observations.

**Compatibility boundary:** scoped credentials are **not** the default for every invocation. Existing `private` launches without `--scoped-credentials` preserve the legacy-compatible path; this release does not silently migrate prior session launchers or establish a production credential lifecycle. A verifier manifest is authentication material and should still be protected appropriately, even though it does not expose the random bearer tokens directly.

## Reproducible experimental check

Run in the disposable Debian 13/Sway VM, from the repository root. The command starts temporary lab resources and exercises only the project's own local sessions:

```sh
/usr/bin/python3 -B -m unittest discover -s tests -v
/usr/bin/python3 -B -m tools.loopbridge_presentation_demo \
  --evidence /tmp/loopbridge-v071-full-01.json \
  --seconds 8 --wait-for-operator
```

Use a new evidence filename for a new run. The interactive confirmation is a human observation gate. The demonstration starts with fluid native streaming and later runs the deliberately slow V0.6 PNG baseline (~1 FPS). For a **view-only smoke** without the full authorization/process matrix, pass `--view-only`. Do not interpret its `sandboxAuthorization: PARTIAL` as a failed test.

### User-reported local observations (2026-11-20, America/Sao_Paulo)

The following figures were supplied from a local, complete demonstration run and have not been independently rerun by CI or checked into the repository as raw evidence. The operator confirmed visible motion and window behavior.

| Signal | Recorded result |
| --- | ---: |
| Existing Python regression suite before the additional tests in this PR | 165 passed / 0 failed |
| Full demonstration stage / overall result | `complete` / `PARTIAL` |
| Motion | 55.99 painted source FPS (462 frames in 8.233 s) |
| App-to-presentation feedback p95 | 40.84 ms (462 samples) |
| Capture-to-receive p95 | 6.53 ms (486 samples) |
| Viewer first paint | 76.67 ms |
| Baseline V0.6 PNG | 1.00 unique FPS |
| Viewer exit to idle capturer | 83.93 ms |
| Human observation | Confirmed |
| Credential checks | 7 reported true, including separation and retired-session rejection |
| Isolated client and presentation negative checks | Reported passing in the full matrix |

The new `tests/test_loopbridge_identity_v071.py` adds deterministic, nonprivileged unit coverage of the verifier schema and role authentication. It does not replace the end-to-end VM matrix. Its passing status must be established by a fresh test or CI run; **do not count it among the previously observed 165 tests**.

## Gate matrix

| Gate | Result | Basis / limitation |
| --- | --- | --- |
| Live streaming | **GO (lab)** | Viewer received and presented real private Sway frames; Firefox remained usable after viewer exit. |
| Performance | **GO (lab)** | Reported FPS and latency met the prior V0.7 fixture thresholds. |
| Isolated-client authorization | **GO (lab)** | Full demonstration reported denial of unauthorized, insufficiently scoped and cross-session access; revocation, expiry, invalid media input and session teardown checks passed. |
| Scoped credential checks | **GO (lab)** | Bootstrap/session credential separation, verifier reuse denial and rejection after session replacement were reported. |
| Human observation | **GO (lab)** | Operator confirmed window and animation. |
| Unrestricted host same-UID isolation | **PARTIAL — open** | Direct private Wayland registry, screencopy, virtual-input protocol advertisements, Sway IPC and session D-Bus remained accessible from the unrestricted same-UID host context. |
| Overall | **PARTIAL** | Secure isolation for unrestricted same-UID processes was not demonstrated. |

### Why the last gate remains PARTIAL

The full lab report explicitly recorded `sameUidHostProcAccess` for private Wayland, Sway and D-Bus as reachable. Its `directDisplay` fields for Wayland registry, screencopy, virtual-input protocol advertisement, Sway output query and D-Bus GetId were all `true`. Some process-level restrictions held for the manager, viewer and Bridge, but the compositor still exposed process inspection surfaces, and the protected Bridge/capture helper retained some host proc-root visibility.

`PR_SET_DUMPABLE=0` restricts selected process-inspection operations; it is not a Linux security identity boundary and should not be assumed to survive every `execve` transition. Socket permission `0600`, namespaces and per-session bearer tokens do not, by themselves, deny direct compositor paths to an unrestricted process operating with the trusted host UID. The verifier manifest was readable in the host experiment, but the report found no persistent per-client bearer files in the scoped credential directory. **Do not infer that it read any real bearer secret.**

The lab authorizes neither execution of hostile agents with unrestricted host credentials nor exposure of sensitive production sessions. The existing sandboxed-client guarantees and the unresolved unrestricted-host boundary must remain distinct.

## Remaining verification before merge / follow-on work

1. Run the full suite after adding the new tests and check PR CI. Record the actual new total; the historical 165-test result is not a new-suite result.
2. Check that legacy fixture/service startup and scoped private-session mode both work with the new manifest format. Confirm rejection of invalid verifier maps and that malformed input cannot replace active identities.
3. Rerun the full GUI integration if changes touch runtime or presentation code. Preserve independent `desktop.stream`, `desktop.capture`, semantic and control grants.
4. Document the host trust assumptions, operationally supported modes and any downgrade/legacy compatibility policy before production use.
5. **Separate hardening milestone:** review an architecture with distinct Linux security identities for the trusted service and untrusted client processes, minimal broker interfaces, an explicit provisioning contract, and host-authorized setup. Verify direct display/IPC denial and compositor/credential lifecycle in a disposable VM before changing this gate to GO.
6. Keep future verified input takeover/handoff gates independent; neither streaming nor credential isolation proves preemption of delayed semantic or conventional effects.

## Next milestone decision

V0.8 Shell may proceed as an **experimental observer/supervisor** using authenticated Bridge presentation with the same documented trust boundary. It must not claim safe operation against unrestricted same-UID adversaries. The host identity separation can be delivered in its own reviewable branch and accepted only when its own criteria are met. No privileged host configuration change is authorized by this document.
