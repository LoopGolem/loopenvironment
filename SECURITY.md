# Security policy

## Project status

LoopEnvironment is currently **design / pre-alpha with bounded M1.1/M1.2 experimental code**. No supported OS image, stable API, installer or production deployment exists. These experiments do not constitute a security-certified Bridge; the full owner/operator authority model and LoopTeach are unimplemented.

## Reporting vulnerabilities

Please **do not disclose a security issue publicly** before maintainers have an opportunity to investigate. Use GitHub's **private vulnerability reporting** facility if it is enabled for this repository. If it is not available, request a private contact method from maintainers without posting exploit details, private data, or working credentials in a public issue.

Include, where safe, affected revision, threat scenario, steps to reproduce, impact, and a minimal test. Never send real credentials or customer data.

A definitive private security contact and response SLA have **not yet been established**; this policy must be updated before public binaries or remote access are offered.

## Principles for future implementations

- Unauthenticated network control is forbidden by design.
- Local sockets, guest/host forwarding and remote transports require independent authorization checks.
- Access to window metadata, screen pixels, input, processes and files must be separately permissioned.
- Sensitive text, credentials, images and LoopTeach annotations must be minimized, scoped and redacted in logs.
- Stored annotations cannot become executable instructions or grants; owner credentials must not become ambient process capabilities.
- Owner/delegate takeover and revocation must not depend on the previous controller's cooperation or whether it is human or AI.
- Design-time claims must be verified with negative security tests before release.

Read [the threat model](docs/SECURITY_MODEL.md). No architecture document constitutes a security certification.
