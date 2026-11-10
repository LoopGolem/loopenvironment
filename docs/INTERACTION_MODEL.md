# Interaction and human observation model

**Status:** intended behavior, not implemented behavior.

## Two complementary channels

**Semantic channel:** structured windows, accessible elements, labels, roles, states and actions, normalized by LoopBridge. This is the preferred path when an application exposes usable metadata.

**Visual channel:** screenshots or optional streaming plus conventional keyboard/pointer actions. It remains available when a third-party program uses custom graphics or incomplete accessibility metadata. A client must know when information is missing or only visually inferred.

No application is required to be rewritten for the OS, and we do not claim universal GUI introspection.

## Real desktop without an active viewer

A windowed Linux session can run with a virtual display and no physical monitor. The compositor and graphical applications still render their content as needed. Disabling a live viewer avoids continuous video capture, encoding and transmission; it **does not** make graphical rendering free.

A human may later attach a viewer and see the current session. Remote view-only access and interactive remote takeover are distinct capabilities with separate grants. The former shares approved pixels. The latter requires an authorized remote human to preempt agent input and control the same session.

## Unified input mediation

External agents and remote human controllers must use authorized LoopBridge capabilities. Physical keyboard and mouse input must be subject to the same session arbitration policy through trusted compositor/input enforcement; per-event synchronous RPC is not required. Recovery must be trusted and must not become an agent bypass. See [Product definition](PRODUCT_DEFINITION.md) and [ADR 0007](DECISIONS/0007-unified-input-mediation.md). These are requirements, not implemented mechanisms.

## Control arbitration

The initial proposed model is **single active input controller per graphical session**, while multiple authorized observers may exist:

1. Session starts under a local user and policy.
2. Agent requests a time-bounded control lease; policy grants or denies it.
3. The agent sends actions against a known state revision.
4. A human requests takeover. Agent input stops before control changes hands.
5. The session emits a control-transition event; the agent can observe state but cannot send input.
6. The human releases control; the agent must reacquire a lease and refresh state.

A disconnect, session switch, denial, or lease expiry must release active input safely. Lease durations, default ownership, and emergency intervention controls are open design choices.

## Example workflow (design target)

A permitted agent:
- Discovers a visible office document and its accessible table/cells, if available.
- Selects a cell and enters test data through a supported element action.
- Watches the relevant document-change event or refreshes state.
- Saves the document, then verifies a result through the application or file state.
- Requests a frame or uses ordinary input only if semantic controls are insufficient.

The OS cannot guarantee that a click or text entry resulted in a valid business action. The agent must check application-specific outcomes.

## Accessibility and input expectations

- Prefer accessibility standards (e.g., AT-SPI) where supported.
- Use compositor- or portal-mediated capture/input consistent with Wayland security.
- Do not require unrestricted global keylogging or unapproved screenshot access.
- Preserve coordinate reference, scaling, focus, and window identity across actions.
- Support multiple monitors/seats as a later expansion, not a hidden initial promise.
- Treat password fields, private windows and security dialogs as sensitive and policy-controlled.

## Observable behavior for human clients

- View-only must be possible without agent control privileges.
- The UI should show whether an agent currently has control and what permission scope applies.
- A person can stop or revoke control without trusting the agent to cooperate.
- Logs must identify attempted and completed commands, but not capture secrets or whole screenshots by default.

## Proof criteria

The M1 demonstration should show authorized UI inspection and control, a denied operation, a view-only attachment, local human takeover on the same session and a state refresh after handoff. A remote view-only attachment paired with local input demonstrates observation and local takeover only. Interactive remote takeover needs a separate proof of authorization, preemption and revocation over the remote input path. [Roadmap](ROADMAP.md#m1--agent-native-desktop-proof) · [ADR 0004](DECISIONS/0004-desktop-and-human-observation.md)
