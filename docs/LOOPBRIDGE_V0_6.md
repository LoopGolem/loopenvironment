# LoopBridge V0.6 — Private Agent Workspace

LoopBridge runs unchanged semantic adapters inside independent, managed Sway headless sessions. The trusted local manager creates a private runtime, D-Bus and AT-SPI endpoints, journal and empty workspace for each instance. The manager socket is owner-only. Agent sockets remain separately authenticated with the existing grants and lease rules.

## Run locally

On the Debian lab host, use the installed Sway, Bubblewrap, D-Bus, Python GI/AT-SPI, GNOME apps and Firefox ESR. Capture and pointer also use the existing C compiler and libwayland-client. The demo requires a trusted graphical host context to probe the live host sockets.

```sh
lab=$(mktemp -d /tmp/lb6.XXXXXXXX)
python3 -m loopbridge provision "$lab/credentials"
python3 -m loopbridge private --root "$lab/private" --credentials "$lab/credentials/service.json"
```

From another terminal, set `lab` to the same directory and connect as owner:

```sh
python3 -m loopbridge client --socket "$lab/private/manager.sock" --token-file "$lab/credentials/owner.token"
```

Send one JSON object per line. Use the returned instance `id` for `private.status` and `private.stop`, and the returned `socket` for agent connections. Each request can use a new authenticated connection. The manager serializes lifecycle requests and retains up to four instance records per run.

```json
{"method":"private.start"}
{"method":"private.list"}
{"method":"private.status","params":{"id":"INSTANCE_ID"}}
{"method":"private.stop","params":{"id":"INSTANCE_ID"}}
```

On the instance socket, discover the session `desktop` and inspect `session.features` for its private identity. The owner grants the principal only the application, workspace, teaching and observation scopes needed using the [existing local grant protocol](LOOPBRIDGE_V0_2.md). Instance identities, epochs, leases, handles, annotations and writable roots are distinct. Credentials are provisioned from a mode-0600 file and passed through anonymous startup pipes. Apps use separate temporary homes. Each instance uses synthetic local account records and a fresh D-Bus machine ID. The browser remains offline by default. An owner can opt one private instance into a tunneled HTTPS hostname allowlist at startup.

## Independent clients and visual observation

Use this stdio command in an MCP host after provisioning a principal and its grants. The launcher pins one Bridge socket and one token in a rootless client sandbox.

```sh
python3 -m tools.loopbridge_mcp_sandbox --socket "$bridge_socket" --token-file "$lab/credentials/delegate.token"
```

Stdio understands [2026-07-28 per-request metadata and discovery](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning), plus `2025-11-25` and `2025-06-18` initialization. `tools/list` checks live grants and feature availability. It is advisory. Every action still passes through the Bridge. References and leases remain connection-bound application state. Protocol extensions, subscription streams and concurrent cancellation were outside this qualification.

Grant the `observer` principal `desktop.capture` with scope `*` to see the whole private output. From a terminal on the Debian graphical desktop, run:

```sh
python3 -B -m tools.loopbridge_watch --socket "$bridge_socket" \
  --token-file "$lab/credentials/observer.token" --expected-private-id "$instance_id"
```

The GTK4 window shows the pinned instance ID and the age of the last frame. **AO VIVO** means the Bridge is returning current frames. **CONGELADO** means the last frame is stale. **DESCONECTADO** clears the picture and keeps trying the same instance. Close the window with its normal close button. The private desktop and its operator use separate connections. The viewer receives PNGs through the Bridge, draws them in memory and has no input tools.

`session.capture` returns native 800×600 PNG metadata, revision and a 20-second reference. `session.capture.read` returns 4 KiB chunks. The Bridge holds up to four frames of at most 512 KiB each and invalidates references on state changes. The viewer checks the frame digest and pins the compositor identity and epoch. To request a single frame instead:

```sh
python3 -m tools.loopbridge_view --socket "$bridge_socket" --token-file "$lab/credentials/observer.token" > "$lab/capture.png"
```

The redirect explicitly persists a frame. `session.pointer.move` and `session.pointer.click` require the current capture, a lease and both wildcard `desktop.capture` and `desktop.input` grants. Input is restricted to the private session. A GTK editor accepted typed text and Backspace with independent AT-SPI readback. The visual Calculator click passed once, with intermittent target selection on repetition. Window cropping and takeover remain outside this qualification.

Run `python3 -B -m tools.loopbridge_live_demo --evidence /tmp/loopbridge-live.json` for a local editor exercise with transitions at 10, 30, 60 and 120 seconds. The HTTPS demo accepts `--with-viewer --hold 120` to open the viewer before Firefox and keep the final form visible. Both demos record frame counts, revisions and timing without saving images. Human attendance is a separate confirmation.

LoopTeach uses the same instance socket. The existing [GTK and CLI workflow](LOOPTEACH.md) can select and teach private editor elements using authorized API calls. The test confirms resolution of a persisted annotation on the reopened editor. Manual follow-up for GTK4 is to select the editor and window, search via Ctrl+F, navigate results and fields with Tab, save with Ctrl+S, then reopen the editor and resolve. Pay attention to the lack of a previous-page button and the space available for evidence and results on small windows. Automated widget coverage does not establish operator usability.

## Model host preparation

The experimental Codex runner uses the existing CLI login in a rootless namespace and routes provider traffic through a constrained proxy. Codex discovered `sessions_list` but requested approval before invoking it. The disposable profile uses `approval_policy = "never"`, so the call stopped at the host. A per-tool approval in that profile cleared the block for this read-only call. `tools.loopbridge_codex_demo --read-only` verified both MCP handshakes with an independent client and a real model call in the Bridge audit. The runner retains no raw model events.

```toml
approval_policy = "never"
sandbox_mode = "read-only"
web_search = "disabled"

[features]
shell_tool = false
view_image = false
multi_agent = false
multi_agent_v2 = false

[mcp_servers.loopbridge]
command = "/usr/bin/python3"
args = ["-B", "-m", "tools.loopbridge_mcp_sandbox", "--socket", "/run/lab/control.sock", "--token-file", "/run/lab/delegate.token"]
required = true
enabled_tools = ["sessions_list", "session_features", "apps_list", "windows_list", "lease_acquire",
  "lease_release", "web_open", "web_navigate", "web_discover", "web_set_text", "web_select",
  "web_activate", "workspace_list", "workspace_read", "workspace_write", "teach_search",
  "teach_resolve", "app_open_document", "element_tree", "element_set_text", "element_invoke",
  "operation_status"]

[mcp_servers.loopbridge.tools.sessions_list]
approval_mode = "approve"
```

Use a disposable host profile and `codex exec --ephemeral`. Provide only a natural-language objective. For example, alternate Harbor/North and Orchard/North, vary the required output name and fields, and independently check the live report content and path. The model should discover the browser controls, search and read records, optionally resolve a save annotation, and verify its artifact. Keep credentials out of the objective and evidence. See the official [Codex configuration](https://developers.openai.com/codex/config-reference) and [MCP configuration](https://developers.openai.com/codex/mcp).

For hosts with a local tool-calling model already provisioned, the repository also includes a minimal [Ollama chat](https://docs.ollama.com/api/chat) host. It sends discovered tools to the model and executes only model-selected calls drawn from its allowlist. It has no model-facing shell or filesystem API other than the Bridge workspace tools, and stops on unknown or unavailable outcomes. The host only connects to a model endpoint on `127.0.0.1`.

```sh
python3 -m tools.loopbridge_local_agent --model "$local_model" --prompt-file "$lab/mission.txt" -- \
  /usr/bin/python3 -B -m tools.loopbridge_mcp_sandbox --socket "$bridge_socket" --token-file "$lab/credentials/delegate.token"
```

Independently verify the workspace file after the host exits. A model's final message is a summary, not proof of the artifact. The Ollama host was exercised with a fixture for the no-replay boundary. A provisioned local model was unavailable.

## Qualification

```sh
python3 -B -m unittest discover -s tests
/usr/bin/python3 -B -m tools.loopbridge_private_demo --evidence /tmp/loopbridge-v06.json
/usr/bin/python3 -B -m tools.loopbridge_private_demo --faults-only --evidence /tmp/loopbridge-v06-faults.json
```

| Scope | Gate | Evidence and limit |
| --- | --- | --- |
| Unit and fixture regression | GO | 161 local unittest cases passed. |
| Two managed sessions and real app mission | GO | Independent MCP client queried real Firefox ESR, used LoopTeach on GNOME Text Editor, and read back the saved report. Host, sibling and private endpoints were denied to the isolated client. |
| Visual observation and pointer/keyboard | PARTIAL | Private output capture and Wayland input are qualified within the private desktop. GTK text/key effects were independently read back. Calculator target selection was intermittent on repetition. |
| Failure and manual replacement | GO | Abrupt client, Sway and adapter exits exercised. The old unknown intent survived and the new instance rejected the old lease. |
| Automatic recovery | PARTIAL | Disabled. The operator can request a fresh independent instance. |
| Actual AI operator | GO for read-only discovery | Codex invoked `sessions_list` through MCP and the Bridge audited the call. The broader report mission remains unqualified. |
| Private HTTPS and generic browser | GO for tested scope | Firefox loaded `example.com` and Vai Coberto over HTTPS. Dynamic DOM discovery, field edits and option selection were confirmed. Per-session proxy is exact-host allowlisted, CONNECT 443 only and rejects non-public DNS results. TLS remains opaque, so allowed host subpaths and subresources cannot be separately inspected. |
| Vai Coberto ordinary interaction | PARTIAL | One explicitly authorized submit was dispatched once. The page displayed “Verificando segurança...” and Firefox connected to `challenges.cloudflare.com`. No visible challenge control or commercial confirmation was observed. The outcome is unknown and was not retried. |
| Commercial quote | PARTIAL | No protocol, quote, plan, price or offer was verified. No purchase or payment occurred. |
| GTK viewer and live private Firefox | GO for visual delivery | A mapped window rendered 133 frames in a single pinned instance, from before Firefox launched through the completed form and a 120-second hold. Human attendance remains unconfirmed. |
| Asynchronous observation | GO for fixtures | A separate MCP observer sampled the editor through 10, 30, 60 and 120-second transitions. Each state was paired with a new frame from the open GTK window. |
| New independently authorized quote | PARTIAL | The live rehearsal reached a validated form. The prior attempt still requires its production read-only reconciliation before dispatch. |

The integrated V0.6 run took 21.108 seconds. This corrective run passed 157 unit tests and the V0.1–V0.5 agent, desktop, LoopTeach and practical demos. GTK failure reproduced at `close_teaching_editor` as `editor_document_ambiguous`. The close path required an editable text buffer marked `showing`, a transient visibility condition. It now requires a unique editable buffer and independently verifies the exact workspace file and content. The fixed GTK demo returned GO. The input repetition returned PARTIAL at Calculator target selection. Historical evidence remains unchanged. [Original evidence](labs/evidence/LOOPBRIDGE_V0_6_PRIVATE_WORKSPACE_01.json) and [corrective qualification](labs/evidence/LOOPBRIDGE_V0_6_QUALIFICATION_01.json).

The original production run dispatched one authorized click, observed a security-check notice and opened a Cloudflare connection. The six post-click polling iterations nominally slept for 12 seconds in a 25.471-second run, which ended at approximately 20:52:13 UTC on 19 November 2026. The evidence kept distinct sampled states without per-poll timestamps. It never captured a transition to submission. The capture API host was outside that instance's exact allowlist. The reconstruction therefore establishes **no HTTP submission demonstrated**. Backend persistence remains unverified.

After a single foreground dispatch, the demo polls on a separate scope for up to 330 seconds by default. It records monotonic offsets and distinct observation states. Verification, sending, receipt and processing are intermediate. Explicit machine-readable terminal states can end the generic observer. A deadline leaves the commercial outcome unknown. A fresh response document can confirm browser navigation. Commercial completion requires an independently verified result. The read-only observer never replays the operation or clears its journal.

A failed or stopped instance keeps its journal and possibly affected workspace. Starting another instance creates an empty independent workspace and never releases the old journal. A manager killed with SIGKILL can leave stale filesystem entries. The manager does not reattach old roots or attempt takeover. The evidence covers bounded namespace and endpoint checks on the tested host, not arbitrary hostile native applications or a general Linux security certification.

### Reconcile the original production attempt

The original code polled through the browser for about 12 seconds after the click. The documented security check can wait for 120 seconds before capture starts. The original allowlist covered the public site and the challenge host. The reconstructed egress evidence contains no connection attempt to the separate API host and no HTTP request, receipt or quotation state. The CONNECT proxy does not see the encrypted HTTP method or response.

An authorized production operator can check the capture database for the synthetic trip from Brazil to Portugal, 12–19 February 2027, one traveler aged 35. Use 19 November 2026, 20:51:30–20:52:30 UTC and compare any candidate privately with the approved test contact if needed. Check the request and outbox first, then the job and result statuses if the quotation tables exist. Report only whether there is a matching request and its state. Use a separate fresh browser profile and a new synthetic request for any independent exercise. Verify the public form creates its own idempotency key and include `api.vaicoberto.com.br` in that instance's egress policy alongside the site and challenge hosts.

[Live observation and reconciliation evidence](labs/evidence/LOOPBRIDGE_V0_6_HUMAN_OBSERVATION_01.json)
