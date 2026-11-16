# Architecture decision records

ADRs preserve **why** a decision was made, its status, and what remains undecided. They are not implementation checklists or proof that a feature already works.

**Current interpretation:** [ADR 0008](0008-operator-neutral-authority.md) replaces earlier human-specific takeover assumptions with owner/delegate principal authority; the historical decisions remain preserved. [ADR 0009](0009-native-loopteach.md) adds native LoopTeach as a planned, not implemented, capability.

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-os-product-boundaries.md) | Independent agent-oriented operating system | Accepted |
| [0002](0002-native-loopbridge.md) | Native, provider-neutral LoopBridge | Accepted |
| [0003](0003-open-source-and-licensing.md) | Open development and Apache-2.0 for original work | Accepted |
| [0004](0004-desktop-and-human-observation.md) | Real GUI, semantic-first control, human observation | Accepted |
| [0005](0005-security-and-transport.md) | Permissioned bridge, transport independence, local-first | Accepted |
| [0006](0006-mandatory-agent-mediation.md) | Mandatory LoopBridge mediation and agent isolation | Accepted |
| [0007](0007-unified-input-mediation.md) | Unified input mediation and distributed enforcement | Accepted; clarified by 0008 |
| [0008](0008-operator-neutral-authority.md) | Owner/principal-neutral authority and delegated takeover | Accepted |
| [0009](0009-native-loopteach.md) | Native LoopTeach and persistent application semantics | Accepted product direction |

## ADR workflow

New records follow the pattern: **Context**, **Decision**, **Consequences**, **Open questions**, **Status**.

Accepted product principles should not be silently replaced by choosing a particular toolkit or library. Technical choices (Linux base, compositor, RPC framework, implementation language, virtual display, capture protocol) require a new ADR after experiments.

When a decision changes, leave its history intact and add a superseding record explaining the change. Keep documents and the roadmap synchronized with adopted decisions.

ADRs describe architecture only. Production readiness depends on implementation, tests, and independent security review.
