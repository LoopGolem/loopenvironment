# SPDX-License-Identifier: Apache-2.0
"""Transport integration and deterministic dispatch failure tests."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

from loopbridge.__main__ import provision, read_private
from loopbridge.adapter import Fixture, Unavailable
from loopbridge.authority import TARGET
from loopbridge.broker import Broker, Connection
from loopbridge.identity import Identities
from loopbridge.protocol import Fault, RPC
from loopbridge.service import Journal, SESSION, serve


def invocation(session, lease, snapshot):
    return dict(session=session, lease=lease['id'], epoch=lease['epoch'],
                generation=lease['generation'], reference=snapshot['element']['reference'])


def grant(call, capability, principal='delegate', session=SESSION, ttl=60):
    return call('delegate', session=session, principal=principal,
                capability=capability, ttl=ttl, target=TARGET)['grant']


class CoreIntegration(unittest.TestCase):
    def test_service_fixture_over_unix_socket(self):
        with ExitStack() as stack:
            folder = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='lb-test-')))
            provision(folder / 'credentials')
            credential_file = folder / 'credentials/service.json'
            self.assertEqual(stat.S_IMODE(credential_file.stat().st_mode), 0o600)
            credentials = {name: read_private(credential_file.with_name(name + '.token')).strip()
                           for name in ('owner', 'delegate', 'observer')}
            identities = Identities()
            identities.load(credentials)
            runtime = folder / 'runtime'
            proc = stack.enter_context(subprocess.Popen(
                [sys.executable, '-B', '-m', 'loopbridge', 'serve', '--runtime', runtime,
                 '--credentials', credential_file, '--mode', 'fixture'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE))
            stack.callback(self.stop, proc)
            self.assertEqual(proc.stdout.readline(), b'ready\n')
            endpoint = runtime / 'socket/control.sock'
            self.assertEqual(stat.S_IMODE(endpoint.stat().st_mode), 0o600)
            with self.assertRaises(BlockingIOError), serve(runtime, identities, 'fixture'):
                self.fail('second service acquired the same runtime')

            def client():
                sock = stack.enter_context(socket.socket(socket.AF_UNIX))
                sock.connect(str(endpoint))
                return RPC(sock).call

            anonymous = client()
            with self.assertRaisesRegex(Fault, '^denied$'):
                anonymous('auth', credential='invalid')
            with self.assertRaisesRegex(Fault, '^denied$'):
                anonymous('discover')
            owner, delegate, observer = client(), client(), client()
            for principal, call in [('owner', owner), ('delegate', delegate), ('observer', observer)]:
                self.assertEqual(call('auth', credential=credentials[principal])['principal'], principal)
            with self.assertRaisesRegex(Fault, '^grant_denied$'):
                observer('discover')
            grant(owner, 'session.discover', 'observer')
            grant(owner, 'desktop.observe', 'observer')
            grant(owner, 'desktop.observe')
            control = grant(owner, 'desktop.control')
            self.assertEqual(observer('discover')['sessions'], [SESSION])
            self.assertEqual(observer('capabilities', session=SESSION)['capabilities'],
                             ['desktop.observe', 'session.discover'])
            with self.assertRaisesRegex(Fault, '^grant_denied$'):
                observer('acquire', session=SESSION, ttl=10)
            observed = observer('snapshot', session=SESSION)
            lease = delegate('acquire', session=SESSION, ttl=15)
            with self.assertRaisesRegex(Fault, '^control_busy$'):
                owner('acquire', session=SESSION, ttl=15)
            snap = delegate('snapshot', session=SESSION)
            params = invocation(SESSION, lease, snap)
            with self.assertRaisesRegex(Fault, '^grant_denied$'):
                observer('invoke7', **params)
            result = delegate('invoke7', **params)
            self.assertEqual(result['status'], 'confirmed')
            self.assertEqual(result['evidence'], {'source': 'fixture_query', 'state': {'display': '7'}})
            events = observer('events', session=SESSION, epoch=observed['epoch'], cursor=observed['cursor'])
            self.assertIn('operation.confirmed', [e['kind'] for e in events['events']])
            self.assertEqual(observer('snapshot', session=SESSION)['state'], {'display': '7'})
            with self.assertRaisesRegex(Fault, '^stale_reference$'):
                delegate('invoke7', **params)
            owner('revoke', session=SESSION, grant=control)
            with self.assertRaisesRegex(Fault, '^grant_denied$'):
                delegate('invoke7', **params)
            audit = owner('audit', session=SESSION)['entries']
            self.assertTrue(any(entry['outcome'] == 'confirmed' for entry in audit))
            self.assertTrue(all(token not in json.dumps(audit) for token in credentials.values()))
            self.stop(proc)
            self.assertEqual(proc.returncode, 0)
            self.assertFalse(endpoint.exists())
            self.assertEqual(proc.stderr.read(), b'')

    @staticmethod
    def stop(proc):
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


class LocalAdapter(Fixture):
    def __init__(self):
        super().__init__()
        self.prepared = None
        self.dispatches = 0
        self.fail_send = False
        self.after_prepare = lambda: None
        self.after_send = lambda: None

    def call(self, method, argument=None):
        if method == 'prepare':
            self.prepared = self.prepare(*argument)
            self.after_prepare()
        elif method == 'send':
            self.dispatches += 1
            self.send(self.prepared)
            self.after_send()
            if self.fail_send:
                raise Unavailable
        elif method == 'confirm':
            return self.confirm(self.prepared)
        elif method == 'snapshot':
            state, ref = self.snapshot()
            return state, (ref, state)


class AuthorityFailures(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='lb-test-')
        self.addCleanup(folder.cleanup)
        self.journal = Journal(Path(folder.name))
        self.adapter = LocalAdapter()
        self.adapters = {SESSION: self.adapter, 'other': LocalAdapter()}
        self.now = 100
        self.identities = Identities()
        self.credentials = self.identities.provision()
        self.broker = self.new_broker()
        self.owner = self.client('owner')
        self.connection = Connection(os.getuid())
        self.delegate = self.client('delegate', self.connection)
        self.control = grant(self.owner, 'desktop.control')
        grant(self.owner, 'desktop.observe')

    def new_broker(self):
        return Broker(self.identities, self.adapters, os.getuid(), self.journal, lambda: self.now)

    def client(self, principal, connection=None):
        if connection is None:
            connection = Connection(os.getuid())

        def call(method, **params):
            return self.broker.handle(connection, method, params)

        call('auth', credential=self.credentials[principal])
        return call

    def prepare(self, session=SESSION, ttl=30):
        lease = self.delegate('acquire', session=session, ttl=ttl)
        return invocation(session, lease, self.delegate('snapshot', session=session))

    def test_reference_expiry_and_generation(self):
        params = self.prepare()
        self.now += 10
        with self.assertRaisesRegex(Fault, '^stale_reference$'):
            self.delegate('invoke7', **params)
        self.delegate('release', **{k: v for k, v in params.items() if k != 'reference'})
        fresh = self.prepare()
        with self.assertRaisesRegex(Fault, '^stale_reference$'):
            self.delegate('invoke7', **{**fresh, 'reference': params['reference']})
        self.assertEqual(self.adapter.dispatches, 0)

    def test_cross_session_reference(self):
        original = self.prepare()
        grant(self.owner, 'desktop.control', session='other')
        grant(self.owner, 'desktop.observe', session='other')
        lease = self.delegate('acquire', session='other', ttl=30)
        with self.assertRaisesRegex(Fault, '^stale_reference$'):
            self.delegate('invoke7', session='other', lease=lease['id'], epoch=lease['epoch'],
                          generation=lease['generation'], reference=original['reference'])
        self.assertEqual(self.adapters['other'].dispatches, 0)

    def test_grant_expiry_during_preparation(self):
        self.adapter.after_prepare = lambda: setattr(self, 'now', 160)
        params = self.prepare(ttl=100)
        with self.assertRaisesRegex(Fault, '^grant_denied$'):
            self.delegate('invoke7', **params)
        self.assertEqual(self.adapter.dispatches, 0)
        self.assertFalse(self.journal.blocked(SESSION))

    def test_disconnect_before_dispatch_releases_lease(self):
        self.connection.alive = lambda: False
        params = self.prepare()
        with self.assertRaisesRegex(Fault, '^dispatch_fenced$'):
            self.delegate('invoke7', **params)
        self.broker.disconnect(self.connection)
        self.assertEqual(self.adapter.dispatches, 0)
        self.assertFalse(self.journal.blocked(SESSION))
        self.owner('acquire', session=SESSION, ttl=30)

    def test_timeout_returns_unknown_and_survives_reboot_of_service(self):
        self.adapter.fail_send = True
        reply = self.delegate('invoke7', **self.prepare())
        self.assertEqual(reply['status'], 'unknown')
        self.assertIsNone(reply['evidence']['state'])
        self.assertTrue(self.journal.blocked(SESSION))
        self.assertEqual(self.adapter.value, '7')
        self.assertEqual(self.adapter.dispatches, 1)
        with self.assertRaisesRegex(Fault, '^control_busy$'):
            self.owner('acquire', session=SESSION, ttl=30)
        self.broker = self.new_broker()
        self.owner = self.client('owner')
        self.assertEqual(self.owner('snapshot', session=SESSION)['phase'], 'blocked')
        with self.assertRaisesRegex(Fault, '^control_busy$'):
            self.owner('acquire', session=SESSION, ttl=30)

    def test_disconnect_after_dispatch_blocks_even_with_late_effect(self):
        self.adapter.after_send = lambda: setattr(self.connection, 'alive', lambda: False)
        self.assertEqual(self.delegate('invoke7', **self.prepare())['status'], 'unknown')
        self.broker.disconnect(self.connection)
        self.assertTrue(self.journal.blocked(SESSION))
        self.assertEqual(self.owner('snapshot', session=SESSION)['phase'], 'blocked')
        self.assertEqual(self.adapter.dispatches, 1)

    def test_revocation_while_preparing_fences_submission(self):
        started, resume = threading.Event(), threading.Event()

        def prepare():
            started.set()
            if not resume.wait(5):
                raise Unavailable

        self.adapter.after_prepare = prepare
        params = self.prepare()
        outcomes = []

        def invoke():
            try:
                self.delegate('invoke7', **params)
            except Fault as error:
                outcomes.append(error.message)

        thread = threading.Thread(target=invoke)
        thread.start()
        try:
            self.assertTrue(started.wait(5))
            self.owner('revoke', session=SESSION, grant=self.control)
            with self.assertRaisesRegex(Fault, '^control_busy$'):
                self.owner('acquire', session=SESSION, ttl=30)
        finally:
            resume.set()
            thread.join(5)
        self.assertEqual(outcomes, ['grant_denied'])
        self.assertEqual(self.adapter.dispatches, 0)
        self.owner('acquire', session=SESSION, ttl=30)

    def test_events_gap_requires_new_snapshot(self):
        snapshot = self.delegate('snapshot', session=SESSION)
        for _ in range(9):
            grant(self.owner, 'desktop.observe')
        for denial in ('gap_snapshot_required', 'snapshot_required'):
            with self.assertRaisesRegex(Fault, '^' + denial + '$'):
                self.delegate('events', session=SESSION, epoch=snapshot['epoch'], cursor=snapshot['cursor'])
        snapshot = self.delegate('snapshot', session=SESSION)
        self.assertEqual(self.delegate('events', session=SESSION, epoch=snapshot['epoch'],
                                       cursor=snapshot['cursor'])['events'], [])


if __name__ == '__main__':
    unittest.main()
