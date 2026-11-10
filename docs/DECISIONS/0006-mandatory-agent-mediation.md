# ADR 0006 — Mandatory LoopBridge mediation and agent isolation

**Status:** Accepted
**Date:** 2026-11-10

## Context

[ADR 0002](0002-native-loopbridge.md) defines LoopBridge as the native agent interface, and [ADR 0005](0005-security-and-transport.md) requires authenticated, scoped access. A local agent that inherits the graphical session's permissions can bypass those checks through desktop sockets, buses or devices. The location of the agent does not establish its trust level.

## Decision

External agents must use the authorized LoopBridge contract for access to the LoopEnvironment graphical session. Here, an external agent runs outside the session's trusted execution context. It may run on another machine, in another environment or on the same machine under enforced isolation.

LoopEnvironment must prevent untrusted agent processes from directly accessing compositor IPC such as Sway IPC, Wayland or X11 display interfaces, AT-SPI, the session D-Bus, and input and capture interfaces or devices. This requirement also covers access obtained through inherited permissions or descriptors. Bridge socket authentication and scoped grants are required alongside OS-enforced isolation.

Administrative processes, trusted applications inside the graphical session and local human control have separate trust boundaries. Their existing authority does not confer a Bridge grant, and agents must stay outside those contexts. Human observation and interactive control remain separately authorized under [ADR 0004](0004-desktop-and-human-observation.md).

## Consequences

The Bridge and its adapters need access to selected session interfaces. The isolated agent needs only the authorized client endpoint for its session access. If the deployment cannot enforce this separation, it must withhold agent access to the session.

This is an architectural requirement. Its enforcement remains to be implemented and validated. The [M1 proof](../ROADMAP.md#m1--agent-native-desktop-proof) must demonstrate a permitted action through LoopBridge and verify that the isolated client cannot use the direct session interfaces, including when it holds a valid Bridge grant. A trusted diagnostic process may inspect those interfaces in M1.1 to assess semantic feasibility.

## Open questions

The OS isolation mechanism, local endpoint placement, session lifecycle and exact validation matrix remain open. The Linux base, compositor, accessibility integration, legacy display support and RPC framework are experiment candidates described in the [M0.5 recommendations](../research/M0_5_RECOMMENDATIONS.md).
