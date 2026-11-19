# LoopTeach — native application-semantic teaching tool

**Status:** V0.2 adds a GTK teacher, annotation search and conservative contextual matches to the structured CLI and SQLite store. The overlay, intercepted hotkey and bundled catalog remain design targets. See the [V0.2 contract and evidence](LOOPBRIDGE_V0_4.md).

## Purpose

LoopTeach will be a **native application of LoopEnvironment** for authorized operators to explain what an element of a specific application means, what it does, when it may be used, and how to recognize it again. LoopBridge should expose these stored descriptions alongside live accessibility and other observed evidence to authorized clients.

The tool is **operator-neutral**: a person may annotate visually, while an automated principal may supply structured annotations through a separately authorized interface. Teaching an application is different from granting permission to operate it.

## Preferred interaction

The intended fast interaction is **Super + click** on a visible control. When a configured teaching mode is active and an authorized principal invokes it, a trusted overlay should identify the intended application/window/element and open an annotation editor.

- Super+click is the **preferred, configurable shortcut**, not a guaranteed binding on all compositors or applications. Evaluate conflicts with the compositor, accessibility shortcuts and application shortcuts.
- A trusted compositor/input component should consume the gesture in teaching mode so it does not also activate the underlying button unintentionally.
- Provide an accessible keyboard-only and structured-API alternative; do not assume a physical mouse or a biological human is required.
- Before storing, show the matched target, confidence and known limitations. Do not claim that a pixel selection necessarily maps uniquely to an accessible element.
- An authorized operator may specify label, purpose, expected result, preconditions, warnings, relations to other controls and suggested semantic operation. Text may require sanitization and review.

## Representation and future recognition

A saved annotation must be associated with an **application-specific profile**, not a global screen coordinate. Candidate matching evidence includes:
- Application identity (app ID / desktop file identity; executable/build/package information where available), version and profile revision.
- Window role/context, accessibility role/name/states, stable application-provided IDs when available and structural relationships.
- Relative element paths with context; localized labels and UI modes where applicable.
- Visual characteristics and geometry as optional, **lower-confidence fallback**; do not use a raw pixel coordinate as stable identity.

At runtime, the Bridge resolves a **new live element** to a candidate saved annotation and reports match provenance, confidence/ambiguity and revision. Previously saved runtime handles are never reused across launches. If versions, hierarchy or context have changed, return an unresolved/needs-review result rather than silently attaching an annotation to a different button.

Profiles should support revisions, migrations, invalidation and operator correction. Matching must be evaluated on application restart, localization/layout changes and updates; no guarantee of universal persistent identification is possible for arbitrary third-party apps.

### Illustrative record (not a committed schema)

```json
{
  "application": { "id": "org.example.Editor", "versionRange": "1.x" },
  "element": {
    "role": "button",
    "accessibleName": "Save",
    "context": "document.toolbar"
  },
  "annotation": {
    "meaning": "Save the current document",
    "operationHint": "document.save",
    "source": "operator_annotation",
    "reviewStatus": "operator_supplied"
  }
}
```

The above is human-readable illustration; neither a stable JSON schema nor proof that an element can be unambiguously matched.

## Data trust, permissions and safety

- Keep **observed native semantics**, **operator-supplied annotations**, **inferred visual meaning** and **project-tested bundled profiles** distinguishable in provenance.
- An annotation can be wrong, malicious or out of date. It is **untrusted task data**, not an instruction to bypass authorization, execute arbitrary code or grant new capabilities.
- A teaching grant permits annotation only in allowed application/session scopes. Annotation read, write, approval, distribution/import/export and UI input are separately authorized.
- Restrict capture and recording of sensitive controls, password fields, personal data and secret-bearing windows; use scoped storage, redaction and audit. Owners choose sharing policy.
- A rich description does not make a click safe or confirm business outcomes. Dispatch remains behind live identity, target validation, input policy and result verification.
- Avoid treating an annotation as proof of an application's integrity or software publisher.

## Bundled and shared profiles

The future distribution may ship **tested profiles for selected packaged applications**, with version compatibility, provenance, signed/updateable packages where appropriate and reproducible functional verification. They remain separate from application code and do not create a closed catalog: normal third-party software must continue to run without a profile.

Owner-created profiles may later be exported to multiple installations or shared with other operators under explicit permission, privacy controls, authenticity checks and conflict resolution. No marketplace or automatic global synchronization is committed.

## Delivery sequence

1. Define a minimal annotation model and provenance in LoopBridge, after core identity/session semantics are clarified.
2. Prototype trusted target picking and the preferred Super+click gesture, with keyboard/structured alternatives and safe gesture interception.
3. Persist one bounded application's annotations; restart the app and prove correct re-identification and deliberate refusal on ambiguous matches.
4. Read annotations through the same authorized Bridge observation model; prove that they do not grant input privilege.
5. Add profile versioning, tests across upgrades/locales, and a small verified bundled catalog.

LoopTeach V0.2 is a bounded implementation on the supervised desktop. The historical M1.1/M1.2 results predate it. See [operator model](OPERATOR_MODEL.md), [LoopBridge](LOOPBRIDGE.md) and [ADR 0009](DECISIONS/0009-native-loopteach.md).
