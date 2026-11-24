# SPDX-License-Identifier: Apache-2.0
"""Preparation and same-UID protocol tests for the D.1C.3 qualification driver."""
from array import array
from contextlib import contextmanager, redirect_stdout
import errno
import io
import json
import os
from pathlib import Path
from queue import Queue
import socket
from tempfile import TemporaryDirectory
from threading import Thread
from time import monotonic, time
import unittest
from unittest.mock import Mock, patch

from experiments.registry_operational import _prepared_registry
from loopbridge.broker import Server
from loopbridge.service_ingress import PeerAdmission, bound_listener
from tools import registry_cross_uid as lab

RUN = '0112345678abcdef'
BOOT = '00000000-0000-0000-0000-000000000001'


class CrossUIDPreflightTests(unittest.TestCase):
    def setUp(self):
        self.plan = dict(version=1, run_id=RUN, boot_id=BOOT, expires_unix=1200,
                         service=[980, 980], desktop=[1000, 1000], third=[1030, 1030])

    def parse(self, value):
        return lab.parse_approval(json.dumps(value).encode(), RUN, boot_id=BOOT, now=1100)

    def test_plan_has_no_side_effects_and_rejects_arbitrary_paths(self):
        with patch.object(lab, 'read_approval') as read, patch.object(lab, 'serve') as serve:
            with redirect_stdout(io.StringIO()) as report:
                self.assertEqual(lab.main(['--run-id', RUN, 'plan']), 0)
                self.assertEqual(lab.main([]), 0)
            read.assert_not_called()
            serve.assert_not_called()
        plans = [json.loads(line) for line in report.getvalue().splitlines()]
        self.assertEqual(plans[0]['root'], f'/run/loop-registry-d1c3-{RUN}')
        self.assertTrue(all(row['status'] == 'PREPARED / NOT EXECUTED' for row in plans))
        for attempt in ('../../var/lib/loopbridge', '/run/loopbridge-ingress', 'a' * 17, RUN.upper()):
            with self.subTest(attempt=attempt), self.assertRaisesRegex(lab.QualificationError, 'invalid_run_id'):
                lab.run_layout(attempt)

    def test_missing_or_untrusted_approval_never_reaches_fixture(self):
        with TemporaryDirectory() as folder, patch.object(lab, 'BASE', Path(folder)), \
                patch.object(lab, 'serve') as serve, patch.object(lab, 'ControlInput') as input_pipe:
            with redirect_stdout(io.StringIO()) as report:
                status = lab.main(['--run-id', RUN, 'broker', '--phase', 'initial'])
            self.assertEqual(status, 1)
            self.assertEqual(json.loads(report.getvalue())['event'], 'qualification_failed')
            self.assertEqual(list(Path(folder).iterdir()), [])
            serve.assert_not_called()
            input_pipe.assert_not_called()

    @unittest.skipIf(os.getuid() == 0, 'non-root ownership check')
    def test_attempt_to_self_approve_with_same_shape_is_refused(self):
        with TemporaryDirectory() as folder, patch.object(lab, 'BASE', Path(folder)):
            root = Path(folder)
            root.chmod(0o755)
            layout = lab.run_layout(RUN)
            layout.root.mkdir(mode=0o755)
            marker = layout.root / 'approval.json'
            marker.write_text(json.dumps(self.plan))
            marker.chmod(0o444)
            with self.assertRaisesRegex(lab.QualificationError, 'unsafe_run_parent'):
                lab.read_approval(layout, RUN)

    def test_approval_requires_bound_boot_run_time_and_distinct_real_uids(self):
        self.assertEqual(self.parse(self.plan).service, (980, 980))
        self.assertIsNone(self.parse(self.plan | {'third': None}).third)
        for change in ({'service': [1000, 980]}, {'third': [980, 1030]}, {'desktop': [0, 1000]},
                       {'service': [True, 980]}, {'third': [1030]}, {'expires_unix': 1100},
                       {'expires_unix': 999999}, {'run_id': 'ffffffffffffffff'}, {'boot_id': RUN},
                       {'extra': 'production'}, {'version': True}):
            with self.subTest(change=change), self.assertRaises(lab.QualificationError):
                self.parse(self.plan | change)
        raw = json.dumps(self.plan)[:-1] + ', "version": 1}'
        with self.assertRaisesRegex(lab.QualificationError, 'invalid_approval'):
            lab.parse_approval(raw.encode(), RUN, boot_id=BOOT, now=1100)

    def test_wrong_identity_groups_graphical_environment_and_inherited_fd_are_rejected(self):
        lab.check_identity((980, 980), 980, 980, 980, 980, [])
        for arguments in ((980, 1000, 980, 980, []), (980, 980, 980, 33, []),
                          (980, 980, 980, 980, [27]), (1000, 1000, 1000, 1000, [])):
            with self.assertRaisesRegex(lab.QualificationError, 'wrong_process_identity'):
                lab.check_identity((980, 980), *arguments)
        approved = self.parse(self.plan)
        with patch.object(lab, 'check_identity'), patch.dict(lab.os.environ, {'SWAYSOCK': 'fixture'}, clear=True):
            with self.assertRaisesRegex(lab.QualificationError, 'inherited_graphical_environment'):
                lab.check_process(approved, 'service')
        with patch.object(lab, 'check_identity'), patch.object(lab, 'check_privileges'), \
                patch.dict(lab.os.environ, {}, clear=True):
            fd = os.memfd_create('fixture-inherited-fd', os.MFD_CLOEXEC)
            try:
                with self.assertRaisesRegex(lab.QualificationError, 'inherited_descriptor'):
                    lab.check_process(approved, 'service')
            finally:
                os.close(fd)

    def test_role_requires_no_capabilities_and_no_new_privileges(self):
        clean = 'CapEff: 0000\nCapPrm: 0000\nCapAmb: 0000\nNoNewPrivs: 1\n'
        lab.check_privileges(clean)
        for status in ('', clean.replace('NoNewPrivs: 1', 'NoNewPrivs: 0'),
                       clean.replace('CapPrm: 0000', 'CapPrm: 0100')):
            with self.assertRaisesRegex(lab.QualificationError, 'unexpected_process_privileges'):
                lab.check_privileges(status)

    def test_pipe_seed_and_single_line_control_are_bounded(self):
        reader, writer = os.pipe()
        test_seed = '01' * 32
        try:
            os.write(writer, (test_seed + '\nrestrict\nstop\n').encode())
            stream = lab.ControlInput(reader)
            self.assertEqual(stream.seed(), bytes.fromhex(test_seed))
            self.assertEqual(stream.line(1), b'restrict')
            self.assertEqual(stream.line(1), b'stop')
            os.write(writer, b'a' * 65 + b'\n')
            with self.assertRaisesRegex(lab.QualificationError, 'control_message_limit'):
                stream.line(1)
        finally:
            os.close(reader)
            os.close(writer)
        with TemporaryDirectory() as folder:
            fifo = Path(folder) / 'named-fifo'
            os.mkfifo(fifo)
            fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
            try:
                with self.assertRaisesRegex(lab.QualificationError, 'anonymous_pipe_required'):
                    lab.ControlInput(fd)
            finally:
                os.close(fd)

    def test_denial_requires_permission_error_and_sanitizes_evidence(self):
        with redirect_stdout(io.StringIO()) as report:
            lab.check_denied('fixture', Mock(side_effect=PermissionError(errno.EPERM, 'detail')))
        self.assertEqual(json.loads(report.getvalue()), dict(
            event='direct_access', check='fixture', outcome='denied', errno=errno.EPERM))
        for op, result in ((Mock(side_effect=FileNotFoundError(errno.ENOENT, 'missing')), 'partial'),
                           (Mock(return_value=None), 'no_go')):
            with self.assertRaises(lab.QualificationError) as caught:
                lab.check_denied('fixture', op)
            self.assertEqual(caught.exception.result, result)

    def test_ancillary_descriptors_are_closed_and_report_no_go(self):
        fd = os.memfd_create('fixture-scm-rights', os.MFD_CLOEXEC)
        try:
            sender, receiver = socket.socketpair()
            with sender, receiver:
                sender.sendmsg([b'x'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array('i', [fd]))])
                with patch.object(lab.os, 'close', wraps=os.close) as close:
                    with self.assertRaises(lab.QualificationError) as caught:
                        lab.JsonSocket(receiver).recv(1)
                self.assertEqual(caught.exception.result, 'no_go')
                close.assert_called_once()
                with self.assertRaisesRegex(OSError, 'Bad file descriptor'):
                    os.fstat(close.call_args.args[0])
        finally:
            os.close(fd)

    def test_sentinel_is_live_and_cleanup_covers_failure(self):
        with TemporaryDirectory() as folder:
            private = Path(folder)
            with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
                with lab.sentinel_resources(private) as fd:
                    self.assertFalse(os.get_inheritable(fd))
                    lab.connect_sentinel(private / lab.PRIVATE_SOCKET)
                    self.assertIn(b'synthetic', os.pread(fd, 64, 0))
                    raise RuntimeError('fixture failure')
            self.assertFalse((private / lab.PRIVATE_SOCKET).exists())
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_start_refuses_nonempty_private_and_ingress_before_initializing(self):
        with TemporaryDirectory() as folder:
            layout = lab.Layout(Path(folder))
            layout.private.mkdir()
            layout.ingress.mkdir()
            approval = self.parse(self.plan)
            for occupied, diagnostic in ((layout.private, 'private_not_fresh'),
                                         (layout.ingress, 'ingress_not_fresh')):
                artifact = occupied / 'foreign'
                artifact.write_text('preserve')
                with patch.object(lab, 'initialize_registry_database') as initialize:
                    with self.assertRaisesRegex(lab.QualificationError, diagnostic):
                        lab.serve(layout, approval, None, {}, phase='initial', original_pin=None)
                    initialize.assert_not_called()
                self.assertEqual(artifact.read_text(), 'preserve')
                artifact.unlink()

    def test_exact_driver_rpc_flow_rotation_and_reopen_with_real_same_uid_socket(self):
        uid, gid = os.getuid(), os.getgid()
        with TemporaryDirectory() as folder:
            layout = lab.Layout(Path(folder))
            layout.private.mkdir(mode=0o700)
            layout.ingress.mkdir(mode=0o700)
            credentials = lab.tokens(bytes(range(32)), RUN)
            self.assertNotEqual(credentials, lab.tokens(bytes(range(32)), '0123456789abcdee'))
            expires = int(time()) + 200
            approval = lab.Approval(RUN, (uid, gid), (uid + 1, gid + 1), None, expires)
            admission = PeerAdmission.local_only(uid)
            reports = Queue()

            def record(event, **fields):
                reports.put((event, fields))

            # Only the UID ingress is replaced. The operational broker, pinned
            # store, sentinels, control pipe, client stages and cleanup are real.
            @contextmanager
            def serve_local(_ingress, *, database_pin, policy_pin):
                with _prepared_registry(layout.private, admission, database_pin, policy_pin, wall_clock=time,
                                        clock=monotonic) as (broker, control):
                    with bound_listener(layout.endpoint) as listener, Server(broker, listener):
                        yield layout.endpoint, control

            @contextmanager
            def broker_phase(phase, original_pin):
                reader, writer = os.pipe()
                source = lab.ControlInput(reader)
                errors = []

                def broker():
                    try:
                        lab.serve(layout, approval, source, credentials, phase=phase,
                                  original_pin=original_pin)
                    except Exception as error:
                        errors.append(error)
                        reports.put(('fixture_error', {}))

                worker = Thread(target=broker)
                worker.start()
                try:
                    event, ready = reports.get(timeout=5)
                    self.assertEqual(event, 'broker_ready', errors)
                    self.assertTrue((layout.private / lab.PRIVATE_SOCKET).exists())
                    self.assertFalse(os.get_inheritable(ready['sentinel_fd']))
                    yield writer, ready
                finally:
                    try:
                        os.write(writer, b'stop\n')
                    finally:
                        os.close(writer)
                        worker.join(5)
                        os.close(reader)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(reports.get(timeout=5)[0], 'broker_stopped')
                self.assertFalse(layout.endpoint.exists())
                self.assertFalse((layout.private / lab.PRIVATE_SOCKET).exists())

            with patch.object(lab, 'CrossUIDIngress', return_value=None), \
                    patch.object(lab, 'serve_operational_registry', new=serve_local), \
                    patch.object(lab, 'emit', new=record):
                with broker_phase('initial', None) as (writer, ready):
                    raw_pin = ready['database_pin']
                    self.assertEqual(lab.serialize_pin(lab.parse_pin(raw_pin)), raw_pin)
                    self.assertEqual(ready['broker_uid'], uid)
                    lab.initial_flow(layout, (uid, gid), ready['broker_pid'], credentials)
                    self.assertTrue(reports.get(timeout=5)[1]['acceptance'])
                    with lab.connect(layout, (uid, gid), ready['broker_pid']) as existing:
                        lab.authenticate(existing, credentials['executor'], lab.EXECUTOR)
                        os.write(writer, b'restrict\n')
                        self.assertEqual(reports.get(timeout=5), ('policy_restricted', {'generation': 2}))
                        lab.denied_rpc(existing, 'objective.status', objective_id=lab.OBJECTIVE)
                    lab.restricted_flow(layout, (uid, gid), ready['broker_pid'], credentials)
                    with self.assertRaisesRegex(lab.QualificationError, 'unexpected_broker_identity'):
                        with lab.connect(layout, (uid, gid), 1):
                            self.fail('wrong PID accepted')
                with broker_phase('restart', raw_pin) as (_, ready):
                    lab.restricted_flow(layout, (uid, gid), ready['broker_pid'], credentials)
                manifest = (layout.private / lab.POLICY_FILE).read_bytes()
                self.assertEqual(manifest, lab.policy_bytes(credentials, 2, expires))
                for secret in credentials.values():
                    self.assertNotIn(secret.encode(), manifest)
                    self.assertNotIn(secret.encode(), (layout.private / lab.DATABASE).read_bytes())
