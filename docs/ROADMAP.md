# Roadmap

This roadmap retains historical experiment milestones and applies [ADR 0010](DECISIONS/0010-linux-environment-not-os.md): LoopEnvironment is an environment on existing Linux, centered on LoopBridge. A VM image is optional, not the next required gate.

## M0 — Product and architecture foundation

**Historical goal:** document an agent-oriented Linux product and its LoopBridge, security posture, open questions, contribution rules, and licensing. The standalone-OS boundary is superseded by ADR 0010.

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

**Status:** M1.3A control-plane experiment recorded; M1.3B/M1.3C remain unqualified. The Debian/Sway preflight performed in the local VM reported **NO-GO for its investigated input/preemption approach** (not for the OS concept). Capture, observer attachment, takeover and idle-encoding tests were **not executed**. The [historical report and evidence](labs/M1_3_FALLBACK_HUMAN_CONTROL.md) are preserved without re-running the experiment. They predate ADR 0008 and Session Authority V1 and do not change the later acceptance gates.

#### M1.3A — Identity, Grants & Session Authority

**Status:** bounded GO recorded in the [lab and evidence](labs/M1_3A_SESSION_AUTHORITY.md): server-authenticated principals, scoped grants/revocation, exclusive connection-bound leases, 96 passing tests including M1.1/M1.2 regressions, and one real Calculator action with negative isolation probes. Takeover is explicitly abstract policy simulation only. M1.3B still requires the actual compositor/conventional and semantic dispatch barrier; M1.3C visual observation remains separate. No GO for M1.3 overall or image work.

#### M1.3B — Trusted Input & Enforcement Feasibility

**Status:** [bounded feasibility assessment](labs/M1_3B_TRUSTED_INPUT_FEASIBILITY.md) records **NO-GO for takeover on the current unmodified Sway + M1.3A composition**. Real AT-SPI timeout/revocation/disconnection produced a late Calculator effect while the broker remained blocked. 101 tests and the existing authorized-client isolation regression passed; none proves a compositor barrier. Cooperative IPC, patch, nested and EIS alternatives were compared; no enforcement candidate was implemented, and future patched/nested paths are not disproven. The next M1.3B step is review of an explicit delivery/receipt contract for a minimal patch in an isolated nested testbed, before authorizing build dependencies. M1.3C and later gates remain unqualified.

##### M1.3B.1 — Delivery & Acknowledgement Contract

**Status:** [candidate specification and feasibility analysis](design/DELIVERY_ACKNOWLEDGEMENT_V1.md) recorded, without implementation or execution of the proposed matrix. Defines delivery versus processing/effects, operation states, authenticated fencing/receipts and conservative blocking. A nested patched Sway testbed with a cooperative receiver is a plausible bounded next POC; this is not GO for M1.3B or arbitrary applications. M1.3B.2 requires separate review and authorization for missing build dependencies; no package installation or parent-compositor change is authorized by this specification.

##### M1.3B.2 — Nested Sway build/smoke feasibility (PARTIAL)

**Local result reported on 2026-11-18; evidence files not yet committed to `main`.** Meson exited 1 because local wlroots lacked `include/wlr/config.h.in` and `wlroots.syms`, while Sway lacked `config.in` and `sway.desktop`. The private wlroots subproject failed configure and Meson detected system wlroots. No nested binary or Pixman one-output smoke was executed (**BUILD_FAIL**, **NESTED_FAIL** as not run). Parent Sway remained running with unchanged PID, sockets and `Virtual-1`; no install/download/configuration change and cleanup passed (**CLEANUP_PASS**). **ISOLATION_NOT_YET_VALIDATED**, **ACK_NOT_TESTED**, **TAKEOVER_NOT_TESTED**. This is PARTIAL, not GO or a new proof that nested enforcement is impossible. Historical late AT-SPI effect and unmodified-Sway NO-GO remain valid.

The user reported local-only evidence under `docs/labs/M1_3B2_NESTED_SMOKE_01.md` and `docs/labs/evidence/M1_3B2_NESTED_SMOKE_01/` (`configure.log`, `result.json`, `parent-after-cleanup.json`). These paths are **not verified remote artifacts**. A future rerun requires complete upstream tarballs with verified SHA-256 and separate authorization; this change does not authorize downloads/builds/installation.

**Preserved historical preflight — Fallback and Human Control:**

**Status:** preflight stopped with NO-GO for the investigated approach; [assessment and evidence](labs/M1_3_FALLBACK_HUMAN_CONTROL.md). A real Foot semantic gap and isolated clipboard endpoint denials were observed. Target-bound conventional input and safe compositor-side preemption were not qualified; the existing-session portal RemoteDesktop/EIS availability check did not provide an alternative. No capture/observer/takeover or 30-second idle encoding proof was performed. This is not evidence of a demonstrated bypass or universal Sway impossibility. The complete M1 gate and image work remain blocked.

**Next gate (M1.3B):** extend the bounded M1.3A authority proof to trusted physical-input principal/session binding, enforce leases at the conventional **and semantic** dispatch boundaries, and prove the acknowledgement barrier for real takeover. Then perform one bounded proof with a genuine missing-semantic control, separate frame/input grants, view-only observation, denial of unauthorized clipboard/input, a real owner/delegate override, cancelled/stale actions, and zero active capture/encoding increases over 30 seconds before/after attachment without requests. No GO if the tested approach cannot actually stop the old controller; do not mistake a broker flag for compositor enforcement.

### M1.4 — Compatibility and reproducibility

**Status:** deferred until the clarified M1.3 gate is met. Reproduce the complete validated M1 scenario with an independent operator, native Wayland and XWayland fixtures, a less accessible application, supported software rendering and negative-case evidence. Do not start image construction merely because M1.1/M1.2 were GO.

### Native LoopTeach

**Status:** [V0.1](LOOPBRIDGE_V0_3.md) implements scoped structured selection, revisioned SQLite annotations and conservative reidentification. Trusted compositor gesture interception, GUI overlays, cross-version matching and bundled profiles remain open. See [LoopTeach design](LOOPTEACH.md) and [ADR 0009](DECISIONS/0009-native-loopteach.md).

## LoopBridge Core V0.1

The [experimental local service](LOOPBRIDGE_CORE_V0_1.md) implements the bounded Calculator path on existing Linux. See the [qualification results](LOOPBRIDGE_CORE_V0_1_RESULTS.md). The M1.3B and M1.3C gates remain open. Cua Driver comparison and any decision to adopt an external dependency remain separate work.

## M2 — Reproducible installation on existing Linux

**Goal:** package the validated environment services for existing Linux installations, not build a mandatory standalone ISO/image.

**Demonstrate:** package install/uninstall/upgrades, secure owner bootstrap design, consistent service/session provisioning, diagnostics, recovery and update provenance, basic graphics, host compatibility and measured resource costs.

**Gate:** the applicable complete M1 proof is reproducible on a supported Linux host; an optional preconfigured image needs a separate maintenance/value justification.

## M3 — External interoperability and authorized session handoff

**Goal:** support at least two independent client implementations and reliable human observation/control handoff.

**Demonstrate:** version negotiation, authenticated principals and distinct grants, event resynchronization, disconnection recovery, view-only operator observation, owner/delegate-authorized session handoff and negative security cases.

Any claim of remote interactive takeover requires evidence that an authenticated owner/delegate with its own control grant can preempt the previous controller in the same session, with enforced revocation and no automatic privilege based on a human label.

**Gate:** documented protocol/SDK examples and repeatable compatibility/security test suite.

## M4 — Environment hardening and optional images

**Goal:** release qualified Linux environment packages with documented provenance, host compatibility, third-party licenses, known limitations and security procedures. A preconfigured VM image may be offered only if it simplifies deployment enough to justify ongoing maintenance.

**Gate:** package verification automation, upgrade/rollback exercises, documented minimum requirements and vulnerability reporting. Any optional image needs additional integrity and licensing gates.

## Later candidates (not committed releases)

- Broader Linux distribution and physical-hardware compatibility matrix.
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
- Do not introduce dependencies on proprietary agents or services for core LoopEnvironment operation.
