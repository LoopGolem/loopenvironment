# ADR 0004 — Real graphical desktop with optional human observation

**Status:** Accepted  
**Date:** 2026-11-10

## Context

The product should support graphical tasks—spreadsheets, email, browsers—rather than only terminal commands. A human needs the option to inspect or take over a working session.

## Decision

Keep a real Linux graphical session and compatibility with standard GUI applications. Prefer semantic information (accessibility/official APIs) and fall back to pixels and conventional input when metadata is absent.

Allow an authorized human to attach a viewer, observe the session and request control. The session may operate without an active viewer or physical monitor. Distinguish graphical rendering from capture, encoding and streaming costs.

Treat view-only and input-control privileges as separate. Human control may preempt agent input through an OS-enforced control model.

## Consequences

The system needs compositor integration, a control-arbitration design, event consistency and security around screen capture. Accessibility completeness will vary by application. A headless session still performs some rendering.

## Open questions

Desktop/compositor, virtual display, media codecs, control lease details, UI presentation, multi-seat and multi-display policy.
