# Product vision

**Status:** accepted product direction; details remain subject to proof of concept.

## Purpose

Create an open-source **agent-oriented environment for existing Linux**, centered on LoopBridge. Structured machine operation is the preferred interface for agents; the normal graphical desktop stays available for human observation/control and compatibility fallbacks. An authenticated principal may be controlled by a person, AI, script or external service without the environment classifying its nature.

A master/responsible owner is provisioned at installation and delegates access. LoopBridge is the native operational interface, not a required in-guest agent process. See [operator model](OPERATOR_MODEL.md).

## The problem

- Existing desktops primarily communicate through pixels and input devices; a generic agent often has to infer the intended control.
- Accessibility trees and app APIs exist but are inconsistent across applications and toolkits.
- Screenshot-only automation is costly, brittle, and difficult to audit.
- Powerful automation can expose personal data or take unsafe actions without explicit boundaries.
- A headless development container cannot fully represent an employee's graphical workstation.

## Intended experience

An authorized operator can use a browser, application, file manager or text editor through the real desktop, or query structured session/window/accessibility state and request permitted actions through LoopBridge. When an app offers incomplete semantics, the Bridge reports the gap and may offer separately authorized visual/keyboard/pointer fallback.

A native **LoopTeach** tool will let an authorized operator identify an element in a specific application (ideally via configurable **Super+click**) and annotate its meaning, expected result and conditions. Future launches should use those annotations only when a new live element can be matched reliably; uncertain matches require review. Distribution-bundled, tested profiles for selected applications are a future option, never a closed-app requirement.

A session may run without a viewer. Independent sessions are preferred by default but shared control and observation are possible through explicit grants. The owner or delegated authority—not an automatically privileged "human"—can request takeover; no physical mouse event proves that authority. An owner can be operated by automation, including unattended VM provisioners.

LoopEnvironment runs on conventional Linux, physically or in a VM. A preconfigured image is optional; host compatibility and headless rendering remain qualification tasks. See [interaction](INTERACTION_MODEL.md) and [LoopTeach](LOOPTEACH.md).

## Product principles

1. **Operator-neutral ownership.** Authenticate principals and their capabilities, not biological human vs AI.
2. **Structured-first operation with visual observability.** Expose only what Linux and adapters can really observe; never invent missing semantics.
3. **Native teaching.** LoopTeach stores app-scoped operator annotations with provenance and careful re-identification.
4. **Explicit delegation.** Owner/bootstrap, scope, lease, revocation and audit define authority.
5. **Distributed enforcement.** Trusted compositor, kernel and services apply policy; Bridge is no universal syscall interceptor.
6. **Real Linux compatibility.** Support ordinary apps and user programs without a required LLM or vendor.
7. **Deployment independence.** Interactive or unattended installs, physical/VM and local/external clients share a conceptual API.
8. **Open, incremental evidence.** Separate accepted product requirements from tested prototypes and future implementation.

## Target use cases

- A company provisions a VM, configures an owner credential, creates limited operator identities and delegates work.
- A person installs LoopEnvironment and interacts normally while automated clients use independent sessions.
- An external AI service connects using an authorized principal without running inside the guest.
- An authorized operator teaches a legacy application with LoopTeach and reuses that meaning after restart.
- An owner/delegate explicitly observes, revokes or assumes control of a session under tested policy.

## Deliberate non-goals for early milestones

- Building a custom kernel, hypervisor, browser, spreadsheet editor, or LLM.
- Guaranteeing semantic visibility into every proprietary or custom-rendered application.
- Allowing untrusted network clients to control a desktop by default.
- Automatically granting root, full disk, camera/microphone, passwords, or unrestricted internet access.
- Promising lossless rollback of actions outside the machine (emails sent, purchases, remote edits).
- Requiring a new Linux distribution or ISO for LoopBridge to work.

## Success criteria

Prove a real GUI and a structured operational model, enforce authenticated scopes, prevent untrusted access bypass, demonstrate owner/delegate session control and a safe visual fallback. Later demonstrate LoopTeach annotations surviving an app restart with reliable re-identification and refusal on ambiguous controls. Historical M1.1/M1.2 results cover only bounded subsets. See [Roadmap](ROADMAP.md).

## Open design questions

Owner/credential bootstrapping and recovery, principal-to-device binding, delegated administration, session ownership and preemption barriers, compositor choice, structured schema, LoopTeach profiles/matching, RPC transport, Linux packaging/update choices, optional image format and hardware support remain unresolved.
