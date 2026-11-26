# SPDX-License-Identifier: Apache-2.0
"""Nonprivileged D.2C.2 rehearsals. Kernel cross-UID observations remain NOT RUN."""
from contextlib import redirect_stdout
from dataclasses import asdict
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
from tempfile import TemporaryDirectory
from time import monotonic, time
import unittest
from unittest.mock import patch

from loopbridge.service_ingress import bound_listener, path_inode
from tools.registry_cross_uid import QualificationError
from tools.workspace_cross_uid import (EVENT_FIELDS, MAX_WINDOW, SCHEMA, Evidence, error_check, main,
                                       parse_approval, process_record, remove_stale_endpoint, run_session)
from tools.workspace_cross_uid_fixture import (CASES, CONTENT, DIGEST, NO_CALL, CapabilityClock, Instrumentation,
                                               Layout, Window, admin_command, validate_rpc_command)
from tools.workspace_cross_uid_operator import decode_mount_path, mount_free, occupants_exited


RUN = '0123456789abcdef'
ROWS = {'schema', 'mode', 'run_id', 'sequence', 'event', 'wall_unix_ns', 'monotonic_ns'}


def fixture_approval():
    marker = dict(run_id=RUN, boot_id='boot', clone_dmi='clone', revision='a' * 40,
                  identities={'service': [980, 980], 'desktop': [1000, 1000], 'third': [65534, 65534]})
    approval = dict(version=1, profile='workspace-d2c2', fixture=marker.copy(), issued_unix=1000,
                    expires_unix=1100, issued_monotonic=20, expires_monotonic=120)
    return marker, approval


class ApprovalAndAllowlist(unittest.TestCase):
    def test_approval_binds_identity_and_independent_fresh_windows(self):
        marker, approval = fixture_approval()
        self.assertEqual(parse_approval(approval, marker, wall=1030, elapsed=50, fresh=True).wall_end, 1100)
        for field in marker:
            with self.subTest(field=field), self.assertRaisesRegex(QualificationError, 'approval_identity_mismatch'):
                parse_approval(approval, marker | {field: None}, wall=1030, elapsed=50, fresh=True)
        for change in ({'issued_unix': True}, {'expires_unix': 1000 + MAX_WINDOW + 1},
                       {'expires_monotonic': 80}, {'issued_monotonic': 52}):
            with self.subTest(change=change), self.assertRaises(QualificationError):
                parse_approval(approval | change, marker, wall=1030, elapsed=50)
        for wall, elapsed, fresh in ((1090, 50, True), (1100, 50, False), (1030, 120, False)):
            with self.subTest(wall=wall, elapsed=elapsed), self.assertRaisesRegex(
                    QualificationError, 'approval_window_invalid'):
                parse_approval(approval, marker, wall=wall, elapsed=elapsed, fresh=fresh)

    def test_virtual_deadline_cannot_prolong_real_approval(self):
        wall, elapsed = [1000], [20]
        window = Window(1100, 120, wall=lambda: wall[0], elapsed=lambda: elapsed[0])
        clock = CapabilityClock(window, restart=False)
        before = clock()
        clock.utc += 1
        self.assertEqual(clock(), before + 1)
        self.assertEqual(window.remaining(), 100)
        elapsed[0] = 120
        with self.assertRaisesRegex(EOFError, 'approval_expired'):
            clock()
        elapsed[0], wall[0] = 20, 1100
        with self.assertRaisesRegex(EOFError, 'approval_expired'):
            clock()

    def test_plan_is_read_only_and_actual_commands_require_root(self):
        output = StringIO()
        with redirect_stdout(output), patch('tools.workspace_cross_uid.read_marker', side_effect=AssertionError):
            self.assertEqual(main(['--run-id', RUN, 'plan']), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual((plan['status'], plan['real_cross_uid']), ('PREPARED / NOT EXECUTED', 'NOT RUN'))
        if os.geteuid() != 0:
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(['--run-id', RUN, 'execute', '--archive', '/unopened']), 1)
            self.assertEqual(json.loads(output.getvalue())['check'], 'independent_root_operator_required')

    def test_allowlists_keep_admin_grants_off_desktop_channel(self):
        self.assertEqual(admin_command(dict(op='grant', case='base', mode='all')), ('grant', 'base', 'all'))
        for data in ({'op': 'exec', 'command': 'anything'}, {'op': 'grant', 'case': 'base', 'mode': 'all', 'uid': 0},
                     {'op': 'authority', 'case': 'base'}, {'op': 'released', 'case': 'fresh'}):
            with self.subTest(data=data), self.assertRaises((ValueError, QualificationError)):
                admin_command(data)
        good = dict(op='rpc', case='base', action='authorize', revision=0, number=0, variant='exact')
        method, params = validate_rpc_command('issuer', good)
        self.assertEqual(method, 'effect.authorize')
        scope = asdict(CASES['base'].scope)
        self.assertEqual({key: params[key] for key in scope if key != 'digest'},
                         {key: value for key, value in scope.items() if key != 'digest'})
        self.assertEqual(sha256(params['content'].encode()).hexdigest(), scope['digest'])
        for role, data in (('executor', {'op': 'grant'}), ('executor', {'action': 'cancel'}),
                           ('observer', {'action': 'authorize'}), ('issuer', {'variant': 'arbitrary text'}),
                           ('executor', {'op': 'send_only', 'action': 'step'}), ('executor', {'path': '/tmp'})):
            with self.subTest(role=role, data=data), self.assertRaises(QualificationError):
                validate_rpc_command(role, good | data)

    def test_counter_rejects_an_untracked_adapter_call(self):
        proof = Instrumentation(Window(time() + 5, monotonic() + 5))
        with self.assertRaisesRegex(ValueError, 'untracked_publication'):
            proof.count('unknown-operation')
        self.assertEqual(proof.snapshot()['untracked'], 1)
        self.assertEqual(proof.snapshot()['links'], {})

    def test_evidence_schema_refuses_unexpected_fields_and_redacts_exact_secrets(self):
        output = StringIO()
        token = 'lab-synthetic-test-token'
        emit = Evidence(output, mode='rehearsal', run_id=RUN, secrets=(token,))
        with self.assertRaisesRegex(QualificationError, 'invalid_evidence_event'):
            emit('failure', check='invalid_scope', classification='partial', credential=token)
        for hidden in (token, CONTENT.strip()):
            with self.subTest(hidden=hidden), self.assertRaisesRegex(QualificationError, 'secret_in_evidence'):
                emit('failure', check=hidden, classification='partial')
        self.assertEqual(output.getvalue(), '')
        emit('failure', check='timeout', classification='partial')
        self.assertEqual(json.loads(output.getvalue())['sequence'], 1)
        self.assertEqual(error_check(EOFError()), ('approval_or_transport_interrupted', 'partial'))
        self.assertEqual(error_check(QualificationError('invalid_access', 'no_go')), ('invalid_access', 'no_go'))


class CleanupGuards(unittest.TestCase):
    def test_stale_endpoint_requires_exact_inode_exit_and_no_listener(self):
        service = (os.geteuid(), os.getegid())
        with TemporaryDirectory() as path:
            endpoint = Path(path) / 'test.sock'
            with bound_listener(endpoint):
                pin = path_inode(endpoint.lstat())
                with self.assertRaisesRegex(QualificationError, 'unix_endpoint_still_listed'):
                    remove_stale_endpoint(endpoint, pin, service, None, exited=True)
                self.assertTrue(endpoint.is_socket())
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(endpoint))
                endpoint.chmod(0o600)
                pin = path_inode(endpoint.lstat())
            for tested_pin, exited in ((pin, False), ((0, 0), True)):
                with self.assertRaisesRegex(QualificationError, 'stale_endpoint_identity_changed'):
                    remove_stale_endpoint(endpoint, tested_pin, service, None, exited=exited)
            remove_stale_endpoint(endpoint, pin, service, None, exited=True)
            self.assertFalse(endpoint.exists())

    def test_cleanup_blocks_mounts_and_unreaped_processes(self):
        self.assertEqual(decode_mount_path(r'/path/with\040spaces'), '/path/with spaces')
        rows = '27 21 0:1 / /run/fixture/inner rw - tmpfs tmpfs rw\n'
        with patch('tools.workspace_cross_uid_operator.open', return_value=StringIO(rows)):
            with self.assertRaisesRegex(QualificationError, 'fixture_contains_mount'):
                mount_free(Path('/run/fixture'))
        with subprocess.Popen(['/bin/cat'], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL) as helper:
            process = dict(pid=helper.pid, identity=process_record(helper.pid), exit_code=None, role='helper')
            lifecycle = dict(pins=None, processes=[process], endpoint_pin=None)
            with self.assertRaisesRegex(QualificationError, 'process_lifecycle_incomplete'):
                occupants_exited(lifecycle)
            with self.assertRaisesRegex(QualificationError, 'fixture_process_still_live'):
                occupants_exited(lifecycle | {'processes': [process | {'exit_code': 0}]})
            helper.stdin.close()
            process['exit_code'] = helper.wait(timeout=3)
            occupants_exited(lifecycle)


@unittest.skipIf(os.geteuid() == 0 or not Path('/usr/bin/setpriv').exists() or not hasattr(os, 'pidfd_open'),
                 'same-UID rehearsal requires a non-root Linux process, setpriv and pidfds')
class FullWorkspaceRehearsal(unittest.TestCase):
    def test_real_same_uid_rpc_storage_gates_restart_and_classification(self):
        output = StringIO()
        with TemporaryDirectory(prefix='loop-d2c2-test-') as path:
            layout = Layout(Path(path))
            layout.private.mkdir(mode=0o700)
            layout.ingress.mkdir(mode=0o700)
            result = run_session(layout, RUN, Window(time() + 120, monotonic() + 120),
                                 output, real=False)
            self.assertFalse(layout.endpoint.exists())
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(result, 0, [row for row in rows if row['event'] == 'failure'])
        self.assertEqual([row['sequence'] for row in rows], list(range(1, len(rows) + 1)))
        for row in rows:
            self.assertEqual(row['schema'], SCHEMA)
            self.assertEqual(row['mode'], 'rehearsal')
            self.assertIn(row.keys() - ROWS, [set(shape.split()) for shape in EVENT_FIELDS[row['event']]])
        self.assertNotIn(CONTENT.strip(), output.getvalue())
        self.assertEqual(rows[-1]['classification'], 'rehearsal_passed')
        self.assertTrue(all(row.get('outcome') == 'NOT RUN' for row in rows
                            if row['event'] in ('direct_access', 'non_admitted_peer')))
        broker_ready = [row for row in rows if row['event'] == 'broker_ready']
        self.assertEqual(len({row['pid'] for row in broker_ready}), 4)
        self.assertEqual(len({json.dumps(row['storage_pins'], sort_keys=True) for row in broker_ready}), 1)
        kills = [row for row in rows if row['event'] == 'broker_interrupted']
        self.assertEqual([(row['case'], row['signal']) for row in kills],
                         [(name, signal.SIGKILL) for name in ('d1', 'd2', 'd3')])
        gates = {row['case']: row['edge'] for row in rows if row['event'] == 'gate'}
        self.assertEqual(gates, {name: case.gate for name, case in CASES.items() if case.gate})
        counters = [row for row in rows if row['event'] == 'publication_counters']
        self.assertTrue(all(not row['calls'] and not row['links'] for row in counters if row['recovery']))
        self.assertEqual(counters[-1]['expected_zero'], sorted(NO_CALL))
        self.assertEqual(set(counters[-1]['total']), CASES.keys() - NO_CALL)
        self.assertTrue(all(value['calls'] == value['links'] == 1 for value in counters[-1]['total'].values()))
        file_events = [row for row in rows if row['event'] == 'independent_filesystem' and row['final']]
        self.assertTrue(all(row['file']['sha256'] == DIGEST for row in file_events))
        self.assertEqual({row['case'] for row in rows if row['event'] == 'audit_verified'
                          and row['events'][-1]['state'] == 'uncertain'}, {'d2', 'd3'})
        self.assertEqual(len([row for row in rows if row['event'] == 'process_started']),
                         len([row for row in rows if row['event'] == 'process_exited']))


if __name__ == '__main__':
    unittest.main()
