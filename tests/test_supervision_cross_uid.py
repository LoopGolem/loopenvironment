# SPDX-License-Identifier: Apache-2.0
"""Non-privileged rehearsal. The actual two-UID proof belongs to the clone."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import StringIO
from hashlib import sha256
import json
import multiprocessing
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
import unittest
from unittest.mock import patch

from experiments.objective_registry import RegistryError
from experiments.registry_operational import POLICY_FILE, PolicyPin
from experiments.supervision_operational import (DATABASE, initialize_supervision_database,
                                                 serve_operational_supervision)
from loopbridge.service_ingress import CrossUIDIngress, PeerAdmission, bound_listener, path_inode
from tools import registry_cross_uid as previous
from tools import supervision_cross_uid as driver
from tools import supervision_cross_uid_flow as workflow
from tools.supervised_execution import main as reference_client

RUN = '0123456789abcdef'
MACHINE = '1' * 32
BOOT = '25ebc73e-2efe-4444-8724-bd5fee05da1e'
HOST = 'looplab-d1c3'
SEED = b'\xb2' * 32
LOCAL = (os.getuid(), os.getgid())
WAIT = 20


def local_layout(root):
    layout = driver.Layout(root)
    layout.private.mkdir(mode=0o700)
    layout.ingress.mkdir(mode=0o700)
    return layout


@contextmanager
def same_uid_listener(ingress, endpoint):
    assert endpoint.parent == ingress.directory
    with bound_listener(endpoint) as listener:
        yield listener


@contextmanager
def local_ingress_checks():
    # Only the two-UID configuration and ACL setup are simulated. The socket
    # transport and both ends' SO_PEERCRED checks still use the Linux kernel.
    with (patch.object(CrossUIDIngress, '__post_init__'),
          patch.object(CrossUIDIngress, 'validate', lambda ingress: path_inode(ingress.directory.stat())),
          patch.object(CrossUIDIngress, 'listen', same_uid_listener)):
        yield


class PipeInput:
    def __init__(self, pipe):
        self.pipe = pipe

    def line(self, seconds):
        if not self.pipe.poll(seconds):
            return None
        try:
            return self.pipe.recv()
        except EOFError:
            return None


def run_service(layout, approval, restart, original_pin, pipe):
    def evidence(event, **details):
        pipe.send(dict(event=event, **details))

    try:
        with local_ingress_checks(), patch.object(driver, 'emit', evidence):
            driver.serve(layout, approval, PipeInput(pipe), driver.credentials_from_seed(SEED, RUN),
                         restart=restart, original_pin=original_pin, window=driver.Window(approval.expires, monotonic_deadline=approval.expires_monotonic))
    except BaseException as error:
        pipe.send(dict(event='test_service_error', kind=type(error).__name__,
                       detail=getattr(error, 'check', str(error))))
    finally:
        pipe.close()


class SupervisionPreflightTests(unittest.TestCase):
    def test_plan_is_read_only_and_run_id_cannot_select_a_path(self):
        out = StringIO()
        with redirect_stdout(out), patch.object(driver, 'read_approval') as read:
            self.assertEqual(driver.main(['--run-id', RUN, 'plan']), 0)
            read.assert_not_called()
        result = json.loads(out.getvalue())
        self.assertEqual(result['status'], 'PREPARED / NOT EXECUTED')
        self.assertEqual(result['endpoint'], f'/run/loop-supervision-d2b1-{RUN}/ingress/supervised.sock')
        for value in ('../private', '/tmp/anything', RUN.upper()):
            with redirect_stdout(StringIO()) as failed:
                self.assertEqual(driver.main(['--run-id', value, 'plan']), 1)
            self.assertEqual(json.loads(failed.getvalue())['check'], 'invalid_run_id')

    def test_approval_is_strict_profile_bound_and_boot_bound(self):
        approval = dict(version=1, profile=driver.PROFILE, run_id=RUN, boot_id=BOOT, hostname=HOST,
                        machine_id=MACHINE, expires_unix=1010, expires_monotonic=60,
                        service=[980, 980], desktop=[1000, 1000])
        confirmed = driver.parse_approval(json.dumps(approval), RUN, boot_id=BOOT, now=1000, elapsed=50,
                                          hostname=HOST, machine_id=MACHINE)
        self.assertEqual((confirmed.service, confirmed.desktop), ((980, 980), (1000, 1000)))
        for changes in (dict(version=True), dict(profile='registry-d1c3'), dict(boot_id='old'),
                        dict(run_id='f' * 16), dict(machine_id='2' * 32), dict(hostname='other'),
                        dict(expires_unix=1000), dict(expires_unix=4000), dict(expires_monotonic=50),
                        dict(expires_monotonic=4000), dict(service=[0, 0]),
                        dict(service=[1000, 980]), dict(desktop=[1000, -1]), dict(path='/run')):
            with self.subTest(changes=changes), self.assertRaises(previous.QualificationError):
                driver.parse_approval(json.dumps(dict(approval, **changes)), RUN, boot_id=BOOT,
                                      now=1000, elapsed=50, hostname=HOST, machine_id=MACHINE)
        duplicate = json.dumps(approval)[:-1] + ', "version":1}'
        with self.assertRaises(previous.QualificationError):
            driver.parse_approval(duplicate, RUN, boot_id=BOOT, now=1000, elapsed=50,
                                  hostname=HOST, machine_id=MACHINE)

    def test_missing_or_self_issued_approval_refuses_before_launch(self):
        with TemporaryDirectory() as folder, patch.object(previous, 'BASE', Path(folder)):
            layout = driver.run_layout(RUN)
            with redirect_stdout(StringIO()), patch.object(driver, 'serve') as serve:
                self.assertEqual(driver.main(['--run-id', RUN, 'broker', '--phase', 'initial']), 1)
                layout.root.mkdir(mode=0o755)
                (layout.root / 'approval.json').write_text('{}')
                (layout.root / 'approval.json').chmod(0o444)
                self.assertEqual(driver.main(['--run-id', RUN, 'broker', '--phase', 'initial']), 1)
                serve.assert_not_called()

    def test_role_check_refuses_wrong_identity_before_secrets_or_socket_access(self):
        approval = previous.Approval(RUN, (980, 980), (1000, 1000), None, int(time()) + 60)
        with (patch.object(driver, 'read_approval', return_value=approval),
              patch.object(previous.os, 'getuid', return_value=1000),
              patch.object(driver, 'ControlInput') as control,
              patch.object(driver, 'serve') as serve, redirect_stdout(StringIO()) as out):
            self.assertEqual(driver.main(['--run-id', RUN, 'broker', '--phase', 'initial']), 1)
            self.assertEqual(json.loads(out.getvalue())['check'], 'wrong_process_identity')
            control.assert_not_called()
            serve.assert_not_called()

    def test_expiry_is_bounded_by_wall_and_monotonic_and_control_eof_stops(self):
        wall, elapsed = [1000], [40]
        window = driver.Window(1010, monotonic_deadline=50, wall=lambda: wall[0], elapsed=lambda: elapsed[0])
        self.assertEqual(window.remaining(), 10)
        wall[0], elapsed[0] = 990, 50
        self.assertEqual(window.remaining(), 0)
        gates = driver.Gates(window)
        self.assertEqual(driver.broker_control(None, None, gates, None, 1010, restart=False),
                         'approval_expired')
        wall[0], elapsed[0] = 1009, 40
        window = driver.Window(1010, monotonic_deadline=50, wall=lambda: wall[0], elapsed=lambda: elapsed[0])
        gates = driver.Gates(window)
        reader, writer = os.pipe()
        try:
            channel = driver.ControlInput(reader)
            os.close(writer)
            writer = None
            self.assertEqual(driver.broker_control(channel, None, gates, None, 1010, restart=False),
                             'control_closed')
        finally:
            os.close(reader)
            if writer is not None:
                os.close(writer)

    def test_stub_credential_and_attempt_references_are_unique_and_validated(self):
        credentials = driver.credentials_from_seed(SEED, RUN)
        self.assertEqual(len(credentials), len(set(credentials.values())))
        self.assertNotEqual(credentials, previous.tokens(SEED, RUN))
        self.assertNotEqual(credentials, driver.credentials_from_seed(SEED, 'f' * 16))
        manifest = driver.policy_bytes(credentials, 2000)
        for bearer in credentials.values():
            self.assertNotIn(bearer.encode(), manifest)
        valid = {case: f'{index:032x}' for index, case in enumerate(workflow.CASES, 1)}
        self.assertEqual(driver.parse_attempts(json.dumps(valid)), valid)
        for changed in ({}, dict(valid, flow='../private'), dict(valid, flow=valid['revoked'])):
            with self.assertRaises(previous.QualificationError):
                driver.parse_attempts(json.dumps(changed))


class OperationalSupervisionTests(unittest.TestCase):
    def setUp(self):
        if LOCAL[0] == 0:
            self.skipTest('service fixtures require an unprivileged test UID')
        root = TemporaryDirectory(prefix='d2b1-fixture-')
        self.addCleanup(root.cleanup)
        self.layout = local_layout(Path(root.name))
        self.approval = driver.Approval(RUN, LOCAL, LOCAL, None, int(time()) + 600,
                                        int(driver.monotonic()) + 600)
        self.credentials = driver.credentials_from_seed(SEED, RUN)

    def _ingress(self):
        return CrossUIDIngress(self.layout.ingress, self.layout.private, PeerAdmission.local_only(LOCAL[0]))

    def _initialize(self):
        database_pin = initialize_supervision_database(self.layout.private)
        raw = driver.policy_bytes(self.credentials, self.approval.expires)
        previous.publish_policy(self.layout.private, raw, initial=True)
        return database_pin, PolicyPin(1, sha256(raw).hexdigest())

    def test_profile_refuses_same_uid_configuration_without_explicit_test_adapter(self):
        with self.assertRaisesRegex(ValueError, 'invalid_cross_uid_ingress'):
            self._ingress()

    def test_pin_enrollment_is_exclusive_and_missing_or_replaced_bank_fails(self):
        database_pin, policy_pin = self._initialize()
        with self.assertRaisesRegex(RegistryError, 'storage_unavailable'):
            initialize_supervision_database(self.layout.private)
        with local_ingress_checks():
            with serve_operational_supervision(self._ingress(), database_pin=database_pin,
                                               policy_pin=policy_pin) as (endpoint, _, _):
                self.assertTrue(endpoint.is_socket())
            self.assertFalse(endpoint.exists())
            database = self.layout.private / DATABASE
            with database.open('rb') as original:
                database.unlink()
                with self.assertRaises(RegistryError):
                    with serve_operational_supervision(self._ingress(), database_pin=database_pin, policy_pin=policy_pin):
                        self.fail('opened missing database')
                replacement_pin = initialize_supervision_database(self.layout.private)
                self.assertNotEqual(replacement_pin, database_pin)
                self.assertEqual(os.fstat(original.fileno()).st_ino, database_pin.file[1])
                with self.assertRaises(RegistryError):
                    with serve_operational_supervision(self._ingress(), database_pin=database_pin, policy_pin=policy_pin):
                        self.fail('opened replaced database')
            self.assertFalse(endpoint.exists())

    def test_wrong_policy_pin_and_invalid_manifest_fail_before_listener(self):
        database_pin, _ = self._initialize()
        with local_ingress_checks():
            with self.assertRaisesRegex(ValueError, 'registry_policy_pin_mismatch'):
                with serve_operational_supervision(self._ingress(), database_pin=database_pin,
                                                   policy_pin=PolicyPin(1, '0' * 64)):
                    self.fail('opened policy with mismatched pin')
            manifest = b'{"version":1,"version":1}'
            (self.layout.private / POLICY_FILE).write_bytes(manifest)
            with self.assertRaisesRegex(ValueError, 'invalid_registry_policy'):
                with serve_operational_supervision(self._ingress(), database_pin=database_pin,
                                                   policy_pin=PolicyPin(1, sha256(manifest).hexdigest())):
                    self.fail('opened structurally invalid policy')
        self.assertFalse(self.layout.endpoint.exists())

    def test_reference_client_explicit_kernel_credentials_and_same_uid_default(self):
        database_pin, policy_pin = self._initialize()
        with local_ingress_checks(), serve_operational_supervision(
                self._ingress(), database_pin=database_pin, policy_pin=policy_pin) as (endpoint, _, _):
            base = ['--socket', str(endpoint)]
            exact = ['--service-pid', str(os.getpid()), '--service-uid', str(LOCAL[0]),
                     '--service-gid', str(LOCAL[1])]
            wrong = exact.copy()
            wrong[1] = str(os.getpid() + 1)
            action = ['status', workflow.CASE_IDS['flow']]
            with patch('tools.supervised_execution.getpass') as prompt, redirect_stderr(StringIO()) as error:
                self.assertEqual(reference_client([*base, *wrong, *action]), 1)
                prompt.assert_not_called()
                self.assertIn('unexpected_service_identity', error.getvalue())
            with patch('tools.supervised_execution.getpass', return_value=self.credentials['observer']) as prompt:
                for options in ([], exact):
                    with redirect_stderr(StringIO()) as error:
                        self.assertEqual(reference_client([*base, *options, *action]), 1)
                        self.assertIn('RPC error -32001', error.getvalue())  # Peer verified, grant denied.
                self.assertEqual(prompt.call_count, 2)
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                reference_client([*base, '--service-uid', str(LOCAL[0]), *action])

    @contextmanager
    def service_process(self, *, restart=False, original_pin=None):
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe()
        with parent, child:
            process = context.Process(target=run_service,
                                      args=(self.layout, self.approval, restart, original_pin, child))
            process.start()
            child.close()
            try:
                self.assertTrue(parent.poll(WAIT), 'broker readiness timeout')
                ready = parent.recv()
                self.assertEqual(ready['event'], 'broker_ready', ready)
                self.assertEqual(ready['broker_pid'], process.pid)
                yield parent, ready
                process.join(WAIT)
                self.assertFalse(process.is_alive())
                self.assertEqual(process.exitcode, 0)
            finally:
                if process.is_alive():
                    try:
                        parent.send(b'stop')
                    except (OSError, EOFError):
                        pass
                    process.join(1)
                if process.is_alive():
                    process.kill()
                    process.join()
                process.close()

    def event(self, channel, name):
        self.assertTrue(channel.poll(WAIT), name)
        data = channel.recv()
        self.assertEqual(data['event'], name, data)
        return data

    def test_same_uid_rehearsal_exercises_real_rpc_barriers_and_new_process_recovery(self):
        emitted = []

        def relay(event, **details):
            emitted.append(dict(event=event, **details))
            if event == 'release_required':
                channel.send(f"release {details['case']}".encode())

        with self.service_process() as (channel, ready):
            first_pid = ready['broker_pid']
            pin = ready['database_pin']
            client = workflow.DesktopFlow(self.layout, LOCAL, first_pid, self.credentials)
            with patch.object(previous, 'emit', relay), patch.object(workflow, 'emit', relay):
                previous.initial_flow(self.layout, LOCAL, first_pid, self.credentials)
                client.prepare()
                channel.send(b'arm')
                attempts = self.event(channel, 'fixture_armed')['attempts']
                client.active(attempts)
            done = self.event(channel, 'broker_stopped')
            self.assertEqual(done['reason'], 'interrupted_pending_dispatch')
            self.assertEqual(done['dispatch_calls'], workflow.EXPECTED_CALLS)
            self.assertTrue(done['sentinel_closed'])
        self.assertFalse(self.layout.endpoint.exists())
        audit_pin = next(row['audit_sha256'] for row in emitted if row['event'] == 'recovery_reference')
        with self.service_process(restart=True, original_pin=pin) as (channel, ready):
            self.assertNotEqual(first_pid, ready['broker_pid'])
            self.assertEqual(pin, ready['database_pin'])
            client = workflow.DesktopFlow(self.layout, LOCAL, ready['broker_pid'], self.credentials)
            with patch.object(workflow, 'emit', relay):
                client.before_regrant(attempts)
                channel.send(b'reissue')
                self.event(channel, 'recovery_grants_reissued')
                client.recovered(attempts, audit_pin)
            channel.send(b'stop')
            stopped = self.event(channel, 'broker_stopped')
            self.assertTrue(stopped['sockets_removed'])
            self.assertFalse(any(stopped['dispatch_calls'].values()))
        self.assertTrue(any(row['event'] == 'desktop_recovered' for row in emitted))
        serialized = json.dumps(emitted)
        for secret in (SEED.hex(), *self.credentials.values(),
                       *(sha256(token.encode()).hexdigest() for token in self.credentials.values()),
                       previous.FIXTURE_TEXT, str(self.layout.private)):
            self.assertNotIn(secret, serialized)

    def test_broker_shuts_down_and_unlinks_sockets_on_window_expiry(self):
        elapsed = [0]
        window = driver.Window(self.approval.expires, monotonic_deadline=600, elapsed=lambda: elapsed[0])

        class ExpireWhileWaiting:
            def line(self, seconds):
                elapsed[0] = 1000
                return None

        with local_ingress_checks(), redirect_stdout(StringIO()) as out:
            driver.serve(self.layout, self.approval, ExpireWhileWaiting(), self.credentials,
                         restart=False, original_pin=None, window=window)
        ready, stopped = map(json.loads, out.getvalue().splitlines())
        self.assertEqual(ready['event'], 'broker_ready')
        self.assertEqual(stopped['reason'], 'approval_expired')
        self.assertFalse(self.layout.endpoint.exists())
        self.assertFalse((self.layout.private / previous.PRIVATE_SOCKET).exists())

    def test_broker_shuts_down_and_unlinks_sockets_on_lost_control_pipe(self):
        with self.service_process() as (channel, _):
            channel.send(None)  # PipeInput delivers the same EOF sentinel as ControlInput.
            stopped = self.event(channel, 'broker_stopped')
            self.assertEqual(stopped['reason'], 'control_closed')
            self.assertFalse(any(stopped['dispatch_calls'].values()))
        self.assertFalse(os.path.lexists(self.layout.endpoint))
        self.assertFalse(os.path.lexists(self.layout.private / previous.PRIVATE_SOCKET))
