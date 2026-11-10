# ADR 0003 — Open-source code and honest distribution licensing

**Status:** Accepted  
**Date:** 2026-11-10

## Context

The operating system should be independently auditable, usable, forkable and compatible with agents from any organization. Community participation is a product goal.

## Decision

Publish project-owned code and design documentation openly under **Apache License 2.0** by default. Require no closed-source proprietary service for core OS operation. The whole distributed OS should use redistributable open-source components with their individual licenses preserved.

An Apache-2.0 repository license does **not** relicense the Linux kernel, third-party userland, fonts, firmware or other bundled material. Track copyright, license, corresponding-source and notice obligations before shipping images.

## Consequences

Build scripts, dependency inventory, image provenance, licenses and modification notices must be public and maintainable. Branding may be covered by a future policy distinct from software copyright.

## Open questions

Contribution/legal processes, official release signing model, policy for logos and marks, SBOM implementation.
