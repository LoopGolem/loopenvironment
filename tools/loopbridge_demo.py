# SPDX-License-Identifier: Apache-2.0
"""Reproduce LoopBridge V0.1 with isolated external Calculator clients."""
import argparse
from contextlib import ExitStack
import glob
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]

# Reuse the historical OS probes only in the demonstration harness.
from experiments.m1_2.isolation import command, namespaces
from experiments.m1_2.probe import connect
from experiments.m1_2.run import endpoints
from loopbridge.__main__ import read_private
from loopbridge.authority import TARGET
from loopbridge.service import SESSION


def check(condition):
    if not condition:
        raise AssertionError('demo_check_failed')


class Process:
    def __init__(self, stack, command, **options):
        self.child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, close_fds=True, **options)
        stack.callback(self.close)

    def close(self):
        self.child.stdin.close()
        if self.child.poll() is None:
            try:
                self.child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.child.terminate()
                try:
                    self.child.wait(timeout=40)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                    self.child.wait()
        self.child.stdout.close()

    def send(self, data):
        self.child.stdin.write(json.dumps(data).encode() + b'\n')
        self.child.stdin.flush()

    def line(self, timeout=45):
        deadline = time.monotonic() + timeout
        data = bytearray()
        while len(data) < 16384:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.child.stdout], [], [], remaining)[0]:
                break
            part = os.read(self.child.stdout.fileno(), 1)
            if not part:
                break
            data.extend(part)
            if part == b'\n':
                return data
        raise RuntimeError('child_response_unavailable')

    def call(self, method, **params):
        self.send(dict(method=method, params=params))
        result = json.loads(self.line())
        check(set(result) == {'result'})
        return result['result']

    def denied(self, denial, method, **params):
        self.send(dict(method=method, params=params))
        check(json.loads(self.line()) == {'error': denial})


def launch(stack, folder, paths, token, broker_pid):
    args = command(folder)
    historical = str(ROOT / 'experiments/m1_2')
    mount = args.index(historical)
    args[mount - 1:mount + 2] = [
        '--ro-bind', str(ROOT / 'loopbridge'), '/app/loopbridge',
        '--ro-bind', str(ROOT / 'tools/loopbridge_isolated_client.py'), '/app/client.py',
        '--ro-bind', historical + '/probe.py', '/app/probe.py',
    ]
    # Deliberately open an inheritable compositor FD. close_fds must exclude it.
    with socket.socket(socket.AF_UNIX) as sentinel:
        sentinel.connect(paths['sway'])
        sentinel.set_inheritable(True)
        client = Process(stack, args, env={'PATH': '/usr/bin'})
    client.send(dict(credential=token, endpoints=paths, host_ns=namespaces(),
                     broker_pid=broker_pid, devices=sorted(set(
                         glob.glob('/dev/input/event*') + glob.glob('/dev/dri/*') +
                         glob.glob('/dev/video*') + ['/dev/uinput']))))
    probes = json.loads(client.line())
    auth = json.loads(client.line())
    return client, probes, auth


def independent_display():
    import pyatspi

    from loopbridge.calculator import correlate, sway, texts, unique, windows

    pyatspi.setTimeout(1000, 2000)
    records = windows(sway('get_tree'))
    record = unique([w for w in records if w['app_id'] == 'org.gnome.Calculator'],
                    'calculator_missing_or_ambiguous')
    _, _, frame = correlate(records, list(pyatspi.Registry.getDesktop(0)), record['pid'])
    return texts(frame)


def clean_demo(root, report):
    if (root / 'runtime' / (SESSION + '.pending')).exists():
        # Preserve the protected runtime and its fence after an uncertain action.
        shutil.rmtree(root / 'credentials')
        report['blocked_runtime'] = str(root / 'runtime')
    else:
        shutil.rmtree(root)


def demo(report):
    with ExitStack() as stack:
        report['stage'] = 'session_baseline'
        paths = endpoints()
        canary = stack.enter_context(socket.socket(socket.AF_UNIX))
        canary.bind(b'\0loopbridge-demo-' + os.urandom(8).hex().encode())
        canary.listen(4)
        paths['abstract_canary'] = canary.getsockname().decode()
        report['baseline'] = {k: connect(v)['connected'] for k, v in paths.items()}
        check(all(report['baseline'][k] for k in
                  ('sway', 'wayland', 'session_bus', 'atspi_bus', 'abstract_canary')))
        root = Path(tempfile.mkdtemp(prefix='lb-'))
        stack.callback(clean_demo, root, report)
        credentials, runtime = root / 'credentials', root / 'runtime'
        subprocess.run([sys.executable, '-m', 'loopbridge', 'provision', credentials],
                       check=True, close_fds=True, timeout=5)
        report['stage'] = 'service_start'
        server = Process(stack, [sys.executable, '-m', 'loopbridge', 'serve',
                                '--runtime', runtime, '--credentials', credentials / 'service.json'])
        check(server.line() == b'ready\n')
        report['stage'] = 'client_isolation_and_authentication'
        clients = {}
        secrets = []
        report['probes'] = {}
        for principal in ('owner', 'delegate', 'observer', 'invalid'):
            token = (read_private(credentials / (principal + '.token')).strip()
                     if principal != 'invalid' else 'invalid')
            if principal != 'invalid':
                secrets.append(token)
            client, probes, auth = launch(stack, runtime / 'socket', paths, token, server.child.pid)
            if principal == 'invalid':
                check(auth == {'error': 'denied'})
                check(client.child.wait(timeout=5) == 1)
            else:
                check(auth['result']['principal'] == principal)
                clients[principal] = client
            report['probes'][principal] = probes

        report['stage'] = 'delegation_and_calculator'
        owner, delegate, observer = (clients[p] for p in ('owner', 'delegate', 'observer'))
        for principal in ('delegate', 'observer'):
            for capability in ('session.discover', 'desktop.observe'):
                owner.call('delegate', session=SESSION, principal=principal,
                           capability=capability, target=TARGET, ttl=90)
        grant = owner.call('delegate', session=SESSION, principal='delegate',
                           capability='desktop.control', target=TARGET, ttl=90)['grant']
        check(observer.call('discover')['sessions'] == [SESSION])
        check(observer.call('capabilities', session=SESSION)['capabilities'] ==
              ['desktop.observe', 'session.discover'])
        observer.denied('grant_denied', 'acquire', session=SESSION, ttl=20)
        initial = observer.call('snapshot', session=SESSION)
        check(initial['state'] == independent_display())
        lease = delegate.call('acquire', session=SESSION, ttl=30)
        old = delegate.call('snapshot', session=SESSION)
        snap = delegate.call('snapshot', session=SESSION)
        params = dict(session=SESSION, lease=lease['id'], generation=lease['generation'],
                      epoch=lease['epoch'], reference=snap['element']['reference'])
        delegate.denied('stale_reference', 'invoke7', **{**params, 'reference': old['element']['reference']})
        result = delegate.call('invoke7', **params)
        display = independent_display()
        check(result['status'] == 'confirmed' and '7' in display.values())
        check(result['evidence'] == dict(source='atspi_query', state=display))
        check(observer.call('snapshot', session=SESSION)['state'] == display)
        observer.denied('grant_denied', 'invoke7', **params)
        delegate.denied('stale_reference', 'invoke7', **params)
        owner.call('revoke', session=SESSION, grant=grant)
        delegate.denied('grant_denied', 'invoke7', **params)
        delegate.denied('grant_denied', 'acquire', session=SESSION, ttl=20)
        check(independent_display() == display)
        report['calculator'] = dict(before=initial['state'], independently_verified=display)
        report['audit'] = owner.call('audit', session=SESSION)['entries']
        check(all(token not in json.dumps(report) for token in secrets))
        report['stage'] = 'service_shutdown'
        for client in clients.values():
            client.child.stdin.close()
            check(client.child.wait(timeout=5) == 0)
        server.child.terminate()
        check(server.child.wait(timeout=15) == 0)
        check(not (runtime / 'socket/control.sock').exists())
        report['stage'] = 'completed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    report = {'result': 'PARTIAL'}
    try:
        demo(report)
    except Exception as error:
        report['failure'] = type(error).__name__
    else:
        report['result'] = 'GO'
    if args.evidence:
        with args.evidence.open('x') as stream:
            print(json.dumps(report, indent=2), file=stream)
    print(report['result'], report.get('stage'))
    return int(report['result'] != 'GO')


if __name__ == '__main__':
    raise SystemExit(main())
