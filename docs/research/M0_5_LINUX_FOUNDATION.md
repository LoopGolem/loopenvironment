# M0.5 — Linux foundation, graphics and accessibility

**Status:** desk research and recommendations for review. Sources consulted on **2026-11-10**. No Linux session, installer, image, performance benchmark or hardware test was run. **High** confidence means a primary source documents the stated interface or artifact. **Medium** means an integration inference or a conclusion that depends on package version or configuration. The confidence ratings do not certify runtime behavior.

See the [executive recommendations](M0_5_RECOMMENDATIONS.md) for the M1 gates and the [LoopBridge study](M0_5_LOOPBRIDGE_FEASIBILITY.md) for the adapter, transport and security design. The [accepted ADRs](../DECISIONS/README.md) govern this study. Distribution and compositor choices remain open.

## Linux base

Use **Debian 13 stable (trixie), amd64**, installed without a general desktop task and with an explicit graphical package set, as the first reference environment. The choice rests on native glibc application compatibility, usable install and package tooling, and a slower supported release cadence. Debian supplies Sway, Weston, XWayland, wayvnc and AT-SPI as packages. That makes the hard part of M1 a desktop integration test without requiring the team to maintain a kernel, libc, compositor fork or package ecosystem. Debian documents full support through August 2028 and LTS through June 2030. Check the actual architecture and package coverage before relying on LTS. [Debian release and lifecycle][F1], [security FAQ][F2], [packaged Sway][G2], [packaged AT-SPI][A1].

Use **Ubuntu Server 26.04 LTS with a minimal installation and an explicit desktop package set** as the base fallback. It preserves the glibc, apt, systemd and D-Bus assumptions, has Subiquity autoinstall and has standard LTS maintenance into May 2031. Check each chosen package's archive component and its public security coverage. Optional extended coverage and external accounts must stay outside the product baseline. Consider switching only for a demonstrated hardware enablement, accessibility or compositor packaging blocker, with the same app and authorization tests. [Ubuntu lifecycle][F5], [Subiquity autoinstall][F6].

| Base | Application and development fit | Boot, image and update path | Operational and redistribution trade-off |
| --- | --- | --- | --- |
| Debian 13 minimal | glibc, native GTK/Qt/browser/office ecosystem, Python and upstream-supported .NET installation paths. Check binary requirements against the stable libc and libraries. | Debian Installer netinst/USB, amd64/arm64 options, Debian Live and `live-build` for later media. apt/dpkg, signed archive metadata and security updates. | Best first fit for a small team. Stable packages can lag required compositor/portal fixes. Prefer packages from `main` and audit any dependency on `non-free-firmware`. [Debian release][F1], [Live manual][F3], [Social Contract][F4], [.NET Linux guidance][F12], [apt-secure][F13]. |
| Ubuntu 26.04 LTS minimal | Similar broad desktop compatibility. Python and .NET are available through documented paths. Confirm which applications are delivered as debs, snaps or other packages, their offline behavior, and the maintenance scope of each. | Subiquity autoinstall for repeatable bare-metal or VM installation, official ISO and cloud artifacts, apt/dpkg and security archive. A cloud image is a different artifact from install media. | Viable fallback. Audit Main/Universe coverage and derivative branding and redistribution terms. A maintained desktop or kernel package advantage needs evidence for the actual target. [Ubuntu lifecycle][F5], [autoinstall][F6], [media listing][F7], [IP policy][F14], [.NET Linux guidance][F12]. |
| Fedora, 44 as a documented media example | glibc, mainstream desktop and developer packages, Python and distro-maintained .NET packages. Useful comparison when a newer graphics or desktop component is decisive. | RPM/DNF, bootable Fedora Everything network installer, Anaconda/Kickstart and Pungi compose tooling. Retain and test SELinux policy with the actual service. | Defer as the product base. Approximately 13 months of support implies a recurring requalification cost across desktop, app and graphics packages. Useful as a diagnostic comparison, with an inventory of package licenses. [Fedora downloads][F8], [Fedora release policy discussion][F9], [Pykickstart][F15], [Pungi][F31], [.NET Linux guidance][F12]. |
| Alpine 3.24 | musl/BusyBox/OpenRC. Native Alpine GUI packages and musl .NET builds can work. A glibc-targeted binary or manylinux-only Python wheel needs a separate compatible build or packaging decision. The systemd-specific adapter would need an alternative. | apk, release branches, standard and virtual install media and custom `mkimage` profiles. Confirm boot drivers and firmware for each image flavor. | Defer for general desktop use. Smaller base storage does not compensate for ABI and adapter divergence. `main` and `community` have different support windows. Verify every bundled package and its license. [Alpine overview][F10], [releases and support][F11], [image downloads][F16], [musllinux wheels][F17], [.NET Linux guidance][F12]. |
| Buildroot, 2026-series tool | Configurable libc including glibc. Can build GUI components but expects a configured target and cross-built packages. Desktop app availability, native tooling and runtime compatibility would become project integration work. | Produces configured bootloader/kernel/root filesystems and image layouts. Board/firmware, installer, release and recovery design are project responsibilities. Normal updates are a rebuilt system artifact, with no general target binary package manager generated. | Reject as the general-purpose base. Its strength is controlled appliance builds. Even on a maintained Buildroot branch the project would own runtime integration and update delivery. `legal-info` assists inventory and has documented coverage gaps. [Buildroot manual][F18], [release channels][F19]. |

The practical baseline is x86-64 UEFI in a VM, then a representative physical machine when the roadmap permits it. Standard distribution kernels and installers reduce bring-up work but do not qualify physical graphics, Wi-Fi, storage, Secure Boot, suspend or ARM boards. Confirm boot mode, CPU baseline, available kernel/driver/firmware, input and graphics on each target. Record the host architecture and hypervisor separately from the guest OS. A hardware target that cannot function under the open-source image policy is a support decision for review. [Debian amd64 installer guide][F20], [Debian Social Contract][F4], [project licensing](../LICENSING.md).

### Footprint evidence

Install media, installed disk use and idle memory are distinct. Netboot media can download most of the installed system. A live installer may contain many packages unnecessary for the final image. The values below describe upstream artifacts or upstream installation guidance. Confidence is **high** for the named source figures and **low** for predicting any LoopEnvironment runtime footprint from them.

| Base | Initial media or storage evidence | Memory evidence |
| --- | --- | --- |
| Debian 13 | The Debian CD mirror lists `debian-13.7.0-amd64-netinst.iso` at `756M`. The installer guide budgets 4 GB disk without a desktop and 10 GB with one. | Upstream amd64 guidance is 512 MB minimum and 1 GB recommended without a desktop, 1 GB minimum and 2 GB recommended with one. This is installation guidance for generic profiles. [Debian netinst][F21], [installer requirements][F22], [Debian CD mirror][F27]. |
| Ubuntu 26.04.1 | The release listing labels the amd64 live-server ISO `2.7G`. Selecting a minimal install changes the installed package set. | The Server guide lists 1.5 GB minimum for ISO installs and 1 GB for cloud images. It does not describe Sway, GNOME or this project's idle usage. [Ubuntu ISO listing][F7], [Server requirements][F23]. |
| Fedora | The Fedora Everything 44 x86-64 network installer build `44-1.7` is listed at `1G` by a release mirror. | No comparable minimal desktop idle estimate established. [Fedora downloads][F8], [Fedora release mirror][F28]. |
| Alpine 3.24 | The Alpine mirror lists the standard `3.24.4` x86-64 ISO at `353M`. Alpine documents about 130 MB of storage for a minimal disk install, excluding a comparable desktop. | No comparable desktop estimate established. [Alpine overview][F10], [download variants][F16], [Alpine release mirror][F29]. |
| Buildroot | Image contents and footprint are determined by the configuration, libc, filesystem, drivers and included packages. | No representative desktop configuration or comparable estimate established. [Buildroot manual][F18]. |

### Sustainable release path

For a later image milestone, track an exact package manifest, verified source archives, archive snapshot date, architecture, build tool versions and signing inputs. Evaluate `mmdebstrap` for a minimal rootfs recipe and `live-build` for bootable media. Verify signed apt metadata and package digests, then pin the selected snapshot for repeatability. Establish a scheduled path to refreshed security packages, track coverage and rebuild with the patched versions. A permanently frozen snapshot creates its own security risk. Compare manifests and unsigned image hashes across independent clean builds. Record variable timestamps, filesystem UUIDs, embedded keys and post-install scripts where output differs. Debian's snapshot service and live tooling enable this workflow. Bit-for-bit reproducibility and transactional rollback need separate proof. [Debian Live][F3], [snapshot archive][F24], [apt-secure][F13], [reproducible build environment][F25], [mmdebstrap][F30].

Before distributing an image, keep an SBOM and license manifest keyed to the actual package and source version. Include required notices, corresponding source or source offers, modifications and build material as required by each license. Verify firmware, microcode, fonts, codecs and trademark rights independently of the distro's ability to install them. Keep the official image within the accepted open-source boundary. Validate boot, signature verification, patched rebuild, failed update recovery and rollback together before choosing a long-term update mechanism. Plain apt is a reasonable experiment baseline. A/B updates, immutable root filesystems, secure-boot signing and production recovery remain open. [Project licensing](../LICENSING.md), [ADR 0003](../DECISIONS/0003-open-source-and-licensing.md), [Debian Social Contract][F4], [Ubuntu IP policy][F14].

## Graphics and monitorless sessions

### Which component knows what

Wayland is a client/compositor protocol. Core Wayland and `xdg-shell` give an application objects for its own surfaces and interaction, without a general desktop-wide window list, global window positions, arbitrary focus, input injection or capture. The compositor owns policy, output layout and seat focus. Activation tokens are requests under compositor policy. Foreign-toplevel listing, image capture and virtual-input extensions are separate features with separate versions and compositor-specific visibility. The foreign-toplevel list gives metadata and lifetime where advertised, without a generic focus/geometry/control API. Verify the actual advertised globals, which processes can bind them, what is captured and which method works on the pinned release. [Wayland architecture][G1], [Wayland protocol model][G3], [foreign-toplevel XML][G4], [capture XML][G5], [activation XML][G6].

Run native Wayland apps first. Include XWayland to support legacy X11 applications and test at least one. An XWayland server knows its X clients, while the compositor manages native and XWayland toplevels. Conventional X11 inspection or input within a shared X server has a broader trust surface and does not cover native Wayland windows. Keep X clients of different trust levels out of a shared X server and avoid global X11 automation as a fallback. Native accessibility in the application toolkit can still be available for either display backend. [Wayland X11 support][G7], [GTK accessibility][A2], [Qt accessibility][A3].

| Stack | Evidence and integration cost | Disposition |
| --- | --- | --- |
| **Sway/wlroots + XWayland** | Debian trixie packages Sway `1.10.1-2` with wlroots `0.18`. It also provides wayvnc `0.9.1-1` and portal-wlr `0.7.1-2`. Sway IPC documents output and tree queries, window subscriptions and commands. A wlroots headless output can be used by wayvnc. Verify pinned IPC fields, headless output, native and XWayland clients and the rendering/input path together. IPC can run commands and is a trusted adapter surface. | First experiment. Use an ordinary Sway session with a synthetic output, a small set of apps and session services, AT-SPI, and a separate view-only attachment. Sway provides a tiling desktop session. User-friendly onboarding, desktop integration and physical display profiles are later work. [Debian Sway][G2], [Sway IPC][G8], [wlroots headless backend][G9], [Debian wayvnc][G10], [wayvnc manpage][G11], [portal-wlr v0.7.1][G12], [Debian wlroots][G25]. |
| **GNOME Shell/Mutter + GNOME Remote Desktop** | Full desktop with upstream headless and remote paths. GNOME Remote Desktop documents existing-session assistance, single-user headless and remote login as distinct modes. It uses Mutter APIs, PipeWire and libei. A remote-login session can differ from the session the agent already owns. A portal workflow alone does not provide a global window inventory. | One bounded graphics fallback if the Sway path fails. Compare on the same base, with an authorized same-session viewer and a supported, versioned way to identify windows/focus. Recheck package coverage and renderer requirements. [GNOME Remote Desktop][G13], [RemoteDesktop portal][G14], [ScreenCast portal][G15]. |
| **KDE Plasma/KWin + KRdp** | Full desktop, KWin scripting with window access and upstream RDP integration. Pin the KWin/Plasma and KRdp versions. Script API scope, headless virtual output creation, attach to the same session, permission checks and capture lifetime need independent verification. | Defer. Viable as a later desktop choice if its window and viewer path closes a documented gap without exposing arbitrary scripting. [KWin scripting][G16], [KRdp][G17]. |
| **Weston/libweston** | Reference compositor with desktop and specialized shells plus DRM, nested, headless and remote backends in upstream documentation. Headless backend is useful for tests. The packaged Debian `14.0.2-1` need not expose all capabilities described in newer docs. A backend alone does not supply the desktop inventory, policy integration or viewer lifecycle. | Useful for isolating renderer or Wayland protocol questions. Defer as the main desktop to avoid maintaining a shell or building more compositor integration before M1. [Weston documentation][G18], [Debian Weston][G19]. |
| **Xorg with a light window manager** | Mature conventional window and input tooling, including legacy X applications. A shared X server does not provide the desired policy mediation by default, and its window/input mechanisms cannot be assumed for native Wayland apps. | Diagnostic baseline for distinguishing toolkit failures from Wayland integration failures. Defer as a product stack. [Wayland architecture][G1], [XWayland security model][G7]. |

### One session, optional observer

Start the normal graphical session and its user bus before launching apps. Bring up one synthetic output at a fixed mode and scale, independently of viewer attachment. Bind the adapter to that exact session and capture output. Keep inventory, AT-SPI and semantic commands working while there is no capture consumer. Start a view-only wayvnc attachment only for an authorized observer in M1. Its documented disable-input mode is useful for separating observation from input. Verify clipboard isolation and deny attachment if the backend cannot enforce it. Use a private local endpoint with independent access control and only synthetic session data. Use viewer lifecycle events or explicit teardown to stop the capture producer after the last authorized observer leaves. Confirm the absence of capture subscriptions and encoded frames before first attach and after last detach. A separately authorized one-frame screenshot can be acquired without enabling a long-lived stream. [wayvnc configuration][G11], [wayvnc control and client events][G22], [capture protocol][G5].

For M1 human takeover, use a local human input path on the same session, with a proof that it preempts both semantic mutation and synthetic input. A remote interactive viewer would need to participate in the same control arbitration. A view-only viewer paired with separately verified local takeover is the bounded starting point. A headless output is not an input backend. A VM console can provide input only if a guest-visible seat and the chosen compositor backends route it into that session. For conventional agent input on Sway, evaluate the compositor's virtual keyboard and virtual pointer protocols behind the adapter. Check whether the pinned compositor exposes them to the adapter and how to withhold them from an untrusted agent process. These protocols emulate a seat and do not guarantee delivery to a named window. If scope or takeover cannot be enforced, compare the bounded graphics alternative. [Interaction model](../INTERACTION_MODEL.md), [Sway IPC][G8], [wayvnc manpage][G11], [virtual keyboard protocol][G23], [virtual pointer protocol][G24].

### Portals and emulated input

`ScreenCast` negotiates sources and a session and can return a PipeWire remote carrying approved stream nodes. `RemoteDesktop` negotiates input devices and can be used with ScreenCast. `ConnectToEIS`, introduced in RemoteDesktop interface v2, returns a connection FD where the backend implements it. EIS is the input server side of the protocol and libei supplies client/server libraries. The compositor or input server ultimately decides which devices and events to accept. Absolute input should use the approved stream/device mapping where the interface exposes it. Portal request/session lifecycle, consent, supported source types and persistence depend on the backend and policy. An unattended headless session may have no way to complete a consent prompt, and restore tokens are not portable blanket grants. The pinned portal-wlr README lists Screenshot and ScreenCast, so do not infer RemoteDesktop or EIS from that package name or a frontend interface. Check advertised device/source types, consent, denial, FD/session closure and revocation on each target. [ScreenCast portal][G15], [RemoteDesktop portal][G14], [libei/EIS][G20], [portal-wlr v0.7.1][G12].

### Rendering and virtualization

Use the VM as a repeatable test environment for normal Linux clients. Start with a software-rendered headless path, verify that the compositor and selected apps work, and separately test the display/seat path for takeover. Compositor Pixman rendering and app-side Mesa software rendering are distinct. A browser or accelerated Qt/Electron surface can behave differently from simple GTK clients even on the same output. QEMU documents virtio-gpu 2D with guest software 3D and accelerated options such as virgl and rutabaga. Hardware acceleration depends on guest drivers, host drivers and renderer, device configuration, feature negotiation and builds. A VM display console is not proof of Wayland session capture, and a working virtual output is not proof of hardware rendering. [QEMU virtio-gpu][G21], [Weston renderers][G18], [wlroots headless][G9].

Use QEMU/KVM as a qualification candidate when an appropriate Linux host already exists. Hyper-V, VMware and VirtualBox use different guest device/driver combinations and are unqualified here. For each later target, record boot and seat lifecycle, native Wayland and XWayland, software rendering, accelerated rendering when available, resolution/scaling and same-session viewing/input. A software path sufficient for M1 may still miss a product performance budget. Defer GPU passthrough, DMA-BUF zero-copy assumptions, hardware encoding and claims of hypervisor parity until evidence warrants them. [QEMU virtio-gpu][G21].

## Accessibility as the semantic layer

AT-SPI2 is the Linux assistive-technology interface used by applications and clients such as Orca. An AT client can use libatspi (with bindings where available) to discover the accessibility bus and registry from the graphical session and query exported D-Bus objects. The accessibility bus has a separate address, discoverable through the session bus via `org.a11y.Bus.GetAddress`. The system bus serves a different purpose, including OS services. The accessible desktop root represents registered applications, each of which can expose a tree of objects and optional interfaces. Orca shows how an AT consumes those interfaces and events. Its screen-reading behavior and toolkit workarounds illustrate real-world variation. LoopBridge can consume the underlying interface directly without embedding Orca or requiring changes to apps with working exports. Debian trixie packages AT-SPI2 2.56.2 with distro updates. The upstream API reference consulted describes libatspi 2.62.0.1, so confirm API availability against the pinned package. [libatspi API][A4], [bus lookup implementation][A18], [desktop root][A5], [Orca][A6], [Flatpak bus permissions][A7], [Debian AT-SPI2][A1].

| Question | Documented interface and remaining limit |
| --- | --- |
| Enumerate apps and windows | `atspi_get_desktop` and `Accessible` children list registered apps and exposed top-level accessible objects. Inventory actual managed windows from compositor IPC. Invisible, unregistered or otherwise unexported apps may have no corresponding tree. [Desktop root][A5], [Accessible][A8], [Sway IPC][G8]. |
| Identify window owner | AT-SPI can report an application object and PID. Sway can report PID, Wayland app ID and/or XWayland window properties for managed windows. Correlate with session, window lifecycle and trusted launch/process metadata. Client-supplied titles, app IDs and classes are hints. A PID can own multiple windows or be a broker or namespace-mapped PID. No standard one-to-one compositor/AT-SPI join was established. [Accessible/PID][A8], [Sway IPC][G8]. |
| Query an element | Query advertised `Accessible`, `Component`, `Action`, `Text`, `EditableText`, `Value`, `Selection` or table interfaces as applicable. Roles, names, values, states and relations reflect what the app exports. A component can report extents in a requested coordinate space. Test unsupported or inaccurate global coordinates on Wayland and compare logical/output/stream coordinates before using them. [Accessible][A8], [Component][A9], [Text][A10]. |
| Receive changes and track focus | Register AT-SPI events for relevant window, object, children, property, text and state changes. Keep accessible focus separate from compositor seat focus. A toolkit can omit or coalesce changes. Invalidate on app/bus owner loss, focus change, defunct state or timeout. Requery after loss and verify meaningful state before another action. [EventListener][A11], [state types][A12], [Sway IPC][G8]. |
| Invoke actions | Enumerate supported actions and invoke by an action index resolved against a current handle. Optional editable-text, value and selection interfaces can change state where implemented. A successful dispatch does not establish the final application or business outcome. Sensitive actions require policy and the control lease even when they bypass pointer focus. [Action][A13], [Accessible interfaces][A8]. |
| Detect gaps and operate in a VM | Missing apps, empty/partial trees, unsupported interfaces, ambiguous mapping, defunct nodes and D-Bus failures are distinct outcomes. Bus access and toolkit initialization can work in a virtual graphical session because AT-SPI uses IPC, but the actual exported trees must be tested there. Input and pixel fallback require separate grants and a valid capture/input backend. No generic interface can prove why an arbitrary visual control has no accessible object. [AT-SPI API][A4], [Flatpak bus permissions][A7], [portals][G14]. |

**Toolkit and application variance.** GTK 4 documents standard accessible widgets and an AT-SPI backend. Custom-drawn GTK widgets and composite controls need app-supplied metadata. Check GTK 3 independently through the packaged AT-SPI stack and test toolkit initialization on both display backends. Qt Widgets has `QAccessible`; Qt Quick uses accessible metadata on items. Qt documents D-Bus status conditions and an accessibility configuration override, so confirm the activation behavior in the distro's pinned Qt/Wayland backend rather than treating a current Qt reference as a package guarantee. [GTK accessibility][A2], [Qt Widgets][A3], [Qt Quick][A14], [Debian AT-SPI][A1].

Chromium and Firefox construct accessibility trees that reflect browser chrome and exposed page semantics, with browser-managed composition across processes. An OS consumer receives the exported accessibility representation, whose completeness depends on activation, HTML/ARIA, browser version, virtualized content, canvas and custom controls. It does not gain the DOM, application state, all background tabs or a browser debugging privilege. Electron inherits Chromium's accessibility model and can enable accessibility in the presence of assistive technology or through its app configuration. Verify the behavior of the actual Electron binary, including packaging/sandbox settings. A web app, Electron app or spreadsheet can remain partial even after accessibility is enabled. [Chromium accessibility][A15], [Firefox architecture][A16], [Electron accessibility][A17].

### Compatibility evidence to collect

For each unmodified application, record its version, native Wayland or XWayland backend, accessibility activation state, sandbox and whether its tree appears. Record compositor window and application candidates, one supported action and its observed effect, and fields or events missing from a known control. Compare the exported tree with an independent assistive technology inspection where available. A missing event warrants a fresh query. An unchanged snapshot after dispatch is an uncertain or failed result, depending on the action's contract. Distinguish a source being down from a source with no exported object for a known visible control. [Orca][A6], [AT-SPI events][A11], [AT-SPI actions][A13].

| Fixture profile | Question to resolve on the selected build |
| --- | --- |
| GTK calculator | Does a standard button expose its role, label and action, and does invoking it change the displayed expression or result? Reopen the app and check that prior handles expire. [GTK accessibility][A2]. |
| Qt Widgets and Qt Quick | With accessibility activation recorded, which standard controls export names, bounds, actions and focus events? Test the cases separately because a Qt Quick item may rely on application-supplied metadata. [Qt Widgets][A3], [Qt Quick][A14]. |
| Firefox and Chromium | Compare an ordinary local HTML form and a local canvas-only fixture. Check whether focused fields and actions are exposed, and verify an honest gap where a visible canvas control has no counterpart. Track browser chrome and page elements separately. [Chromium accessibility][A15], [Firefox architecture][A16]. |
| Electron application | Compare actual exported window and page elements before and after the application's documented accessibility activation path, with sandbox boundaries intact. Record whether the app supplies useful names and actions. [Electron accessibility][A17]. |
| Spreadsheet | Check a selected cell, headers, editable value and selection events with a disposable file. Record virtualized ranges or grid elements omitted by the application. A one-window GTK result cannot establish spreadsheet feasibility. [AT-SPI interfaces][A8]. |

**What LoopBridge must supply.** Keep compositor windows and AT-SPI objects as separate inventories and publish explicit `matched`, `ambiguous`, `unavailable` or `redacted` outcomes for the join. Give handles a session epoch and per-source generation. Limit traversal depth, node count, text size and request time. Filter sensitive state before returning snapshots, events or diagnostics. Recheck target, grant and control immediately before dispatch and verify the result by event or refresh. No generic adapter can recover unexported app state, resolve all cross-process identities, reliably redact arbitrary secrets from pixels or guarantee correct activation in every app. [LoopBridge feasibility](M0_5_LOOPBRIDGE_FEASIBILITY.md), [project interaction model](../INTERACTION_MODEL.md).

## Resource accounting and validation deferred to M1/M2

| Cost layer | What determines the cost | Evidence to collect later |
| --- | --- | --- |
| Kernel and services | Kernel config, drivers, page cache, login/session services, logging and background updates. | Boot to settled base, guest available memory and cgroup counters, installed and compressed artifact sizes. |
| Session and renderer | Shell/compositor, output resolution, refresh, scale, buffer copies, GPU or software rendering, XWayland when needed. | Settled session with no apps and no viewer, then output/render matrix. |
| Apps | App/browser subprocesses, content, GPU cache and number of open windows. | Fixed fixture and profiles with identical app and workload versions. |
| Accessibility and bridge | App-side accessibility tree construction and serialization, adapter calls, cache, event fan-out and queue limits. | Compare accessibility inactive/active, cold/bounded trees and event load. Use cgroup CPU/memory, per-process proportional set size where available and command/event latency. |
| Capture and viewer | Frame production, readbacks, damage handling, copies, encoding, bitrate and connected viewers. | Observe capture nodes/subscriptions, encoded frame counts, bytes and incremental CPU/RAM from no viewer to first viewer and back to zero. Track one-frame requests separately. |
| VM | Guest reservation/ballooning, host memory and vCPU scheduling, virtual devices, display/renderer and storage I/O. | Record guest and host separately, then compare software/accelerated profiles with identical workloads. |

No credible like-for-like idle RAM, CPU, disk or latency estimate was found for the proposed full stack. No benchmark was executed. Kernel accounting and virtual GPU documentation explain where to collect future evidence. They do not predict the observed costs for this configuration. [Kernel cgroup v2][F26], [QEMU virtio-gpu][G21].

## Primary source notes

All links below were consulted on **2026-11-10**. Package pages are trixie snapshots observed during research. The protocol references rendered by Wayland Explorer reproduce upstream protocol XML. Rolling API documentation and protocol versions should be checked against what the installed compositor and applications advertise. The proposed stack and fit judgments have **medium** confidence pending the gates. Numerical image/RAM comparisons are limited to the named profiles and artifacts above.

[F1]: https://www.debian.org/releases/trixie/
[F2]: https://www.debian.org/security/faq
[F3]: https://live-team.pages.debian.net/live-manual/html/live-manual/index.en.html
[F4]: https://www.debian.org/social_contract
[F5]: https://ubuntu.com/about/release-cycle
[F6]: https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html
[F7]: https://releases.ubuntu.com/26.04/
[F8]: https://fedoraproject.org/misc/
[F9]: https://communityblog.fedoraproject.org/fedora-strategy-faq-part-3-what-does-this-mean-for-fedora-releases/
[F10]: https://www.alpinelinux.org/about/
[F11]: https://www.alpinelinux.org/releases/
[F12]: https://learn.microsoft.com/en-us/dotnet/core/install/linux
[F13]: https://manpages.debian.org/trixie/apt/apt-secure.8.en.html
[F14]: https://ubuntu.com/legal/intellectual-property-policy
[F15]: https://pykickstart.readthedocs.io/en/latest/
[F16]: https://www.alpinelinux.org/downloads/
[F17]: https://peps.python.org/pep-0656/
[F18]: https://buildroot.org/downloads/manual/manual.html
[F19]: https://buildroot.org/download.html
[F20]: https://www.debian.org/releases/trixie/amd64/
[F21]: https://www.debian.org/CD/netinst/
[F22]: https://www.debian.org/releases/trixie/amd64/ch03s04.en.html
[F23]: https://documentation.ubuntu.com/server/reference/installation/system-requirements/
[F24]: https://snapshot.debian.org/
[F25]: https://reproducible-builds.org/docs/perimeter/
[F26]: https://docs.kernel.org/admin-guide/cgroup-v2.html
[F27]: https://ftp.osuosl.org/pub/ftp.debian.org/debian-cdimage/current/amd64/iso-cd/
[F28]: https://fedora.is/fedora/releases/44/Everything/x86_64/iso/
[F29]: https://uk.alpinelinux.org/v3.24/releases/x86_64/
[F30]: https://manpages.debian.org/trixie/mmdebstrap/mmdebstrap.1.en.html
[F31]: https://packages.fedoraproject.org/pkgs/pungi/pungi/
[G1]: https://wayland.freedesktop.org/architecture.html
[G2]: https://packages.debian.org/trixie/sway
[G3]: https://wayland.freedesktop.org/docs/book/Protocol.html
[G4]: https://wayland.app/protocols/ext-foreign-toplevel-list-v1
[G5]: https://wayland.app/protocols/ext-image-copy-capture-v1
[G6]: https://wayland.app/protocols/xdg-activation-v1
[G7]: https://wayland.freedesktop.org/docs/book/Xwayland.html
[G8]: https://manpages.debian.org/trixie/sway/sway-ipc.7.en.html
[G9]: https://wlroots.pages.freedesktop.org/wlroots/wlr/backend/headless.h.html
[G10]: https://packages.debian.org/trixie/wayvnc
[G11]: https://manpages.debian.org/trixie/wayvnc/wayvnc.1.en.html
[G12]: https://github.com/emersion/xdg-desktop-portal-wlr/blob/v0.7.1/README.md
[G13]: https://github.com/GNOME/gnome-remote-desktop/blob/main/README.md
[G14]: https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html
[G15]: https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html
[G16]: https://develop.kde.org/docs/plasma/kwin/api/
[G17]: https://github.com/KDE/krdp
[G18]: https://wayland.pages.freedesktop.org/weston/toc/running-weston.html
[G19]: https://packages.debian.org/trixie/weston
[G20]: https://libinput.pages.freedesktop.org/libei/
[G21]: https://www.qemu.org/docs/master/system/devices/virtio/virtio-gpu.html
[G22]: https://manpages.debian.org/trixie/wayvnc/wayvncctl.1.en.html
[G23]: https://wayland.app/protocols/virtual-keyboard-unstable-v1
[G24]: https://wayland.app/protocols/wlr-virtual-pointer-unstable-v1
[G25]: https://packages.debian.org/source/trixie/wlroots
[A1]: https://packages.debian.org/trixie/at-spi2-core
[A2]: https://docs.gtk.org/gtk4/section-accessibility.html
[A3]: https://doc.qt.io/qt-6/qaccessible.html
[A4]: https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/index.html
[A5]: https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/func.get_desktop.html
[A6]: https://orca.gnome.org/
[A7]: https://docs.flatpak.org/en/latest/sandbox-permissions.html
[A8]: https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/class.Accessible.html
[A9]: https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/iface.Component.html
[A10]: https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/iface.Text.html
[A11]: https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/class.EventListener.html
[A12]: https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/enum.StateType.html
[A13]: https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/iface.Action.html
[A14]: https://doc.qt.io/qt-6/qml-qtquick-accessible.html
[A15]: https://chromium.googlesource.com/chromium/src/+/HEAD/docs/accessibility/overview.md
[A16]: https://firefox-source-docs.mozilla.org/accessible/Architecture.html
[A17]: https://www.electronjs.org/docs/latest/tutorial/accessibility
[A18]: https://gnome.pages.gitlab.gnome.org/at-spi2-core/coverage/atspi/atspi-misc.c.html
