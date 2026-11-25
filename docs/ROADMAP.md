# Roadmap

LoopEnvironment runs on existing Linux, centered on LoopBridge. [ADR 0010](DECISIONS/0010-linux-environment-not-os.md) makes a VM image optional. The [LoopBridge release track](#loopbridge-release-track) applies [ADR 0011](DECISIONS/0011-session-presentation-and-operator-shell.md) incrementally and uses the historical experiment gates where applicable.

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

## LoopBridge release track

[V0.6](LOOPBRIDGE_V0_6.md) delivered managed private Sway sessions and a GTK4 viewer using periodic authorized PNG captures.

### V0.7 — Live Session Presentation

[V0.7](LOOPBRIDGE_V0_7.md) implements ADR 0011 Alternative A for the Debian lab. It adds a pinned, separately authorized private Sway stream and a read-only GTK4 viewer. The report includes graphical performance, idle behavior and isolation evidence. Unrestricted same-UID host isolation remains PARTIAL. Shell supervision, handoff, compositor development and Alternative B belong to later or open work.

### V0.7.1 — Scoped Credentials and Process Hardening

[V0.7.1](LOOPBRIDGE_V0_7_1.md) consolidates per-instance credential verifiers (opt-in scoped private mode), reduces bearer-token exposure during trusted process bootstrap and adds process-local inspection hardening. The complete Debian VM demonstration reported GO for live streaming, performance, authorization, scoped credential checks and human observation. **Unrestricted same-UID host isolation remains PARTIAL:** direct private Wayland/Sway IPC/D-Bus access was still observed. Do not claim production-grade mediation or unrestricted-host safety.

### Separate hardening track — Trusted service identity boundary

**Status: D1–D3 merged. D4.2C recorded a functional cross-UID smoke on the opt-in profile. Host isolation remains PARTIAL.** [ADR 0012](DECISIONS/0012-trusted-service-identity-boundary.md) accepts a dedicated Linux identity for private-session services. The [D2 ingress contract](design/TRUSTED_SERVICE_INGRESS_D2.md) separates Linux peer admission from principal authentication and capability grants. The [D3 lifecycle](design/TRUSTED_SERVICE_LIFECYCLE_D3.md) provides the unprivileged same-UID listener and cleanup baseline.

The [D4.2A implementation and deployment contract](design/TRUSTED_SERVICE_BOUNDARY_D42A.md) covers the nominal ACL policy, bounded relay, durable verifier enrollment and versioned release. The [D4.2A.1 administrative complement](design/TRUSTED_SERVICE_ADMIN_D42A1.md) adds exclusive fresh bootstrap and authenticated empty-manager readiness. D4.2B is separately authorized VM provisioning. The [D4.2C result](design/TRUSTED_SERVICE_SMOKE_D42C.md#gate-3-functional-result) records a private Calculator session, authenticated observation with a painted GTK frame, and exact-ID retirement on the offline clone. The first clone failure remains inconclusive.

The next hardening milestone is the [D5 qualification matrix](design/TRUSTED_SERVICE_BOUNDARY_V1.md#acceptance-matrix-for-eventual-d5), after review of D4.2C and separate approval. It requires reproducible evidence of direct private-resource and descriptor denial, scoped authorization and credential replacement, sustained media and lifecycle checks. The scope is the bounded Linux profile. Takeover and preemption retain their own gates. V0.8 remains the next release-track milestone.

### V0.8 — LoopShell and Session Supervisor

**Status: architectural specification accepted; bounded experiments recorded. Full V0.8 qualification remains open.** [ADR 0013](DECISIONS/0013-loopshell-layout-and-mission-boundaries.md) refines ADR 0011. See the [V0.8 design](design/LOOPSHELL_V0_8.md) for layout invariants, operator-neutral interfaces, safety boundaries and a bounded lab matrix. LoopShell is a separate unprivileged client of LoopBridge, not a general-purpose shell or enforcement service.

- **V0.8-A — LoopShell Layout:** prototype a full-height, width-adjustable left/right rail; a top/bottom Bridge console over the remaining width; and unobstructed Sway-managed workspace. Evaluate layer-shell reserved zones and bounded fallback; test focus, resize, crash/restart and screen changes.
- **V0.8-B — LoopBridge Shell:** [B.1](labs/LOOPSHELL_V0_8_B1_CONSOLE.md) demonstrates explicit authentication and typed session reads over the existing broker. [B.2](labs/LOOPSHELL_V0_8_B2_ANCHORED_CONSOLE.md) validates that console in the anchored layout. The wider package includes sanitized events and additional authorized operations.
- **V0.8-C — Session Views:** [C.1](labs/LOOPSHELL_V0_8_C1_VISUAL_VIEWS.md) demonstrates authorized Visual windows over V0.7 streaming. [C.2](labs/LOOPSHELL_V0_8_C2_ACTIVITY_VIEWS.md) follows authorized structured events. [C.3](labs/LOOPSHELL_V0_8_C3_COMBINED_VIEWS.md) composes both authorized feeds in one window. The [paired C.4 results](labs/LOOPSHELL_V0_8_C4_PERFORMANCE.md) qualify performance as PARTIAL for the local two-vCPU Cairo/Pixman profile.
- **V0.8-D — Agent/Mission Foundation:** provider-neutral agent registration, free-text objective delegation, bounded optional external orchestrator, validated structured requests. [D.1A](labs/LOOPSHELL_V0_8_D1A_OBJECTIVE_REGISTRY.md) validates the in-memory domain. [D.1B](labs/LOOPSHELL_V0_8_D1B_DURABLE_REGISTRY.md) qualifies an experimental SQLite registry and process-local authorization boundary. [D.1C.1](labs/LOOPSHELL_V0_8_D1C1_TRUSTED_REGISTRY.md) validates authenticated Registry RPC on a disposable local Unix socket. [D.1C.2](labs/LOOPSHELL_V0_8_D1C2_OPERATIONAL_REGISTRY.md) exercises a restricted Registry profile with pinned policy and storage. [D.1C.3](labs/LOOPSHELL_V0_8_D1C3_CROSS_UID_PREFLIGHT.md) prepares the cross-UID driver and runbook.
  - [D.1C.4](labs/LOOPSHELL_V0_8_D1C4_CROSS_UID_EXECUTION.md) records **experimental GO** for the Registry on a disposable Debian 13 clone, based on operator-supplied terminal output. The result covers authenticated cross-UID RPC, 18 direct-access denials, grant revocation, credential rotation, recovery using the same pinned SQLite database and verified fixture cleanup. Objective acceptance records receipt. The Registry remains experimental and the host D5 gate remains PARTIAL.
  - [D.2A proposal](design/LOOPSHELL_V0_8_D2A_EXECUTOR_PROPOSAL.md) is ready for review. It scopes the first executor to a deterministic synthetic operation with separate, explicit LoopBridge authorization and an auditable execution lifecycle. Implementation remains pending.

Mission, session, controller lease, observation surface and event stream have distinct lifecycles. An operator's biological nature grants no authority; API or physical input is not proof of a human. Handoff remains a **separate future qualification**; D5 host security and M1.3B trusted input/semantic barriers are unchanged.

### V0.9 — Observable Actuation

Study and implement configurable actuation modes. The efficient mode uses native and semantic actions. The observable mode uses visually comprehensible graphical input where technically viable and authorized. Observer connections leave the selected mode unchanged. The interaction style conveys no operator identity or authority.

### Future milestone — Operator Handoff

Qualify authorized transfer of control between operators under [ADRs 0007](DECISIONS/0007-unified-input-mediation.md) and [0008](DECISIONS/0008-operator-neutral-authority.md). Preserve the [M1.3B gates](#m13b--trusted-input--enforcement-feasibility). Confirm a handoff only after demonstrating a real revocation barrier against stale input and late conventional and semantic effects at the trusted dispatch boundaries.

### Future hypothesis — Nested Session Presentation

Keep Alternative B as a candidate for local presentation. Study it if there is a justified use case, and base any adoption decision on security, compatibility and measured benefit. Scheduling and implementation remain open.

### Parallel track — Real AI Agent Qualification

Continue qualifying complete missions in which a real model selects operations through LoopBridge/MCP and the resulting artifacts or effects are independently verified. Scripted MCP runs qualify client workflows. V0.6 evidence for a real model is limited to audited read-only discovery. This track can advance independently of streaming.

## M2 — Reproducible installation on existing Linux

**Goal:** package the validated environment services for existing Linux installations, not build a mandatory standalone ISO/image.

**Demonstrate:** package install/uninstall/upgrades, secure owner bootstrap design, consistent service/session provisioning, diagnostics, recovery and update provenance, basic graphics, host compatibility and measured resource costs.

**Gate:** the applicable complete M1 proof is reproducible on a supported Linux host; an optional preconfigured image needs a separate maintenance/value justification.

## M3 — External interoperability and authorized session handoff

**Goal:** support at least two independent client implementations and reliable authorized observation and control handoff.

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
