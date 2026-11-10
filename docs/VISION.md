# Product vision

**Status:** accepted product direction; details remain subject to proof of concept.

## Purpose

Create a real, Linux-based operating system whose primary design target is **operation by software agents** rather than exclusively by humans. A human must still be able to observe and operate the environment. LoopEnvironment is an OS, not an agent, model, hypervisor, remote-desktop subscription, or container-only execution wrapper.

## The problem

- Existing desktops primarily communicate through pixels and input devices; a generic agent often has to infer the intended control.
- Accessibility trees and app APIs exist but are inconsistent across applications and toolkits.
- Screenshot-only automation is costly, brittle, and difficult to audit.
- Powerful automation can expose personal data or take unsafe actions without explicit boundaries.
- A headless development container cannot fully represent an employee's graphical workstation.

## Intended experience

An authorized agent can open a browser, read an application's visible and accessible state, navigate windows, work with a spreadsheet, interact with an email client, and report the result. The OS exposes **what it can know** through a versioned, structured interface. It never promises to see internal application state that the application does not expose. Pixels and conventional input remain essential fallbacks.

The graphical session can exist while nobody is watching. When a human connects, they observe the current session; when authorized, they can take or yield input control. Not streaming video does not imply that applications stop rendering.

A person may also install and use LoopEnvironment as an ordinary OS on suitable hardware. Physical installation is a long-term requirement, not a claim of day-one hardware compatibility.

## Product principles

1. **Agent-first, human-capable.** Keep ordinary desktop semantics; do not force a human-free environment.
2. **Independence.** Support arbitrary compatible agents and client languages. No built-in model or required vendor service.
3. **Semantic before visual.** Prefer typed element roles/states/actions; make gaps and ambiguity explicit.
4. **Permissioned mediation.** The OS owns the authorization boundary; mere API access is not blanket permission.
5. **Same OS everywhere.** Physical vs virtual deployments must not change the agent-facing meaning of an action.
6. **Predictable operations.** Versioned API, observable failures, diagnostics, reproducible builds, rollback design.
7. **Open development.** Public design, open project-owned code, clear dependency licensing.
8. **Incremental delivery.** Demonstrate the distinctive interaction capability before designing a bespoke distribution.

## Target use cases

- An agent completing spreadsheet and browser tasks in a graphical workspace.
- A person remotely viewing a running session and intervening when necessary.
- Agent research and benchmarking in repeatable virtualized images.
- A dedicated physical machine operated primarily through an agent.

## Deliberate non-goals for early milestones

- Building a custom kernel, hypervisor, browser, spreadsheet editor, or LLM.
- Guaranteeing semantic visibility into every proprietary or custom-rendered application.
- Allowing untrusted network clients to control a desktop by default.
- Automatically granting root, full disk, camera/microphone, passwords, or unrestricted internet access.
- Promising lossless rollback of actions outside the machine (emails sent, purchases, remote edits).
- Delivering a production-ready general-purpose desktop distribution during the API proof of concept.

## Success criteria

The first meaningful demonstration must show one real graphical application being inspected and controlled through a secured interface, with observable events and an independent human viewing/reclaiming the session. See [ROADMAP.md](ROADMAP.md).

## Open design questions

Linux base, desktop/compositor, implementation languages, RPC framework, image format, remote desktop transport, packaging, and exact permission policy are hypotheses until evaluated and recorded in decision records.
