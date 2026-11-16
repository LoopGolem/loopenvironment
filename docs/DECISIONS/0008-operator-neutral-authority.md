# ADR 0008 — Operator-neutral ownership, identities and delegated session authority

**Status:** Accepted
**Date:** 2026-11-16

## Context

Earlier documents described a "human takeover" and distinguished "agent" from "human" in the control plane. That phrasing can mistakenly imply biological verification or special rights for physical input. LoopEnvironment must also support unattended installation and owner administration by automation, including an agent that provisions a virtual machine. An agent is not necessarily a Linux process in the guest: it may be a remote authenticated client of the native OS interface.

## Decision

- Establish a **master/responsible owner principal** during installation. The owner may be controlled by a human, AI, service or other actor; the OS does not test biological identity.
- Principals authenticate and act with explicitly scoped, revocable capabilities. "Agent", "human" and "automation" are useful descriptions, **not security classes or proof of identity**.
- The owner defines and delegates administration and session control. No default operator may override a session controller merely by being human or moving a physical device.
- An authorized owner/delegate can request explicit takeover; the control transition must be enforced against stale and pending input and semantic actions before its completion is acknowledged.
- Support interactive and unattended secure bootstrap with equivalent owner authority, without assuming a particular hypervisor, external orchestrator or AI provider.
- LoopBridge binds operations to authenticated principals and scopes. The kernel, trusted compositor/input and narrowly scoped services enforce their respective boundaries. This does not classify or intercept every Linux syscall.
- A deliberately authorized or compromised owner can exercise or change its own administrative privileges. Protect non-owner processes from **ambient** access to those privileges; do not promise protection from the ultimate owner.

## Relationship to prior ADRs

This record **clarifies and supersedes human-specific control assumptions** in [ADR 0004](0004-desktop-and-human-observation.md), [ADR 0005](0005-security-and-transport.md), [ADR 0006](0006-mandatory-agent-mediation.md) and [ADR 0007](0007-unified-input-mediation.md), without removing their obligations for a real GUI, mandatory mediation, least privilege, trusted physical input enforcement and safe control revocation.

"Human takeover" in historical experiments is now interpreted as **authorized principal takeover**, with a physical/local path only when explicitly bound to such a principal. Historic experimental records remain untouched.

## Consequences

Define principal provisioning, credential recovery, scopes, session ownership, control leases, trusted input binding, revocation barriers and audit. Avoid equating principal with UID or a process and avoid hardcoded distinction based on whether the caller is an LLM.

## Open questions

Principal storage, installation flows, cryptographic identity, local device binding, privilege delegation, multi-owner recovery, identity federation, enforcement mechanism and compositor choice. See [operator model](../OPERATOR_MODEL.md).
