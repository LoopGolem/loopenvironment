# Environment architecture

**Status:** conceptual Linux environment architecture with bounded prototypes; no stable or production-secure Bridge runtime has been released.

## Boundaries

LoopEnvironment is a set of installable services and integrations for **existing Linux**, centered on LoopBridge. Real sessions and supported resources should be operable through structured, permissioned interfaces. A **principal** may be controlled by a person, AI or script inside or outside the host; no LLM, special kernel or standalone distribution is mandatory.

An initial owner principal is bound during secure interactive or unattended provisioning and manages delegates and sessions. LoopBridge is the native API/authority. LoopTeach is a planned native semantic annotation application. See [operator model](OPERATOR_MODEL.md) and [LoopTeach](LOOPTEACH.md).

## Logical layers

+--------------------------------------------------------+
    | Controllers (people / AI / services)                    |
    | Authenticated principals: initial owner + delegates    |
    +-----------------------------+--------------------------+
                                  | versioned Bridge contract
    +-----------------------------v--------------------------+
    | LoopBridge: identity | session | grants | actions      |
    | structured state | annotations | events | audit        |
    +-----------------------+-----------------+--------------+
                            |                 |
    +-----------------------v---+ +-----------v--------------+
    | Semantic adapters        | | Trusted input/media       |
    | AT-SPI, apps, profiles    | | compositor / portals      |
    +-----------------------+---+ +-----------+--------------+
                            |                 |
    +-----------------------v-----------------v--------------+
    | Real Linux applications, graphical sessions            |
    +-----------------------------+--------------------------+
                                  |
    +-----------------------------v--------------------------+
    | Kernel, narrow privileged services, isolation          |
    +--------------------------------------------------------+

LoopTeach feeds application-scoped descriptions into the semantic observation layer as **data**, not authorization. Prefer structured/native actions when reliable; visual input is an authorized fallback. Existing solutions such as Cua Driver are research/reuse candidates, not selected dependencies. Compositor, Linux host base and transport remain experiment choices.

## Core components

### Linux base and graphical session

- Reuse an existing Linux distribution's boot, kernel, packages and session lifecycle; add only qualified environment services.
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

Installable environment components need documented provenance, upgrade/rollback guidance, software supply-chain tracking and physical/virtual host compatibility. An optional preconfigured VM image may simplify onboarding later, but is not a prerequisite or evidence of better capability.

## Deployment neutrality

**Physical machine:** a local agent may connect to an authenticated per-user Unix-domain socket. Remote control may be enabled explicitly using authenticated, encrypted transport.

**Virtual guest:** the exact same LoopBridge protocol can be reached through a private virtual network or a guest/host transport with a host-side adapter. The guest does not need to know which VM manager starts it. Localhost forwarding is only a reachability mechanism; it does not provide identity or authorization.

The agent contract is independent of transport, though latency, disconnection and supported media codecs can vary.

## Session and control model

- Principals are authenticated subjects, not synonyms for a Linux UID/process, human body or AI model.
- Owner bootstrap occurs once per installation through an interactive or unattended protected flow.
- Session and target identifiers are scoped; live references must be revalidated.
- Independent sessions are a preferred default, with shared sessions and separately authorized observers.
- Observation, media capture, semantic action, conventional input, teaching, process/file access and administration are distinct capabilities.
- Takeover is an **explicit authenticated owner/delegate operation**, not an automatic response to pointer motion or a claim to be human.
- Trusted input policy must prevent old queued/in-flight commands from affecting the new owner after a confirmed handoff; semantic and conventional paths must be coordinated.
- Untrusted clients cannot directly bypass protected compositor/session interfaces. Bridge cannot itself intercept every syscall.
- Learned application semantics cannot grant new input privileges.

See [operator model](OPERATOR_MODEL.md), [interaction model](INTERACTION_MODEL.md) and [ADR 0008](DECISIONS/0008-operator-neutral-authority.md).

## Expected data flow

1. Environment bootstrap securely establishes an initial master/responsible owner.
2. Owner creates/delegates principals, permissions and session policies.
3. A local or remote client authenticates to LoopBridge as a principal.
4. Client receives a permitted structured snapshot, including reliably matched LoopTeach annotations with distinct provenance.
5. A permitted semantic or conventional operation is validated against current target/lease; trusted OS components enforce protected paths.
6. Bridge reports an outcome with known/unknown status; events and snapshots repair stream gaps.
7. An owner/delegate can explicitly request a control transfer, refresh state and grant new leases under tested revocation barriers.

This is the intended product data flow, not the currently implemented end-to-end runtime.

## Constraints and risks

- Accessibility metadata may be missing, stale, or inconsistent.
- Wayland security boundaries restrict global input and capture; use documented compositor/portal mechanisms, not unsafe bypasses.
- Browser DOM and app-specific models are separate from the OS accessibility tree; expose richer adapters only with explicit permissions.
- Network/storage/hardware isolation depends on deployment and is not automatically guaranteed by LoopBridge.
- Host↔guest shared folders, clipboard, networking and credential injection require threat modeling.
- Graphics performance and virtual GPU compatibility must be measured, not assumed.

## Architecture quality gates

No implementation is accepted merely because it can click a coordinate. The proof must demonstrate authorization, semantic inspection of a real application, event consistency, denial of an unauthorized operation, and authorized observation/owner-delegate interruptibility.

See [LoopBridge](LOOPBRIDGE.md), [Interaction](INTERACTION_MODEL.md), [Security](SECURITY_MODEL.md) and [Roadmap](ROADMAP.md).
