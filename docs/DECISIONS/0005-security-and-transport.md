# ADR 0005 — Permissioned, local-first agent access

**Status:** Accepted  
**Date:** 2026-11-10

## Context

The ability to observe screens and control apps is highly sensitive. A virtual machine, loopback port, Unix-domain socket or encrypted channel is not by itself proof that a client is authorized.

## Decision

LoopBridge must use authenticated clients and scoped capabilities. By default, expose a local-only, per-user/session interface; do **not** open unauthenticated network control. Support a private guest/host transport and opt-in remote authenticated transport without changing the semantic API.

Separate permissions for accessible state, screen capture, input, process launch and file access. Human takeover/revocation should interrupt agent control even if the agent does not cooperate. Deny unsafe fallback on missing permissions, stale targets, lost sessions and failed adapters.

## Consequences

Peer-identity checks, explicit grants, audit, stale-handle invalidation, revocation, streaming privacy and negative security tests are required. Remote pairing and human consent need concrete policy before feature rollout.

## Open questions

Exact authentication and credential storage design, pairing UX, access tokens vs peer credentials, event retention, sensitive-field redaction and permission grant lifetime.
