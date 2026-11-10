# Interaction and human observation model

**Status:** intended behavior, not implemented behavior.

## Two complementary channels

**Semantic channel:** structured windows, accessible elements, labels, roles, states and actions, normalized by LoopBridge. This is the preferred path when an application exposes usable metadata.

**Visual channel:** screenshots or optional streaming plus conventional keyboard/pointer actions. It remains available when a third-party program uses custom graphics or incomplete accessibility metadata. A client must know when information is missing or only visually inferred.

No application is required to be rewritten for the OS, and we do not claim universal GUI introspection.

## Real desktop without an active viewer

A windowed Linux session can run with a virtual display and no physical monitor. The compositor and graphical applications still render their content as needed. Disabling a live viewer avoids continuous video capture, encoding and transmission; it **does not** make graphical rendering free.

A human may later attach a viewer and see the current session. View-only and interactive access must be distinct grants.

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

A practical demonstration should show authorized UI inspection/control, a denied operation, a visual attachment, a user takeover, and a successful state refresh after the handoff. This is a **design acceptance target**, not an existing feature.
