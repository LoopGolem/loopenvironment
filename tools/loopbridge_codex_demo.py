# SPDX-License-Identifier: Apache-2.0
"""Run a model-controlled local mission with Codex in a separate OS namespace."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from loopbridge.__main__ import provision, read_private
from loopbridge.https_egress import Egress
from loopbridge.service import DESKTOP_SESSION, Journal

from .loopbridge_demo import Process
from .loopbridge_desktop_demo import grant
from .loopbridge_private_demo import connect_rpc

ROOT = Path(__file__).resolve().parents[1]
PROVIDER = frozenset(('chatgpt.com', 'auth.openai.com', 'api.openai.com'))
MCP_TOOLS = [
    'sessions_list', 'session_features', 'apps_list', 'windows_list', 'lease_acquire',
    'lease_release', 'web_open', 'web_navigate', 'web_discover', 'web_set_text', 'web_select',
    'web_activate', 'workspace_list', 'workspace_read', 'workspace_write', 'operation_status',
]
INSIDE = """
import os
import re, socket, sys, threading
from loopbridge.https_egress import Forward
names = ('user','mnt','pid','net','ipc')
if not all(os.readlink('/proc/self/ns/'+ns) != expected for ns, expected in zip(names,sys.argv[1:6])):
    raise SystemExit(3)
assert not any(os.path.exists(path) for path in ('/run/user','/private','/bridge/workspace','/dev/input'))
with socket.socket() as test:
    test.settimeout(.5)
    assert test.connect_ex(('1.1.1.1',443)) != 0
print('boundary_checked', file=sys.stderr, flush=True)
proxy = Forward('/egress.sock', 8181)
threading.Thread(target=proxy.serve_forever, daemon=True).start()
import subprocess
def run():
    env = dict(os.environ, HTTPS_PROXY='http://127.0.0.1:8181', HTTP_PROXY='http://127.0.0.1:8181')
    return subprocess.run(['/codex',*sys.argv[6:]],env=env,close_fds=True).returncode
raise SystemExit(run())
"""


def filtered_events(path):
    tools, events, terminal, messages, types = [], 0, None, [], set()
    with path.open() as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            name = event.get('type', '')
            events += 1
            types.add(name)
            if name in ('turn.failed', 'turn.completed'):
                terminal = name
            item = event.get('item') or {}
            if item.get('type'):
                types.add('item:' + item['type'])
            if item.get('type') == 'error':
                text = str(item.get('message', ''))
                safe_phrases = ('rate limit', 'bad request', 'tool', 'unavailable', 'websocket',
                                'exhausted', 'internal error', 'missing', 'timeout', 'warn', 'disabled')
                for marker in safe_phrases:
                    if marker in text.lower() and 'error:' + marker not in messages:
                        messages.append('error:' + marker)
            if name == 'item.completed' and item.get('type') == 'agent_message':
                text = item.get('text', '').lower()
                for marker in ('no mcp', 'tools are not', 'not available', 'not exposed', 'connected',
                               'loopbridge', 'wrote', 'created', 'cannot', 'permission'):
                    if marker in text and marker not in messages:
                        messages.append(marker)
            if item.get('type') == 'mcp_tool_call' and name == 'item.completed':
                tool = item.get('tool')
                if tool in MCP_TOOLS:
                    row = dict(tool=tool, status=item.get('status'),
                               eventFields=sorted(key for key in item
                                                  if key not in ('arguments', 'result', 'input')))
                    # Preserve only a bounded, redacted diagnostic. Raw MCP/provider
                    # events can contain user data and are never copied to evidence.
                    error = item.get('error')
                    if error is not None:
                        row['errorType'] = type(error).__name__
                        if isinstance(error, (dict, list)):
                            row['errorFields'] = sorted(error) if isinstance(error, dict) else ['list']
                    if isinstance(error, str):
                        lowered = error.lower()
                        for marker in ('invalid_tool_arguments', 'not_initialized', 'unknown_tool',
                                       'bridge_connection_closed', 'bridge_response_missing',
                                       'invalid_request', 'timeout', 'permission', 'failed',
                                       'error', 'tool call', 'schema', 'argument', 'protocol'):
                            if marker in lowered:
                                row['errorCategory'] = marker
                                break
                        if 'errorCategory' not in row:
                            row['errorCategory'] = 'unclassified_tool_error'
                    if isinstance(error, dict):
                        detail = error.get('message', '')
                        row['errorMessageType'] = type(detail).__name__
                        if type(detail) is int:
                            row['errorCode'] = detail
                        message = str(detail).lower()
                        message = re.sub(r'[a-z0-9._%+-]+@[a-z0-9.-]+', '[redacted]', message)
                        message = re.sub(r'/[^\s]+', '[path]', message)
                        for marker in ('invalid_tool_arguments', 'not_initialized',
                                       'unknown_tool', 'bridge_connection_closed',
                                       'bridge_response_missing', 'invalid_request',
                                       'timeout', 'permission', 'failed', 'error',
                                       'tool', 'protocol', 'schema', 'argument'):
                            if marker in message:
                                row['errorCategory'] = marker
                                break
                        if 'errorCategory' not in row:
                            row['errorCategory'] = 'unclassified_tool_error'
                    result = item.get('result')
                    if isinstance(result, dict):
                        structured = result.get('structuredContent')
                        if isinstance(structured, dict):
                            for key in ('status', 'reason', 'bridgeCode'):
                                value = structured.get(key)
                                if isinstance(value, (str, int)):
                                    row[key] = value
                        content = result.get('content')
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and isinstance(block.get('text'), str):
                                    try:
                                        parsed = json.loads(block['text'])
                                    except ValueError:
                                        continue
                                    if isinstance(parsed, dict):
                                        for key in ('status', 'reason', 'bridgeCode'):
                                            value = parsed.get(key)
                                            if isinstance(value, (str, int)):
                                                row[key] = value
                    if isinstance(result, str):
                        try:
                            parsed = json.loads(result)
                        except ValueError:
                            parsed = None
                        if isinstance(parsed, dict):
                            for key in ('status', 'reason', 'bridgeCode'):
                                value = parsed.get(key)
                                if isinstance(value, (str, int)):
                                    row[key] = value
                    if item.get('status') == 'failed' and not any(
                            key in row for key in ('errorCategory', 'reason', 'status')):
                        # Diagnostic shape only: never copy arguments or raw result text.
                        row['failureShape'] = sorted(key for key in item if key not in ('arguments', 'result'))
                    tools.append(row)
    return tools, events, terminal, messages, sorted(types)


def model(root, endpoint, credential, auth, evidence):
    proxy_path = root / 'egress.sock'
    binary = Path(shutil.which('codex')).resolve(strict=True)
    with Egress(proxy_path, PROVIDER) as egress:
        server = threading.Thread(target=egress.serve_forever, daemon=True)
        server.start()
        try:
            home = Path.home()
            folder = root / 'codex-profile'
            folder.mkdir(mode=0o700)
            (folder / 'config.toml').write_text(
                'approval_policy = "never"\nweb_search = "disabled"\n'
                '[projects."/app"]\ntrust_level = "trusted"\n'
                '[features]\nshell_tool = false\nview_image = false\n'
                'multi_agent_v2 = false\nskill_mcp_dependency_install = false\n'
                '[agents]\nenabled = false\n'
                '[mcp_servers.loopbridge]\ncommand = "/usr/bin/python3"\ncwd = "/app"\n'
                'args = ["-B", "-m", "loopbridge.mcp", "--socket", "/bridge/control.sock", '
                '"--token-file", "/identity/token"]\nrequired = true\ntool_timeout_sec = 48\n'
                f'enabled_tools = {json.dumps(MCP_TOOLS)}\n')
            command = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session',
                       '--clearenv', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                       '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
                       '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
                       '--ro-bind', '/etc/ssl/certs', '/etc/ssl/certs',
                       '--ro-bind', str(binary), '/codex',
                       '--ro-bind', str(binary.with_name('codex-code-mode-host')), '/codex-code-mode-host',
                       '--ro-bind', str(ROOT / 'loopbridge'), '/app/loopbridge',
                       '--ro-bind', endpoint, '/bridge/control.sock',
                       '--ro-bind', str(credential), '/identity/token',
                       '--ro-bind', str(proxy_path), '/egress.sock',
                       '--bind', str(folder), str(home / '.codex'),
                       '--ro-bind', str(auth), str(home / '.codex/auth.json'),
                       '--setenv', 'PATH', '/usr/bin', '--setenv', 'HOME', str(home),
                       '--setenv', 'LANG', 'C.UTF-8', '--cap-drop', 'ALL', '--chdir', '/app',
                       '--', '/usr/bin/python3', '-B', '-c', INSIDE]
            command += [os.readlink('/proc/self/ns/' + ns) for ns in ('user', 'mnt', 'pid', 'net', 'ipc')]
            command += ['exec', '--ignore-rules', '--ephemeral', '--skip-git-repo-check',
                        '--sandbox', 'read-only', '--json', '-']
            prompt = ('Use the LoopBridge tools to research fictional records on its packaged local website. '
                      'Find records about Orchard in North, and save a UTF-8 report at orchard-review.txt '
                      'containing their record IDs, names, regions and counts. Read the workspace file back '
                      'to verify it and release the lease. Choose the tools yourself. If a tool reports an '
                      'unknown effect, stop without retrying it.')
            with tempfile.TemporaryFile() as errors, (root / 'model.jsonl').open('w') as output:
                result = subprocess.run(command, input=prompt.encode(), stdout=output, stderr=errors,
                                        timeout=250, check=False, close_fds=True)
                errors.seek(0)
                diagnostic = errors.read(65536)
            calls, event_count, terminal, markers, event_types = filtered_events(root / 'model.jsonl')
            for line in (root / 'model.jsonl').read_text()[:50000].splitlines():
                row = json.loads(line)
                item = row.get('item', {})
                if item.get('type') == 'error':
                    message = str(item.get('message', ''))
                    message = re.sub(r'[^\s"<>]+@[^\s"<>]+|[A-Za-z0-9_-]{25,}|/home/[^\s]+', '[redacted]', message)
                    evidence.setdefault('modelErrors', []).append(message[:220])
            evidence.update(exitCode=result.returncode, state=terminal, eventCount=event_count,
                            privateBoundaryChecked=b'boundary_checked' in diagnostic,
                            toolCalls=calls, modelMessageMarkers=markers, eventTypes=event_types)
            with (root / 'model.jsonl').open() as stream:
                # Do not publish provider diagnostics, raw output, prompt or auth.
                tail = stream.read(262144).lower()
            for token, label in ((b'mcp', 'mcp_startup'), (b'proxy', 'proxy'),
                                 (b'login', 'authentication'), (b'websocket', 'provider_websocket')):
                if token in diagnostic.lower() and result.returncode:
                    evidence.setdefault('diagnosticCategories', []).append(label)
            if '401 unauthorized' in tail or 'status 401' in tail:
                evidence.setdefault('diagnosticCategories', []).append('provider_unauthorized')
            return result.returncode == 0 and terminal == 'turn.completed'
        finally:
            evidence['providerEgress'] = egress.snapshot()
            egress.shutdown()
            server.join(timeout=2)


def run(root, auth, evidence):
    with ExitStack() as stack:
        creds = root / 'credentials'
        provision(creds)
        owner_token = read_private(creds / 'owner.token').strip()
        manager = Process(stack, [sys.executable, '-B', '-m', 'loopbridge', 'private', '--root',
                                  root / 'private', '--credentials', creds / 'service.json'])
        if manager.line() != b'ready\n':
            raise RuntimeError('private_manager_unavailable')
        admin = connect_rpc(stack, root / 'private/manager.sock', owner_token)
        private = admin.call('private.start')
        owner = connect_rpc(stack, private['socket'], owner_token)
        for cap in ('session.discover', 'workspace.read', 'workspace.write'):
            grant(owner, 'delegate', cap)
        for cap in ('app.launch', 'desktop.observe', 'desktop.control'):
            grant(owner, 'delegate', cap, 'app:browser')
        complete = model(root, private['socket'], creds / 'delegate.token', auth, evidence)
        entries = owner.call('audit', session=DESKTOP_SESSION)['entries']
        evidence['bridgeMethods'] = [row['method'] for row in entries if row['principal'] == 'delegate']
        report = root / 'private' / private['id'] / 'workspace/orchard-review.txt'
        if report.is_file():
            data = report.read_bytes()
            enough = all(value in data.lower() for value in (b'r-103', b'orchard sensor', b'north', b'7'))
            evidence['independentReport'] = dict(verified=enough, sha256=hashlib.sha256(data).hexdigest())
            required = {'web.navigate', 'web.activate', 'workspace.write', 'workspace.read'}
            if enough and complete and required <= set(evidence['bridgeMethods']):
                evidence['result'] = 'GO'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--auth-file', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    evidence = dict(result='PARTIAL', operator='codex_cli')
    root = Path(tempfile.mkdtemp(prefix='lb6-model-'))
    try:
        if not args.auth_file.is_file():
            raise ValueError('codex_auth_unavailable')
        run(root, args.auth_file.resolve(), evidence)
    except (OSError, ValueError, RuntimeError, EOFError, subprocess.SubprocessError) as error:
        evidence['failure'] = type(error).__name__
    finally:
        if any(Journal(p).blocked(DESKTOP_SESSION) for p in root.glob('private/*/runtime')):
            shutil.rmtree(root / 'credentials', ignore_errors=True)
            (root / 'model.jsonl').unlink(missing_ok=True)
            evidence['blockedRootPreserved'] = True
        else:
            shutil.rmtree(root)
    evidence['elapsedSeconds'] = round(time.monotonic() - started, 3)
    with args.evidence.open('x') as output:
        print(json.dumps(evidence, indent=2), file=output)
    print(evidence['result'])
    return int(evidence['result'] != 'GO')


if __name__ == '__main__':
    raise SystemExit(main())
