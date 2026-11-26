# SPDX-License-Identifier: Apache-2.0
"""D.2C.1 qualification with authenticated Unix RPC, pinned SQLite and real files."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager, redirect_stdout
from dataclasses import replace
from hashlib import sha256
from io import BytesIO, StringIO, TextIOWrapper
import json
import multiprocessing
import os
from pathlib import Path
from secrets import token_urlsafe
import shutil
import signal
import socket
import sqlite3
import stat
from tempfile import TemporaryDirectory
from threading import Barrier, Event
import unittest
from unittest.mock import patch

from experiments.objective_registry import Error, RegistryError
from experiments.registry_operational import POLICY_FILE, PolicyPin
from experiments.registry_rpc import VERSION as REGISTRY
from experiments.supervision_operational import DATABASE as SUPERVISED_DB, initialize_supervision_database
from experiments.workspace_document import (CAPABILITY, FINAL, MAX_CONTENT, DocumentCreate, enroll_workspace,
                                            resource_path, stage_name)
from experiments.workspace_effect_lab import (DATABASE, ENDPOINT, VERSION, WorkspaceEffects,
                                              initialize_workspace_database, serve_workspace)
from experiments.workspace_effect_storage import Scope, WorkspaceRegistry
from loopbridge.protocol import DeadlineChannel, Fault, MAX_FRAME, RPC
from tools.workspace_effect import main as client_main

WALL = 1_780_000_000
WAIT = 8
CONTENT = 'Olá, workspace!\n`touch side-effect` and $(false) are data.\n'


def opaque(number):
    return f'{number:032x}'


ADMIN, ISSUER, EXECUTOR, SUPERVISOR, OBSERVER, AUDITOR = map(opaque, range(1, 7))
TARGET, OBJECTIVE, RESOURCE, OTHER, ATTEMPT = map(opaque, range(10, 15))


def envelope(identity, method, **params):
    return dict(jsonrpc='2.0', id=identity, version=VERSION, method=method, params=params)


def digest(content):
    return sha256(content.encode()).hexdigest()


def scope(attempt=ATTEMPT, resource=RESOURCE, content=CONTENT):
    return Scope(attempt, TARGET, OBJECTIVE, 3, CAPABILITY, resource, digest(content))


def grant_attempt(effects, target, *, deadline=WALL + 1000):
    for subject, permissions in (
        (ISSUER, ('authorize',)), (EXECUTOR, ('perform',)),
        (SUPERVISOR, ('step', 'continue', 'cancel', 'pause')),
        (OBSERVER, ('status',)), (AUDITOR, ('audit',)),
    ):
        for permission in permissions:
            effects.grant(subject, permission, target, expires_at=deadline)


def crash_broker(root, resources, db_pin, policy_pin, gate, at):
    def stopped(*args):
        gate.send('barrier')
        Event().wait()

    target = DocumentCreate if at == 'after_link' else WorkspaceEffects
    method = 'inspect' if at == 'after_link' else '_boundary'
    with patch.object(target, method, side_effect=stopped), serve_workspace(
            root, resources=resources, database_pin=db_pin, policy_pin=policy_pin,
            wall_clock=lambda: WALL) as (endpoint, effects, _):
        grant_attempt(effects, scope())
        gate.send(endpoint)
        gate.recv()


class DocumentRequest(unittest.TestCase):
    def test_utf8_is_not_normalized_or_interpreted(self):
        text = 'e\u0301\n$(false)'
        self.assertEqual(DocumentCreate.validate_request(text), text.encode('utf-8'))
        self.assertNotEqual(DocumentCreate.validate_request(text), 'é\n$(false)'.encode('utf-8'))

    def test_bounds_apply_to_utf8_bytes(self):
        limit = 'é' * (MAX_CONTENT // 2)
        self.assertEqual(len(DocumentCreate.validate_request(limit)), MAX_CONTENT)
        for payload in (None, b'hello', limit + 'a', '\ud800', 'text\0'):
            with self.assertRaisesRegex(Fault, '^invalid_params$'):
                DocumentCreate.validate_request(payload)


class WorkspaceEffectRPC(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='loop-d2c1-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.clock = WALL
        self.tokens = {principal: token_urlsafe(32)
                       for principal in (ADMIN, ISSUER, EXECUTOR, SUPERVISOR, OBSERVER, AUDITOR)}
        raw = json.dumps(dict(
            version=1, generation=1, retired_verifiers=[],
            principals={actor: digest(token) for actor, token in self.tokens.items()},
            grants=[dict(principal=who, scope=permission, executor=TARGET, expires_unix=WALL + 1000)
                    for who, permission in (
                        (ADMIN, 'registry.executor.register'), (EXECUTOR, 'registry.executor.confirm'),
                        (ISSUER, 'registry.objective.author'), (EXECUTOR, 'registry.objective.respond'),
                    )],
        )).encode()
        self.policy_pin = PolicyPin(1, sha256(raw).hexdigest())
        with open(self.root / POLICY_FILE, 'xb', opener=self.private_open) as policy:
            policy.write(raw)
        self.resources = {resource: enroll_workspace(self.root, resource) for resource in (RESOURCE, OTHER)}
        self.db_pin = initialize_workspace_database(self.root, wall_clock=lambda: self.clock)
        self.db_path = self.root / DATABASE

    @staticmethod
    def private_open(path, flags):
        return os.open(path, flags, 0o600)

    def path(self, resource=RESOURCE):
        return resource_path(self.root, resource) / FINAL

    @contextmanager
    def service(self):
        with serve_workspace(self.root, resources=self.resources, database_pin=self.db_pin,
                             policy_pin=self.policy_pin, wall_clock=lambda: self.clock) as profile:
            self.endpoint, self.effects, self.registry_control = profile
            self.assertEqual(stat.S_IMODE(self.endpoint.stat().st_mode), 0o600)
            yield profile
        self.assertFalse((self.root / ENDPOINT).exists())

    @contextmanager
    def client(self, actor, version=VERSION, endpoint=None):
        with socket.socket(socket.AF_UNIX) as peer:
            peer.connect(str(endpoint or self.endpoint))
            rpc = RPC(peer, version, timeout=2 * WAIT)
            if actor is not None:
                self.assertEqual(rpc.call('auth', credential=self.tokens[actor])['principal'], actor)
            yield rpc

    def call(self, actor, method, **params):
        with self.client(actor) as rpc:
            return rpc.call(f'effect.{method}', **params)

    def fault(self, reason, action, *args, **kwargs):
        with self.assertRaisesRegex(Fault, f'^{reason}$'):
            action(*args, **kwargs)

    def register_accept(self):
        with self.client(ADMIN, REGISTRY) as rpc:
            rpc.call('executor.register', request_id=opaque(20), executor_id=TARGET,
                     bound_principal_id=EXECUTOR, label='workspace fixture')
        with self.client(EXECUTOR, REGISTRY) as rpc:
            rpc.call('executor.confirm', request_id=opaque(21), executor_id=TARGET, expected_revision=1)
        with self.client(ISSUER, REGISTRY) as rpc:
            rpc.call('objective.create', request_id=opaque(22), objective_id=OBJECTIVE, executor_id=TARGET,
                     text=f'$(touch {self.root / "objective-sentinel"})', ttl_seconds=600)
            rpc.call('objective.offer', request_id=opaque(23), objective_id=OBJECTIVE, expected_revision=1)
        with self.client(EXECUTOR, REGISTRY) as rpc:
            rpc.call('objective.respond', request_id=opaque(24), objective_id=OBJECTIVE,
                     expected_revision=2, decision='accept')

    def authorize(self, actor=ISSUER, **changes):
        params = dict(attempt_id=ATTEMPT, executor_id=TARGET, objective_id=OBJECTIVE, accepted_revision=3,
                      capability=CAPABILITY, resource_id=RESOURCE, content=CONTENT, request_id=opaque(30),
                      ttl_seconds=120)
        return self.call(actor, 'authorize', **(params | changes))

    def control(self, action, revision, request, *, actor=SUPERVISOR, attempt=ATTEMPT):
        return self.call(actor, action, attempt_id=attempt, expected_revision=revision, request_id=opaque(request))

    def status(self, attempt=ATTEMPT):
        return self.call(OBSERVER, 'status', attempt_id=attempt)

    def audit(self, attempt=ATTEMPT, after=0):
        return self.call(AUDITOR, 'audit', attempt_id=attempt, after_revision=after)

    def ready(self):
        self.register_accept()
        grant_attempt(self.effects, scope())
        return self.authorize()

    def assert_state(self, state, mode, effect, *, attempt=ATTEMPT):
        view = self.status(attempt)
        self.assertEqual((view['state'], view['supervision'], view['effect']), (state, mode, effect))
        return view['revision']

    def reissue_reads(self):
        self.effects.grant(OBSERVER, 'status', scope(), expires_at=WALL + 1000)
        self.effects.grant(AUDITOR, 'audit', scope(), expires_at=WALL + 1000)

    def test_real_two_step_document_with_separate_audit_and_reference_client(self):
        with self.service():
            self.assertEqual(self.ready(), dict(id=ATTEMPT, revision=1, kind='admitted'))
            self.assert_state('ready', 'paused', 'none')
            self.assertEqual(list(self.path().parent.iterdir()), [])
            self.assertEqual(self.control('step', 1, 31), dict(id=ATTEMPT, revision=2, kind='step'))
            revision = self.assert_state('prepared', 'paused', 'none')
            self.assertFalse(self.path().exists())
            self.assertEqual(len(list(self.path().parent.iterdir())), 1)
            self.control('step', revision, 32)
            self.assert_state('completed', 'stopped', 'confirmed')
            audit = self.audit()
            self.assertEqual([event['kind'] for event in audit['events']],
                             'admitted step preparing prepared step dispatched effect_observed completed'.split())
            self.assertEqual(audit['scope']['digest'], digest(CONTENT))
            self.assertNotEqual(audit['operation_id'], ATTEMPT)
            self.assertEqual(audit['performer'], EXECUTOR)
            final = self.path()
            self.assertEqual(final.read_bytes(), CONTENT.encode())
            self.assertTrue(stat.S_ISREG(final.lstat().st_mode))
            self.assertEqual(stat.S_IMODE(final.lstat().st_mode), 0o600)
            stage = final.parent / stage_name(audit['operation_id'])
            self.assertEqual(final.stat().st_ino, stage.stat().st_ino)
            self.assertEqual(final.stat().st_nlink, 2)
            self.assertFalse((self.root / 'objective-sentinel').exists())
            wire = json.dumps(audit)
            for hidden in (str(self.root), 'touch side-effect', *self.tokens.values()):
                self.assertNotIn(hidden, wire)
            self.assertNotIn(b'touch side-effect', self.db_path.read_bytes())
            output = StringIO()
            with patch('tools.workspace_effect.getpass', return_value=self.tokens[OBSERVER]), redirect_stdout(output):
                self.assertEqual(client_main(['--socket', str(self.endpoint), 'status', ATTEMPT]), 0)
            self.assertEqual(json.loads(output.getvalue()), self.status())
            with closing(sqlite3.connect(self.db_path)) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(db.execute('PRAGMA application_id').fetchone(), (WorkspaceRegistry.application_id,))
                self.assertEqual(db.execute("SELECT count(*) FROM sqlite_schema WHERE name GLOB 'execution_*'").fetchone(),
                                 (0,))

    def test_exact_grants_and_observer_cannot_mutate(self):
        with self.service():
            self.register_accept()
            self.fault('denied', self.authorize)
            self.effects.grant(ISSUER, 'authorize', scope(), expires_at=WALL + 100)
            self.effects.grant(OBSERVER, 'perform', scope(), expires_at=WALL + 100)
            self.fault('denied', self.authorize)
            grant_attempt(self.effects, scope())
            for field, value in dict(executor_id=OTHER, objective_id=OTHER, accepted_revision=2,
                                     resource_id=OTHER, attempt_id=opaque(45), content='different').items():
                with self.subTest(field=field):
                    self.fault('denied', self.authorize, **{field: value})
            bad_revision = replace(scope(), accepted_revision=2)
            grant_attempt(self.effects, bad_revision)
            self.fault('denied', self.authorize, accepted_revision=2)
            self.fault('invalid_params', self.authorize, capability='workspace.document.update')
            self.fault('denied', self.authorize, OBSERVER)
            self.fault('denied', self.authorize, None)
            self.authorize()
            self.assert_state('ready', 'paused', 'none')
            for action in ('pause', 'step', 'continue', 'cancel'):
                self.fault('denied', self.control, action, 1, 74, actor=OBSERVER)
            self.fault('denied', self.audit, OTHER)
            self.fault('denied', self.call, OBSERVER, 'audit', attempt_id=ATTEMPT, after_revision=0)
            self.assertFalse(self.path().exists())

    def test_strict_payload_and_rpc_schema(self):
        with self.service():
            self.register_accept()
            grant_attempt(self.effects, scope())
            for content in ('', '\0', '\ud800', 'é' * (MAX_CONTENT // 2 + 1), 'x' * (MAX_CONTENT + 1),
                            {'text': CONTENT}, self.tokens[EXECUTOR]):
                self.fault('invalid_params', self.authorize, content=content)
            for value in ('../escape', '/abs/path', 'folder/file', 'A' * 32):
                self.fault('invalid_params', self.authorize, resource_id=value)
            self.fault('invalid_params', self.authorize, path='/external')
            self.fault('invalid_params', self.authorize, accepted_revision=True)
            self.fault('invalid_params', self.authorize, ttl_seconds=301)
            self.fault('method_not_found', self.call, ISSUER, 'enroll', resource_id=OTHER)
            with self.client(ISSUER) as rpc:
                self.fault('method_not_found', rpc.call, 'execution.start', attempt_id=ATTEMPT)
                self.fault('method_not_found', rpc.call, 'snapshot', session='workspace')
            with self.client(ISSUER, REGISTRY) as rpc:
                self.fault('method_not_found', rpc.call, 'effect.status', attempt_id=ATTEMPT)
            with socket.socket(socket.AF_UNIX) as peer:
                peer.connect(str(self.endpoint))
                peer.settimeout(WAIT)
                peer.sendall(b'x' * MAX_FRAME + b'\n')
                try:
                    self.assertEqual(peer.recv(1), b'')
                except ConnectionResetError:
                    pass  # Closing with unread bytes can reset the socket.
            with socket.socket(socket.AF_UNIX) as peer:
                peer.connect(str(self.endpoint))
                peer.settimeout(WAIT)
                peer.sendall(json.dumps(envelope(1, 'auth', credential=self.tokens[ISSUER])).encode() + b'\n')
                data, ancillary, _, _ = peer.recvmsg(8192, socket.CMSG_SPACE(32))
                self.assertTrue(data)
                self.assertEqual(ancillary, [])
                peer.sendall(b'{"jsonrpc":"2.0","id":2,"id":3,"version":"workspace-effect/1",'
                             b'"method":"effect.status","params":{}}\n')
                self.assertEqual(peer.recv(1), b'')
            self.assertFalse(self.path().exists())

    def test_reference_client_submits_maximum_utf8_bytes(self):
        text = 'é' * (MAX_CONTENT // 2)
        with self.service():
            self.register_accept()
            grant_attempt(self.effects, scope(content=text))
            args = ['--socket', str(self.endpoint), 'authorize', ATTEMPT, TARGET, OBJECTIVE, '3',
                    RESOURCE, opaque(30), '120']
            output = StringIO()
            with TextIOWrapper(BytesIO(text.encode())) as body, patch('tools.workspace_effect.sys.stdin', body), \
                    patch('tools.workspace_effect.getpass', return_value=self.tokens[ISSUER]), redirect_stdout(output):
                self.assertEqual(client_main(args), 0)
            self.assertEqual(json.loads(output.getvalue())['kind'], 'admitted')
            self.control('continue', 1, 31)
            self.assertEqual(self.path().read_bytes(), text.encode())

    def test_rejects_occupied_destination_and_symlink_without_overwrite(self):
        with self.service():
            self.register_accept()
            grant_attempt(self.effects, scope())
            final = self.path()
            final.write_bytes(CONTENT.encode())
            original = final.stat().st_ino
            self.fault('destination_exists', self.authorize)
            self.assertEqual(final.stat().st_ino, original)
            final.unlink()
            sentinel = self.root / 'outside'
            sentinel.write_bytes(b'unchanged')
            final.symlink_to(sentinel)
            self.fault('destination_exists', self.authorize)
            self.assertTrue(final.is_symlink())
            self.assertEqual(sentinel.read_bytes(), b'unchanged')

    def test_resource_directory_symlink_and_replacement_are_refused(self):
        with self.service():
            self.ready()
            self.control('step', 1, 31)
            parent = self.path().parent
            old = self.root / 'displaced'
            parent.rename(old)
            parent.symlink_to(old, target_is_directory=True)
            self.control('step', self.status()['revision'], 32)
            self.assert_state('failed', 'stopped', 'absent')
            self.assertFalse((old / FINAL).exists())
            parent.unlink()
            parent.mkdir(mode=0o700)
            fresh = opaque(40)
            grant_attempt(self.effects, scope(attempt=fresh))
            self.fault('resource_unavailable', self.authorize, attempt_id=fresh, request_id=opaque(41))
            self.assertFalse(self.path().exists())

    def test_substituted_stage_symlink_cannot_publish(self):
        with self.service():
            self.ready()
            self.control('step', 1, 31)
            stage = next(self.path().parent.glob('.stage-*'))
            sentinel = self.root / 'outside'
            sentinel.write_bytes(CONTENT.encode())
            stage.unlink()
            stage.symlink_to(sentinel)
            self.control('step', self.status()['revision'], 32)
            self.assert_state('failed', 'stopped', 'absent')
            self.assertFalse(self.path().exists())
            self.assertTrue(stage.is_symlink())
            self.assertEqual(sentinel.read_bytes(), CONTENT.encode())

    def test_modified_stage_bytes_cannot_publish(self):
        with self.service():
            self.ready()
            self.control('step', 1, 31)
            stage = next(self.path().parent.glob('.stage-*'))
            stage.write_bytes(b'x' * len(CONTENT.encode()))
            self.control('step', self.status()['revision'], 32)
            self.assert_state('failed', 'stopped', 'absent')
            self.assertFalse(self.path().exists())

    def test_database_pin_fences_live_publication_and_startup(self):
        reached, release = Event(), Event()
        boundary = WorkspaceEffects._boundary

        def delayed(*args):
            reached.set()
            self.assertTrue(release.wait(WAIT))
            return boundary(*args)

        with self.service(), patch.object(WorkspaceEffects, '_boundary', autospec=True, side_effect=delayed):
            self.ready()
            self.control('step', 1, 31)
            revision = self.status()['revision']
            with ThreadPoolExecutor() as executor:
                future = executor.submit(self.control, 'step', revision, 32)
                try:
                    self.assertTrue(reached.wait(WAIT))
                    moved = self.db_path.with_suffix('.old')
                    self.db_path.rename(moved)
                    shutil.copy2(moved, self.db_path)
                finally:
                    release.set()
                self.fault('storage_unavailable', future.result, WAIT)
            self.assertFalse(self.path().exists())
        with self.assertRaises(RegistryError) as caught, self.service():
            self.fail('replacement database accepted')
        self.assertIs(caught.exception.code, Error.STORAGE_UNAVAILABLE)

    def test_historical_schema_is_rejected_even_with_matching_inode(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            historical = initialize_supervision_database(root, wall_clock=lambda: WALL)
            shutil.copy2(self.root / POLICY_FILE, root / POLICY_FILE)
            (root / SUPERVISED_DB).rename(root / DATABASE)
            with self.assertRaises(RegistryError) as caught, serve_workspace(
                    root, resources=self.resources, database_pin=historical, policy_pin=self.policy_pin,
                    wall_clock=lambda: WALL):
                self.fail('execution/2 schema accepted')
            self.assertIs(caught.exception.code, Error.INVALID_STORAGE)

    def test_pause_cancel_revoke_replacement_and_expiry_before_link(self):
        for index, decision in enumerate(('pause', 'cancel', 'revoked', 'replaced', 'expired', 'advance_expired')):
            with self.subTest(decision=decision):
                self._before_boundary(decision, index)

    def _before_boundary(self, decision, index):
        reached, release = Event(), Event()
        boundary = WorkspaceEffects._boundary
        resource = opaque(80 + index)
        self.resources[resource] = enroll_workspace(self.root, resource)
        target = scope(attempt=opaque(90 + index), resource=resource)

        def delayed(*args):
            reached.set()
            self.assertTrue(release.wait(WAIT))
            return boundary(*args)

        base_time = self.clock
        with self.service(), patch.object(WorkspaceEffects, '_boundary', autospec=True, side_effect=delayed):
            if index == 0:
                self.register_accept()
            grant_attempt(self.effects, target)
            if decision == 'advance_expired':
                self.effects.grant(SUPERVISOR, 'step', target, expires_at=base_time + 5)
            self.authorize(attempt_id=target.attempt_id, resource_id=resource, request_id=opaque(100 + index),
                           ttl_seconds=5 if decision == 'expired' else 120)
            self.control('step', 1, 31, attempt=target.attempt_id)
            revision = self.status(target.attempt_id)['revision']
            with ThreadPoolExecutor() as executor:
                future = executor.submit(self.control, 'step', revision, 32, attempt=target.attempt_id)
                try:
                    self.assertTrue(reached.wait(WAIT))
                    revision = self.assert_state('dispatched', 'stepping', 'pending', attempt=target.attempt_id)
                    if decision in ('pause', 'cancel'):
                        self.control(decision, revision, 33, attempt=target.attempt_id)
                    elif decision == 'revoked':
                        self.effects.revoke(EXECUTOR, 'perform', target)
                    elif decision == 'replaced':
                        self.effects.grant(EXECUTOR, 'perform', target, expires_at=WALL + 1000)
                    else:
                        self.clock = base_time + 5
                    self.assertFalse(self.path(resource).exists())
                finally:
                    release.set()
                self.assertEqual(future.result(WAIT)['kind'], 'step')
            expected = {
                'pause': ('prepared', 'paused', 'none'),
                'cancel': ('cancelled', 'stopped', 'absent'),
                'revoked': ('revoked', 'stopped', 'absent'),
                'replaced': ('revoked', 'stopped', 'absent'),
                'expired': ('expired', 'stopped', 'absent'),
                'advance_expired': ('expired', 'stopped', 'absent'),
            }
            self.assertFalse(self.path(resource).exists())
            self.assert_state(*expected[decision], attempt=target.attempt_id)
            if decision == 'pause':
                revision = self.status(target.attempt_id)['revision']
                self.control('step', revision, 34, attempt=target.attempt_id)
                self.assert_state('completed', 'stopped', 'confirmed', attempt=target.attempt_id)
                self.assertEqual(self.path(resource).read_bytes(), CONTENT.encode())

    def test_last_clock_check_follows_resource_preconditions(self):
        validate = DocumentCreate.validate_publication

        def expire_during_resource_check(*args):
            validate(*args)
            self.clock = WALL + 5

        with self.service(), patch.object(DocumentCreate, 'validate_publication', autospec=True,
                                          side_effect=expire_during_resource_check):
            self.register_accept()
            grant_attempt(self.effects, scope())
            self.effects.grant(EXECUTOR, 'perform', scope(), expires_at=WALL + 5)
            self.authorize()
            self.control('continue', 1, 31)
            self.assert_state('expired', 'stopped', 'absent')
            self.assertFalse(self.path().exists())

    def test_pause_during_preparation_drains_to_paused_without_dispatch(self):
        reached, release = Event(), Event()
        prepare = DocumentCreate.prepare

        def delayed(*args):
            reached.set()
            self.assertTrue(release.wait(WAIT))
            return prepare(*args)

        with self.service(), patch.object(DocumentCreate, 'prepare', autospec=True, side_effect=delayed):
            self.ready()
            with ThreadPoolExecutor() as executor:
                future = executor.submit(self.control, 'continue', 1, 31)
                try:
                    self.assertTrue(reached.wait(WAIT))
                    revision = self.assert_state('preparing', 'flowing', 'none')
                    self.control('pause', revision, 32)
                    self.assert_state('preparing', 'pause_requested', 'none')
                    self.assertFalse(self.path().exists())
                finally:
                    release.set()
                future.result(WAIT)
            self.assert_state('prepared', 'paused', 'none')
            self.assertNotIn('dispatched', [row['kind'] for row in self.audit()['events']])
            self.assertFalse(self.path().exists())

    def test_revocation_pause_cancel_and_expiry_after_link_preserve_effect(self):
        reached, release = Event(), Event()
        inspect = DocumentCreate.inspect

        def delayed(*args):
            reached.set()
            self.assertTrue(release.wait(WAIT))
            return inspect(*args)

        with self.service(), patch.object(DocumentCreate, 'inspect', autospec=True, side_effect=delayed):
            self.register_accept()
            grant_attempt(self.effects, scope())
            self.authorize(ttl_seconds=5)
            with ThreadPoolExecutor() as executor:
                future = executor.submit(self.control, 'continue', 1, 31)
                try:
                    self.assertTrue(reached.wait(WAIT))
                    self.assertEqual(self.path().read_bytes(), CONTENT.encode())
                    revision = self.assert_state('dispatched', 'flowing', 'pending')
                    self.effects.revoke(EXECUTOR, 'perform', scope())
                    self.clock = WALL + 5
                    self.fault('effect_boundary_closed', self.control, 'pause', revision, 32)
                    self.fault('effect_boundary_closed', self.control, 'cancel', revision, 33)
                finally:
                    release.set()
                future.result(WAIT)
            self.assert_state('completed', 'stopped', 'confirmed')
            self.assertEqual(self.path().read_bytes(), CONTENT.encode())

    def test_registry_principal_disable_is_serialized_with_the_effect_boundary(self):
        reached, release = Event(), Event()
        boundary = WorkspaceEffects._boundary

        def delayed(*args):
            reached.set()
            self.assertTrue(release.wait(WAIT))
            return boundary(*args)

        with self.service(), patch.object(WorkspaceEffects, '_boundary', autospec=True, side_effect=delayed):
            self.ready()
            with ThreadPoolExecutor() as executor:
                future = executor.submit(self.control, 'continue', 1, 31)
                try:
                    self.assertTrue(reached.wait(WAIT))
                    policy = self.root / POLICY_FILE
                    changed = json.loads(policy.read_bytes())
                    changed['generation'] = 2
                    changed['retired_verifiers'] = [changed['principals'][EXECUTOR]]
                    changed['principals'][EXECUTOR] = None
                    changed['grants'] = [row for row in changed['grants'] if row['principal'] != EXECUTOR]
                    raw = json.dumps(changed).encode()
                    replacement = self.root / 'new-policy'
                    with open(replacement, 'xb', opener=self.private_open) as target:
                        target.write(raw)
                    replacement.replace(policy)
                    self.registry_control.reload(PolicyPin(2, sha256(raw).hexdigest()))
                finally:
                    release.set()
                future.result(WAIT)
            self.assert_state('revoked', 'stopped', 'absent')
            self.assertFalse(self.path().exists())

    def test_duplicate_admission_and_payload_or_resource_replay_conflicts(self):
        gate = Barrier(2)

        def duplicate():
            gate.wait(WAIT)
            return self.authorize()

        with self.service(), ThreadPoolExecutor() as executor:
            self.register_accept()
            grant_attempt(self.effects, scope())
            requests = [executor.submit(duplicate) for _ in range(2)]
            receipts = [request.result(WAIT) for request in requests]
            self.assertEqual(receipts, [dict(id=ATTEMPT, revision=1, kind='admitted')] * 2)
            for changes in (dict(content='other payload'), dict(resource=OTHER)):
                changed = scope(**changes)
                grant_attempt(self.effects, changed)
                self.fault('request_conflict', self.authorize, resource_id=changed.resource_id,
                           content=changes.get('content', CONTENT))
            self.fault('request_conflict', self.authorize, request_id=opaque(46))
            self.control('step', 1, 31)
            self.fault('request_conflict', self.control, 'cancel', 1, 31)
            self.fault('stale_revision', self.control, 'step', 1, 33)
            self.assert_state('prepared', 'paused', 'none')

    def test_audit_pagination_and_reserved_cancel_at_receipt_capacity(self):
        with self.service():
            self.ready()
            revision = 1
            for i in range(15):
                revision = self.control('pause', revision, 100 + i)['revision']
            self.fault('capacity', self.control, 'step', revision, 120)
            self.fault('capacity', self.control, 'pause', revision, 121)
            self.control('cancel', revision, 122)
            self.assert_state('cancelled', 'stopped', 'absent')
            first = self.audit()
            self.assertEqual(first['next_after'], 12)
            second = self.audit(after=first['next_after'])
            self.assertIsNone(second['next_after'])
            self.assertEqual([event['revision'] for event in first['events'] + second['events']],
                             list(range(1, 18)))

    def test_concurrent_publication_for_one_resource_has_one_winner(self):
        gate = Barrier(2)
        boundary = WorkspaceEffects._boundary

        def delayed(*args):
            gate.wait(WAIT)
            return boundary(*args)

        with self.service():
            self.ready()
            other_attempt = opaque(54)
            other_text = 'second attempt'
            grant_attempt(self.effects, scope(attempt=other_attempt, content=other_text))
            self.authorize(attempt_id=other_attempt, content=other_text, request_id=opaque(53))
            for attempt in (ATTEMPT, other_attempt):
                self.control('step', 1, 31, attempt=attempt)
            revisions = {attempt: self.status(attempt)['revision'] for attempt in (ATTEMPT, other_attempt)}
            with patch.object(WorkspaceEffects, '_boundary', autospec=True, side_effect=delayed), \
                    ThreadPoolExecutor() as executor:
                futures = [executor.submit(self.control, 'step', revision, 32, attempt=attempt)
                           for attempt, revision in revisions.items()]
                for future in futures:
                    future.result(WAIT)
            results = {attempt: self.status(attempt)['state'] for attempt in revisions}
            self.assertCountEqual(results.values(), ('completed', 'failed'))
            winner = next(attempt for attempt in results if results[attempt] == 'completed')
            expected = CONTENT if winner == ATTEMPT else other_text
            self.assertEqual(self.path().read_bytes(), expected.encode())
            self.assertEqual(len(list(self.path().parent.glob(FINAL))), 1)
            loser = other_attempt if winner == ATTEMPT else ATTEMPT
            self.assertEqual(self.audit(loser)['events'][-1]['reason'], 'destination_exists')

    def test_preparation_failure_proves_no_publication(self):
        with self.service(), patch.object(DocumentCreate, 'prepare', side_effect=OSError):
            self.ready()
            self.control('continue', 1, 31)
            self.assert_state('failed', 'stopped', 'absent')
            self.assertFalse(self.path().exists())
            self.assertNotIn('dispatched', [row['kind'] for row in self.audit()['events']])

    def test_ambiguous_link_error_with_absence_is_uncertain(self):
        with self.service(), patch.object(DocumentCreate, 'apply', side_effect=OSError):
            self.ready()
            self.control('continue', 1, 31)
            self.assert_state('uncertain', 'stopped', 'unknown')
            self.assertEqual(self.audit()['events'][-1]['reason'], 'absent')
            self.assertFalse(self.path().exists())

    def test_ambiguous_link_reply_is_resolved_from_actual_file(self):
        apply = DocumentCreate.apply

        def link_then_fail(*args):
            apply(*args)
            raise OSError('simulated syscall reply failure')

        with self.service(), patch.object(DocumentCreate, 'apply', side_effect=link_then_fail):
            self.ready()
            self.control('continue', 1, 31)
            self.assert_state('completed', 'stopped', 'confirmed')
            self.assertEqual(self.audit()['events'][-2]['reason'], 'publication_error')
            self.assertEqual(self.path().read_bytes(), CONTENT.encode())

    def test_sync_failure_keeps_observed_effect_and_restart_confirms_without_apply(self):
        with self.service(), patch.object(DocumentCreate, 'synchronize', side_effect=OSError):
            self.ready()
            self.control('continue', 1, 31)
            self.assert_state('uncertain', 'stopped', 'observed')
            self.assertEqual(self.audit()['events'][-1]['reason'], 'sync_unconfirmed')
            pin = self.path().stat().st_ino
        with patch.object(DocumentCreate, 'apply') as apply, self.service():
            self.fault('denied', self.audit)
            self.reissue_reads()
            self.assert_state('reconciled', 'stopped', 'confirmed')
            apply.assert_not_called()
            self.assertEqual(self.path().stat().st_ino, pin)
            self.assertEqual(self.path().read_bytes(), CONTENT.encode())

    def test_lost_rpc_reply_preserves_command_receipt_and_terminal_history(self):
        send = DeadlineChannel.send
        withheld = Event()

        def lose_reply(channel, value):
            if (value.get('version') == VERSION and value.get('result', {}).get('kind') == 'step'
                    and value['result']['revision'] == 5 and not withheld.is_set()):
                withheld.set()
                raise BrokenPipeError
            return send(channel, value)

        with self.service(), patch.object(DeadlineChannel, 'send', autospec=True, side_effect=lose_reply):
            self.ready()
            self.control('step', 1, 31)
            revision = self.status()['revision']
            with self.assertRaises(EOFError):
                self.control('step', revision, 32)
            self.assertTrue(withheld.is_set())
            inode = self.path().stat().st_ino
            receipt = self.control('step', revision, 32)
            self.assertEqual(receipt, dict(id=ATTEMPT, revision=5, kind='step'))
            audit = self.audit()
            self.assertEqual(audit['state'], 'completed')
            self.assertEqual(self.authorize()['revision'], 1)
        with patch.object(DocumentCreate, 'apply') as apply, self.service():
            self.fault('denied', self.control, 'step', revision, 32)
            self.reissue_reads()
            self.effects.grant(SUPERVISOR, 'step', scope(), expires_at=WALL + 1000)
            self.assertEqual(self.control('step', revision, 32), receipt)
            self.assertEqual(self.audit(), audit)
            self.assertEqual(self.path().stat().st_ino, inode)
            apply.assert_not_called()

    def test_termination_after_link_reconciles_pinned_document_and_requires_new_grants(self):
        self.crash('after_link')
        final = self.path()
        inode = final.stat().st_ino
        with patch.object(DocumentCreate, 'apply', wraps=DocumentCreate.apply) as apply, self.service():
            self.fault('denied', self.status)
            self.fault('denied', self.authorize)
            self.reissue_reads()
            revision = self.assert_state('reconciled', 'stopped', 'confirmed')
            apply.assert_not_called()
            self.assertEqual(final.stat().st_ino, inode)
            self.assertEqual(final.read_bytes(), CONTENT.encode())
            self.effects.grant(SUPERVISOR, 'step', scope(), expires_at=WALL + 1000)
            self.fault('invalid_state', self.control, 'step', revision, 49)
            new_scope = scope(attempt=opaque(56), resource=OTHER)
            self.fault('denied', self.authorize, attempt_id=new_scope.attempt_id, resource_id=OTHER, request_id=opaque(57))
            grant_attempt(self.effects, new_scope)
            self.authorize(attempt_id=new_scope.attempt_id, resource_id=OTHER, request_id=opaque(57))
            self.control('continue', 1, 31, attempt=new_scope.attempt_id)
            apply.assert_called_once()
            self.assertEqual(self.path(OTHER).read_bytes(), CONTENT.encode())

    def test_termination_after_dispatch_before_link_does_not_prove_absence_on_restart(self):
        self.crash('before_link')
        self.assertFalse(self.path().exists())
        with patch.object(DocumentCreate, 'apply') as apply, self.service():
            self.reissue_reads()
            self.assert_state('uncertain', 'stopped', 'unknown')
            self.assertEqual(self.audit()['events'][-1]['reason'], 'absent')
            apply.assert_not_called()
        self.assertFalse(self.path().exists())

    def test_missing_and_same_digest_unattributed_evidence_remain_uncertain(self):
        for scenario in ('missing_stage', 'same_digest', 'different_bytes', 'missing_resource'):
            with self.subTest(scenario=scenario):
                self._assert_contradictory_evidence(scenario)

    def _assert_contradictory_evidence(self, scenario):
        # Restore fixture attributes after temporarily running against independent storage.
        saved = (self.root, self.resources, self.db_pin, self.db_path)
        with TemporaryDirectory(prefix='loop-d2c1-evidence-') as directory:
            try:
                self.root = Path(directory)
                shutil.copy2(saved[0] / POLICY_FILE, self.root / POLICY_FILE)
                self.resources = {item: enroll_workspace(self.root, item) for item in (RESOURCE, OTHER)}
                self.db_pin = initialize_workspace_database(self.root, wall_clock=lambda: WALL)
                self.db_path = self.root / DATABASE
                self.crash('after_link')
                final = self.path()
                if scenario == 'missing_stage':
                    next(final.parent.glob('.stage-*')).unlink()
                elif scenario == 'same_digest':
                    final.unlink()
                    with open(final, 'xb', opener=self.private_open) as substitute:
                        substitute.write(CONTENT.encode())
                elif scenario == 'different_bytes':
                    final.write_bytes(b'x' * len(CONTENT.encode()))
                else:
                    final.parent.rename(self.root / 'missing')
                with patch.object(DocumentCreate, 'apply') as apply, self.service():
                    self.reissue_reads()
                    self.assert_state('uncertain', 'stopped', 'unknown')
                    reason = 'unavailable' if scenario == 'missing_resource' else 'conflicting'
                    self.assertEqual(self.audit()['events'][-1]['reason'], reason)
                    apply.assert_not_called()
                if scenario != 'missing_resource':
                    expected = b'x' * len(CONTENT.encode()) if scenario == 'different_bytes' else CONTENT.encode()
                    self.assertEqual(final.read_bytes(), expected)
            finally:
                self.root, self.resources, self.db_pin, self.db_path = saved

    def test_restart_before_dispatch_proves_absence_and_keeps_payload_out_of_database(self):
        with self.service():
            self.ready()
            self.control('step', 1, 31)
            self.assert_state('prepared', 'paused', 'none')
        with patch.object(DocumentCreate, 'apply') as apply, self.service():
            self.reissue_reads()
            self.assert_state('interrupted', 'stopped', 'absent')
            self.assertFalse(self.path().exists())
            apply.assert_not_called()
            self.assertNotIn(CONTENT.encode(), self.db_path.read_bytes())

    def test_confirmation_commit_failure_recovers_without_duplicate(self):
        commit = WorkspaceRegistry._commit

        def fail_confirmation(registry, db):
            row = db.execute('SELECT 1 FROM workspace_events WHERE kind=?', ('completed',)).fetchone()
            if row:
                raise sqlite3.OperationalError('simulated confirmation commit failure')
            return commit(registry, db)

        with self.service(), patch.object(WorkspaceRegistry, '_commit', autospec=True, side_effect=fail_confirmation):
            self.ready()
            self.fault('commit_unknown', self.control, 'continue', 1, 31)
            self.assert_state('dispatched', 'flowing', 'pending')
            self.assertEqual(self.path().read_bytes(), CONTENT.encode())
        with patch.object(DocumentCreate, 'apply') as apply, self.service():
            self.reissue_reads()
            self.assert_state('reconciled', 'stopped', 'confirmed')
            apply.assert_not_called()

    def crash(self, at):
        context = multiprocessing.get_context('spawn')
        guardian, child = context.Pipe()
        process = context.Process(target=crash_broker, args=(
            self.root, self.resources, self.db_pin, self.policy_pin, child, at))
        process.start()
        child.close()
        try:
            self.assertTrue(guardian.poll(WAIT))
            self.endpoint = guardian.recv()
            self.register_accept()
            self.authorize()
            with ThreadPoolExecutor() as executor:
                pending = executor.submit(self.control, 'continue', 1, 31)
                try:
                    self.assertTrue(guardian.poll(WAIT))
                    self.assertEqual(guardian.recv(), 'barrier')
                    self.assertEqual(self.path().exists(), at == 'after_link')
                finally:
                    process.kill()
                    process.join(WAIT)
                self.assertEqual(process.exitcode, -signal.SIGKILL)
                with self.assertRaises(EOFError):
                    pending.result(WAIT)
        finally:
            guardian.close()
            if process.is_alive():
                process.kill()
                process.join(WAIT)
        self.assertTrue(stat.S_ISSOCK(self.endpoint.lstat().st_mode))
        self.endpoint.unlink()  # This exact disposable endpoint belonged to the dead child.


if __name__ == '__main__':
    unittest.main()
