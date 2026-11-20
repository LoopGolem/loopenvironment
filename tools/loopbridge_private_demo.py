# SPDX-License-Identifier: Apache-2.0
"""Qualify isolated MCP clients against managed private Sway instances."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

from loopbridge.__main__ import provision, read_private
from loopbridge.browser import process_tree
from loopbridge.protocol import Fault, RPC
from loopbridge.service import DESKTOP_SESSION, Journal

from .loopbridge_agent_demo import isolated_command
from .loopbridge_demo import Process, check, connect, endpoints
from .loopbridge_desktop_demo import SESSION, element, grant, writable
from .loopbridge_view import capture
from .mcp_mission import Client, mission


def connect_rpc(stack, path, token):
    sock = stack.enter_context(socket.socket(socket.AF_UNIX))
    sock.connect(str(path))
    rpc = RPC(sock)
    rpc.call('auth', credential=token)
    return rpc


def denied(code, function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except Fault as error:
        check(error.message == code)
    else:
        raise AssertionError('expected_bridge_denial')


def namespaced_process(manager, instance, executable):
    ns = json.loads((instance / 'display/boundary.json').read_text())['pid']
    result = []
    for pid, row in process_tree(manager).items():
        if Path(row[3]).name == executable and os.readlink(f'/proc/{pid}/ns/pid') == ns:
            result.append(pid)
    check(len(result) == 1)
    return result[0]


def await_phase(admin, id_, expected):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        status = admin('private.status', id=id_)
        if status['phase'] == expected:
            return status
        time.sleep(.1)
    raise AssertionError('private_phase_not_reached')


def sockets(root):
    return {entry.name: str(entry) for entry in root.rglob('*') if entry.is_socket()}


def closed(root):
    return not any((root / name).exists() for name in ('display', 'home', 'system')) and not sockets(root)


def qualify(root, evidence, faults_only=False):
    with ExitStack() as stack:
        credentials = root / 'credentials'
        provision(credentials)
        token = lambda principal: read_private(credentials / (principal + '.token')).strip()
        manager = Process(stack, [sys.executable, '-B', '-m', 'loopbridge', 'private', '--root',
                                  root / 'private', '--credentials', credentials / 'service.json'])
        check(manager.line() == b'ready\n')
        control = root / 'private/manager.sock'
        with socket.socket(socket.AF_UNIX) as peer:
            peer.connect(str(control))
            remote = RPC(peer)
            denied('denied', remote.call, 'private.start')
            denied('denied', remote.call, 'auth', credential=token('delegate'))
        def admin(method, **params):
            with ExitStack() as request:
                return connect_rpc(request, control, token('owner')).call(method, **params)
        started = time.monotonic()
        a = admin('private.start')
        evidence['stage'] = 'second_private_session'
        b = admin('private.start')
        evidence['startupSeconds'] = round(time.monotonic() - started, 3)
        folders = [root / 'private' / row['id'] for row in (a, b)]
        first, second = folders
        first_ns, second_ns = [json.loads((folder / 'display/boundary.json').read_text()) for folder in folders]
        check(all(first_ns[key] != second_ns[key] for key in first_ns))
        check(all(all(row['namespaces'].values()) for row in (a, b)))
        owner, other = [connect_rpc(stack, row['socket'], token('owner')) for row in (a, b)]
        verify = [owner.call('session.features', **SESSION), other.call('session.features', **SESSION)]
        check([row['privateId'] for row in verify] == [a['id'], b['id']])
        evidence['twoPrivateNamespaces'] = sorted(first_ns)
        if faults_only:
            for capability in ('session.discover', 'workspace.read', 'workspace.write'):
                grant(owner, 'delegate', capability)
            content = b'Private test report.\n'
            lease = writable(owner)
            check(owner.call('workspace.write', **lease, path='fault-report.txt',
                             text=content.decode())['status'] == 'confirmed')
            owner.call('release', **lease)
            qualify_failures(stack, admin, manager.child.pid, a, b, first, second, owner, other,
                             credentials, first_ns['pid'], 'fault-report.txt', content, evidence)
            return

        evidence['stage'] = 'teaching_and_visual'
        for principal in ('observer', 'delegate'):
            grant(owner, principal, 'session.discover')
            for app in ('editor', 'browser'):
                grant(owner, principal, 'desktop.observe', 'app:' + app)
        for app in ('editor', 'browser'):
            for capability in ('app.launch', 'desktop.control', 'app.close'):
                grant(owner, 'delegate', capability, 'app:' + app)
        for cap in ('workspace.read', 'workspace.write'):
            grant(owner, 'delegate', cap, 'workspace')
        grant(owner, 'delegate', 'teach.read', 'app:editor')
        grant(owner, 'observer', 'desktop.capture')

        lease = writable(owner)
        check(owner.call('workspace.write', **lease, path='teaching.txt',
                         text='Disposable teaching context.\n')['status'] == 'confirmed')
        check(owner.call('app.open_document', **lease, app='editor',
                         document='teaching.txt')['status'] == 'confirmed')
        note = element(owner, 'editor', lambda row: row['role'] == 'frame')
        owner.call('teach.create', **SESSION, ref=note['ref'], meaning='document.save',
                   operationHint='page.save', conditions='', warnings='')
        denied('stale_reference', other.call, 'element.inspect', **SESSION, ref=note['ref'])
        denied('stale_lease', other.call, 'workspace.write', **lease, path='forbidden.txt', text='denied')
        check(not (second / 'workspace/forbidden.txt').exists())
        denied('application_not_running', other.call, 'window.list', **SESSION, app='editor')

        evidence['stage'] = 'visual'
        check(capture(a['socket'], token('observer'), DESKTOP_SESSION).startswith(b'\x89PNG'))
        shot = owner.call('session.capture', **SESSION)
        check(shot['privateId'] == a['id'] and shot['mimeType'] == 'image/png')
        png = b''.join(base64.b64decode(owner.call('session.capture.read', **SESSION, ref=shot['ref'],
                                                   index=index)['data'], validate=True)
                       for index in range(shot['chunks']))
        check(png.startswith(b'\x89PNG\r\n\x1a\n') and hashlib.sha256(png).hexdigest() == shot['sha256'])
        evidence['stage'] = 'pointer_move'
        pointer = owner.call('session.pointer.move', **lease, ref=shot['ref'], x=400, y=300)
        check(pointer['status'] == 'confirmed')
        denied('stale_reference', owner.call, 'session.capture.read', **SESSION, ref=shot['ref'], index=0)
        fresh = owner.call('session.capture', **SESSION)
        evidence['stage'] = 'pointer_click'
        click = owner.call('session.pointer.click', **lease, ref=fresh['ref'], x=400, y=300)
        check(click['status'] == 'confirmed')
        denied('stale_reference', other.call, 'session.capture.read', **SESSION, ref=fresh['ref'], index=0)
        evidence['visual'] = dict(width=shot['width'], height=shot['height'], bytes=shot['bytes'],
                                  verifiedDigest=True, move=pointer['evidence']['state'],
                                  click=click['evidence']['state'], staleRefused=True)
        check(owner.call('app.close', **lease, app='editor')['status'] == 'confirmed')
        owner.call('release', **lease)

        evidence['stage'] = 'mcp_mission'
        paths = endpoints()
        listener = stack.enter_context(socket.socket(socket.AF_UNIX))
        listener.bind(b'\0lb6-agent-' + os.urandom(6).hex().encode())
        listener.listen(8)
        paths['abstract_canary'] = listener.getsockname().decode()
        for label, folder in zip(('private', 'sibling'), folders):
            for name, path in sockets(folder / 'display').items():
                paths[label + ':' + name] = path
        paths['sibling_bridge'] = b['socket']
        paths['manager'] = str(control)
        check(all(connect(address)['connected'] for address in paths.values()))
        private_pid = namespaced_process(manager.child.pid, first, 'sway')
        started = time.monotonic()
        runtime = [str(second), str(first / 'workspace'), str(first / 'display')]
        observer_cmd = isolated_command(first, 'observer', paths, private_pid, credentials)
        config = credentials / 'checks.json'
        checks = json.loads(config.read_text())
        checks['private_paths'].extend(runtime)
        config.write_text(json.dumps(checks))
        with Client(observer_cmd) as observer:
            check('session_capture' in observer.tools and 'session_pointer_click' not in observer.tools)
            check(observer.refused('lease_acquire', **SESSION, ttl=15) == 'grant_denied')
            check(observer.refused('workspace_read', **SESSION, path='teaching.txt') == 'grant_denied')
            check(observer.refused('session_pointer_click', **lease, ref=fresh['ref'],
                                   x=400, y=300) == 'grant_denied')
            check(observer.call('session_capture', **SESSION)['privateId'] == a['id'])
        delegate_cmd = isolated_command(first, 'delegate', paths, private_pid, credentials)
        config.write_text(json.dumps(checks))
        mission_evidence = {}
        evidence['mission'] = mission_evidence
        with Client(delegate_cmd, modern=True) as agent:
            check('session_capture' not in agent.tools)
            mission(agent, mission_evidence)
        evidence['mcpSeconds'] = round(time.monotonic() - started, 3)
        report = mission_evidence['report']
        content = (first / 'workspace' / report['path']).read_bytes()
        check(hashlib.sha256(content).hexdigest() == report['sha256'])
        check(not (second / 'workspace' / report['path']).exists())
        evidence['independentDiskRead'] = True
        evidence['clientIsolation'] = dict(endpointAttempts=len(paths), observerDeniedControl=True,
                                           siblingReferenceDenied=True, siblingLeaseDenied=True)

        qualify_failures(stack, admin, manager.child.pid, a, b, first, second, owner, other,
                         credentials, first_ns['pid'], report['path'], content, evidence)


def qualify_failures(stack, admin, pid, a, b, first, second, owner, other,
                     credentials, first_namespace, report_path, content, evidence):
    evidence['stage'] = 'client_exit'
    # This launcher mounts only the selected endpoint and delegate token.
    client = Client([sys.executable, '-B', '-m', 'tools.loopbridge_mcp_sandbox',
                     '--socket', a['socket'], '--token-file', credentials / 'delegate.token'])
    with client as reconnect:
        reconnect.call('lease_acquire', **SESSION, ttl=45)
        reconnect.process.kill()
        reconnect.process.wait(timeout=10)
    deadline = time.monotonic() + 4
    while owner.call('snapshot', **SESSION)['phase'] != 'idle' and time.monotonic() < deadline:
        time.sleep(.05)
    lease = writable(owner)
    owner.call('release', **lease)
    evidence['abruptClientExitReleasedLease'] = True

    evidence['stage'] = 'compositor_exit'
    # Interrupt a real supervised Firefox launch after its journal intent.
    # The transport can disappear before a reply. The durable record decides.
    journal = Journal(second / 'runtime')
    lease = writable(other)
    victim = namespaced_process(pid, second, 'sway')
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(other.call, 'web.open', **lease, app='browser')
        deadline = time.monotonic() + 10
        while not journal.blocked(DESKTOP_SESSION) and not pending.done() and time.monotonic() < deadline:
            time.sleep(.005)
        check(journal.blocked(DESKTOP_SESSION))
        intent = journal.intent(DESKTOP_SESSION)
        os.kill(victim, signal.SIGKILL)
        try:
            status = pending.result(timeout=45)
            check(status['status'] == 'unknown')
            reply = status['status']
        except (EOFError, OSError):
            reply = 'transport_closed'
    status = await_phase(admin, b['id'], 'failed')
    check(status['blocked'] and status['unknownOperation'] == intent)
    check(closed(second) and not Path(f'/proc/{victim}').exists())
    evidence['unexpectedCompositorExit'] = dict(phase=status['phase'], cleanup=True, reply=reply,
                                                 unknownIntentPreserved=True, replayed=False)
    fresh = admin('private.start')
    third = first.parent / fresh['id']
    alternate = connect_rpc(stack, fresh['socket'], read_private(credentials / 'owner.token').strip())
    check(fresh['id'] != b['id'] and not fresh['blocked'] and journal.blocked(DESKTOP_SESSION))
    check(not list((third / 'workspace').iterdir()))
    denied('stale_lease', alternate.call, 'workspace.write', **lease, path='forbidden.txt', text='denied')
    stopped = admin('private.stop', id=fresh['id'])
    check(stopped['phase'] == 'stopped' and stopped['exitCode'] == 0 and closed(third))
    evidence['manualReplacement'] = dict(newWorkspace=True, oldFencePreserved=True, automatic=False)
    evidence['normalShutdown'] = True

    evidence['stage'] = 'worker_exit'
    workers = []
    for candidate, row in process_tree(pid).items():
        if not Path(row[3]).name.startswith('python'):
            continue
        argv = Path(f'/proc/{candidate}/cmdline').read_bytes().split(b'\0')
        if (b'--multiprocessing-fork' in argv
                and os.readlink(f'/proc/{candidate}/ns/pid') == first_namespace):
            workers.append(candidate)
    check(len(workers) == 1)
    os.kill(workers[0], signal.SIGKILL)
    status = await_phase(admin, a['id'], 'failed')
    check(closed(first) and (first / 'workspace' / report_path).read_bytes() == content)
    evidence['unexpectedWorkerExit'] = dict(phase=status['phase'], cleanup=True, reportPreserved=True)
    evidence['stage'] = 'completed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--faults-only', action='store_true')
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix='lb6-'))
    started = time.monotonic()
    evidence = dict(result='PARTIAL', stage='startup', operator='scripted_independent_mcp_client')
    try:
        qualify(root, evidence, faults_only=args.faults_only)
        evidence['result'] = 'GO'
    except (OSError, RuntimeError, AssertionError, ValueError, KeyError, Fault) as error:
        evidence['failure'] = str(error) if isinstance(error, (RuntimeError, Fault)) else type(error).__name__
    finally:
        if any(Journal(folder).blocked(DESKTOP_SESSION) for folder in root.glob('private/*/runtime')):
            shutil.rmtree(root / 'credentials', ignore_errors=True)
            evidence['blockedRootPreserved'] = str(root)
        else:
            shutil.rmtree(root)
    evidence['elapsedSeconds'] = round(time.monotonic() - started, 3)
    with args.evidence.open('x') as file:
        json.dump(evidence, file, indent=2)
        file.write('\n')
    print(evidence['result'], evidence['stage'], evidence.get('failure', ''))
    return int(evidence['result'] != 'GO')


if __name__ == '__main__':
    raise SystemExit(main())
