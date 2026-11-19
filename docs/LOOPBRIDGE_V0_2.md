# LoopBridge V0.2

The local Unix-socket service exposes one Sway desktop via scoped, structured operations. A private worker correlates each supervised process with its executable, UID, start time, native Sway window and AT-SPI frame. It reports ambiguity or missing accessibility coverage instead of following focus. The catalog qualifies only applications launched by the service. Existing windows are not adopted.

## Run

From the repository root in an existing Sway session, use system Python with `pyatspi`. The reproducible graphical demo also needs Bubblewrap and the applications already installed on the host.

```sh
/usr/bin/python3 -B -m tools.loopbridge_desktop_demo --evidence /tmp/loopbridge-v02.json
/usr/bin/python3 -B -m unittest discover -s tests
```

To start the service manually with a disposable workspace:

```sh
lab=$(mktemp -d /tmp/lb2.XXXXXX)
mkdir -m 700 "$lab/workspace"
/usr/bin/python3 -m loopbridge provision "$lab/credentials"
/usr/bin/python3 -m loopbridge serve --runtime "$lab/runtime" \
  --credentials "$lab/credentials/service.json" --workspace "$lab/workspace"
```

The CLI accepts one JSON request per line after authenticating. Use the same private `lab` path in another terminal. For untrusted clients use the demo's Bubblewrap profile with only the socket directory and client code mounted. Deliver the individual credential over stdin.

```sh
/usr/bin/python3 -m loopbridge client --socket "$lab/runtime/socket/control.sock" \
  --token-file "$lab/credentials/owner.token" <<'JSON'
{"method":"discover"}
{"method":"app.list","params":{"session":"desktop"}}
{"method":"snapshot","params":{"session":"desktop"}}
JSON
```

## Wire contract

Requests use the [V0.1 JSON-RPC envelope](LOOPBRIDGE_CORE_V0_1.md#experimental-wire-contract) with `version: "0.2"`, newline framing and an 8 KiB encoded frame limit. The legacy `calculator` and `fixture` modes continue to accept 0.1. Desktop mode requires 0.2. All methods below take `session: "desktop"`. Mutations also take the `lease`, `epoch` and `generation` from `acquire`.

| Method | Additional parameters and authority |
| --- | --- |
| `app.list` | Session discovery grant. Returns catalog entries for apps the principal can observe or launch. |
| `app.launch` | `app`. Requires `app.launch` on that catalog application. No shell, executable path or caller-supplied arguments. |
| `window.list` | `app`. Scoped observation. Returns window and process identity, semantic status and a ref if correlated. |
| `window.inspect` | Window `ref`. Scoped observation. |
| `element.tree` | Window `ref`, `offset`, `depth` up to 40. Returns pages of eight elements with paths, semantics, actions and refs. Follow `next` until null. Limits and omissions are surfaced through truncation flags or a refusal. |
| `element.actions`, `element.get_text`, `element.get_value` | Element `ref`. Scoped observation. Text is bounded and reports truncation. Available interfaces determine read support. |
| `element.invoke`, `element.set_text`, `element.set_value` | Element `ref` and `action`, `text` or `value`. Scoped observation and control plus lease. The app adapter checks the action and the effect it can independently verify. |
| `workspace.list`, `workspace.read` | `offset` or relative filename `path`. Requires `workspace.read`. |
| `workspace.write` | Relative filename `path`, UTF-8 `text` up to 3,000 bytes. Requires both workspace grants plus lease. Confirmation re-reads the file and returns byte count and SHA-256. |
| `operation.status` | `operation`. Submitter or owner can read recent outcomes. The owner can query an unresolved operation by ID after restart. |
| `snapshot`, `events` | Session discovery grant. Snapshot supplies epoch, phase, revision and event cursor. Events use the V0.1 epoch/cursor parameters and report authority changes and operation outcomes. Poll application state through scoped queries. |

`delegate` and `revoke` retain their V0.1 shapes. Use `app:editor`, `app:calculator`, `app:files`, `app:browser`, `workspace`, or `*` as applicable. Grant `session.discover` on `*`. Observers cannot receive mutation grants. Leases are exclusive for the desktop and each operation checks its scope again before dispatch. Temporary refs belong to the requesting connection, session, revision and generation. Use fresh refs after mutations or policy changes. Worker identity checks also reject expired or ambiguous targets.

## Workspace, application policy and failure

The optional workspace is a canonical, mode-`0700` directory owned by the service UID. Operations are relative to its pinned directory descriptor. Clients can list directory entries and read or write top-level UTF-8 files. Traversal, subdirectory access, symlinks, hard links and special files are refused. The trusted owner must keep this directory private from other host processes.

Calculator allows verified digit clicks. GNOME Text Editor opens only `report.txt` in the workspace. Create that file before launch. The editor adapter checks document identity and supports the multiline AT-SPI field and the window's `page.save` action. Saving also requires `workspace.write` and verifies the saved bytes, including GtkSourceView's implicit final newline. An editor observation grant permits reading that document's displayed text. Nautilus is observation-only, with window and tree labels redacted to avoid exposing unrelated host paths or mount names. Firefox is detected but launch is disabled in the catalog. The service expects the supervised applications to run in a dedicated trusted lab context without concurrent desktop interaction.

Mutations report `confirmed`, `refused` or `unknown`. Authorization and validation can also return a structured error before dispatch. The journal preserves an intent before submission and writes a matching resolution receipt only for independently verified effects or proved non-submission. Missing, malformed or mismatched records block recovery when an intent exists. A matching receipt can prove resolution even if the last directory sync was interrupted and both records survived. A confirmed response may include `session_blocked` when receipt storage fails.

After an unknown result, keep the same runtime directory. There is no retry, takeover, cancellation claim or API to clear an uncertain intent. Adapter calls remain bounded. An AT-SPI call already submitted can still take effect. The runtime belongs to the trusted service and the filesystem must honor the synchronization guarantees.

## Qualification

**GO for the report mission and the tested local profile.** The isolated delegate launched GNOME Text Editor, found its multiline AT-SPI field, edited it and invoked `page.save`. An independent filesystem read verified the complete report. The observer read the edited buffer and was refused mutation. After owner revocation, the delegate held a new lease under another grant and was still refused further editor mutations. The demo also confirmed a separate workspace write, traversal denial, Calculator digit invocation, and observation of the Nautilus window and redacted semantic tree with all three applications running together. Isolated clients could not reach tested graphical/session endpoints, input devices, the workspace or the credential directory directly. See the [sanitized real-run evidence](labs/evidence/LOOPBRIDGE_V0_2_RUN_01.json).

Executed `/usr/bin/python3 -B -m unittest discover -s tests` (123 tests, including historical M1 and journal fault injection), `/usr/bin/python3 -B -m tools.loopbridge_demo --evidence /tmp/lb2-release-v01.json` (real Calculator regression, GO) and `/usr/bin/python3 -B -m tools.loopbridge_desktop_demo --evidence /tmp/lb2-release-v02.json` (GO). Journal tests cover write and sync failure, failed removal of unpublished data, mismatched or missing records, abrupt exit and restart. A diagnostic editor run also encountered an unconfirmed save before the final-newline verification was corrected. That run stayed blocked and its runtime was retained.

**PARTIAL.** Nautilus semantics can be temporarily unavailable while its accessibility tree registers. Browser operation, arbitrary app launch, window adoption, split-session operation, compositor preemption, visual capture and conventional input remain unqualified. The real run did not inject late AT-SPI effects or qualify power-loss behavior on a physical storage stack.

V0.2 supplies the live observation and temporary selection primitives for an observation-first LoopTeach MVP. A trusted picker, persisted annotation provenance, reliable re-identification and separate teaching authority still need implementation.
