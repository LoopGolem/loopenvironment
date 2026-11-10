# ADR 0002 — Native, provider-neutral LoopBridge

**Status:** Accepted  
**Date:** 2026-11-10

## Context

Agent interaction should not depend on knowing the hypervisor or using an external proprietary manager. A physical installation must offer the same conceptual agent capabilities as a virtual installation.

## Decision

Implement **LoopBridge as a native, open-source service belonging to LoopEnvironment**. It mediates authorized semantic window/element inspection, UI actions, event subscriptions and optional visual observation. External agents are clients; LoopBridge is not an LLM.

Use one versioned agent-facing contract with transport adapters for local connections, private guest communication and future opt-in remote connections. Transport does not grant authority. Document unsupported capabilities instead of fabricating UI semantics.

## Consequences

LoopBridge must define authentication, session identity, permissions, revisions, event consistency, action errors and adapter capability discovery. Third-party applications may expose partial semantics; a visual/input fallback remains necessary.

The design shall not depend on any single graphical toolkit, agent framework or virtualization product.

## Open questions

RPC framework, schemas, implementation language, specific per-user socket path, remote pairing mechanics, compositor and accessibility adapters, media transport.

## Alternatives deferred

A fixed localhost HTTP port or gRPC over Unix socket can be prototyped, but neither is yet a mandated implementation.
