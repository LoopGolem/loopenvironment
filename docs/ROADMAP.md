# Roadmap

**Status:** planned milestones. This roadmap is intentionally gated: do not build a full operating system before proving the distinguishing interaction capabilities.

## M0 — Product and architecture foundation

**Goal:** document an independent open-source OS, its native LoopBridge, security posture, open questions, contribution rules, and licensing.

**Completion:** repository contains a clear README, vision, architecture, initial Bridge contract, human-interaction model, security model, licensing guidance and ADRs. Documentation must distinguish accepted decisions from proposals.

**Scope excluded:** runtime code, installer, image, ISO, virtualization manager, promises of device support.

## M1 — Agent-native desktop proof

**Goal:** prove LoopBridge concepts on an existing maintained Linux graphical session.

**Demonstrate:**
1. Start a real graphical session with a known test application.
2. Connect an explicitly authorized client through a local-only channel.
3. Enumerate one window and inspect real accessible element metadata.
4. Invoke one permitted UI action and receive an observable event or refreshed state.
5. Deny an unauthorized command and report the denial.
6. Attach a human observer, then safely interrupt or reclaim input.
7. Document one application with missing semantic metadata and the safe visual fallback.

**Gate:** reproducible demo, limitations, tests and a written security assessment. If compositor/accessibility restrictions block this, document the blocker and compare one bounded alternative rather than endlessly changing the stack.

## M2 — First bootable environment image

**Goal:** package the proven interaction service into a maintainable Linux image suitable for a virtual machine.

**Demonstrate:** deterministic startup, user/session provisioning, basic graphics, permitted client connection, logging, a clean reboot, and install/update/rollback design. Reuse existing tools; do not implement a kernel or hypervisor.

**Gate:** full M1 scenario works **inside** the image with measured CPU, RAM, storage and startup cost.

## M3 — External interoperability and human session

**Goal:** support at least two independent client implementations and reliable human observation/control handoff.

**Demonstrate:** version negotiation, distinct identities/permissions, event resynchronization, disconnection recovery, view-only observer and human takeover, security negative cases.

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
