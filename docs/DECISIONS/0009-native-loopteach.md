# ADR 0009 — Native LoopTeach and persistent application semantics

**Status:** Accepted (product direction; implementation unproven)
**Date:** 2026-11-16

## Context

Existing applications expose incomplete or unstable accessibility metadata. LoopEnvironment should not require every operator or agent to rediscover what controls mean on each launch. Authorized operators should be able to teach the OS the meaning and intended effect of elements in specific applications.

## Decision

- Include **LoopTeach** as a native LoopEnvironment tool for application-specific semantic annotation and recall through LoopBridge.
- Prefer an operator-configurable **Super+click** teaching gesture with a trusted picker/annotation overlay; supply non-pointer alternatives. Do not deliver the underlying click when the gesture is intercepted for teaching.
- Bind saved annotations to an application/profile and robust contextual element evidence. On later app launches, resolve annotations to **new live elements**, never reuse stale runtime IDs.
- On ambiguous or changed interfaces, return unresolved/needs-review. Do not promise perfect persistent recognition of arbitrary third-party controls or pure coordinate matching.
- Preserve provenance and distinguish native app metadata, operator annotations, visual inference and independently tested bundled profiles.
- Teaching, reading, approving and sharing annotations are independently authorized. Stored descriptions cannot create new input privileges or bypass live validation.
- Future distribution images may bundle tested/versioned profiles for selected applications without requiring a closed application catalog or a particular AI provider.

## Consequences

The LoopBridge semantic model needs extensible provenance and profile references. Teaching UX requires trusted target selection, accessibility, careful gesture interception and protected annotation storage. Profile validation across app restarts, versions, languages and layouts must be tested.

## Open questions

Matching strategy, storage schema, profile signatures and updates, package identity, conflict resolution, annotation trust levels, shortcut portability, keyboard-only flows and privacy controls.

See [LoopTeach design](../LOOPTEACH.md), [LoopBridge](../LOOPBRIDGE.md) and [operator model](../OPERATOR_MODEL.md).
