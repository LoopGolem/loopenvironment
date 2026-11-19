# Licensing and third-party software

**Decision:** LoopEnvironment project-owned code is intended to be released under the **Apache License, Version 2.0**. The root [LICENSE](../LICENSE) is the repository license.

## What Apache-2.0 covers

Original source files and documentation contributed to this repository, unless an individual file clearly specifies different rights. Contributions should preserve the required attribution, copyright and notices. See [CONTRIBUTING](../CONTRIBUTING.md).

## What it does not cover

An **optional** future LoopEnvironment VM image would bundle Linux and third-party packages under diverse licenses:

- The Linux kernel is under GPL-2.0-only (with relevant notices/exceptions).
- Desktop, compositor, accessibility, networking, crypto and system utilities retain their respective licenses.
- Some packages may impose source-offer, license notice, attribution, modification-disclosure or redistribution obligations.

**We must not advertise an optional binary image as uniformly Apache-2.0.** LoopEnvironment runs on an existing Linux distribution; bundled components retain their actual licenses and any copyleft obligations. Apache-2.0 on project-owned code does not erase copyleft obligations in upstream work.

## Before distributing an optional image or installable packages

Even without an image, document Linux package dependencies, license provenance, installer/uninstaller behavior and update responsibilities.

- Maintain a package/dependency inventory and license manifest, ideally machine-readable.
- Include copyright notices, licenses and any required source or source offers.
- Document modifications to copyleft components and publish required corresponding source.
- Verify redistribution rights for bundled fonts, firmware, media, trademarks and branding.
- Produce a software bill of materials and release provenance where feasible.
- Define a reproducible update/security maintenance workflow.

## Trademarks

Code licensing does not automatically grant permission to misrepresent an unofficial derivative as an official release. A separate public trademark/branding policy may be adopted later; none is finalized here.

This is engineering guidance, not a legal opinion.
