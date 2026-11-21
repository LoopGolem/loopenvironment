# SPDX-License-Identifier: Apache-2.0
"""D4.2C fixtures using the installed manager and broker RPC contracts."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import threading
from unittest.mock import Mock, patch

from loopbridge import service_admin as admin, service_smoke as smoke
from loopbridge.identity import Identities
from loopbridge.presentation import Presentation
from loopbridge.presentation_client import LiveConnection
from loopbridge.private_session import Instance, NS, handle, manager_socket
from loopbridge.protocol import Fault, RPC
from loopbridge.service import serve
from loopbridge.service_bootstrap import VerifierRegistry
from loopbridge.service_ingress import peer_uid
from test_trusted_service_d42a import ServiceFixture
from tools.loopbridge_d42c_probe import check_ingress, ingress_rpc


class SmokeFixture(ServiceFixture):
    def setUp(self):
        super().setUp()
        self.seed()
        self.registry = VerifierRegistry(self.state)
        self.registry.enroll_manager(self.manifest)
        (self.state / 'sessions').mkdir(mode=0o700)
        self.instances = {}
        self.session_manifests = []
        self.enterContext(patch.object(Instance, 'start_desktop', autospec=True,
                                       side_effect=self.start_desktop))

        def relay_peer(sock):
            if Path(sock.getsockname()).parent == self.ingress:
                return self.client_uid
            return peer_uid(sock)

        self.enterContext(patch('loopbridge.service_relay.peer_uid', side_effect=relay_peer))
        adapter = self.enterContext(patch('loopbridge.service.Adapter')).return_value
        adapter.source = 'synthetic'
        adapter.call.return_value = {'calculator': 'mapped'}
        listener = self.enterContext(manager_socket(self.runtime, self.runtime / 'manager.sock',
                                                    hardened=True))
        executor = self.enterContext(ThreadPoolExecutor(1))
        stop = threading.Event()

        def run():
            while not stop.is_set():
                try:
                    peer, _ = listener.accept()
                except TimeoutError:
                    continue
                with peer:
                    handle(peer, self.runtime, self.identities, self.instances, self.manifest, True,
                           set(), hardened=self.profile, registry=self.registry)
            for instance in self.instances.values():
                instance.stop()

        future = executor.submit(run)
        self.addCleanup(future.result, 5)
        self.addCleanup(stop.set)

    def start_desktop(self, instance, manifest):
        identities = Identities()
        identities.load_manifest(manifest)
        self.session_manifests.append(manifest)
        instance.ingress.enter_context(serve(
            instance.runtime, identities, 'desktop', instance.workspace,
            presentation=Presentation(instance.id, '/usr/bin/true'), session_state=instance.state))
        instance.checks = dict.fromkeys(NS, True)
        instance.process = Mock()
        instance.process.poll.return_value = None
        instance.process.wait.return_value = 0

    def admin(self, operation, **params):
        return smoke.smoke(self.runtime, self.ingress, self.tokens['owner'],
                           os.getuid(), os.getgid(), operation, **params)

    def observer(self):
        identity = Identities()
        token = identity.provision()['observer']
        return token, identity.manifest()['verifiers']['observer']

    def test_start_observe_stop_and_replace(self):
        token, verifier = self.observer()
        first = self.admin('start', observer_verifier=verifier)
        first_id = first['privateId']
        self.assertEqual(set(first), {'session', 'privateId', 'epoch', 'ingressSocket', 'grantTtlSeconds'})
        self.assertEqual(self.session_manifests[0]['verifiers']['observer'], verifier)
        self.assertNotIn(hashlib.sha256(self.tokens['owner'].encode()).hexdigest(),
                         self.session_manifests[0]['verifiers'].values())
        self.assertEqual(self.admin('list'), {'instances': [{'id': first_id, 'phase': 'ready'}]})
        endpoint = Path(first['ingressSocket'])
        first_report = check_ingress(endpoint, os.getuid(), token, first_id, first['epoch'])
        self.assertEqual(first_report['event'], 'control.released')
        self.assertNotIn('administrativeRpcDenied', first_report)
        self.assertEqual(self.admin('stop', session_id=first_id),
                         {'id': first_id, 'phase': 'stopped', 'retired': True})
        self.assertFalse(endpoint.exists())
        self.assertFalse((self.runtime / first_id).exists())
        self.assertTrue((self.state / 'sessions' / first_id / 'workspace').is_dir())
        self.assertEqual(self.admin('list'), {'instances': []})
        with self.assertRaisesRegex(Fault, 'reused_session_verifier'):
            self.admin('start', observer_verifier=verifier)

        new_token, new_verifier = self.observer()
        second = self.admin('start', observer_verifier=new_verifier)
        for key in ('privateId', 'epoch', 'ingressSocket'):
            self.assertNotEqual(first[key], second[key])
        report = check_ingress(second['ingressSocket'], os.getuid(), new_token, second['privateId'],
                               second['epoch'], prior_token=token)
        self.assertTrue(report['priorBearerDenied'])
        self.assertTrue(report['administrativeRpcDenied'])
        self.assertTrue(report['wrongPinDenied'])
        self.admin('stop', session_id=second['privateId'])

    def test_failure_after_start_stops_only_that_instance_and_retires_verifier(self):
        _, verifier = self.observer()
        with patch.object(smoke, 'seed_presentation', side_effect=ValueError('fixture failed')):
            with self.assertRaisesRegex(ValueError, 'fixture failed'):
                self.admin('start', observer_verifier=verifier)
        self.assertEqual(self.admin('list'), {'instances': []})
        self.assertFalse(list(self.ingress.iterdir()))
        self.assertEqual(len(list((self.state / 'sessions').iterdir())), 1)
        self.assertIn(verifier, VerifierRegistry(self.state).used)

    def test_does_not_start_over_existing_instance_or_stop_without_exact_id(self):
        _, verifier = self.observer()
        started = self.admin('start', observer_verifier=verifier)
        _, next_verifier = self.observer()
        with self.assertRaisesRegex(ValueError, 'smoke_requires_empty_manager'):
            self.admin('start', observer_verifier=next_verifier)
        with self.assertRaisesRegex(ValueError, 'invalid_smoke_arguments'):
            self.admin('stop', session_id='../manager.sock')
        self.assertTrue(Path(started['ingressSocket']).is_socket())
        self.assertNotIn(next_verifier, VerifierRegistry(self.state).used)

    def test_unconfirmed_start_can_be_listed_and_stopped_explicitly(self):
        _, verifier = self.observer()
        original = RPC.call

        def lose_start_result(rpc, method, **params):
            result = original(rpc, method, **params)
            if method == 'private.start':
                raise EOFError
            return result

        with patch.object(RPC, 'call', lose_start_result), self.assertRaises(EOFError):
            self.admin('start', observer_verifier=verifier)
        active, = self.admin('list')['instances']
        self.assertEqual(active['phase'], 'ready')
        self.assertEqual(self.admin('stop', session_id=active['id'])['phase'], 'stopped')
        self.assertEqual(self.admin('list'), {'instances': []})

    def test_viewer_rejects_wrong_kernel_peer_before_sending_bearer(self):
        token, verifier = self.observer()
        started = self.admin('start', observer_verifier=verifier)
        viewer = LiveConnection(started['ingressSocket'], token, started['session'],
                                started['privateId'], started['epoch'], expected_peer_uid=self.client_uid)
        with viewer.peer, self.assertRaisesRegex(ValueError, 'unexpected_presentation_peer'):
            viewer.connect()
        with ingress_rpc(started['ingressSocket'], os.getuid()) as rpc:
            with self.assertRaisesRegex(Fault, '^denied$'):
                rpc.call('auth', credential=self.tokens['owner'])

    def test_root_required_before_reading_bootstrap(self):
        with (patch.object(admin.os, 'geteuid', return_value=1000),
              patch.object(admin, 'checked_owner_data') as read):
            with self.assertRaisesRegex(ValueError, 'root_administration_required'):
                smoke.admin_smoke(Path('/unused'), 'a' * 64, 980, 980, 'list', None, None)
        read.assert_not_called()
