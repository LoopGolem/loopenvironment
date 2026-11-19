# LoopBridge V0.4 and LoopTeach V0.2

Experimental, local-only computer use on a supervised Sway desktop. Start the service using the [private runtime, workspace and credential setup](LOOPBRIDGE_V0_2.md#run). The JSON-lines client uses wire version `0.4`. The documented V0.1–V0.3 calls remain supported in their respective modes.

## Practical API

Use the existing `session`, app grants, lease/epoch/generation and temporary references. Discover applications with `app.list` and backend availability with `session.features`.

| V0.3 → V0.4 | Capability |
| --- | --- |
| Firefox unqualified → private offline fixture | `browser.open_fixture` with `app: "browser"`, `app.launch` grant and lease. `browser.document` with a fresh window `ref` reads the fixture page or receipt. Browser operations additionally need the normal app observation/control grants. |
| Tree pages → native search | `element.find` with a window `ref` and exact `role`, `name`, `interface`, `action`. Supply empty strings for unused filters. Only a unique complete match gets a fresh ref. |
| Top-level files → structured workspace paths | `workspace.mkdir(path)`, `workspace.list_at(directory, offset)` and no-replacement `workspace.rename(source, destination)`. Read/write and editor open support nested, authorized paths. These are Linux filesystem operations. |
| Fixed Nautilus launch → scoped directory | `app.open_directory` with `app: "files"`, `directory` and lease. Requires app launch and workspace read. Evidence identifies the validated launch argument and supervised Sway window. |
| Structured CLI → GTK4 teacher and search | `teach-gui` uses the same teaching authority as the CLI. `teach.search(app, query, revision, offset)` searches current notes by case-insensitive meaning and revision. Use revision `0` for any current revision. |
| Exact matching → bounded context tolerance | `teach.resolve` reports `matchQuality` of `exact` or `strong_contextual`. At most two unnamed layout wrapper edits are allowed when the named anchor and native action still match. Equally plausible candidates remain ambiguous. A different app/build returns `incompatible`. |

Workspace mutations run through the same pending-operation journal. Descriptor-relative access rejects traversal, symlinks, hard-linked files, mount crossings and unsafe directory ownership or write modes. Rename preserves an existing destination. Keep the root private to the service and trusted host operator. Native creation and rename are separate from Nautilus interactions.

An independent JSON-RPC client can use this sequence. `rpc` represents its authenticated socket connection.

```python
session = {"session": "desktop"}
capabilities = rpc.call("session.features", **session)
catalog = rpc.call("app.list", **session)
notes = rpc.call("teach.search", **session, app="editor", query="document.save", revision=0, offset=0)
window = rpc.call("window.list", **session, app="editor")["windows"][0]
target = rpc.call("teach.resolve", **session, ref=window["ref"], annotation=notes["annotations"][0]["id"])
```

Check the result status before consuming its ref. Obtain a new window ref and resolve again after a mutation or stale-reference refusal. An execution request passes the lease independently, and `operation.status` can inspect a recent result.

### Firefox boundary

The fixture is bundled, read-only and local. A fresh Firefox ESR profile runs in Bubblewrap namespaces with a private home, no personal profile mounts and no host network. It exposes only the Wayland and accessibility endpoints needed by the trusted browser process. A private session bus only supplies the AT-SPI locator. The service checks Firefox's executable, process start identity, subprocess ancestry and non-host namespaces. Untrusted Bridge clients see neither the application bus nor the browser profile.

Firefox AT-SPI advertised editable text and acknowledged the initial write, but independent readback found an empty field. That attempt returned `unknown`, leaving the session blocked. [AT-SPI-only attempt](labs/evidence/LOOPBRIDGE_V0_4_FIREFOX_ATSPI_PARTIAL.json). The explicit Firefox profile uses AT-SPI for discovery/revalidation and independent verification, and an allowlisted native Marionette adapter for form effects. Its TCP listener lives on the sandbox loopback. The host connects through a private Unix socket that accepts only the three fixed fixture operations. The client supplies no script, selector, URL, arbitrary keys, or browser-chrome operation. The profile accepts only fixture text in an empty field, a category change, and form submission. No fallback is attempted automatically after uncertainty.

### Visual capture and conventional input

`desktop.capture` requires its own app-scoped grant and a live window ref. `input.key` needs `desktop.input`, app observation and a current lease and window ref. This release refuses both on the tested Sway backend. The Wayland registry exposed output screencopy/export and virtual input, but no qualified window-capture source or target-bound conventional input. No crop of an output or global input fallback is used. See the [observed registry](labs/evidence/LOOPBRIDGE_V0_4_SWAY_PROTOCOLS_01.json). Super+click, takeover, preemption, and cancellation remain outside the qualification.

## GTK teaching and evidence

Grant `session.discover` and, for the chosen app, `desktop.observe` and `teach.write`. Launch the app using a separately authorized controller.

```sh
/usr/bin/python3 -B -m loopbridge teach-gui \
  --socket "$lab/runtime/socket/control.sock" \
  --token-file "$lab/credentials/observer.token"
```

Choose a running application and window, filter or page through the elements, inspect a row, enter the annotation and save. Standard GTK focus and selection controls support keyboard use. The GTK process renders its own window and goes through the Bridge socket for target data and annotation writes. Use the Bubblewrap client profile for untrusted automation.

```sh
cc tools/wayland_scope_probe.c -lwayland-client -o /tmp/loopbridge-wayland-scope
/tmp/loopbridge-wayland-scope
/usr/bin/python3 -B -m tools.loopbridge_practical_demo --evidence /tmp/loopbridge-v04.json
/usr/bin/python3 -B -m unittest discover -s tests
```

Remote navigation, personal browser sessions, arbitrary webpage interaction, and wider app policies are outside the fixture profile. An optional Cua Driver adapter could add other app-native effects only behind the same scoped grant and verified target/dispatch boundary. It was not added or qualified.

## Qualified run

**GO for the integrated fixture workflow.** The isolated controller created a nested workspace file, renamed it with native Linux operations, and opened the directory in supervised Nautilus. Another isolated client later read the actual Firefox receipt after the controller filled the field, changed the radio selection and submitted the form. All data was fictitious. Firefox's process tree was checked under private namespaces. The GTK teacher used scripted widget events on its real visible window. After reopening the editor, an isolated controller found the saved meaning through `teach.search`, received a new matching ref and completed an editor save verified by a separate filesystem read. The [integrated evidence](labs/evidence/LOOPBRIDGE_V0_4_PRACTICAL_RUN_01.json) records the outcomes and client probes.

**PARTIAL for graphical file selection and visual/conventional control.** Nautilus opened the authorized directory. Its later AT-SPI search reported multiple native Selection candidates, so the run did not use one to mutate files. The native workspace actions provided the verified file effects. Capture and conventional input were refused. A captured window, compositor hotkey, native file-manager actions beyond directory launch, and general-site browser operations remain unqualified.

The integrated run also checked a stale element ref, read denial for a password control, expiry of a real scoped grant, and capture/input authority. Automated tests cover duplicate contextual candidates, build changes, protected metadata, journal recovery and refusal to retry uncertain actions.

The final suite reported **139 tests passed**. The prior V0.1, V0.2 and V0.3 graphical demos completed with their respective wire versions using the following commands. The qualification uses real applications; fixture-based fault tests are part of the automated suite.

```sh
/usr/bin/python3 -B -m tools.loopbridge_demo --evidence /tmp/lb4-release-v01.json
/usr/bin/python3 -B -m tools.loopbridge_desktop_demo --evidence /tmp/lb4-release-v02.json
/usr/bin/python3 -B -m tools.loopteach_demo --extra-catalog --evidence /tmp/lb4-release-v03.json
```

The final integrated command was `/usr/bin/python3 -B -m tools.loopbridge_practical_demo --evidence /tmp/lb4-release-v04.json`. It reported `GO completed`.
