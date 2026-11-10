# Security policy

## Project status

LoopEnvironment is currently **documentation-only / pre-alpha**. There is no supported released operating system, API server, binary image, installation package, or production deployment to secure. Features and controls described in design documents are planned, not implemented.

## Reporting vulnerabilities

Please **do not disclose a security issue publicly** before maintainers have an opportunity to investigate. Use GitHub's **private vulnerability reporting** facility if it is enabled for this repository. If it is not available, request a private contact method from maintainers without posting exploit details, private data, or working credentials in a public issue.

Include, where safe, affected revision, threat scenario, steps to reproduce, impact, and a minimal test. Never send real credentials or customer data.

A definitive private security contact and response SLA have **not yet been established**; this policy must be updated before public binaries or remote access are offered.

## Principles for future implementations

- Unauthenticated network control is forbidden by design.
- Local sockets, guest/host forwarding and remote transports require independent authorization checks.
- Access to window metadata, screen pixels, input, processes and files must be separately permissioned.
- Sensitive text, credentials and image content should be minimized and redacted in logs.
- Human permission revocation and input takeover must not depend on agent cooperation.
- Design-time claims must be verified with negative security tests before release.

Read [the threat model](docs/SECURITY_MODEL.md). No architecture document constitutes a security certification.
