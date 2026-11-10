# ADR 0001 — Independent agent-oriented operating system

**Status:** Accepted  
**Date:** 2026-11-10

## Context

The goal is not simply a container for running AI tools. Agents should use a real computer environment, including existing GUI applications, while humans can optionally operate the same computer. Deployment may be on bare metal or in a virtual machine.

## Decision

Build LoopEnvironment as a standalone Linux-based **operating system** whose primary interface is optimized for agents while preserving ordinary human interaction and application compatibility.

- OS capabilities must not require a particular model, agent vendor, proprietary orchestrator, subscription or remote service.
- The same OS should operate in virtualized and physical contexts; hardware certification is future work.
- The project reuses upstream kernel, userland, compositor, and Linux software rather than writing them from scratch.
- A runnable Linux desktop with a proof of agent interaction precedes a custom distribution image.

## Consequences

The project must eventually handle boot, system updates, third-party license obligations, device/session lifecycle and deployment formats. Hardware support and performance will require incremental qualification. Physical-installation intent does not imply an installable ISO is available today.

## Open questions

Base distribution, update model, images, bootloader, exact system services, device compatibility and release process.

## Rejected shortcuts

A non-graphical command container is insufficient as the full product. A fully custom kernel is unnecessary for demonstrating agent-native interaction.
