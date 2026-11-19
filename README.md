# LoopEnvironment

**An open-source agent-oriented Linux environment, centered on LoopBridge: structured, permissioned access for operators controlled by people, AI or other software.**

> **Status: design / pre-alpha.** LoopEnvironment is **not a standalone operating system**. It is an environment for existing Linux installations (Debian is the current lab base), centered on LoopBridge. M1.1–M1.3B contain bounded experiments, not a production-ready service, stable API or security certification. A preconfigured VM image is an optional future convenience, not a requirement.

## The idea

LoopEnvironment prioritizes **structured machine operation**: authorized clients observe sessions, applications, supported system resources, controls, states and events, and invoke permitted actions through LoopBridge. An agent should prefer native APIs and semantic operations rather than pixels and clicks. The real graphical desktop remains available for human observation/control and for compatibility fallbacks. Missing semantics must be reported honestly; JSON is one possible representation, not a selected transport.

The environment's authority model authenticates **principals** and applies roles/capabilities, not biological classifications. Installation establishes a **master/responsible owner**, which may be controlled by a person, AI or automation. That owner delegates grants, administers sessions and may explicitly authorize a control handoff. No physical input is inherently a privileged "human" takeover.

An agent does **not** need to run as a process in LoopEnvironment. Clients can operate locally under isolation or connect from outside via authenticated transports. Interactive installation and secure unattended VM provisioning must lead to the same owner-authority semantics.

**LoopTeach** is a planned native tool to let authorized operators explain what a particular application's controls mean, then expose confidently re-identified annotations through LoopBridge when that app runs again. The product requires no specific model, proprietary vendor or closed app catalog.

All these are design targets, not released environment capabilities. See [operator model](docs/OPERATOR_MODEL.md), [LoopTeach](docs/LOOPTEACH.md) and [ADR 0008](docs/DECISIONS/0008-operator-neutral-authority.md).

## What makes it different?

| Principle | Intended behavior |
| --- | --- |
| Operator-neutral | Authenticate principals and scopes, not whether an operator is biologically human or an AI. |
| Owner-configured | A master/responsible initial owner delegates capabilities, sessions and authority. |
| Structured-first, visual when useful | Machine-readable state/actions, human-visible desktop, and explicitly authorized fallback. |
| Teachable | Native LoopTeach can annotate application-specific controls and reuse meaning on later launches. |
| Compatible | Normal Linux applications remain usable even without a semantic profile. |
| Mandatory mediation | Untrusted operators must not bypass trusted Bridge/OS input boundaries. |
| Existing-Linux first | Installable services on an existing Linux host; optional preconfigured VM image. |
| Open source | Apache-2.0 original code with third-party licenses preserved. |

## LoopBridge: the native agent interface

**LoopBridge is the central LoopEnvironment service, not an agent runtime or kernel replacement.** It exposes session/window discovery, accessible state, semantic actions, ordinary input fallbacks, events, captures and administrative capabilities to authenticated principals. It is not an LLM or agent runtime.

Authority is established by owner-delegated grants: observing does not permit control; teaching does not permit invoking actions; screenshots, clipboard, file access and administration require separate scopes. An authorized owner or delegate may request control transfer; the system must enforce cancellation/preemption at trusted boundaries rather than infer a "human" from an input device.

Live accessibility metadata, inferred visual meaning and stored LoopTeach annotations have distinct provenance. Saved profiles cannot grant authority or guarantee persistent target identity. When semantic matching is uncertain, the API reports ambiguity rather than guessing.

The external contract may use a local socket, VM channel or opt-in remote transport, retaining the same conceptual semantics. Bridge cannot observe or veto every syscall.

Read [LoopBridge](docs/LOOPBRIDGE.md), [operator model](docs/OPERATOR_MODEL.md), [interaction](docs/INTERACTION_MODEL.md), and [security](docs/SECURITY_MODEL.md).

## Conceptual architecture

Operator principals: owner / delegates / local or external clients
                             |
                Authenticated structured API
                             |
                        LoopBridge
            grants | sessions | actions | events
                /                     \
      semantic/profile adapters    trusted input/media
         AT-SPI + LoopTeach          compositor/portals
                \                     /
                 Real graphical applications
                             |
                   Linux kernel/services

The compositor and other trusted OS services enforce their own policy boundaries. LoopTeach annotates semantics; it does not authorize input. The system does not require an AI process inside the guest.

## Project status

**M0.5 — feasibility research complete.** The [study recommendations](docs/research/M0_5_RECOMMENDATIONS.md) identify candidates for experiments. [ADR 0006](docs/DECISIONS/0006-mandatory-agent-mediation.md) records the accepted agent isolation requirement.

**M1.1 — Semantic Feasibility: experiment recorded.** The [local diagnostic and evidence](docs/labs/M1_1_VIRTUALBOX.md) demonstrate three clean GNOME Calculator launches, window/tree correlation, a semantic action with independently queried result and stale-reference rejection on the existing VirtualBox/Sway output. Synthetic/headless output remains unvalidated. This is not a full LoopBridge implementation. Subsequent experiments cover isolated agents, authorization and owner/delegate control; an image is not a mandatory gate.

**M1.2 — Authorization and Events: bounded experiment recorded.** The [lab report and evidence](docs/labs/M1_2_AUTHORIZATION_EVENTS.md) demonstrate a provisioned client in explicit Bubblewrap namespaces, denied direct session access, expired-reference rejection and query-derived events with gap detection and snapshot recovery. This is a fixture-specific prototype, not a stable or production-secure LoopBridge. Native upstream event completeness and broader isolation remain unvalidated.

**M1.3 — Fallback and Human Control: preflight NO-GO for the investigated approach.** The [lab assessment](docs/labs/M1_3_FALLBACK_HUMAN_CONTROL.md) records a real Foot accessibility gap and blocked clipboard transport paths in the M1.2 isolation profile. Target-bound input and safe compositor-side preemption remain unqualified; the existing-session portal alternative was unavailable. Capture, observation, takeover and idle encoding measurements were not implemented or demonstrated.

This historical preflight predates the authority clarification in [ADR 0008](docs/DECISIONS/0008-operator-neutral-authority.md) and [Session Authority V1](docs/design/SESSION_AUTHORITY_V1.md); it does not change their later acceptance gates or demonstrate them.

**M1.3A — Identity, Grants & Session Authority: bounded experiment recorded.** The [lab and reproducible evidence](docs/labs/M1_3A_SESSION_AUTHORITY.md) report server-authenticated identities, scoped delegation/revocation, exclusive leases, 96 passing tests and a real authorized Calculator action from isolated clients. Takeover is policy simulation only; real compositor/semantic preemption remains unqualified for M1.3B. This does not qualify M1.3 overall or production security.

**M1.3B — Trusted Input & Enforcement Feasibility: NO-GO for enabling takeover on the current unmodified Sway + M1.3A stack.** The [assessment and real diagnostics](docs/labs/M1_3B_TRUSTED_INPUT_FEASIBILITY.md) compare cooperative integration, patches, nesting and EIS. A timed-out AT-SPI action took effect after revocation and client disconnection; the broker correctly stayed blocked. No real takeover, compositor patch or input injection was implemented. Future patched/nested approaches remain unqualified.

The [roadmap](docs/ROADMAP.md) defines acceptance criteria and stop conditions. Performance, application compatibility, physical-hardware support, and security have **not** yet been validated.

**M1.3B.1 — Delivery & Acknowledgement:** the [candidate contract](docs/design/DELIVERY_ACKNOWLEDGEMENT_V1.md) specifies operation states, a joint takeover barrier and a nested testbed acceptance matrix. A bounded cooperative-receiver POC is technically plausible; no patch or takeover was implemented, and arbitrary-app acknowledgements remain unavailable.

**M1.3B.2 — Nested build preflight: PARTIAL (local result, 2026-11-18).** The Meson configure exited 1 on incomplete wlroots/Sway source trees, so neither a child binary nor nested smoke test existed. Cleanup passed without modifications to the parent Sway or system installation. **Isolation, ACK and takeover were not tested.** The local logs/report were not yet versioned; this summary does not certify their evidence. The earlier late AT-SPI effect/NO-GO remains in force.

**LoopBridge Core V0.1 — experimental implementation.** The Unix-socket service supports authenticated principals, scoped grants, leases, structured Calculator observation and one semantic action. See the [architecture and run instructions](docs/LOOPBRIDGE_CORE_V0_1.md) and [qualification results](docs/LOOPBRIDGE_CORE_V0_1_RESULTS.md).

## Documentation

- [Product definition and authority model](docs/PRODUCT_DEFINITION.md)
- [Owner and operator identity model](docs/OPERATOR_MODEL.md)
- [LoopTeach — native semantic teaching](docs/LOOPTEACH.md)
- [Vision and boundaries](docs/VISION.md)
- [Environment architecture](docs/ARCHITECTURE.md)
- [LoopBridge API and transport design](docs/LOOPBRIDGE.md)
- [Interaction and human-control model](docs/INTERACTION_MODEL.md)
- [Security and threat model](docs/SECURITY_MODEL.md)
- [Roadmap and milestone gates](docs/ROADMAP.md)
- [Licensing and third-party software](docs/LICENSING.md)
- [Architecture decision records](docs/DECISIONS/README.md)
- [Contributing](CONTRIBUTING.md) · [Security reporting](SECURITY.md)

## License and contributions

The repository includes the [Apache License, Version 2.0](LICENSE). New project-owned source code and documentation are intended to be contributed under that license unless a file explicitly states otherwise. The Linux kernel and packaged third-party software have their **own** licenses; an optional future system image will not be uniformly Apache-licensed.

The project welcomes thoughtful design discussion, accessibility expertise, security review, and reproducible research. See [CONTRIBUTING.md](CONTRIBUTING.md).

Developed as an open-source project in the Nancode ecosystem. No vendor-specific account, proprietary orchestrator, or closed service is intended to be required for core operation.
