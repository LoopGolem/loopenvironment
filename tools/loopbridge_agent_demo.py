# SPDX-License-Identifier: Apache-2.0
"""Provision and qualify an independent MCP client against the real desktop."""
import argparse
from contextlib import ExitStack
import glob
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

from .loopbridge_demo import (ROOT, Process, check, command, connect, endpoints,
                              launch, namespaces, read_private)
from .loopbridge_desktop_demo import SESSION, grant, writable
from .loopbridge_practical_demo import run_gui
from loopbridge.service import DESKTOP_SESSION, Journal


def isolated_command(root, principal, paths, pid):
    folder = root / 'runtime/socket'
    sandbox = command(folder)
    historical = str(ROOT / 'experiments/m1_2')
    mount = sandbox.index(historical)
    private = (str(root / 'workspace'), str(root / 'credentials'), str(root / 'runtime'))
    checks = root / 'credentials/checks.json'
    checks.write_text(json.dumps(dict(endpoints=paths, host_ns=namespaces(), broker_pid=pid,
                                     private_paths=private, devices=sorted(set(
                                         glob.glob('/dev/input/event*') + glob.glob('/dev/dri/*')
                                         + glob.glob('/dev/video*') + ['/dev/uinput'])))))
    sandbox[mount - 1:mount + 2] = [
        '--ro-bind', str(ROOT / 'loopbridge'), '/app/loopbridge',
        '--ro-bind', str(ROOT / 'tools/mcp_isolated.py'), '/app/client.py',
        '--ro-bind', historical + '/probe.py', '/app/probe.py',
        '--ro-bind', str(checks), '/identity/checks.json',
        '--ro-bind', str(root / 'credentials' / (principal + '.token')), '/identity/token',
    ]
    return sandbox


def run_client(root, principal, paths, server):
    args = [sys.executable, '-B', '-m', 'tools.mcp_mission']
    if principal == 'observer':
        args.append('--observer')
    args += ['--', *isolated_command(root, principal, paths, server.child.pid)]
    result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=140, check=False)
    return json.loads(result.stdout)


def run(evidence, seed):
    with ExitStack() as stack:
        evidence['stage'] = 'baseline'
        paths = endpoints()
        listener = stack.enter_context(socket.socket(socket.AF_UNIX))
        listener.bind(b'\0lb5-agent-' + os.urandom(6).hex().encode())
        listener.listen(8)
        paths['abstract_canary'] = listener.getsockname().decode()
        check(all(connect(paths[key])['connected'] for key in
                  ('sway', 'wayland', 'session_bus', 'atspi_bus', 'abstract_canary')))
        root = Path(tempfile.mkdtemp(prefix='lb5-'))
        def cleanup():
            if Journal(root / 'runtime').blocked(DESKTOP_SESSION):
                shutil.rmtree(root / 'credentials', ignore_errors=True)
                evidence['blocked_runtime_preserved'] = True
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
        endpoint = root / 'runtime/socket/control.sock'
        owner, probes, auth = launch(stack, endpoint.parent, paths,
            read_private(root / 'credentials/owner.token').strip(), server.child.pid,
            (str(workspace), str(root / 'credentials')))
        check(auth['result']['principal'] == 'owner')
        evidence['isolation'] = dict(endpoints_denied=len(probes['endpoints']),
                                     namespaces=probes['private_namespaces'])
        for principal in ('delegate', 'observer'):
            grant(owner, principal, 'session.discover')
            grant(owner, principal, 'desktop.observe', 'app:editor')
            grant(owner, principal, 'desktop.observe', 'app:browser')
        for app in ('editor', 'browser'):
            for capability in ('app.launch', 'desktop.control', 'app.close'):
                grant(owner, 'delegate', capability, 'app:' + app)
        for capability in ('workspace.read', 'workspace.write'):
            grant(owner, 'delegate', capability, 'workspace')
        for capability in ('teach.write', 'teach.read', 'teach.review'):
            grant(owner, 'observer', capability, 'app:editor')
        grant(owner, 'delegate', 'teach.read', 'app:editor')
        evidence['stage'] = 'teach_seed'
        lease = writable(owner)
        check(owner.call('workspace.write', **lease, path='teaching.txt', text='Disposable teaching context.\n')['status']=='confirmed')
        check(owner.call('app.open_document', **lease, app='editor', document='teaching.txt')['status']=='confirmed')
        if seed == 'gtk':
            created = run_gui(root, endpoint)
            reviewed = run_gui(root, endpoint, review=True)
            annotation = reviewed['annotation']
            check(annotation['id'] == created and annotation['revision'] == 3
                  and annotation['reviewState'] == 'approved' and reviewed['matchQuality'] == 'exact')
            evidence['gtk_teacher'] = dict(toolkit='GTK4', input=reviewed['input'],
                                           revision=annotation['revision'], review='approved',
                                           match=reviewed['matchQuality'])
        else:
            from .loopbridge_desktop_demo import element
            note = element(owner, 'editor', lambda row: row['role'] == 'frame')
            owner.call('teach.create', **SESSION, ref=note['ref'], meaning='document.save',
                       operationHint='page.save', conditions='', warnings='')
        check(owner.call('app.close', **lease, app='editor')['status']=='confirmed')
        owner.call('release', **lease)
        evidence['stage'] = 'grant_expiry'
        owner.call('delegate', **SESSION, principal='observer', capability='workspace.read',
                   target='workspace', ttl=1)
        time.sleep(1.05)
        evidence['observer'] = run_client(root, 'observer', paths, server)
        check(evidence['observer']['result'] == 'GO')
        evidence['stage'] = 'mcp_mission'
        evidence['mission'] = run_client(root, 'delegate', paths, server)
        check(evidence['mission']['result'] == 'GO')
        report = evidence['mission']['report']
        content = (workspace / report['path']).read_bytes()
        check(hashlib.sha256(content).hexdigest() == report['sha256'])
        check(b'Harbor sensor' in content and b'Harbor gateway' in content and b'South' not in content)
        check(not (root / 'outside.txt').exists())
        evidence['independent_disk_verification'] = True
        server.child.terminate()
        check(server.child.wait(timeout=30) == 0)
        evidence.update(result='GO', stage='completed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--seed', choices=('gtk', 'rpc'), default='gtk')
    args = parser.parse_args()
    start = time.monotonic()
    evidence = dict(result='PARTIAL', teacher=args.seed)
    try:
        run(evidence, args.seed)
    except Exception as error:
        evidence['failure'] = type(error).__name__
    evidence['elapsed_seconds'] = round(time.monotonic() - start, 3)
    with args.evidence.open('x') as stream:
        print(json.dumps(evidence, indent=2), file=stream)
    print(evidence['result'], evidence.get('stage'))
    return int(evidence['result'] != 'GO')


if __name__ == '__main__':
    raise SystemExit(main())
