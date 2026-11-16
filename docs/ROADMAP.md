# Roadmap

This roadmap tracks completed and planned milestones. The desktop proof is the gate for building the first bootable image.

## M0 — Product and architecture foundation

**Goal:** document an independent open-source OS, its native LoopBridge, security posture, open questions, contribution rules, and licensing.

**Completion:** repository contains a clear README, vision, architecture, initial Bridge contract, human-interaction model, security model, licensing guidance and ADRs. Documentation must distinguish accepted decisions from proposals.

**Scope excluded:** runtime code, installer, image, ISO, virtualization manager, promises of device support.

## M0.5 — Linux foundation and LoopBridge feasibility research

**Status:** research complete. Merging the research documentation into `main` is the acceptance gate.

**Deliverables:** [Linux foundation study](research/M0_5_LINUX_FOUNDATION.md), [LoopBridge feasibility study](research/M0_5_LOOPBRIDGE_FEASIBILITY.md) and [recommendations and experiment gates](research/M0_5_RECOMMENDATIONS.md).

The study proposes technologies for M1 experiments. Accepted [ADR 0008](DECISIONS/0008-operator-neutral-authority.md) clarifies principal-neutral owner/delegated control, and [ADR 0009](DECISIONS/0009-native-loopteach.md) adds future native teaching. Historical M0.5 recommendations describe the earlier *human takeover* language and remain research evidence, not an override of accepted product requirements. [ADR 0006](DECISIONS/0006-mandatory-agent-mediation.md) requires agent isolation; [ADR 0007](DECISIONS/0007-unified-input-mediation.md) establishes unified remote and physical input mediation. The [product definition](PRODUCT_DEFINITION.md) describes their scope. Enforcement remains unvalidated.

## M1 — Agent-native desktop proof

**Goal:** prove LoopBridge concepts on an existing maintained Linux graphical session.

**Demonstrate:**
1. Start a real graphical session with a known test application.
2. Connect an explicitly authorized, isolated agent client through a local-only LoopBridge channel.
3. Enumerate one window and inspect real accessible element metadata.
4. Invoke one permitted UI action and receive an observable event or refreshed state.
5. Deny an unauthorized command and report the denial. Verify that the isolated agent cannot bypass LoopBridge through direct session interfaces.
6. Attach a separately authorized view-only observer and demonstrate takeover by an authenticated owner/delegate on the same session through a trusted path; input origin or biological humanity alone grants no override. Remote interactive takeover is a distinct demonstration.
7. Document one application with missing semantic metadata and the safe visual fallback.
8. Qualify the trusted compositor/input and semantic-dispatch boundaries for owner/delegate preemption, verified pending-action cancellation and a safe failure/recovery path. Physical input must be bound to a principal/session, not assumed to be the owner.

**Gate:** reproducible demo, limitations, tests and a written security assessment. If compositor/accessibility restrictions block this, document the blocker and compare one bounded alternative rather than endlessly changing the stack.

### M1.1 — Semantic Feasibility

**Status:** bounded experiment recorded; [lab procedure and evidence](labs/M1_1_VIRTUALBOX.md) report semantic GO across three clean launches on the existing VirtualBox output, with stale-reference rejection. Synthetic/headless output remains unvalidated. The experiment uses a trusted local diagnostic process on an existing graphical session to correlate one real window with its accessible tree, invoke a supported action and verify the result. Repeat after restarting the application and check that the earlier reference is stale. This experiment provides semantic evidence for M1. The isolated client and its mediation checks belong to the subsequent authorization experiment. [Experiment sequence and GO/NO-GO criteria](research/M0_5_RECOMMENDATIONS.md#proposed-m1-experiment-sequence).

### M1.2 — Authorization and Events

**Status:** bounded local fixture experiment recorded; [procedure and evidence](labs/M1_2_AUTHORIZATION_EVENTS.md) report GO for a provisioned client in explicit Bubblewrap namespaces, an unenrolled client denied, direct session access denied even with a valid grant, expired references rejected, and query-derived events with retention-gap detection and snapshot recovery after disconnect. Native upstream event completeness, multiuser/session isolation and production authorization remain unvalidated. This is not a stable LoopBridge API. No M1.3 work is included.

### M1.3 — Fallback and operator-authorized takeover

**Authority specification:** [Session Authority V1](design/SESSION_AUTHORITY_V1.md) defines the bounded M1.3A identity/grant/lease control-plane proof and the separate M1.3B trusted-input and M1.3C visual gates. It is a proposed implementation contract, not evidence that a control handoff already works.

**Status:** re-scope required before renewed implementation. The Debian/Sway preflight performed in the local VM reported **NO-GO for its investigated input/preemption approach** (not for the OS concept). Capture, observer attachment, takeover and idle-encoding tests were **not executed**. That preflight is local/unmerged at the time of this documentation update; do not cite its report as a published repository artifact.

**Next gate:** define how owner/delegated identity is bound to the graphical session, how a control lease is enforced at the conventional **and semantic** input boundaries, and what counts as an acknowledged takeover. Then perform one bounded proof with a genuine missing-semantic control, separate frame/input grants, view-only observation, denial of unauthorized clipboard/input, a real owner/delegate override, cancelled/stale actions, and zero active capture/encoding increases over 30 seconds before/after attachment without requests. No GO if the tested approach cannot actually stop the old controller; do not mistake a broker flag for compositor enforcement.

### M1.4 — Compatibility and reproducibility

**Status:** deferred until the clarified M1.3 gate is met. Reproduce the complete validated M1 scenario with an independent operator, native Wayland and XWayland fixtures, a less accessible application, supported software rendering and negative-case evidence. Do not start image construction merely because M1.1/M1.2 were GO.

### Later product capability — Native LoopTeach

**Status:** accepted product direction, **not** part of current runtime experiments. Specify application-scoped annotations and provenance; later demonstrate a trusted target picker (preferred configurable Super+click plus alternatives), saved-profile lookup after restart, correct/ambiguous-match handling, and permission separation. A curated tested profile set for bundled applications is a future distribution goal. [LoopTeach design](LOOPTEACH.md) · [ADR 0009](DECISIONS/0009-native-loopteach.md).

## M2 — First bootable environment image

**Goal:** package the proven interaction service into a maintainable Linux image suitable for a virtual machine.

**Demonstrate:** deterministic startup, user/session provisioning, basic graphics, permitted client connection, logging, a clean reboot, and install/update/rollback design. Reuse existing tools; do not implement a kernel or hypervisor.

**Gate:** full M1 scenario works **inside** the image with measured CPU, RAM, storage and startup cost.

## M3 — External interoperability and authorized session handoff

**Goal:** support at least two independent client implementations and reliable human observation/control handoff.

**Demonstrate:** version negotiation, authenticated principals and distinct grants, event resynchronization, disconnection recovery, view-only operator observation, owner/delegate-authorized session handoff and negative security cases.

Any claim of remote interactive takeover requires evidence that an authenticated owner/delegate with its own control grant can preempt the previous controller in the same session, with enforced revocation and no automatic privilege based on a human label.

**Gate:** documented protocol/SDK examples and repeatable compatibility/security test suite.

## M4 — Distribution and hardening

**Goal:** release a clearly labeled experimental image with documented update provenance, dependency licenses, supported virtualization platforms, known limitations and security procedures.

**Gate:** image build and verification automation; update/rollback exercises; documented minimal system requirements; responsible vulnerability reporting channel.

## Later candidates (not committed releases)

- Physical-hardware installation and hardware compatibility matrix.
- More complete accessibility and application-specific adapters.
- Remote authenticated operation, if threat-model and tests support it.
- Multimedia, multi-display, multi-seat, network policy and resource profiles.
- Stable API and reproducible long-term security maintenance.

## Development discipline

- Each milestone has a fixed demonstration, explicit acceptance criteria, and a stop/reassess condition.
- Keep experiments short, reversible, and isolated from production user data.
- Maintain the distinction between historical experiment terminology and the current operator-neutral identity/ownership contract.
- Record measured findings and unresolved risks; avoid calling speculative features "implemented".
- Maintain main as the reference branch; use at most one active short-lived implementation branch at a time where practical.
- Do not introduce dependencies on proprietary agents or services for core OS operation.
