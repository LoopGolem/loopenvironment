# V0.8-D.2C.2 — Proposed cross-UID acceptance matrix

**Status: NOT RUN.** D.2C.2 requires an independently authorized disposable
Debian clone. Use separately identified service and executor identities, an
approved source revision, a private fixture root, a preprovisioned ingress
outside that root and a bounded run window. Retain the trusted pins through
restart. Use the existing [cross-UID preflight](../labs/LOOPSHELL_V0_8_D2B1_CROSS_UID_PREFLIGHT.md)
as a runbook reference. The workspace capability has its own gate.

| Gate | Required observations |
| --- | --- |
| A1 — Linux identities and ingress | Record effective UID/GID and process identity on both ends, nominal socket access, `SO_PEERCRED` and Bridge authentication. Test invalid credentials and an unauthorized peer. Verify the expected service peer again after restart. |
| A2 — Direct resource denial | With the real executor UID, attempt traversal and listing of the private root and enrolled directory. Attempt direct create, read, open for write and access through service descriptors in `/proc`, including after a mediated document exists. Test direct access to the database and policy. Record denials and an authorized control read by the trusted verifier. Check the ingress sends no private file descriptors. |
| B1 — Exact authority | Register, confirm and accept an objective through authenticated Registry RPC. Show denial with only objective acceptance, an unrelated principal, wrong resource, revision, attempt, capability or payload digest, and replaced/revoked or expired grants. Verify view-only status and audit grants separately from control. |
| B2 — Authorized real effect | Observe an empty final name after admission and after the preparation step. Publish through an explicit later step or authorized continue. An independent trusted verifier opens the regular file, checks pin and protection, verifies operation attribution and compares a synthetic SHA-256. Correlate with the durable audit. |
| C — Fence and supervision | Use deterministic gates before the authority fence and after the actual link. Race pause, cancellation, revocation and expiry on both sides. Exercise concurrent publications to one resource and a lost reply with request replay. Verify the final name, digest, ledger and same inode. |
| D1 — Interruption and recovery | Stop the trusted broker after the link and before durable confirmation, then reopen the same pins under a fresh service process. Repeat with a dispatch-only interruption and with one deliberately missing or contradictory observation in a separate synthetic fixture. Show `reconciled` or preserved uncertainty as appropriate, no automatic redispatch, no duplicate final and no restored volatile grants. |
| D2 — Explicit reissuance | Verify reads and controls are denied before reissuance. Reissue only the specific read or receipt grant, then verify retained state. A new operation needs a new attempt, request ID and exact approvals. Confirm resource direct-access denial under the executor UID after restart. |
| E1 — Cleanup and installed service preservation | Preserve the installed unit's baseline and compare before and after. Confirm fixture broker and helper termination, retained evidence export and cleanup of only the approved fixture paths. Check for stale sockets, mounts and access rules. |
| E2 — Revised Sway baseline | Capture component-wise Sway baselines from the existing desktop UID before provisioning and after cleanup at stable points. Record process and socket identity, version, configuration evidence and output identity separately from dynamic state. Predeclare expected dynamic differences and corroborate them with operator observations. Missing evidence is inconclusive. Use the [revised comparison methodology](../labs/LOOPSHELL_V0_8_D2B1_CROSS_UID_PREFLIGHT.md#baseline-gráfico-para-qualificações-futuras). |

Require complete mandatory evidence for an experimental GO. Missing or
inconclusive required evidence keeps the result PARTIAL. Any observed unauthorized
effect, overwrite or direct access is a NO-GO for the affected boundary.
D5 remains PARTIAL and private graphical resource isolation remains NOT RUN.
The Sway checks here cover baseline preservation only. M1.3B keeps its own
preemption gates.
