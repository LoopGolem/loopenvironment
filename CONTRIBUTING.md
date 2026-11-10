# Contributing to LoopEnvironment

Thanks for considering a contribution. The project is at the **design / pre-alpha** stage: there is currently no runnable OS build or stable agent API.

## Before contributing

1. Read [VISION](docs/VISION.md), [ARCHITECTURE](docs/ARCHITECTURE.md), [LOOPBRIDGE](docs/LOOPBRIDGE.md), and [SECURITY_MODEL](docs/SECURITY_MODEL.md).
2. Check existing issues and ADRs before proposing a major change.
3. For architecture proposals, describe the problem, constraints, alternatives, security impact, test plan and observable acceptance criteria.
4. Prefer the smallest change that produces measurable evidence.
5. Do not claim functionality is implemented if it only exists in documentation.

## Workflow

- The default integration branch is **main**.
- Keep development focused on one small, short-lived feature branch at a time where practical; do not maintain multiple long-running competing branches.
- Use pull requests for substantive code or architecture changes; maintainers may integrate small foundational documentation directly into main.
- Do not rewrite existing design decisions silently. Update an ADR or add a superseding one when a decision changes.
- Commit documentation and tests alongside behavior changes.
- Prefer portable, standard protocols to vendor-specific clients.
- Do not introduce a mandatory proprietary AI provider into the operating system.

## Review criteria

- Correct scoping and security boundaries.
- Real Linux graphical application interoperability.
- Honest disclosure of accessibility and Wayland restrictions.
- Measured resource usage and testable failure cases.
- Compatible third-party software licenses and provenance.
- Clear upgrade/migration paths for protocol changes.

## Licensing of contributions

Unless otherwise specified for a particular file, contributions to project-owned code and documentation are made under the repository's Apache License 2.0. Contributors must have the right to submit their work. Do not copy third-party code, files, trademarks or media without appropriate rights and notices. A future image will have additional upstream licenses: see [LICENSING](docs/LICENSING.md).

## Vulnerability reports

**Do not publish exploit details, credentials, or sensitive logs in issues.** Follow [SECURITY.md](SECURITY.md) for a private reporting path.

## Communication

Use issues/discussions where enabled for design proposals, reproducible bugs and accessibility observations. Include environment information, expected vs observed behavior, and minimally reproducible examples; strip sensitive data first.

We value constructive disagreement and evidence-based revisions. This is an early project: roadmap items are goals, not promises or supported production features.
