# SPDX-License-Identifier: Apache-2.0
"""Exercise V0.2 with independent Bubblewrap clients and real applications."""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

from .loopbridge_demo import Process, check, connect, endpoints, launch, read_private
from loopbridge.service import DESKTOP_SESSION, Journal

SESSION = {'session': DESKTOP_SESSION}
REPORT = 'LoopBridge V0.2\nSemantic editing through an authorized client.\n'
BUFFER = REPORT.removesuffix('\n')


def grant(owner, principal, capability, target='*'):
    return owner.call('delegate', **SESSION, principal=principal, capability=capability,
                      target=target, ttl=175)['grant']


def writable(client):
    lease = client.call('acquire', **SESSION, ttl=175)
    return dict(**SESSION, lease=lease['id'], generation=lease['generation'], epoch=lease['epoch'])


def semantic_elements(client, app, partial=None):
    window = client.call('window.list', **SESSION, app=app)['windows'][0]
    check(window['semantic'] == 'correlated')
    offset = 0
    while offset is not None:
        page = client.call('element.tree', **SESSION, ref=window['ref'], offset=offset, depth=40)
        if partial is not None:
            partial.extend((item['role'], item['name'], item['actions']) for item in page['elements']
                           if item['name'] or item['actions'])
        yield from page['elements']
        offset = page['next']


def element(client, app, predicate):
    return next(item for item in semantic_elements(client, app) if predicate(item))


def perform(report, stack, root, workspace, server, paths):
    clients = {}
    report['isolation'] = {}
    for name in ('owner', 'delegate', 'observer', 'invalid'):
        token = (read_private(root / 'credentials' / (name + '.token')).strip()
                 if name != 'invalid' else 'invalid')
        client, probes, auth = launch(stack, root / 'runtime/socket', paths, token, server.child.pid,
                                      private_paths=(str(workspace), str(root / 'credentials')), version='0.2')
        if name == 'invalid':
            check(auth == {'error': 'denied'})
            check(client.child.wait(timeout=5) == 1)
        else:
            check(auth['result']['principal'] == name)
            clients[name] = client
        report['isolation'][name] = dict(denied_endpoints=sorted(probes['endpoints']),
                                         denied_devices=len(probes['devices']),
                                         private_namespaces=probes['private_namespaces'],
                                         private_paths_denied=probes['private_paths_denied'],
                                         no_inherited_sockets=probes['inherited_socket_count'] == 0)
    owner, delegate, observer = (clients[name] for name in ('owner', 'delegate', 'observer'))
    report['stage'] = 'grants'
    for principal in ('delegate', 'observer'):
        grant(owner, principal, 'session.discover')
        grant(owner, principal, 'desktop.observe', 'app:editor')
    for app in ('editor', 'calculator', 'files', 'browser'):
        grant(owner, 'delegate', 'desktop.observe', 'app:' + app)
        grant(owner, 'delegate', 'app.launch', 'app:' + app)
    editor_control = grant(owner, 'delegate', 'desktop.control', 'app:editor')
    grant(owner, 'delegate', 'desktop.control', 'app:calculator')
    grant(owner, 'delegate', 'workspace.read', 'workspace')
    grant(owner, 'delegate', 'workspace.write', 'workspace')
    observer.denied('grant_denied', 'acquire', **SESSION, ttl=30)
    check([app['app'] for app in observer.call('app.list', **SESSION)['applications']] == ['editor'])
    report['catalog'] = delegate.call('app.list', **SESSION)['applications']
    write = writable(delegate)

    report['stage'] = 'workspace_seed'
    check(delegate.call('workspace.write', **write, path='report.txt', text='')['status'] == 'confirmed')
    proof = 'Verified workspace write\n'
    result = delegate.call('workspace.write', **write, path='workspace-proof.txt', text=proof)
    check(result['status'] == 'confirmed')
    check(delegate.call('workspace.read', **SESSION, path='workspace-proof.txt')['text'] == proof)
    check((workspace / 'workspace-proof.txt').read_text() == proof)
    report['workspace_write_sha256'] = hashlib.sha256(proof.encode()).hexdigest()
    refused = delegate.call('workspace.write', **write, path='../outside.txt', text='denied')
    check(refused['status'] == 'refused' and not (root / 'outside.txt').exists())
    report['workspace_traversal_refused'] = True
    observer.denied('grant_denied', 'workspace.read', **SESSION, path='report.txt')
    report['stage'] = 'editor_launch'
    result = delegate.call('app.launch', **write, app='editor')
    report['editor_launch'] = result['status']
    check(result['status'] == 'confirmed')
    check(delegate.call('operation.status', **SESSION, operation=result['operation'])['status'] == 'confirmed')
    report['stage'] = 'editor_edit'
    editor = element(delegate, 'editor', lambda item: item['editable'] and 'multi_line' in item['state'])
    check(delegate.call('element.set_text', **write, ref=editor['ref'], text=BUFFER)['status'] == 'confirmed')
    observed = element(observer, 'editor', lambda item: item['editable'] and 'multi_line' in item['state'])
    check(observer.call('element.get_text', **SESSION, ref=observed['ref'])['text'] == BUFFER)
    observer.denied('grant_denied', 'element.set_text', **write, ref=observed['ref'], text='denied')
    report['editor'] = dict(scope='editor', observed_edit=True, observer_mutation_denied=True)

    report['stage'] = 'editor_save'
    frame = element(delegate, 'editor', lambda item: item['role'] == 'frame')
    actions = delegate.call('element.actions', **SESSION, ref=frame['ref'])
    if 'page.save' in actions['actions']:
        result = delegate.call('element.invoke', **write, ref=frame['ref'], action='page.save')
        report['editor']['save'] = result.get('reason', result['status'])
        if result['status'] == 'unknown':
            report['editor']['ui_file_verified'] = (workspace / 'report.txt').read_text() == REPORT
            report['editor']['session_blocked'] = delegate.call('snapshot', **SESSION)['phase'] == 'blocked'
            return
    else:
        report['editor']['save'] = 'save_action_not_exposed'
    report['editor']['ui_file_verified'] = (
        delegate.call('workspace.read', **SESSION, path='report.txt')['text'] == REPORT
        and (workspace / 'report.txt').read_text() == REPORT)
    if report['editor']['ui_file_verified']:
        report['editor']['file_sha256'] = hashlib.sha256((workspace / 'report.txt').read_bytes()).hexdigest()
    if not report['editor']['ui_file_verified']:
        result = delegate.call('workspace.write', **write, path='verified.txt', text=REPORT)
        check(result['status'] == 'confirmed' and (workspace / 'verified.txt').read_text() == REPORT)
        report['editor']['separate_workspace_write_verified'] = True

    report['stage'] = 'revoke'
    owner.call('revoke', **SESSION, grant=editor_control)
    write = writable(delegate)
    editor = element(delegate, 'editor', lambda item: item['editable'] and 'multi_line' in item['state'])
    delegate.denied('grant_denied', 'element.set_text', **write, ref=editor['ref'], text='denied')
    report['revocation_verified'] = True

    report['stage'] = 'calculator'
    check(delegate.call('app.launch', **write, app='calculator')['status'] == 'confirmed')
    seven = element(delegate, 'calculator', lambda item: item['name'] == '7' and 'click' in item['actions'])
    result = delegate.call('element.invoke', **write, ref=seven['ref'], action='click')
    check(result['status'] == 'confirmed' and result['evidence']['state']['display'] == '7')
    report['calculator'] = 'confirmed'
    refused = delegate.call('app.launch', **write, app='browser')
    check(refused.get('reason') == 'launch_unsupported')
    report['browser'] = refused['reason']
    report['stage'] = 'file_manager'
    result = delegate.call('app.launch', **write, app='files')
    report['file_manager'] = result.get('reason', result['status'])
    if result['status'] == 'confirmed':
        deadline = time.monotonic() + 5
        while True:
            delegate.send(dict(method='window.list', params=dict(**SESSION, app='files')))
            reply = json.loads(delegate.line())
            if 'error' in reply:
                check(reply['error'] == 'target_unavailable')
                report['file_manager_observation'] = reply['error']
            observed = reply.get('result', {}).get('windows', [])
            report['file_manager_semantic'] = [row['semantic'] for row in observed]
            if observed and observed[0]['ref']:
                delegate.send(dict(method='element.tree', params=dict(
                    **SESSION, ref=observed[0]['ref'], offset=0, depth=8)))
                reply = json.loads(delegate.line())
                report['file_manager_tree'] = ('confirmed' if reply.get('result', {}).get('elements')
                                               else reply.get('error', 'no_elements'))
                if report['file_manager_tree'] == 'confirmed':
                    break
            if time.monotonic() >= deadline:
                break
            time.sleep(.25)
        report['running_together'] = sorted(app['app'] for app in
                                           delegate.call('app.list', **SESSION)['applications']
                                           if app['state'] == 'running')
        check(report['running_together'] == ['calculator', 'editor', 'files'])
    report['stage'] = 'shutdown'
    for client in clients.values():
        client.child.stdin.close()
        check(client.child.wait(timeout=5) == 0)
    server.child.terminate()
    check(server.child.wait(timeout=20) == 0)
    check(not (root / 'runtime/socket/control.sock').exists())
    report['stage'] = 'completed'
    report['result'] = 'GO' if report['editor']['ui_file_verified'] else 'PARTIAL'


def demo(report):
    import os
    import shutil
    with ExitStack() as stack:
        report['stage'] = 'baseline'
        paths = endpoints()
        canary = stack.enter_context(socket.socket(socket.AF_UNIX))
        canary.bind(b'\0loopbridge-v02-' + os.urandom(8).hex().encode())
        canary.listen(8)
        paths['abstract_canary'] = canary.getsockname().decode()
        check(all(connect(paths[key])['connected'] for key in
                  ('sway', 'wayland', 'session_bus', 'atspi_bus', 'abstract_canary')))
        root = Path(tempfile.mkdtemp(prefix='lb2-'))
        def cleanup():
            if Journal(root / 'runtime').blocked(DESKTOP_SESSION):
                shutil.rmtree(root / 'credentials', ignore_errors=True)
                report['blocked_runtime_preserved'] = True
            else:
                shutil.rmtree(root)
        stack.callback(cleanup)
        workspace = root / 'workspace'
        workspace.mkdir(mode=0o700)
        subprocess.run([sys.executable, '-B', '-m', 'loopbridge', 'provision', root / 'credentials'],
                       check=True, timeout=5)
        report['stage'] = 'startup'
        server = Process(stack, [sys.executable, '-B', '-m', 'loopbridge', 'serve',
                                '--runtime', root / 'runtime', '--workspace', workspace,
                                '--credentials', root / 'credentials/service.json'])
        check(server.line() == b'ready\n')
        report['stage'] = 'isolation'
        perform(report, stack, root, workspace, server, paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    report = dict(result='PARTIAL')
    try:
        demo(report)
    except Exception as error:
        report['failure'] = type(error).__name__
    with args.evidence.open('x') as output:
        print(json.dumps(report, indent=2), file=output)
    print(report['result'], report.get('stage'))
    return int(report['result'] != 'GO')


if __name__ == '__main__':
    raise SystemExit(main())
