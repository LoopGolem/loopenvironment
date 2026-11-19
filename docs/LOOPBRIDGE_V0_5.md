# LoopBridge V0.5 and LoopTeach V0.3

The experimental service adds local MCP stdio and a browser model for a read-only packaged site. Start it with the [private credentials, runtime and workspace](LOOPBRIDGE_V0_2.md#run). The Bridge wire version is `0.5`. The server accepts V0.1–V0.4 on their existing profiles.

## Connect a local MCP client

Launch this subprocess with the provisioned principal's token file. Its stdout contains MCP JSON-RPC only.

```sh
/usr/bin/python3 -B -m loopbridge.mcp \
  --socket "$lab/runtime/socket/control.sock" \
  --token-file "$lab/credentials/delegate.token"
```

For a direct client test from a trusted lab terminal after the grants and note are ready:

```sh
/usr/bin/python3 -B -m tools.mcp_mission -- \
  /usr/bin/python3 -B -m loopbridge.mcp \
  --socket "$lab/runtime/socket/control.sock" \
  --token-file "$lab/credentials/delegate.token"
```

An untrusted client uses the existing [Bubblewrap pattern](LOOPBRIDGE_V0_2.md#run) with the Bridge socket and only its own token. Run `initialize`, send `notifications/initialized`, then use `tools/list` and `resources/list`. The adapter implements the [MCP stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle), [tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools), and [resources](https://modelcontextprotocol.io/specification/2025-11-25/server/resources) for version `2025-11-25`, with `2025-06-18` negotiation also supported.

Grant `session.discover` on `*`. For the mission, grant `app.launch`, `desktop.observe` and `desktop.control` on the supervised browser and editor, `workspace.read` and `workspace.write` on `workspace`, and `teach.read` on the editor. Prepare a `document.save` annotation through a separate, authorized teacher. Acquire a lease before mutation. Grants and audit remain in the Bridge. An MCP connection uses one downstream connection with an idle timeout. Reconnect and rediscover after it closes, using fresh references and a fresh lease. Tool errors retain explicit `refused` and `unknown` statuses. A missing mutation response is uncertain and no tool is replayed automatically.

The standalone client in `tools/mcp_mission.py` uses stdlib and the public MCP wire only. It discovers the site, searches for records, reads the resulting table, uses a fresh LoopTeach match to save the report in the editor, and verifies file contents and the site confirmation.

```sh
/usr/bin/python3 -B -m tools.loopbridge_agent_demo --evidence /tmp/loopbridge-v05.json
/usr/bin/python3 -B -m tools.loopbridge_private_probe --evidence /tmp/loopbridge-v05-private.json
/usr/bin/python3 -B -m unittest discover -s tests
```

Evidence paths must be new. The desktop demo uses the currently available trusted Sway session and ephemeral data. The headless probe uses installed Sway, Bubblewrap, GTK4 and the installed Wayland compiler headers/library to build its probe in a temporary directory.

## Capability matrix

| Capability | V0.4 | V0.5 |
| --- | --- | --- |
| Agent transport | Bridge JSON-lines Unix socket | Adds local MCP tools and per-session resources. No command execution or arbitrary HTTP. |
| Firefox ESR | One disposable form with fixed native handlers | Named packaged pages, DOM discovery by role/name, text fields, select controls, local links/forms and result tables. The inspector is fixed trusted code. Neither selectors nor scripts are client inputs. |
| Firefox limits | Offline profile | Still offline. Browser refs identify the exact document and verified DOM control behind temporary session refs. A native readback checks value changes, navigation and submitted GET fields. Other sites and network policy enforcement remain unqualified. |
| Editor and workspace | Supervised AT-SPI edit/save and verified Linux files | MCP mission combines both with a fresh LoopTeach match. Calculator digit entry and Nautilus directory launch were confirmed through prior profiles. Nautilus selection stays partial. GNOME Clocks was launched and its window observed. |
| Teaching | GTK picker filtered one page, approval through API | Bounded whole-tree GTK search, note lookup/edit/review/resolve with provenance and quality. Search caps are reported. |
| Visual and pointer | Refused on the main compositor | Real isolated Sway headless experiment captured its only output and clicked its sole private GTK window. No production capture or input endpoint was enabled. |
| Unknown operation | Journal blocks further dispatch | Same block. Admin-only `session.recovery` reports the preserved unknown operation and disabled replacement policy. Separate root/epoch/lease/ref checks pass in a fixture. **PARTIAL** for full service replacement and late persistent effects. |

The headless experiment proves socket and namespace separation, one observed window, bounded output capture, one confirmed pointer effect and shutdown. It retains only capture metadata. It does not establish a cancellation barrier, automatic quarantine, or safe reuse of mutable state. Recovery stays disabled. The existing desktop runtime must stay blocked after an uncertain dispatch. A future replacement has to use a separate compositor instance, runtime, authenticated connection and writable root, and independently establish what old effects can persist.

## LoopTeach manual check

Use the trusted `teach-gui` launcher from [V0.4](LOOPBRIDGE_V0_4.md#gtk-teaching-and-evidence). Use an editor with a disposable file and a principal with app observation and the appropriate teaching grants.

1. Navigate with Tab, Shift+Tab and arrow keys. Choose the editor and its window.
2. Press Ctrl+F, type `page.save` and press Enter. Confirm that the scope is the tree and the real control shows its AT-SPI evidence.
3. Select the frame and save a meaning and suggested action. The fields have contextual help. Ctrl+S uses the current selection.
4. Use **Search saved annotations**, select the record, edit it and check that the revision advances. Approve or reject it with a principal holding `teach.review`. A principal without that grant should see a denial.
5. Resolve in a live window. Inspect the reported quality, provenance and criteria. Close/reopen the app and reload the selection. An expired selection or conflicting revision should ask for reselection.

The shipped widget-driven regression exercises real GTK search, creation, editing, approval and resolution. Human usability and keyboard-only completion still need manual evaluation. Super+click, cross-app takeover and networked browsing remain disabled.

## Executed qualification

- **MCP mission GO.** The independent client searched for Harbor records in North, read two records, saved `harbor-report.txt` through the supervised editor, verified the file and submitted its name on a second form. A separate filesystem read checked the file digest. The client completed in 58.939 s, and provisioning plus verification took 87.681 s end to end. The real GTK run used scripted widgets to create, edit, approve and resolve the note at revision 3. The observer could not acquire a lease or read the workspace after its grant expired. Stale refs, the protected field, an external destination and workspace traversal were also checked. [Sanitized mission run](labs/evidence/LOOPBRIDGE_V0_5_MCP_MISSION_01.json).
- **Private Sway experiment GO.** A live check excluded the private window from the host tree before effects. The sole headless output produced an 800×600 frame with distinct pixels and the private GTK target confirmed the click. All supervisor-owned processes and Wayland/Sway sockets shut down. The run took 13.861 s. [Private desktop evidence](labs/evidence/LOOPBRIDGE_V0_5_PRIVATE_DESKTOP_01.json).
- **Recovery PARTIAL.** The fixture checked the original journal remains blocked and a separate root/epoch rejects old references and leases. The graphical probe does not supervise a full replacement Bridge or verify the scope of late persistent effects. No automatic replacement, cancellation or host input path is enabled.
- **Regressions.** The 145-test suite includes MCP protocol handling, changed document policy, unknown-result propagation, separate recovery roots and historical journal tests. The graphical V0.1–V0.4 regressions completed with GO. They cover Calculator digit entry, GNOME Text Editor save/reidentification, Nautilus observation and launch, and the original Firefox form in its disposable profile.

```sh
/usr/bin/python3 -B -m unittest discover -s tests
/usr/bin/python3 -B -m tools.loopbridge_agent_demo --evidence /tmp/lb5-release-mission.json
/usr/bin/python3 -B -m tools.loopbridge_private_probe --evidence /tmp/lb5-private-qualified.json
/usr/bin/python3 -B -m tools.loopbridge_demo --evidence /tmp/lb5-final-v01.json
/usr/bin/python3 -B -m tools.loopbridge_desktop_demo --evidence /tmp/lb5-final-v02.json
/usr/bin/python3 -B -m tools.loopteach_demo --extra-catalog --evidence /tmp/lb5-final-v03.json
/usr/bin/python3 -B -m tools.loopbridge_practical_demo --evidence /tmp/lb5-final-v04.json
```
