# V0.8-D.2C.1 — Local mediated workspace qualification

**Experimental GO for the disposable local profile.** A same-UID LoopBridge
broker accepted exact authorization, published a real regular file,
independently reopened it, and recorded confirmation separately from dispatch.
The [capability contract](../design/LOOPSHELL_V0_8_D2C1_MEDIATED_WORKSPACE.md)
defines the authority fence and recovery semantics.

## Environment and fixtures

The base was `origin/main` at `319973b65985880c6704d6ebe494d902d15e387f`,
the incorporation of [PR #43](https://github.com/LoopGolem/loopenvironment/pull/43).
Work used a dedicated checkout on `codex/v08d2c1-mediated-workspace`.
The historical checkout and existing worktrees were preserved.

The focused proof ran as an ordinary user on Debian with Linux
`6.12.117+deb13-amd64` and SQLite `3.46.1`, using disposable ext4
directories for real files, SQLite and Unix sockets. The same integration
also ran on the local tmpfs used by test discovery. All workspace content
and verifiers came from synthetic fixtures. GTK tests used a separate,
temporary headless Sway session, a private session bus and isolated XDG
directories. The harness stopped the test compositor and removed its
temporary runtime directory.

## Observations

| Boundary | Result |
| --- | --- |
| Authority and pause | Authenticated registration, confirmation, and objective acceptance succeeded. Acceptance alone did not grant a capability. Separate exact grants were necessary. Admission was paused with an empty resource. One step created only the protected staging entry. Wrong scopes, malformed or oversized content, observer commands and a disabled Registry principal were rejected at the relevant boundary. |
| Publication and inspection | Explicit publication created one mode-`0600` regular file. The test opened the actual final file independently and verified the two links pointed to the same inode. The fixture held 60 UTF-8 bytes with SHA-256 `a6e69dc60c5da8014be9d028c5ea580b1834df0d51a40d766d95cfc927efcb55`. An audit page contained the authorized digest and effect events. Document bytes and credentials stayed outside the projection. |
| No replace | An existing regular file and symlink were preserved. An enrolled directory replacement, stage symlink, modified staging bytes and database pin mismatch fenced publication. Two concurrent advances to the same destination produced one winner and one definite destination conflict. Duplicate IDs returned their original receipts under authorized replay, and divergent eligible requests were rejected. |
| Supervision | Barriers exercised pause during preparation and pause, cancel, revoke, replaced generations and expiry before publication. A simulated clock change between resource checks and the final authority sample prevented the link. After the actual link, revoked authority and an expired attempt had no effect on confirmation. Pause and cancellation were refused at the closed boundary. |
| Failure injection | Preparation failure left the final name absent. A simulated ambiguous publication error was resolved only where independent inspection found the attributed file. Simulated synchronization failure retained an observed-but-unconfirmed effect. Simulated SQLite commit failure left a real file and durable publication intent. Both cases reconciled on restart. Deliberately dropping an RPC reply after confirmation preserved the historical receipt and inode across replay and restart. |
| Real interruption | A subprocess was sent `SIGKILL` after the actual link and before confirmation. The next broker verified the same inode with the original pins, persisted `reconciled` and did zero apply calls. A separate kill after dispatch and before link left an absent path and an uncertain operation. Pre-dispatch interruption was recorded as demonstrated absence. |
| Conflicting evidence and restart | A replaced file with the same digest, changed bytes on the original inode, a missing attribution link and a displaced resource all left uncertainty. Previously confirmed history was preserved. Capability grants were empty on restart. Explicit reissuance enabled a receipt or read in the original scope and enabled new work only under a distinct exact approval. |

The file creation, directory entries, SQLite state, filesystem opens, process
termination and restart were actual observations. The scheduling barriers
and injected syscall, sync, commit and response failures were controlled
simulations. The local result covers process interruption with retained
storage. Host power loss and filesystem rollback remain unqualified.

## Regression and contract checks

- `python3 -B -m unittest discover -s tests -p 'test_workspace_effect.py' -v`
  ran **30 tests successfully** on ext4. These included strict framing and
  RPC fields, exact schema isolation, real SQLite integrity and foreign key
  checks, and the reference client.
- Focused unittest discovery covered Registry domain, durability, RPC and
  operational profiles, D.2A, D.2B, the existing cross-UID rehearsal code,
  Sway baseline and Activity.
- `python3 -B -m unittest discover -s tests` ran **563 tests**, including
  **8 GTK opt-in skips**. The three suites from the CI unit contracts job
  ran **16 tests** successfully.
- `LOOPSHELL_TEST_GTK=1 /usr/bin/python3 -B -m unittest discover -s tests`
  ran **563 tests successfully** on the temporary headless compositor.
  GTK emitted a deprecation warning for the existing CSS provider call.
- Markdown file and anchor checks and `git diff --check` covered the
  delivered changes.

### Activity timeout reproduction

On incorporated main, `test_timeout_clears_authorization` passed 298 times
and failed twice in 300 repeated runs. One captured failure showed the fake
server hitting the class-wide `DeadlineChannel.receive` mock and closing
first. The client then received `DISCONNECTED`, while the server also
recorded the injected `TimeoutError`. The test now patches only the
client's receive method. The assertions and timeouts are unchanged. All
300 post-fix runs passed. This was a fixture scheduling issue in Activity,
independent of the workspace authority fence.

## Qualification limits

The [D.2C.2 cross-UID matrix](../design/LOOPSHELL_V0_8_D2C2_ACCEPTANCE.md)
is **NOT RUN**. The local run does not establish Linux UID isolation.
Real private graphical resources remain **NOT RUN** and D5 remains
**PARTIAL**. D.1C.4 retains experimental GO for its Registry scope. D.2A
and D.2B retain experimental local GO. D.2B.2 retains experimental GO
for phases A–D, cleanup GO and global PARTIAL. M1.3B remains independent.
