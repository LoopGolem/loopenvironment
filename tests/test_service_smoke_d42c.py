# SPDX-License-Identifier: Apache-2.0
"""D4.2C fixtures using the installed manager and broker RPC contracts."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import hashlib
from io import BytesIO, StringIO
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from loopbridge import service_admin as admin, service_smoke as smoke
from loopbridge.identity import Identities
from loopbridge.presentation import Presentation
from loopbridge.presentation_client import LiveConnection
from loopbridge.private_session import Instance, NS, handle, inside, manager_socket, wait_ready
from loopbridge.protocol import Fault, RPC
from loopbridge.service import serve
from loopbridge.service_bootstrap import VerifierRegistry
from loopbridge.service_diagnostics import Diagnostic, Phase
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
        with self.assertRaisesRegex(Diagnostic, 'phase=start_rejected cleanup=not_attempted'):
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
            with self.assertRaisesRegex(Diagnostic, 'phase=presentation cleanup=confirmed'):
                self.admin('start', observer_verifier=verifier)
        self.assertEqual(self.admin('list'), {'instances': []})
        self.assertFalse(list(self.ingress.iterdir()))
        self.assertEqual(len(list((self.state / 'sessions').iterdir())), 1)
        self.assertIn(verifier, VerifierRegistry(self.state).used)

    def test_does_not_start_over_existing_instance_or_stop_without_exact_id(self):
        _, verifier = self.observer()
        started = self.admin('start', observer_verifier=verifier)
        _, next_verifier = self.observer()
        with self.assertRaisesRegex(Diagnostic, 'phase=manager_not_empty cleanup=not_attempted'):
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

        with (patch.object(RPC, 'call', lose_start_result),
              self.assertRaisesRegex(Diagnostic, 'phase=start_reply_lost cleanup=unconfirmed')):
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
            with self.assertRaisesRegex(Diagnostic, 'phase=admin_bootstrap cleanup=not_attempted'):
                smoke.admin_smoke(Path('/unused'), 'a' * 64, 980, 980, 'list', None, None)
        read.assert_not_called()

    def test_startup_failure_has_distinct_phase_over_manager_rpc(self):
        _, verifier = self.observer()
        failure = OSError('private path and synthetic bearer')
        with (patch.object(Instance, 'start_desktop', side_effect=failure),
              self.assertRaisesRegex(Diagnostic, 'phase=desktop_startup cleanup=confirmed') as error):
            self.admin('start', observer_verifier=verifier)
        self.assertNotIn(str(failure), str(error.exception))
        self.assertEqual(self.admin('list'), {'instances': []})
        self.assertFalse(list(self.ingress.iterdir()))
        self.assertIn(verifier, VerifierRegistry(self.state).used)
        self.assertEqual(len(list((self.state / 'sessions').iterdir())), 1)

    def test_registry_failure_is_reported_without_starting_an_instance(self):
        _, verifier = self.observer()
        with (patch.object(self.registry, 'reserve_session', side_effect=OSError('private path')),
              self.assertRaisesRegex(Diagnostic, 'phase=state_prepare cleanup=not_attempted')):
            self.admin('start', observer_verifier=verifier)
        self.assertFalse(list((self.state / 'sessions').iterdir()))
        self.assertEqual(self.admin('list'), {'instances': []})

    def test_manager_retains_startup_phase_when_its_own_cleanup_fails(self):
        _, verifier = self.observer()
        with (patch.object(Instance, 'start_desktop', side_effect=OSError('private subprocess')),
              patch.object(Instance, 'stop', side_effect=OSError('private path')),
              self.assertRaisesRegex(Diagnostic, 'phase=desktop_startup cleanup=unconfirmed')):
            self.admin('start', observer_verifier=verifier)
        (state,) = (self.state / 'sessions').iterdir()
        self.assertTrue((self.runtime / state.name).is_dir())
        self.assertIn(verifier, VerifierRegistry(self.state).used)

    def test_legacy_manager_error_cannot_be_attributed_to_startup_or_relay(self):
        _, verifier = self.observer()
        original = RPC.call

        def legacy_start_error(rpc, method, **params):
            if method == 'private.start':
                raise Fault(-32006, 'private_session_failed')
            return original(rpc, method, **params)

        with (patch.object(RPC, 'call', legacy_start_error),
              patch.object(smoke, 'stop_instance') as stop,
              self.assertRaisesRegex(Diagnostic, 'phase=manager_start_unclassified cleanup=unconfirmed')):
            self.admin('start', observer_verifier=verifier)
        stop.assert_not_called()

    def test_broker_failures_report_the_phase_and_preserve_retired_state(self):
        original = RPC.call
        phases = {'presentation.describe': 'presentation', 'acquire': 'control_acquire',
                  'app.launch': 'calculator', 'delegate': 'grants', 'release': 'control_release'}
        for failed_method, phase in phases.items():
            with self.subTest(method=failed_method):
                token, verifier = self.observer()
                message = f'{token} {verifier} /private/workspace'

                def fail_phase(rpc, method, **params):
                    if method == failed_method:
                        raise Fault(-32006, message)
                    return original(rpc, method, **params)

                with (patch.object(RPC, 'call', fail_phase),
                      self.assertRaisesRegex(Diagnostic, f'phase={phase} cleanup=confirmed') as error):
                    self.admin('start', observer_verifier=verifier)
                self.assertEqual(str(error.exception), f'loopbridge: phase={phase} cleanup=confirmed')
                self.assertEqual(self.admin('list'), {'instances': []})
                self.assertFalse(list(self.ingress.iterdir()))
                self.assertIn(verifier, VerifierRegistry(self.state).used)
        self.assertEqual(len(list((self.state / 'sessions').iterdir())), len(phases))

    def test_unconfirmed_calculator_result_does_not_reach_grants(self):
        _, verifier = self.observer()
        original = RPC.call
        methods = []

        def refuse_calculator(rpc, method, **params):
            methods.append(method)
            if method == 'app.launch':
                return {'status': 'unknown', 'evidence': 'private effect payload'}
            return original(rpc, method, **params)

        with (patch.object(RPC, 'call', refuse_calculator),
              self.assertRaisesRegex(Diagnostic, 'phase=calculator cleanup=confirmed')):
            self.admin('start', observer_verifier=verifier)
        self.assertNotIn('delegate', methods)
        self.assertEqual(self.admin('list'), {'instances': []})

    def test_rollback_failure_preserves_original_phase_and_reports_uncertainty(self):
        _, verifier = self.observer()
        with (patch.object(smoke, 'seed_presentation', side_effect=Diagnostic(Phase.CALCULATOR)),
              patch.object(smoke, 'stop_instance', side_effect=EOFError),
              self.assertRaisesRegex(Diagnostic, 'phase=calculator cleanup=unconfirmed')):
            self.admin('start', observer_verifier=verifier)
        active, = self.admin('list')['instances']
        with (patch.object(smoke, 'stop_instance', side_effect=EOFError),
              self.assertRaisesRegex(Diagnostic, 'phase=cleanup cleanup=unconfirmed')):
            self.admin('stop', session_id=active['id'])
        self.admin('stop', session_id=active['id'])


class DiagnosticTransportTests(unittest.TestCase):
    def test_supervisor_reports_broker_readiness_failure_and_terminates_children(self):
        compositor, bridge = Mock(), Mock()
        text = StringIO()
        with (patch('loopbridge.private_session.protect_process'),
              patch('loopbridge.private_session.executable_helper', return_value=True),
              patch('loopbridge.private_session.signal.signal'),
              patch('loopbridge.private_session.sys.stdin', SimpleNamespace(buffer=BytesIO(b'{}\n'))),
              patch('loopbridge.private_session.subprocess.Popen', side_effect=[compositor, bridge]),
              patch('loopbridge.private_session.inherited_display', return_value={}),
              patch('loopbridge.private_session.wait_ready', side_effect=RuntimeError('private child trace')),
              patch('loopbridge.private_session.terminate') as terminate,
              redirect_stdout(text)):
            self.assertEqual(inside(hardened=True), 1)
        self.assertEqual(text.getvalue(), 'error:desktop_broker\n')
        self.assertEqual([call.args for call in terminate.call_args_list], [(bridge,), (compositor,)])
        with TemporaryDirectory() as root:
            for record, phase in ((b'error:desktop_broker\n', Phase.DESKTOP_BROKER),
                                  (b'error:desktop_boundary\n', Phase.DESKTOP_BOUNDARY),
                                  (b'error:private child trace\n', None)):
                path = Path(root) / 'readiness'
                path.write_bytes(record)
                with path.open('rb') as output:
                    with self.assertRaises(RuntimeError) as failure:
                        wait_ready(SimpleNamespace(stdout=output), time.monotonic() + 1, diagnostics=True)
                self.assertEqual(getattr(failure.exception, 'phase', None), phase)
                self.assertNotIn('private child trace', str(failure.exception))

    def test_admin_parent_reports_only_exact_allowed_child_record(self):
        for sample, expected in (
                (b'loopbridge: phase=relay_publication cleanup=confirmed\n',
                 'loopbridge: phase=relay_publication cleanup=confirmed\n'),
                (b'loopbridge: phase=calculator cleanup=confirmed private-secret\n',
                 'loopbridge: phase=admin_client_failed cleanup=unconfirmed\n'),
                (b'loopbridge: phase=/private/token cleanup=confirmed\n',
                 'loopbridge: phase=admin_client_failed cleanup=unconfirmed\n'),
                (b'loopbridge: phase=calculator cleanup=confirmed\n\n',
                 'loopbridge: phase=admin_client_failed cleanup=unconfirmed\n')):
            with self.subTest(sample=sample):
                result = SimpleNamespace(returncode=1, stderr=sample, stdout=b'private stdout')
                errors = StringIO()
                output = StringIO()
                with (patch.object(admin, 'require_root'), patch.object(admin, 'protect_admin_process'),
                      patch.object(admin, 'protected_directory', return_value=nullcontext(11)),
                      patch('loopbridge.service_smoke.fcntl.flock'),
                      patch.object(admin, 'checked_owner_data', return_value=b'synthetic owner'),
                      patch.object(admin, 'run_service_client', return_value=result) as launch,
                      redirect_stderr(errors), redirect_stdout(output)):
                    code = smoke.report_smoke(smoke.admin_smoke, Path('/fixture'), 'a' * 64,
                                              980, 980, 'start', 'b' * 64, None)
                self.assertEqual(launch.call_args.kwargs['stderr'], subprocess.PIPE)
                self.assertEqual(code, 1)
                self.assertEqual(errors.getvalue(), expected)
                self.assertEqual(output.getvalue(), '')

    def test_admin_timeout_leaves_start_outcome_unconfirmed(self):
        timeout = subprocess.TimeoutExpired(['fixture', 'private argv'], 150,
                                             output=b'private stdout', stderr=b'private stderr')
        errors = StringIO()
        output = StringIO()
        with (patch.object(admin, 'require_root'), patch.object(admin, 'protect_admin_process'),
              patch.object(admin, 'protected_directory', return_value=nullcontext(11)),
              patch('loopbridge.service_smoke.fcntl.flock'),
              patch.object(admin, 'checked_owner_data', return_value=b'synthetic owner'),
              patch.object(admin, 'run_service_client', side_effect=timeout) as launch,
              redirect_stderr(errors), redirect_stdout(output)):
            code = smoke.report_smoke(smoke.admin_smoke, Path('/fixture'), 'a' * 64,
                                      980, 980, 'start', 'b' * 64, None)
        launch.assert_called_once()
        self.assertEqual(code, 1)
        self.assertEqual(errors.getvalue(), 'loopbridge: phase=admin_client_timeout cleanup=unconfirmed\n')
        self.assertEqual(output.getvalue(), '')
