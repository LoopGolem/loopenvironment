# LoopBridge V0.3 and LoopTeach V0.1

Local experimental service for a supervised Sway/AT-SPI desktop. Use the existing [V0.2 setup](LOOPBRIDGE_V0_2.md#run) and start in `desktop` mode. The JSON-lines client uses wire version `0.3`. The desktop still accepts the documented V0.2 calls and the legacy Calculator mode accepts V0.1.

## Run the teacher

Grant the operator `session.discover` on `*` and `desktop.observe` plus `teach.write` on the intended application, such as `app:editor`. Launch the supervised app with a separately authorized controller.

```sh
/usr/bin/python3 -B -m loopbridge teach \
  --socket "$lab/runtime/socket/control.sock" \
  --token-file "$lab/credentials/observer.token"
```

Choose an application and window. Search or page through live elements, inspect the candidate, then enter its meaning and a suggested operation. For GNOME Text Editor, search for `page.save` and select the document frame. A bounded reference refresh revalidates the same live element before the tool submits its evidence. The CLI uses the Unix socket. Run untrusted operators with the [isolated-client profile](LOOPBRIDGE_V0_2.md#run) and their own credential only.

```sh
/usr/bin/python3 -B -m tools.loopteach_demo --extra-catalog --evidence /tmp/loopteach-result.json
/usr/bin/python3 -B -m unittest discover -s tests
```

## V0.2 → V0.3

| Capability | V0.2 | V0.3 |
| --- | --- | --- |
| AT-SPI operation policy | Fixed checks in the desktop adapter | Shared text, value, selection and invocation handlers check native interfaces, application policy and fresh identity. The calculator display and editor file remain specialized verification contracts. |
| Target discovery | Paged tree, temporary references | Adds `element.inspect`, `element.refresh` and explicit selection queries. Refresh only renews a still-valid identity from the same connection, revision and lease generation. |
| Editor workflow | Fixed `report.txt` | `app.open_document` accepts multiple authorized top-level workspace files. `app.close` terminates only the supervised child and refuses an editor with unsaved changes. |
| Catalog | Calculator, Text Editor and Nautilus | Adds supervised GNOME Clocks observation. Firefox remains disabled. |
| Teaching | No runtime | Structured CLI, scoped API, durable revisioned annotations and conservative matching across application restarts. |

Use `app.open_document` with `app`, `document`, and a lease. This needs `app.launch` on the app and `workspace.read`. Use `app.close` with `app`, a lease and an `app.close` grant. Editor paths pass the existing workspace checks for traversal, links and regular-file ownership. `element.select` takes a container `ref`, `index` and lease, with app observation/control and workspace read. It uses AT-SPI Selection only for allowed, scoped file items, then reads back the selection. `element.get_selection` returns indices for compatible containers. Unsupported actions, ambiguous actions and stale refs are reported explicitly. Mutations with uncertain results keep the existing journal and blocked-session behavior.

## LoopTeach API

Every request includes `session`. Stored records use annotation version `0.1`. The runtime directory holds the mode-`0600` SQLite database. Keep that directory across service restarts. Annotation revisions record the creator, editor/reviewer, timestamps and provenance. Deletion writes a tombstone. Older revisions remain on disk for audit.

| Method | Authority and arguments |
| --- | --- |
| `teach.create` | `teach.write` and `desktop.observe`. Supply a live element `ref` and annotation fields. Native evidence is gathered by the trusted worker. |
| `teach.update` | `teach.write`. Supply `app`, annotation ID as `annotation`, current `revision` and replacement fields. Update resets review status. |
| `teach.delete` | `teach.delete`. Supply `app`, `annotation` and `revision`. |
| `teach.list`, `teach.inspect` | `teach.read`. Supply `app` and either `offset` or `annotation`, respectively. |
| `teach.review` | `teach.review`. Supply `app`, `annotation`, `revision` and `decision` (`approved` or `rejected`). |
| `teach.resolve` | `teach.read` and `desktop.observe`. Supply a live window `ref` and `annotation`. Returns `matched` with the annotation, a fresh element ref and criteria, or `ambiguous`/`unresolved` with a reason. |

All teaching grants can be scoped to an application within a session. The annotation fields are `meaning`, `operationHint`, `conditions` and `warnings`. Pass empty strings for optional fields. The worker records app ID, executable digest, window role and context, semantic role, accessible name, bounded native interface/action evidence and ancestry. It omits document buffers, protected elements, coordinates and runtime handles. Active Bridge credentials are refused if present in annotation text or captured metadata. Use disposable data for teaching. The service cannot identify arbitrary secrets typed into an annotation.

Matching requires a unique candidate with application, window and semantic context evidence. An incomplete search cannot establish uniqueness. Operator text and suggestions stay distinct from AT-SPI evidence and never affect grants or invoke actions. Review metadata documents a decision about a note, separate from dispatch authority.

## Qualification and limits

**GO for the supervised editor workflow.** An isolated observer used the interactive selector to teach `document.save`, without a control lease or grant. The owner reviewed the annotation. After restarting both the editor and service with the same SQLite store, the isolated controller reopened a different workspace document. The old ref was rejected. The saved annotation produced a fresh match, and the filename annotation returned `unresolved` in the changed document context. After editing, the controller resolved again and invoked `page.save`. An independent filesystem read verified the resulting UTF-8 bytes. The privileged-looking hint was refused by the normal action policy. Grant, storage and duplicate-control tests are separate from the real graphical evidence. See the [sanitized run](labs/evidence/LOOPBRIDGE_V0_3_LOOPTEACH_RUN_01.json).

The final verification ran `/usr/bin/python3 -B -m unittest discover -s tests` with **133 passing tests**, including duplicate-match refusal, scoped grants, credential rejection, SQLite revisions and journal regressions. The real commands below each reported `GO completed`.

```sh
/usr/bin/python3 -B -m tools.loopteach_demo --extra-catalog --evidence /tmp/lbt-final.json
/usr/bin/python3 -B -m tools.loopbridge_demo --evidence /tmp/lbt-final-v01.json
/usr/bin/python3 -B -m tools.loopbridge_desktop_demo --evidence /tmp/lbt-final-v02.json
```

**PARTIAL for broader controls.** GNOME Clocks launched and its window was observed. Nautilus launched and its window was observed, but this run found no compatible workspace selection container. Generic value and selection paths were exercised with deterministic fixtures. Cross-version and cross-locale matching, graphical teaching overlays, Super+click interception, Firefox, conventional input, remote control and takeover remain outside this MVP.
