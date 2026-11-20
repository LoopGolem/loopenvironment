# LoopBridge V0.7 — Live Session Presentation

**Status** — Experimental local presentation for managed private Sway desktops. The VM runs a real GTK4 window with continuous read-only delivery. See the [qualification matrix](#qualification) for the tested boundaries.

## V0.6 starting point

| Area | V0.6 implementation |
| --- | --- |
| Startup | The owner calls `private.start` on the local manager. It creates a Bubblewrap instance with a private session bus and starts headless Sway with Pixman and an 800×600 output. It waits for Sway's Wayland and IPC sockets and then starts the Bridge service and its adapter. |
| Display sockets | Sway, the trusted service and supervised applications can reach the private display. Firefox has a further sandbox with selected mounts. V0.6 backed the private runtime with a directory visible on the host; isolated agent clients received only the Bridge socket. |
| Authorization | The Unix-socket broker authenticates the principal and checks the session-wide `desktop.capture` grant for both capture and chunk reads. It binds references to connection, session epoch, generation and revision. |
| Frame path | The existing Wayland helper captures one frame. The adapter encodes PNG in memory. `session.capture` returns reference and metadata; `session.capture.read` returns bounded base64 chunks. The GTK4 watcher authenticates, pins the origin, checks the digest and polls for a new PNG. |
| Identity | The manager assigns a random private instance ID. Each service creates its own epoch, even though logical session names such as `desktop` repeat. Control has its own lease generation. |
| Lifecycle and reuse | The manager watches Sway and Bridge, stops children and removes transient files while keeping workspace and effect-journal state. V0.7 reuses this lifecycle, the authorized socket, per-instance authority and the existing display. |

See [V0.6](LOOPBRIDGE_V0_6.md), [its watcher](../tools/loopbridge_watch.py) and [ADR 0011](DECISIONS/0011-session-presentation-and-operator-shell.md).

## Preflight and technology

The Debian 13 lab already had Sway 1.10.1, wlroots 0.18.2, Bubblewrap 0.12.0, GCC 14, Wayland client headers 1.23.1, GTK 4.18.6 through PyGObject, and Firefox ESR. Sway and the local viewer ran in the same two-vCPU, approximately 3.8 GiB VirtualBox VM. Main Wayland output was about 60 Hz. The private compositor used the headless backend and Pixman.

**WayVNC — PARTIAL preflight.** Debian trixie offered WayVNC `0.9.1-1` and TigerVNC Viewer `1.15.0+dfsg-2.1~deb13u1`. The versioned WayVNC man page lists `-d` (disable input), `-u` (Unix socket), `-x` (inherited listener) and `-S` (control socket path). Headless capture with shared memory is plausible. A deployment would need to confine both the RFB listener and auxiliary control socket, then bind each viewer and disconnect to LoopBridge authority. Its actual runtime and resource usage are unmeasured here. APT simulation against Debian main resolved seven new packages, 1,349 kB of archives and 4,417 kB on disk, with zero upgrades or removals. The lab used its existing packages. [WayVNC upstream](https://github.com/any1/wayvnc), [Debian trixie WayVNC man page](https://manpages.debian.org/trixie/wayvnc/wayvnc.1.en.html).

**Native wlroots capture and Unix IPC — GO.** The existing Sway exposes version 2 of `wlr-screencopy-unstable-v1`. A trusted Wayland client keeps one SHM buffer and an outstanding screencopy request. It sends an initial image and then waits for compositor damage with `copy_with_damage`. A Wayland sync acknowledgment provides a heartbeat on a stationary output. The local GTK4 window consumes BGRX frames. This choice avoids another media service, input protocols, credentials and dependencies for the first local experiment. PipeWire would add a separate broker/node access boundary. Nested presentation remains a future hypothesis. [wlroots screencopy protocol](https://github.com/swaywm/wlr-protocols/blob/master/unstable/wlr-screencopy-unstable-v1.xml).

The new capture source is project-owned Apache-2.0 code. Sway, wlroots and libwayland use MIT licenses. Bubblewrap, GTK and PyGObject use LGPL-2.1-or-later, and Firefox source is principally MPL-2.0. The experiment uses Debian's installed packages, including `sway`, `bubblewrap`, `dbus-daemon`, `gcc`, `libwayland-dev`, `libxkbcommon-dev`, `python3-gi`, `gir1.2-gtk-4.0`, `firefox-esr` and `gnome-calculator`. See [licensing](LICENSING.md).

## Implementation and authority

1. The private compositor and D-Bus listen inside a namespace-local tmpfs. The shared instance control directory exposes its authenticated Bridge socket. The existing application and optional HTTPS egress paths retain their own lifecycle. External agent sandboxes receive only the bound Bridge socket. Executing real applications inside Sway follows the existing adapter policy.
2. An authenticated principal with a session-wide `desktop.stream` grant describes and opens one pinned instance over the local Unix socket. The successful open response upgrades that connection to one-way binary media. The helper runs in the trusted private instance with the exact private display environment and a pipe to the service. The viewer gets pixels and metadata through the connected Unix socket.
3. The service checks the bound grant under the authority lock before each nonblocking splice. Revocation shuts down the socket under the same lock before acknowledging it. Expiry, disconnect, helper failure, session exit and stalled delivery also close the stream. Bytes already queued to the authorized receiver and frames already displayed remain with that receiver.
4. GTK receives data in a worker thread and paints the latest distinct image on its graphical thread. The viewer displays the instance, state, resolution and measured update rate. During the lab fixture it shows compositor-feedback latency where available. Closing the window leaves the private desktop and control lease active.

The helper binds output, SHM and screencopy globals. It has no keyboard, pointer, seat, D-Bus or Sway IPC bindings. The media channel rejects inbound bytes. GTK uses its ordinary connection to the main desktop to draw its own surface. The stream delivers no compositor or input descriptor to the observer. No TCP or media-control listener is created. Frames stay in volatile buffers and are discarded on teardown. The lab records numeric counters and timings, without pixels, session identifiers or credentials.

### Experimental RPC contract

Control uses the existing versioned newline RPC envelope. The experimental methods are available on managed private desktops. Existing PNG and MCP calls retain their wire format. MCP carries neither the media stream nor a live-view tool.

| Method | Parameters | Behavior |
| --- | --- | --- |
| `presentation.describe` | `session` | Requires `desktop.stream`. Returns principal, authorization, origin `privateId` and `epoch`, availability, transport, format, geometry, input flag and reason. |
| `presentation.open` | `session`, `privateId`, `epoch` | Rechecks the grant and exact origin. Returns an opaque stream ID, the above metadata and state `opening`. After this reply the connection carries binary media. |
| `presentation.status` | `session`, `privateId`, `epoch`, `stream` | On a separate authenticated connection, the stream's principal can read bounded status metadata, including terminal reason after revocation. It conveys no media authority. |

`desktop.stream` is a whole-output grant delegated with target `*` on the intended instance. Its grant, capture grant, structured observation, input, administration and actuation lease are independent. Stream state moves from `opening` to `live` to `closed`. The binary header is 17 bytes in network order with a one-byte kind, eight-byte capture sequence and eight-byte monotonic timestamp from the capture callback. A kind 1 header precedes a tightly packed 800×600 BGRX frame. A kind 2 heartbeat carries the previous sequence and has no pixel payload. Two concurrent streams and 32 records are allowed per instance. At capacity the service evicts the oldest closed record. Disconnect by closing the socket. Reconnection repeats authentication and grant validation with the exact origin and epoch. A replaced or stopped instance requires explicit selection of a valid target.

An isolated same-UID client has a different filesystem, PID and network view. A process running unrestricted as the desktop account is inside the lab's host trust boundary. The test reached the private Wayland, Sway IPC and D-Bus sockets through host procfs and verified that this account could read its lab credential file. Mode 0600 alone provides no principal separation for such a process. The experiment leaves protection against hostile unrestricted same-UID software unqualified.

## Run the demonstration

From a terminal in the Debian VM's main Wayland desktop:

```sh
/usr/bin/python3 -B -m tools.loopbridge_presentation_demo \
  --evidence /tmp/loopbridge-v07-run.json --seconds 8 --wait-for-operator
```

Use a new evidence filename for each run. The demo creates disposable credentials and a private session, grants live viewing only, then opens the GTK4 viewer. Once the window has painted, type `yes` in the terminal to launch Calculator and Firefox in sequence. The offline motion fixture draws a continuously moving circle, rotating indicator and counter. Type `yes` again after observing it. The harness closes the viewer, verifies that Firefox remains usable, runs the V0.6 PNG baseline and executes the failure and isolation tests. `--view-only` skips the baseline and failure matrix. Without `--wait-for-operator` the automated check advances after the window paints. `--hold 30` keeps the animation visible for an additional 30 seconds. Closing the live viewer stops observation. The demo manager stops its disposable instance when the run exits.

To attach the viewer to an existing managed instance, the owner delegates `desktop.stream` on that instance. Use the `privateId` and `epoch` returned by the authorized `presentation.describe` call:

```sh
/usr/bin/python3 -B -m tools.loopbridge_live_view \
  --socket "$BRIDGE_SOCKET" --token-file "$OBSERVER_TOKEN_FILE" \
  --session desktop --private-id "$PRIVATE_ID" --epoch "$EPOCH"
```

On loss the viewer removes the stale image and displays the reason. A stalled transport is labeled frozen until termination. A responsive static output is labeled live with no changes. A slow observer is disconnected after sustained backpressure. The user can reopen a failed stream against the same instance with an active grant. An ended session requires a new explicit pin.

## Benchmark methodology

The offline Firefox fixture encodes a draw sequence and wall-clock millisecond timestamp in a small pixel strip on each animation callback. The GTK viewer decodes the marker at the private output's calibrated 1:1 scale. Each new presented marker represents a source update. Missing sequence numbers measure source updates not painted by the viewer. Binary sequence numbers count capture delivery, full-frame comparisons count unchanged duplicates and the bounded GTK mailbox counts overwrites. GDK frame timings distinguish frames painted by GTK from frames with main-compositor presentation feedback. The timestamp originates before Firefox draws and ends at that feedback, so the interval includes browser rendering, private Sway capture, Unix transfer and GTK presentation. It excludes display scan-out and panel response. The viewer correlates monotonic feedback with the local wall clock, then reports median and nearest-rank p95 from valid samples. No estimate is substituted when feedback is unavailable.

Process CPU is normalized to one logical CPU. RSS includes shared pages mapped by each process. The demo samples compositor, capture helper, Bridge and viewer while Firefox animates, then samples the same private session after closing the live viewer. PNG baseline uses the original GTK4 watcher for a second observation of the same Firefox page. The experiment targets at least 28 unique source updates painted per second and p95 app-to-presentation latency no greater than 100 ms on this fixture. Raw media at 800×600 uses 1.92 MB per frame; output scale, additional observers and different workloads require separate measurements.

| Measured at 800×600 | Result |
| --- | --- |
| Source motion | 499 source updates across the painted interval, 479 source updates received across the sampling run, 468 painted. There were 31 source sequence gaps in the painted interval. |
| V0.7 versus V0.6 | 56.26 unique motion updates per second (8.30 s), compared with 1.00 unique PNG capture per second (7.99 s). |
| Firefox draw to main compositor feedback | 32.98 ms median and 43.86 ms p95, 468 valid samples. |
| Capture callback to complete frame at receiver | 2.17 ms median and 7.55 ms p95. The viewer received 500 complete frames across all phases, including 4 pixel duplicates, and overwrote 11 pending pictures. |
| Attach and detach | 40.32 ms for negotiation and 86.36 ms to first GTK paint, measured from viewer window construction. The capture helper exited within 48.26 ms of requesting the viewer to close. |
| Revocation | 0.20 ms from sending the revoke RPC to observing EOF on the authorized reader in this run. |

| Process | With viewer CPU / RSS | Without viewer CPU / RSS |
| --- | ---: | ---: |
| Private Sway | 3.62% / 28.88 MiB | 1.87% / 27.04 MiB |
| Capture helper | 3.25% / 3.38 MiB | Absent |
| Bridge | 3.50% / 24.07 MiB | 0.12% / 24.18 MiB |
| GTK4 viewer | 31.12% / 198.09 MiB | Absent |

The viewer incurred the largest measured CPU and RSS cost. The private Firefox page remained functional after viewer exit. The source-to-feedback timing combines rendering and presentation costs; the capture-to-receive timing covers the IPC segment of that interval.

## Qualification

| Gate | Result | Evidence |
| --- | --- | --- |
| Native preflight and streaming | GO | A GTK4 window on the main Wayland desktop painted real Sway output while Calculator and offline Firefox ran in the private desktop. |
| Performance | GO for this fixture | The valid sample count, unique FPS and feedback latency met the lab thresholds. |
| Authorization and lifecycle for isolated clients | GO | Unauthenticated, under-scoped and cross-session peers were denied. Stale pins, unauthorized reconnect and inbound bytes were rejected. Revocation and expiry stopped media, and viewer or helper failure left Sway alive. Stopping the session closed the stream. |
| Unrestricted same-UID host isolation | PARTIAL | The raw host process could reach the private sockets through procfs and could read the synthetic lab credential. Broader account isolation remains open. |
| Human observation | PARTIAL | The run verified window mapping and presentation feedback. Human observation remains unconfirmed. |
| Overall | PARTIAL | Local presentation and measured performance are working within the tested boundaries. |

See the [sanitized lab evidence](labs/evidence/LOOPBRIDGE_V0_7_PRESENTATION_01.json) for the commands and regression results. Historical M1.3B takeover and preemption gates remain open. Alternative B and the LoopEnvironment Shell are future work under ADR 0011.
