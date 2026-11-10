# Roadmap

This roadmap tracks completed and planned milestones. The desktop proof is the gate for building the first bootable image.

## M0 — Product and architecture foundation

**Goal:** document an independent open-source OS, its native LoopBridge, security posture, open questions, contribution rules, and licensing.

**Completion:** repository contains a clear README, vision, architecture, initial Bridge contract, human-interaction model, security model, licensing guidance and ADRs. Documentation must distinguish accepted decisions from proposals.

**Scope excluded:** runtime code, installer, image, ISO, virtualization manager, promises of device support.

## M0.5 — Linux foundation and LoopBridge feasibility research

**Status:** research complete. Merging the research documentation into `main` is the acceptance gate.

**Deliverables:** [Linux foundation study](research/M0_5_LINUX_FOUNDATION.md), [LoopBridge feasibility study](research/M0_5_LOOPBRIDGE_FEASIBILITY.md) and [recommendations and experiment gates](research/M0_5_RECOMMENDATIONS.md).

The study proposes technologies for M1 experiments. [ADR 0006](DECISIONS/0006-mandatory-agent-mediation.md) records mandatory LoopBridge mediation and agent isolation as architectural requirements whose enforcement still needs validation.

## M1 — Agent-native desktop proof

**Goal:** prove LoopBridge concepts on an existing maintained Linux graphical session.

**Demonstrate:**
1. Start a real graphical session with a known test application.
2. Connect an explicitly authorized, isolated agent client through a local-only LoopBridge channel.
3. Enumerate one window and inspect real accessible element metadata.
4. Invoke one permitted UI action and receive an observable event or refreshed state.
5. Deny an unauthorized command and report the denial. Verify that the isolated agent cannot bypass LoopBridge through direct session interfaces.
6. Attach a view-only human observer and demonstrate safe interruption or takeover through a separate local human input path on the same session. Interactive remote takeover requires a separate demonstration.
7. Document one application with missing semantic metadata and the safe visual fallback.

**Gate:** reproducible demo, limitations, tests and a written security assessment. If compositor/accessibility restrictions block this, document the blocker and compare one bounded alternative rather than endlessly changing the stack.

### M1.1 — Semantic Feasibility

**Status:** planned. Use a trusted local diagnostic process on an existing graphical session to correlate one real window with its accessible tree, invoke a supported action and verify the result. Repeat after restarting the application and check that the earlier reference is stale. This experiment provides semantic evidence for M1. The isolated client and its mediation checks belong to the subsequent authorization experiment. [Experiment sequence and GO/NO-GO criteria](research/M0_5_RECOMMENDATIONS.md#proposed-m1-experiment-sequence).

## M2 — First bootable environment image

**Goal:** package the proven interaction service into a maintainable Linux image suitable for a virtual machine.

**Demonstrate:** deterministic startup, user/session provisioning, basic graphics, permitted client connection, logging, a clean reboot, and install/update/rollback design. Reuse existing tools; do not implement a kernel or hypervisor.

**Gate:** full M1 scenario works **inside** the image with measured CPU, RAM, storage and startup cost.

## M3 — External interoperability and human session

**Goal:** support at least two independent client implementations and reliable human observation/control handoff.

**Demonstrate:** version negotiation, distinct identities/permissions, event resynchronization, disconnection recovery, view-only observer and human takeover, security negative cases.

Any claim of interactive remote takeover requires evidence that an authorized remote human can preempt agent input and take control of the same session, with independent control authorization and revocation.

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
- Record measured findings and unresolved risks; avoid calling speculative features "implemented".
- Maintain main as the reference branch; use at most one active short-lived implementation branch at a time where practical.
- Do not introduce dependencies on proprietary agents or services for core OS operation.
