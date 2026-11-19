# LoopBridge Core V0.1

LoopBridge Core is an experimental local service for one supervised GNOME Calculator on an existing Linux desktop. It implements a bounded subset of [Session Authority V1](design/SESSION_AUTHORITY_V1.md) under [ADR 0010](DECISIONS/0010-linux-environment-not-os.md).

## Architecture

- `loopbridge.protocol` defines the versioned wire envelope, strict request parsing, deadlines and event retention.
- `loopbridge.identity` and `loopbridge.authority` authenticate laboratory principals and arbitrate scoped grants and connection-bound leases. Linux peer credentials constrain transport access to the launching UID. The bearer credential identifies the principal.
- `loopbridge.broker` validates the current grant, lease, session epoch, generation, revision and single-use reference. It serializes desktop calls per session. The authorization check and submission share the session lock, so revocation and new submissions have a defined order.
- `loopbridge.adapter` supervises a separate process with a private channel and deadlines. The Calculator adapter correlates the owned process, native Sway window and AT-SPI tree. Before submission it checks lifecycle, unique element, action support and unchanged queried state. Confirmation requires a new display query with the expected change. The fixture exercises the same broker and process boundary.
- `loopbridge.service` owns the Unix socket and persists an uncertainty marker before submission. The service code has no runtime import from `experiments/`. The demo reuses the M1.2 Bubblewrap profile and independent OS probes.

Run the service from the trusted graphical session. Run untrusted clients under an isolation profile that exposes only the Bridge socket and client code. The demo mounts the socket subdirectory read-only and supplies each credential by a private stdin pipe. A plain same-UID client outside that sandbox has the ambient permissions of its host process.

## Reproduce the real gate

Use an existing Sway/Wayland session with GNOME Calculator, system Python 3.10+ with `pyatspi` and GI, and Bubblewrap with rootless namespaces. Use a disposable lab session and close any existing Calculator manually. Run from the repository root. The demo starts and stops its own Calculator and daemon.

```sh
/usr/bin/python3 -B -m tools.loopbridge_demo --evidence /tmp/loopbridge-v01-evidence.json
```

The evidence path must not already exist. The harness checks host endpoint reachability before running the same negative probes inside each sandbox. An independent trusted AT-SPI query verifies the real display and compares it with the observer snapshot. Read the [recorded run](LOOPBRIDGE_CORE_V0_1_RESULTS.md) for the qualified scope.

## Run the service and CLI

Use two terminals, with the same private lab path in both. Use a short path to stay within the Linux Unix-socket path limit. The first terminal provisions random lab credentials and starts the daemon.

```sh
lab=$(mktemp -d /tmp/lb.XXXXXX)
/usr/bin/python3 -m loopbridge provision "$lab/credentials"
/usr/bin/python3 -m loopbridge serve --runtime "$lab/runtime" \
  --credentials "$lab/credentials/service.json" --mode fixture
```

For a supervised Calculator in an appropriate graphical session, use `--mode calculator`. A `ready` line indicates the adapter and socket are available. Stop the daemon with SIGINT or SIGTERM. The fixture needs only Python and Linux.

In the second terminal, set `lab` to the same directory and run the trusted diagnostic CLI. The CLI authenticates once, reads JSON commands from stdin and prints one response per line until EOF. Omit `--token-file` to read the credential as the first stdin line, as a trusted launcher can do through a pipe.

```sh
/usr/bin/python3 -m loopbridge client --socket "$lab/runtime/socket/control.sock" \
  --token-file "$lab/credentials/owner.token" <<'JSON'
{"method":"discover"}
{"method":"capabilities","params":{"session":"calculator"}}
{"method":"snapshot","params":{"session":"calculator"}}
JSON

/usr/bin/python3 -B -m unittest discover -s tests
```

The service and principal files are mode `0600` in a mode `0700` directory. Credentials are laboratory material. Keep the credential directory outside the socket mount. The trusted operator manages its lifetime.

## Experimental wire contract

Use newline-delimited UTF-8 JSON, up to 8 KiB per frame. Send a strictly increasing nonnegative integer `id` per connection. Each request supplies the exact documented keys, including a parameter object. Extra keys, duplicate keys and invalid wire versions fail closed. A well-formed request returns either `result` or a structured `error` with a numeric code and a fixed message.

```json
{"jsonrpc":"2.0","version":"0.1","id":2,"method":"discover","params":{}}
```

| Method | Parameters and behavior |
| --- | --- |
| `auth` | `credential`. Returns the authenticated principal and connection ID. Reauthentication clears current connection authority first. |
| `discover` | Empty object. Returns permitted session IDs. |
| `capabilities` | `session`. Returns caller capabilities for the known Calculator scope. |
| `delegate` | `session`, `principal`, `capability`, `target`, `ttl`. Owner creates an expiring grant for a lab delegate or observer. Target is `calculator.digit7` or `*` within the named session. The observer role cannot receive control. |
| `revoke` | `session`, `grant`. Fences control and reports whether a pending operation may still take effect. |
| `acquire` | `session`, `ttl`. Returns lease `id`, `epoch` and `generation` among the lease fields. |
| `release` | `session`, `lease`, `epoch`, `generation`. Releases the caller's lease. |
| `snapshot` | `session`. Returns structured display state, authority phase, epoch, cursor and the current element reference. Obtain a fresh snapshot after lease acquisition and after every invocation. |
| `invoke7` | `session`, `lease`, `epoch`, `generation`, `reference` from `snapshot.element.reference`. Requires both observe and control grants and a current lease. |
| `events` | `session`, `epoch`, `cursor`. Requires an authorized snapshot on the same connection. Refresh the snapshot after an epoch change or retention gap. |
| `audit` | `session`. Owner reads up to 32 sanitized request outcomes from the single-session service. |

The four capability IDs are `session.discover`, `desktop.observe`, `desktop.control` and owner-only `identity.admin`. Grants and leases accept TTLs up to 180 seconds. The lab owner's startup grants expire after one hour. Snapshots issue references for up to ten seconds. The service retains eight ordered events per session and limits each connection to 64 requests, 30 seconds idle and a 180-second connection budget. Events cover authority changes, sampled state changes and operation outcomes. They do not subscribe to upstream AT-SPI events.

## Uncertain delivery and recovery

A confirmed result includes an operation ID, the query source and verified display state if observation remains authorized. An action whose result cannot be established returns `status: unknown` with no inferred state. If the peer has disconnected, it may receive no response. Once the broker submits to the adapter, timeout, disconnect before confirmation, or a failed confirmation can leave the session blocked. Revocation works for new submissions. An already submitted AT-SPI action can still arrive.

The `calculator.pending` marker in the private runtime directory survives a daemon restart and reopens the session blocked. Restart with the same runtime directory for the same lab session. No public API clears an uncertainty marker. Retain the marker and investigate the old worker, application and graphical session. A separate test with a fresh runtime and verified fresh graphical context is a new experiment. Do not retry the uncertain operation or rotate the runtime directory as a way to recover control of the same session.

## Open limits

One supervised application, one semantic action, one desktop configuration and one local transport are in scope. Authorization state other than the uncertainty marker is in memory. Persistent provisioning, credential rotation/recovery, generalized sandbox deployment, cross-application operations, compositor input fencing, takeover, capture, teaching and remote access remain open. The result check observes the expected display transition. AT-SPI does not supply a causally authenticated receipt for an action, so the proof assumes a dedicated lab Calculator without concurrent legitimate input.
