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

On the instance socket, discover the session `desktop` and inspect `session.features` for its private identity. The owner grants the principal only the application, workspace, teaching and observation scopes needed using the [existing local grant protocol](LOOPBRIDGE_V0_2.md). Instance identities, epochs, leases, handles, annotations and writable roots are distinct. Credentials are provisioned from a mode-0600 file and passed through anonymous startup pipes. Apps use separate temporary homes. Each instance uses synthetic local account records and a fresh D-Bus machine ID. The browser remains on the offline packaged site, with its own nested namespaces.

## Independent clients and visual observation

Use this stdio command in an MCP host after provisioning a principal and its grants. The launcher pins one Bridge socket and one token in a rootless client sandbox.

```sh
python3 -m tools.loopbridge_mcp_sandbox --socket "$bridge_socket" --token-file "$lab/credentials/delegate.token"
```

Stdio understands [2026-07-28 per-request metadata and discovery](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning), plus `2025-11-25` and `2025-06-18` initialization. `tools/list` checks live grants and feature availability. It is advisory. Every action still passes through the Bridge. References and leases remain connection-bound application state. Protocol extensions, subscription streams and concurrent cancellation were outside this qualification.

Grant `desktop.capture` with scope `*` for whole-private-output observation. `session.capture` returns PNG metadata, dimensions, revision and a 20-second reference. `session.capture.read` retrieves numbered base64 chunks. Only up to four frames are held in memory, and references are invalidated by Bridge state changes. A trusted observer can view a fresh PNG on demand with any local viewer that reads from stdin:

```sh
python3 -m tools.loopbridge_view --socket "$bridge_socket" --token-file "$lab/credentials/observer.token" > "$lab/capture.png"
```

The redirect is optional explicit persistence by the observer. Capture uses one verified 800×600 private output downsampled to 240×180. `session.pointer.move` and `session.pointer.click` require the current capture, a lease and both wildcard `desktop.capture` and `desktop.input` grants. The pointer target must be inside the single focused, supervised window and its process identity and geometry are checked again before submission. `confirmed` here records a Wayland round trip with `applicationOutcome: unverified`. Keyboard remains unavailable. PNG capture shows the complete private output. Window cropping, capture/input on host Sway, and any takeover or cancellation guarantee remain unqualified.

LoopTeach uses the same instance socket. The existing [GTK and CLI workflow](LOOPTEACH.md) can select and teach private editor elements using authorized API calls. The test confirms resolution of a persisted annotation on the reopened editor. Manual follow-up for GTK4 is to select the editor and window, search via Ctrl+F, navigate results and fields with Tab, save with Ctrl+S, then reopen the editor and resolve. Pay attention to the lack of a previous-page button and the space available for evidence and results on small windows. Automated widget coverage does not establish operator usability.

## Model host preparation

The following is a per-run Codex CLI configuration template. Qualify its available tool inventory, filesystem and network boundary before giving a model credentials or a task. Run it from a trusted checkout packaged read-only into an OS-confined host with only the adapter socket, delegate token and independently authorized provider access. Shell-disable flags and read-only sandbox mode are additional controls. The lab did not qualify an OS-confined Codex model host or provision a provider credential.

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
| Unit and fixture regression | GO | 152 local unittest cases passed. The GitHub Actions workflow runs without an interactive graphical session. |
| Two managed sessions and real app mission | GO | Independent MCP client queried real Firefox ESR, used LoopTeach on GNOME Text Editor, and read back the saved report. Host, sibling and private endpoints were denied to the isolated client. |
| Visual observation and pointer | PARTIAL | Private PNG digest verified and Wayland delivery verified. Application outcome of the click and keyboard remain open. |
| Failure and manual replacement | GO | Abrupt client, Sway and adapter exits exercised. The old unknown intent survived and the new instance rejected the old lease. |
| Automatic recovery | PARTIAL | Disabled. The operator can request a fresh independent instance. |
| Actual AI operator | PARTIAL | The independent MCP mission is scripted. Codex CLI configuration prepared; no model run or provider credential used. |
| Vai Coberto production mission | NO-GO for this run | HTTPS egress from the Firefox profile and a qualified model host were unavailable. No form, Turnstile, or commercial send was exercised through LoopBridge. No authorization, quote, purchase or payment was involved. |

The integrated run took 21.108 seconds. The evidence records individual browser, editor and verification times, plus a separate failure run. Graphical V0.1–V0.4, V0.5 with RPC teaching, and the V0.5 headless probe passed. The V0.5 GTK replay reached scripted annotation creation and review, then failed a check in the teaching setup on both this branch and the original PR #15 merge commit. A human keyboard/usability run remains pending. Earlier exploratory runs encountered startup failures and one unknown Firefox operation. The unknown journal was preserved. [Execution evidence](labs/evidence/LOOPBRIDGE_V0_6_PRIVATE_WORKSPACE_01.json)

The public [Vai Coberto](https://vaicoberto.com.br) landing page was checked read-only outside the private Firefox proof. A future production run requires an explicit destination policy for the site and its legitimate dependencies, a qualified model host, approved test contact data, and explicit operator approval before a first real send. This run provides no evidence about Turnstile or quote availability.

A failed or stopped instance keeps its journal and possibly affected workspace. Starting another instance creates an empty independent workspace and never releases the old journal. A manager killed with SIGKILL can leave stale filesystem entries. The manager does not reattach old roots or attempt takeover. The evidence covers bounded namespace and endpoint checks on the tested host, not arbitrary hostile native applications or a general Linux security certification.
