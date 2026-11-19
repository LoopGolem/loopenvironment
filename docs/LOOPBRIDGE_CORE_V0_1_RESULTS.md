# LoopBridge Core V0.1 qualification

**GO for the bounded local Calculator gate. PARTIAL for broader platform security and recovery.** An external client in the demo's Bubblewrap sandbox authenticated to the standalone service, obtained an owner-delegated control lease and invoked the real Calculator's digit 7. A separate trusted AT-SPI query found the digit and matched the observer's authorized snapshot. No system packages or Sway configuration changed.

## Executed checks

| Check | Result |
| --- | --- |
| Daemon start, SIGTERM shutdown and socket removal | PASS with the fixture and with real Calculator |
| Owner, delegate and observer authentication, invalid token denied | PASS with the fixture and all four isolated real clients |
| Discovery, observer-only observation, denial of lease and mutation to observer | PASS on the real session and fixture |
| Delegation, exclusive lease, semantic invocation and fresh display verification | PASS, real display changed from empty to `7` |
| Expired, cross-session and prior-generation references | PASS in deterministic tests. Real demo rejected a superseded reference and replay |
| Revocation and refusal of later actions and lease requests | PASS with the fixture and real demo. Deterministic revocation during preparation prevented dispatch |
| Isolation from protected interfaces | PASS for this Bubblewrap profile and host. Sway, Wayland, session and accessibility buses, X11, PipeWire, system D-Bus, an abstract socket canary and proc-root alternatives were denied. Probes also checked absent input/media devices, inherited descriptors, distinct namespaces, zero capabilities and disabled nested user namespaces |
| Timeout, pre/post-dispatch disconnection, unknown result and persistent blocked state | PASS with deterministic fixtures. Real fault injection and an authenticated recovery protocol remain PARTIAL |
| M1 historical automated regressions | PASS within the 110-test suite. Historical code and evidence files were preserved |

Commands executed for the final run from the repository root:

```sh
/usr/bin/python3 -B -m unittest discover -s tests
/usr/bin/python3 -B -m tools.loopbridge_demo --evidence /tmp/loopbridge-v01-final.json
git diff --check
```

The tests reported `Ran 110 tests` and `OK`. The real demo reported `GO completed`. The default command sandbox denied Unix-socket operations on the first attempt. The final run used the approved local host execution context. See the [sanitized real-run evidence](labs/evidence/LOOPBRIDGE_CORE_V0_1_RUN_01.json).

## Remaining limits

The real qualification covers one existing Sway session, GNOME Calculator and the tested Bubblewrap profile. It does not qualify compositor preemption, cancellation of a submitted AT-SPI operation, multiuser deployment, installation-grade credentials or production hardening. The M1.3B late-effect result and the M1.3B.2 PARTIAL result still apply. See [execution and recovery](LOOPBRIDGE_CORE_V0_1.md#uncertain-delivery-and-recovery).
