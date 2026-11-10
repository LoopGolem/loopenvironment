# LoopEnvironment

**An open-source, Linux-based operating system designed for AI agents — observable and usable by humans.**

> **Status: design / pre-alpha.** LoopEnvironment is a proposed operating system, not a downloadable distribution yet. This repository currently contains product and architecture documentation. No image, ISO, installer, stable API, or security-certified runtime is available.

## The idea

Most operating systems expose a desktop primarily for people. An AI agent can use them, but often has to infer meaning from pixels and imitate mouse and keyboard input.

LoopEnvironment takes a different approach: **agents are first-class operators of the computer.** The system retains a real graphical desktop and compatibility with ordinary Linux applications, while providing native, permissioned access to windows, accessible controls, actions, and events.

A person may run LoopEnvironment on physical hardware or in a virtual machine, watch an agent work, intervene, or use the system directly. A visible display is optional for observation, not a prerequisite for the operating session.

LoopEnvironment does **not** bundle an AI model or require a particular agent vendor. It is an operating environment, not the agent's reasoning engine. It is intended as a complete Linux computer, including ordinary applications and user-written programs.

**Input mediation is an OS requirement:** external agent and remote human controls use LoopBridge, while physical keyboard and mouse input follows the same trusted session arbitration policy. This is a design target, not implemented behavior.

## What makes it different?

| Principle | Intended behavior |
| --- | --- |
| Agent-native | An authenticated agent can discover authorized desktop state and execute approved actions through a structured API. |
| Human-observable | A human can view the same session and, when permitted, take control. |
| Real desktop | Existing Linux graphical applications remain useful; the project does not propose a replacement office suite or web browser. |
| Semantic first | Use accessibility and native application interfaces when available; fall back to screen observation and conventional input when needed. |
| Local-first security | Local access is scoped to authorized users/sessions; network control is disabled by default. |
| OS independence | The same operating system capabilities work on physical hardware and inside virtual machines. |
| Open source | Project-owned code is intended to be licensed under Apache-2.0; upstream Linux components retain their respective licenses. |

## LoopBridge: the native agent interface

**LoopBridge is part of LoopEnvironment itself.** It is the required access path to the graphical session for external agents, including agents running locally in an isolated context. It mediates authorized observation and control of the desktop:

- Discover sessions, windows, focus, geometry, and available accessible elements.
- Query semantic roles, labels, states, and supported actions where applications expose them.
- Perform permitted interactions, such as focus, activation, text entry, and input events.
- Subscribe to changes and receive ordered, documented event streams.
- Request a screenshot or visual stream when semantic data is missing or a human chooses to watch.
- Allow user intervention, revocation, and auditable control handoffs.

The agent-facing contract is intended to be stable across execution environments. Only the **connection transport** changes: an authenticated local Unix socket, a private virtual-machine channel, or explicitly enabled remote access.

These are design goals; none of these capabilities should be mistaken for implemented functionality today.

See [LoopBridge design](docs/LOOPBRIDGE.md), [interaction model](docs/INTERACTION_MODEL.md), and [security model](docs/SECURITY_MODEL.md).

## Conceptual architecture

    Agent or authorized human client
                   |
          Versioned agent API
                   |
             LoopBridge
       Auth / Policy / Sessions / Events
                   |
      Desktop and application adapters
       Wayland / accessibility / D-Bus
                   |
       Linux graphical user session
                   |
       Linux kernel and system services

LoopBridge is not a privileged universal backdoor. The design assumes explicit identities, scoped permissions, least privilege, revocation, and clear ownership of each graphical session.

## Project status

**M0.5 — feasibility research complete.** The [study recommendations](docs/research/M0_5_RECOMMENDATIONS.md) identify candidates for experiments. [ADR 0006](docs/DECISIONS/0006-mandatory-agent-mediation.md) records the accepted agent isolation requirement.

**Next: M1.1 — Semantic Feasibility.** The first planned experiment will correlate one real window with its accessible tree and verify the result of a semantic action on an existing Linux graphical session. Later M1 experiments will verify authorized access from an isolated agent, view-only observation and local human takeover before image work begins.

The [roadmap](docs/ROADMAP.md) defines acceptance criteria and stop conditions. Performance, application compatibility, physical-hardware support, and security have **not** yet been validated.

## Documentation

- [Product definition and authority model](docs/PRODUCT_DEFINITION.md)
- [Vision and boundaries](docs/VISION.md)
- [System architecture](docs/ARCHITECTURE.md)
- [LoopBridge API and transport design](docs/LOOPBRIDGE.md)
- [Interaction and human-control model](docs/INTERACTION_MODEL.md)
- [Security and threat model](docs/SECURITY_MODEL.md)
- [Roadmap and milestone gates](docs/ROADMAP.md)
- [Licensing and third-party software](docs/LICENSING.md)
- [Architecture decision records](docs/DECISIONS/README.md)
- [Contributing](CONTRIBUTING.md) · [Security reporting](SECURITY.md)

## License and contributions

The repository includes the [Apache License, Version 2.0](LICENSE). New project-owned source code and documentation are intended to be contributed under that license unless a file explicitly states otherwise. The Linux kernel and packaged third-party software have their **own** licenses; a future system image will not be uniformly Apache-licensed.

The project welcomes thoughtful design discussion, accessibility expertise, security review, and reproducible research. See [CONTRIBUTING.md](CONTRIBUTING.md).

Developed as an open-source project in the Nancode ecosystem. No vendor-specific account, proprietary orchestrator, or closed service is intended to be required for core operation.
