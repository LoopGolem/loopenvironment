# System architecture

**Status:** conceptual architecture; no runtime is implemented.

## Boundaries

LoopEnvironment is a standalone Linux-based operating system. Its own components include an agent-facing service (LoopBridge), desktop integration/adapters, security policy, and distribution configuration. External agents are clients, not dependencies. The same OS is intended to run on physical hardware or as a guest in a virtual machine.

The implementation should reuse a maintained Linux kernel, userland, display server/compositor, accessibility mechanisms, and existing applications rather than rebuilding them.

## Logical layers

    +--------------------------------------------------------+
    | External client: agent, automation, human viewer       |
    +----------------------+---------------------------------+
                           | authenticated transport
    +----------------------v---------------------------------+
    | LoopBridge                                             |
    | protocol | identities | authorization | sessions      |
    | capability discovery | commands | events | audit       |
    +-----------+----------------+---------------------------+
                |                |
    +-----------v---------+  +---v--------------------------+
    | Semantic adapters   |  | Visual / input adapters      |
    | AT-SPI / D-Bus /     |  | compositor / portals /       |
    | app-specific APIs    |  | screen capture / input       |
    +-----------+---------+  +---+--------------------------+
                |                |
    +-----------v----------------v--------------------------+
    | Real Linux user session, windows, apps and processes   |
    +----------------------+---------------------------------+
                           |
    +----------------------v---------------------------------+
    | Linux kernel, devices and system services              |
    +--------------------------------------------------------+

This is an **intent**, not a selected dependency stack. Wayland, AT-SPI, D-Bus, desktop portals and a lightweight compositor are strong candidates; their capabilities and restrictions need experiment-driven confirmation.

## Core components

### Linux base and graphical session

- Bootable OS with predictable user/session lifecycle.
- Real graphical session, compatible with conventional Linux applications.
- Support for virtual displays and observing the session when requested.
- Preserve trusted local operation/recovery even if the Bridge client endpoint fails, without granting unmediated access to external agents. Exact input-policy failure and recovery behavior requires qualification.
- Treat application rendering, capture, encoding, and video delivery as distinct costs.

### LoopBridge

- Runs in the appropriate user/session security context where possible.
- Discovers and normalizes accessible UI data but does **not** pretend missing semantic metadata exists.
- Brokers authorized input and visual observation through narrowly scoped adapters.
- Owns the public API, event stream, identity, permission and audit interfaces.
- Must never expose arbitrary privileged OS internals directly to clients.

### Adapter boundary

Adapters encapsulate compositor, accessibility bus, portals, and app-specific integrations. They announce supported capabilities and errors. No single adapter is assumed universal. A screenshot/input fallback can work when semantic controls are unavailable, subject to policy.

### Distribution and lifecycle

The final OS must have documented provenance, boot/update/rollback behavior, software supply-chain tracking, and support for physical as well as virtual deployment. A custom image is postponed until semantic interaction works on an existing distribution.

## Deployment neutrality

**Physical machine:** a local agent may connect to an authenticated per-user Unix-domain socket. Remote control may be enabled explicitly using authenticated, encrypted transport.

**Virtual guest:** the exact same LoopBridge protocol can be reached through a private virtual network or a guest/host transport with a host-side adapter. The guest does not need to know which VM manager starts it. Localhost forwarding is only a reachability mechanism; it does not provide identity or authorization.

The agent contract is independent of transport, though latency, disconnection and supported media codecs can vary.

## Session and control model

- Sessions and seats must have stable identifiers within a connection/restart scope; clients must not assume global permanence.
- Only the owning authorized session is exposed.
- Reading accessible state, viewing pixels, sending input, launching processes, and accessing files are separate capabilities.
- Human intervention must be explicit, observable, and able to preempt agent input. Remote human controllers pass through LoopBridge and physical keyboard/mouse input follows trusted session arbitration policy.
- Changes in focus, window lifetime, or permissions must invalidate stale targets or return a safe conflict/error.

## Expected data flow

1. Client authenticates and discovers server/API version and granted capabilities.
2. Client chooses an authorized graphical session.
3. Client gets a state snapshot with element and window identifiers.
4. Client performs an allowed action with target freshness checks.
5. Bridge executes using available adapters and returns a structured outcome.
6. Client subscribes to events, resynchronizing after gaps/reconnects.
7. Human viewer may observe or request control under policy.

## Constraints and risks

- Accessibility metadata may be missing, stale, or inconsistent.
- Wayland security boundaries restrict global input and capture; use documented compositor/portal mechanisms, not unsafe bypasses.
- Browser DOM and app-specific models are separate from the OS accessibility tree; expose richer adapters only with explicit permissions.
- Network/storage/hardware isolation depends on deployment and is not automatically guaranteed by LoopBridge.
- Host↔guest shared folders, clipboard, networking and credential injection require threat modeling.
- Graphics performance and virtual GPU compatibility must be measured, not assumed.

## Architecture quality gates

No implementation is accepted merely because it can click a coordinate. The proof must demonstrate authorization, semantic inspection of a real application, event consistency, denial of an unauthorized operation, and human observation/interruptibility.

See [LoopBridge](LOOPBRIDGE.md), [Interaction](INTERACTION_MODEL.md), [Security](SECURITY_MODEL.md) and [Roadmap](ROADMAP.md).
