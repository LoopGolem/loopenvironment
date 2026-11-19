# SPDX-License-Identifier: Apache-2.0
"""Real V0.4 browser, workspace, editor and GTK teaching qualification."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from .loopbridge_demo import Process, check, connect, endpoints, launch, read_private
from .loopbridge_desktop_demo import SESSION, element, grant, writable
from loopbridge.service import DESKTOP_SESSION, Journal

NAME = 'Sample Operator'
REPORT = 'LoopBridge V0.4\nReport saved using a recovered annotation.'
APP = 'editor'


def run_gui(root, endpoint, review=False):
    # This process renders its own GTK window. It talks to Bridge about the
    # editor exclusively through the observer's authenticated socket.
    result = subprocess.run([sys.executable, '-B', '-m', 'loopbridge', 'teach-gui',
                             '--demo-review' if review else '--demo', '--socket', endpoint, '--token-file',
                             root / 'credentials/observer.token'],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=65, check=True,
                            env={**os.environ, 'GDK_BACKEND': 'wayland'})
    value = json.loads(result.stdout)
    check(value['toolkit'] == 'GTK4' and value['visible_window'])
    return value if review else value['annotation']['id']


def files_and_teaching(report, owner, worker, observer, write, root, workspace):
    report['stage'] = 'workspace'
    mkdir = worker.call('workspace.mkdir', **write, path='drafts')
    check(mkdir['status'] == 'confirmed')
    initial = worker.call('workspace.write', **write, path='drafts/initial.txt', text='Draft.\n')
    check(initial['status'] == 'confirmed')
    listing = worker.call('workspace.list_at', **SESSION, directory='drafts', offset=0)
    check(listing['entries'] == [dict(name='initial.txt', kind='file')])
    renamed = worker.call('workspace.rename', **write, source='drafts/initial.txt',
                          destination='drafts/report.txt')
    check(renamed['status'] == 'confirmed')
    check((workspace / 'drafts/report.txt').read_text() == 'Draft.\n')
    check(not (workspace / 'drafts/initial.txt').exists())
    report['workspace'] = dict(mkdir=mkdir['status'], rename=renamed['status'], independent=True,
                               verifier=renamed['evidence']['state']['verifier'])
    report['stage'] = 'nautilus'
    directory = worker.call('app.open_directory', **write, app='files', directory='drafts')
    report['nautilus'] = dict(status=directory['status'], evidence=directory.get('evidence', {}).get('state'))
    if directory['status'] == 'unknown':
        raise RuntimeError('directory_launch_unknown')
    if directory['status'] == 'confirmed':
        worker.send(dict(method='window.list', params=dict(**SESSION, app='files')))
        observed = json.loads(worker.line()).get('result', {}).get('windows', [])
        if observed and observed[0]['ref']:
            worker.send(dict(method='element.find', params=dict(**SESSION, ref=observed[0]['ref'],
                             role='', name='', interface='Selection', action='')))
            draft = json.loads(worker.line())
            matches = draft.get('result', {})
            report['nautilus']['selection_probe'] = matches.get('reason', matches.get('status', draft.get('error')))
            if matches.get('status') == 'matched':
                report['nautilus']['selection_role'] = matches['element']['role']
        else:
            report['nautilus']['selection_probe'] = 'accessible_window_unavailable'

    report['stage'] = 'editor_open'
    opened = worker.call('app.open_document', **write, app=APP, document='drafts/report.txt')
    check(opened['status'] == 'confirmed')
    before = worker.call('window.list', **SESSION, app=APP)['windows'][0]
    old = element(observer, APP, lambda row: row['role'] == 'frame')
    report['stage'] = 'gtk_teacher'
    ident = run_gui(root, root / 'runtime/socket/control.sock')
    show = worker.call('teach.search', **SESSION, app=APP, query='document.save', revision=1, offset=0)
    check(len(show['annotations']) == 1 and show['annotations'][0]['id'] == ident)
    observer.denied('grant_denied', 'acquire', **SESSION, ttl=25)

    check(worker.call('app.close', **write, app=APP)['status'] == 'confirmed')
    observer.denied('stale_reference', 'element.inspect', **SESSION, ref=old['ref'])
    check(worker.call('app.open_document', **write, app=APP,
                      document='drafts/report.txt')['status'] == 'confirmed')
    after = worker.call('window.list', **SESSION, app=APP)['windows'][0]
    check((before['pid'], before['process_start']) != (after['pid'], after['process_start']))
    first = worker.call('teach.resolve', **SESSION, ref=after['ref'], annotation=ident)
    check(first['status'] == 'matched' and first['element']['ref'] != old['ref'])
    report['gtk_teacher'] = dict(toolkit='GTK4', widget_events='scripted', role='observer',
                                 match=first['matchQuality'], provenance=first['provenance'],
                                 criteria=first['criteria'], fresh_process=True, stale_ref_refused=True)

    report['stage'] = 'desktop_boundaries'
    observer_window = observer.call('window.list', **SESSION, app=APP)['windows'][0]
    observer.denied('grant_denied', 'desktop.capture', **SESSION, ref=observer_window['ref'])
    worker.denied('window_capture_unavailable', 'desktop.capture', **SESSION, ref=after['ref'])
    observer.denied('grant_denied', 'input.key', **write, ref=observer_window['ref'], key='Return')
    unavailable = worker.call('input.key', **write, ref=after['ref'], key='Return')
    check(unavailable['status'] == 'refused' and unavailable['reason'] == 'target_bound_input_unavailable')
    report['capture_input'] = dict(capture_without_grant='denied', capture_with_grant='unavailable',
                                   target_bound_input='unavailable')

    report['stage'] = 'editor_save'
    field = element(worker, APP, lambda row: row['editable'] and 'multi_line' in row['state'])
    check(worker.call('element.set_text', **write, ref=field['ref'], text=REPORT)['status'] == 'confirmed')
    new_window = worker.call('window.list', **SESSION, app=APP)['windows'][0]
    found = worker.call('teach.resolve', **SESSION, ref=new_window['ref'], annotation=ident)
    check(found['status'] == 'matched')
    result = worker.call('element.invoke', **write, ref=found['element']['ref'],
                         action=found['annotation']['annotation']['operationHint'])
    check(result['status'] == 'confirmed')
    reading = (workspace / 'drafts/report.txt').read_bytes()
    check(reading == (REPORT + '\n').encode())
    report['editor'] = dict(saved=True, independent=True, sha256=hashlib.sha256(reading).hexdigest())
    owner.call('delegate', **SESSION, principal='observer', capability='teach.read',
               target='app:editor', ttl=1)
    check(len(observer.call('teach.search', **SESSION, app=APP, query='document.save',
                            revision=0, offset=0)['annotations']) == 1)
    time.sleep(1.05)
    observer.denied('grant_denied', 'teach.search', **SESSION, app=APP, query='document.save',
                    revision=0, offset=0)
    report['expired_grant_denied'] = True


def browser_demo(report, worker, observer, write):
    report['stage'] = 'browser_start'
    result = worker.call('browser.open_fixture', **write, app='browser')
    report['browser'] = dict(launch=result['status'], verification=result.get('evidence', {}).get('state'))
    check(result['status'] == 'confirmed')
    window = worker.call('window.list', **SESSION, app='browser')['windows'][0]
    check(worker.call('browser.document', **SESSION, ref=window['ref'])['page'] == 'form')

    report['stage'] = 'browser_protected'
    protected = element(worker, 'browser', lambda row: row['role'] == 'password text')
    worker.denied('protected_element', 'element.get_text', **SESSION, ref=protected['ref'])
    report['browser']['protected_text_denied'] = True

    report['stage'] = 'browser_text'
    found = worker.call('element.find', **SESSION, ref=window['ref'], role='entry', name='Demo name',
                        interface='EditableText', action='')
    report['browser']['field_discovery'] = found.get('reason', found['status'])
    check(found['status'] == 'matched')
    field = found['element']
    result = worker.call('element.set_text', **write, ref=field['ref'], text=NAME)
    report['browser']['text'] = result.get('reason', result['status'])
    check(result['status'] == 'confirmed')

    report['stage'] = 'browser_selection'
    radio = element(worker, 'browser', lambda row: row['name'] == 'Beta' and row['role'] == 'radio button')
    actions = worker.call('element.actions', **SESSION, ref=radio['ref'])['actions']
    choice = next(action for action in actions if action in ('click', 'select', 'press', 'activate'))
    result = worker.call('element.invoke', **write, ref=radio['ref'], action=choice)
    report['browser']['selection'] = result.get('reason', result['status'])
    check(result['status'] == 'confirmed')

    report['stage'] = 'browser_submit'
    button = element(worker, 'browser', lambda row: row['name'] == 'Submit demo')
    actions = worker.call('element.actions', **SESSION, ref=button['ref'])['actions']
    submit = next(action for action in actions if action in ('click', 'select', 'press', 'activate'))
    result = worker.call('element.invoke', **write, ref=button['ref'], action=submit)
    report['browser']['submit'] = result.get('reason', result['status'])
    check(result['status'] == 'confirmed')
    window = observer.call('window.list', **SESSION, app='browser')['windows'][0]
    observed = observer.call('browser.document', **SESSION, ref=window['ref'])
    check(observed == dict(page='receipt', fields=dict(name=NAME, category='beta'), source='atspi_document'))
    report['browser']['readback'] = observed
    report['browser']['independent_observer'] = True


def run(report, browser_only):
    with ExitStack() as stack:
        report['stage'] = 'baseline'
        paths = endpoints()
        canary = stack.enter_context(socket.socket(socket.AF_UNIX))
        canary.bind(b'\0loopbridge-v04-' + os.urandom(8).hex().encode())
        canary.listen(8)
        paths['abstract_canary'] = canary.getsockname().decode()
        check(all(connect(paths[key])['connected'] for key in
                  ('sway', 'wayland', 'session_bus', 'atspi_bus', 'abstract_canary')))
        root = Path(tempfile.mkdtemp(prefix='lb4-'))

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
        server = Process(stack, [sys.executable, '-B', '-m', 'loopbridge', 'serve',
                                 '--runtime', root / 'runtime', '--workspace', workspace,
                                 '--credentials', root / 'credentials/service.json'])
        check(server.line() == b'ready\n')
        clients = {}
        report['isolation'] = {}
        for principal in ('owner', 'delegate', 'observer'):
            token = read_private(root / 'credentials' / (principal + '.token')).strip()
            client, probe, auth = launch(stack, root / 'runtime/socket', paths, token, server.child.pid,
                                          (str(workspace), str(root / 'credentials')), version='0.4')
            check(auth['result']['principal'] == principal)
            clients[principal] = client
            report['isolation'][principal] = dict(denied_endpoints=len(probe['endpoints']),
                                                  denied_private_paths=probe['private_paths_denied'],
                                                  namespaces=probe['private_namespaces'])
        owner, worker, observer = (clients[name] for name in ('owner', 'delegate', 'observer'))
        for principal in ('delegate', 'observer'):
            grant(owner, principal, 'session.discover')
        for capability in ('app.launch', 'desktop.observe', 'desktop.control'):
            grant(owner, 'delegate', capability, 'app:browser')
        grant(owner, 'observer', 'desktop.observe', 'app:browser')
        if not browser_only:
            for capability in ('app.launch', 'app.close', 'desktop.observe', 'desktop.control',
                               'desktop.capture', 'desktop.input', 'teach.read'):
                grant(owner, 'delegate', capability, 'app:editor')
            for capability in ('app.launch', 'desktop.observe'):
                grant(owner, 'delegate', capability, 'app:files')
            for capability in ('workspace.read', 'workspace.write'):
                grant(owner, 'delegate', capability, 'workspace')
            for capability in ('desktop.observe', 'teach.write'):
                grant(owner, 'observer', capability, 'app:editor')
        write = writable(worker)
        if not browser_only:
            files_and_teaching(report, owner, worker, observer, write, root, workspace)
        browser_demo(report, worker, observer, write)
        server.child.terminate()
        check(server.child.wait(timeout=20) == 0)
        report.update(result='GO', stage='completed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-only', action='store_true')
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    report = dict(result='PARTIAL', browser_only=args.browser_only)
    try:
        run(report, args.browser_only)
    except Exception as error:
        report['failure'] = type(error).__name__
    with args.evidence.open('x') as stream:
        print(json.dumps(report, indent=2), file=stream)
    print(report['result'], report.get('stage'))
    return int(report['result'] != 'GO')


if __name__ == '__main__':
    raise SystemExit(main())
