# SPDX-License-Identifier: Apache-2.0
"""One Calculator, three isolated identities plus unenrolled client. Finite lab run."""
import argparse
from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
import platform
import select
import secrets
import socket
import subprocess
import tempfile
import time

from experiments.m1_1 import semantic as m1
from experiments.m1_2.isolation import command, namespaces
from experiments.m1_2.probe import connect
from experiments.m1_2.run import endpoints
from experiments.m1_3a.adapter import Calculator
from experiments.m1_3a.authority import TARGET
from experiments.m1_3a.broker import Broker, Server
from experiments.m1_3a.identity import Identities


class CheckFailed(Exception):
    pass


def check(condition):
    if not condition:
        raise CheckFailed


class Client:
    def __init__(self, folder, credential, paths):
        # Reuse the M1.2 isolation profile verbatim, replacing only the entrypoint
        # and adding the new client source in a read-only mount.
        args = command(folder)
        source = Path(__file__).resolve().parent
        args[-1] = '/m13/client.py'
        args[1:1] = ['--ro-bind', str(source), '/m13']
        # Deliberately inheritable real Sway descriptor must NOT reach the child.
        sentinel = socket.socket(socket.AF_UNIX)
        try:
            sentinel.connect(paths['sway'])
            sentinel.set_inheritable(True)
            self.child = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, close_fds=True, env={'PATH': '/usr/bin'})
        finally:
            sentinel.close()
        config = dict(credential=credential, endpoints=paths, host_ns=namespaces(), broker_pid=os.getpid(),
                      devices=sorted(set(glob.glob('/dev/input/event*') + glob.glob('/dev/dri/*') +
                                         glob.glob('/dev/video*') + ['/dev/uinput'])))
        self.send(config)

    def send(self, value):
        self.child.stdin.write(json.dumps(value).encode() + b'\n')
        self.child.stdin.flush()

    def receive(self):
        # No unbounded readline from a failed/malicious child.
        data = bytearray()
        deadline = time.monotonic() + 40
        while len(data) < 32768:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.child.stdout], [], [], remaining)[0]:
                raise CheckFailed
            byte = os.read(self.child.stdout.fileno(), 1)
            if not byte:
                raise CheckFailed
            data.extend(byte)
            if byte == b'\n':
                return json.loads(data)
        raise CheckFailed

    def call(self, method, **params):
        self.send(dict(method=method, params=params))
        return self.receive()

    def ok(self, method, **params):
        value = self.call(method, **params)
        check('result' in value)
        return value['result']

    def denied(self, method, expected, **params):
        value = self.call(method, **params)
        check(value == dict(error=expected))
        return value['error']

    def close(self):
        self.child.stdin.close()
        try:
            self.child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.child.terminate()
            self.child.wait(timeout=3)
        for stream in (self.child.stdout, self.child.stderr):
            stream.close()


def execute(report, secret_guard=None):
    report['stage'] = 'session_baseline'
    paths = endpoints()
    report['baseline'] = {k: connect(v) for k, v in paths.items()}
    check(all(report['baseline'][k]['connected'] for k in ('sway', 'wayland', 'session_bus', 'atspi_bus')))
    canary = socket.socket(socket.AF_UNIX)
    adapter, clients = None, []
    try:
        canary.bind('\0m13a-' + secrets.token_hex(12))
        canary.listen(4)
        paths['abstract_canary'] = canary.getsockname().decode()
        report['baseline']['abstract_canary'] = connect(paths['abstract_canary'])
        report['stage'] = 'fixture_readiness'
        adapter = Calculator()
        f = adapter.fixture
        report['fixture'] = dict(window=f.window, atspi_pid=f.app.get_process_id(),
                                 executable=f.identity[3], start_ticks=f.identity[1])
        identities = Identities()
        credentials = identities.provision()
        if secret_guard is not None:
            secret_guard.extend(credentials.values())
        broker = Broker(identities, {'S': adapter}, os.getuid())
        with tempfile.TemporaryDirectory(prefix='m13a-') as folder:
            os.chmod(folder, 0o700)
            with socket.socket(socket.AF_UNIX) as listener:
                endpoint = str(Path(folder) / 'control.sock')
                listener.bind(endpoint)
                os.chmod(endpoint, 0o600)
                listener.listen(8)
                with Server(broker, listener):
                    def launch(principal):
                        client = Client(folder, credentials.get(principal, ''), paths)
                        clients.append(client)
                        ready = client.receive()
                        report['clients'][principal] = {**ready, 'auth':
                            {k: v for k, v in ready.get('auth', {}).items() if k != 'connection'}}
                        check(ready.get('auth', {}).get('principal') == principal if principal != 'unenrolled'
                              else ready.get('auth') == dict(denied='denied'))
                        return client
                    report['stage'] = 'owner_delegation'
                    owner = launch('owner')
                    grants = {}
                    for principal, caps in [('delegate', ('desktop.observe', 'desktop.control')),
                                             ('observer', ('desktop.observe',))]:
                        for cap in caps:
                            grants[principal, cap] = owner.ok('delegate', session='S', principal=principal,
                                                              capability=cap, target=TARGET, ttl=120)['grant']
                    report['stage'] = 'independent_clients'
                    delegate, observer, unenrolled = [launch(p) for p in ('delegate', 'observer', 'unenrolled')]
                    report['negative'] = {}
                    neg = report['negative']
                    neg['unenrolled_read'] = unenrolled.denied('snapshot', 'denied', session='S')
                    neg['unenrolled_write'] = unenrolled.denied('invoke7', 'denied', session='S', lease='x',
                                                               epoch='x', generation=0, reference='x')
                    neg['observer_control'] = observer.denied('acquire', 'grant_denied', session='S', ttl=10)
                    neg['delegate_admin'] = delegate.denied('delegate', 'grant_denied', session='S',
                        principal='delegate', capability='identity.admin', target='*', ttl=10)
                    neg['spoofed_identity'] = delegate.denied('snapshot', 'invalid_params', session='S', role='owner', human=True)
                    report['stage'] = 'authorized_semantic_operation'
                    initial = delegate.ok('snapshot', session='S')['state']
                    check(all(v in ('', '0') for v in initial.values()))
                    lease = delegate.ok('acquire', session='S', ttl=30)
                    snap = delegate.ok('snapshot', session='S')
                    p = dict(session='S', lease=lease['id'], generation=lease['generation'], epoch=lease['epoch'],
                             reference=snap['reference'])
                    response = delegate.ok('invoke7', **p)
                    check(response['confirmed'])
                    # Fresh discovery and broad text query, separate from adapter.confirm.
                    _, _, frame = m1.discover(f.process, f.desktop)
                    independent = m1.texts(frame)
                    check('7' in independent.values())
                    observed = observer.ok('snapshot', session='S')['state']
                    check(observed == independent)
                    neg['observer_write'] = observer.denied('invoke7', 'grant_denied', **p)
                    neg['reference_replay'] = delegate.denied('invoke7', 'stale_reference', **p)
                    report['stage'] = 'revocation'
                    before_revoke = delegate.ok('snapshot', session='S')
                    p['reference'] = before_revoke['reference']
                    owner.ok('revoke', session='S', grant=grants['delegate', 'desktop.control'])
                    neg['revoked_write'] = delegate.denied('invoke7', 'grant_denied', **p)
                    neg['revoked_acquire'] = delegate.denied('acquire', 'grant_denied', session='S', ttl=10)
                    # Observe remains independently granted after control revocation.
                    after = delegate.ok('snapshot', session='S')['state']
                    _, _, frame = m1.discover(f.process, f.desktop)
                    final = m1.texts(frame)
                    check(after == final == independent)
                    report['application'] = dict(initial=initial, independently_verified=independent,
                                                 observer=observed, after_denials=final,
                                                 denied_operations_state_unchanged=True)
                    report['audit'] = list(broker.audit)
                    # Credentials are never copied to evidence. Scan in-memory evidence
                    # before writing, including the independent client's diagnostics.
                    encoded = json.dumps(report)
                    check(not any(c in encoded for c in credentials.values()))
                    report['secrets_scan'] = 'no_provisioned_credentials'
                    for client in clients:
                        client.close()
                        check(client.child.returncode == 0)
                    clients.clear()
        report['stage'] = 'completed'
        report['result'] = 'GO'
    finally:
        for client in clients:
            client.close()
        canary.close()
        if adapter:
            adapter.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    report = dict(result='PARTIAL', started=datetime.now(timezone.utc).isoformat(), clients={},
                  base_commit='76d5504af535d17e94030b7471ca89c18fcff09c',
                  environment=dict(python=platform.python_version(), kernel=platform.release()),
                  scope='M1.3A real Calculator and isolated identities only; takeover is unit simulation')
    secret_guard = []
    with args.evidence.open('x') as output:
        try:
            execute(report, secret_guard)
        except Exception as error:
            report['result'] = 'NO-GO' if isinstance(error, (CheckFailed, AssertionError)) else 'PARTIAL'
            report['failure'] = type(error).__name__  # Never raw exception/payload/credential.
        if any(c in json.dumps(report) for c in secret_guard):
            report = dict(result='NO-GO', stage='evidence_rejected', failure='sensitive_output_removed')
        json.dump(report, output, indent=2)
        output.write('\n')
    print(report['result'], report['stage'])
    return 0 if report['result'] == 'GO' else 1


if __name__ == '__main__':
    raise SystemExit(main())
