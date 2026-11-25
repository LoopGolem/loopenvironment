# SPDX-License-Identifier: Apache-2.0
"""Qualification of D.2A using disposable Unix sockets and actual SQLite commits."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from hashlib import sha256
import multiprocessing
from pathlib import Path
from secrets import token_urlsafe
import socket
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier, Event
import unittest
from unittest.mock import patch

from experiments.execution_lab import Permission, VERSION, serve_execution_lab
from experiments.execution_storage import ExecutionTransaction, OPERATION, Scope
from experiments.objective_registry import ExecutorAction, Permission as Delivery, RegistryError
from experiments.registry_lab import serve_registry
from experiments.registry_rpc import RegistryRequest, VERSION as REGISTRY
from loopbridge.identity import Identities
from loopbridge.protocol import Fault, RPC, VERSION as SESSION

WAIT = 6
WALL = 1_780_000_000


def opaque(number):
    return f'{number:032x}'


ADMIN, ISSUER, EXECUTOR, AUDITOR, CANCELLER, OTHER = map(opaque, range(1, 7))
EXECUTOR_ID, OBJECTIVE, REQUEST = map(opaque, (10, 11, 12))
SCOPE = Scope(EXECUTOR_ID, OBJECTIVE, 3, OPERATION)
DELIVERY_GRANTS = (
    (ADMIN, Delivery.REGISTER),
    (ADMIN, Delivery.MANAGE_EXECUTOR),
    (ISSUER, Delivery.AUTHOR_OBJECTIVE),
    (ISSUER, Delivery.READ_OBJECTIVE),
    (EXECUTOR, Delivery.CONFIRM),
    (EXECUTOR, Delivery.RESPOND_TO_OBJECTIVE),
)
EXECUTION_GRANTS = (
    (ISSUER, Permission.AUTHORIZE),
    (EXECUTOR, Permission.PERFORM),
    (AUDITOR, Permission.AUDIT),
    (CANCELLER, Permission.CANCEL),
)


def configure(broker, execution_grants):
    for principal, permission in DELIVERY_GRANTS:
        broker.access.policy.grant(principal, permission, EXECUTOR_ID, expires_at=WALL + 1000)
    for principal, permission in execution_grants:
        broker.execution.grant(principal, permission, SCOPE, expires_at=WALL + 1000)


def crashable_service(root, verifiers, guardian):
    def pause_at_operation():
        guardian.send('running')
        Event().wait()

    with serve_execution_lab(root, verifiers, create=True, wall_clock=lambda: WALL) as (endpoint, broker):
        configure(broker, EXECUTION_GRANTS)
        with patch('experiments.execution_lab._add_fixed_constants', side_effect=pause_at_operation):
            guardian.send(endpoint)
            guardian.recv()


class AuthorizedExecution(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='loop-d2a-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database = self.root / 'execution.sqlite3'
        self.clock = WALL
        self.tokens = {principal: token_urlsafe(32) for principal in
                       (ADMIN, ISSUER, EXECUTOR, AUDITOR, CANCELLER, OTHER)}
        self.verifiers = {principal: sha256(token.encode()).hexdigest()
                          for principal, token in self.tokens.items()}
        self.sentinel = self.root / 'must-not-exist'

    @contextmanager
    def service(self, *, create=True, grants=EXECUTION_GRANTS):
        with serve_execution_lab(self.root, self.verifiers, create=create,
                                 wall_clock=lambda: self.clock) as (endpoint, broker):
            configure(broker, grants)
            yield endpoint, broker
        self.assertFalse(endpoint.exists())

    @contextmanager
    def client(self, endpoint, principal=None, *, version=VERSION):
        with socket.socket(socket.AF_UNIX) as peer:
            peer.connect(str(endpoint))
            rpc = RPC(peer, version, timeout=WAIT * 2)
            if principal is not None:
                response = rpc.call('auth', credential=self.tokens[principal])
                self.assertEqual(response['principal'], principal)
                rpc.authenticated_connection = response['connection']
            yield rpc

    def call(self, endpoint, principal, method, **params):
        with self.client(endpoint, principal) as rpc:
            return rpc.call(method, **params)

    def auth_params(self, **overrides):
        return dict(dict(request_id=REQUEST, executor_id=EXECUTOR_ID, objective_id=OBJECTIVE,
                         accepted_revision=3, operation=OPERATION, ttl_seconds=60), **overrides)

    def authorize(self, endpoint, **overrides):
        return self.call(endpoint, ISSUER, 'execution.authorize', **self.auth_params(**overrides))

    def admit(self, endpoint, **overrides):
        return self.authorize(endpoint, **overrides)['id']

    def start(self, endpoint, attempt):
        return self.call(endpoint, EXECUTOR, 'execution.start', attempt_id=attempt)

    def cancel(self, endpoint, attempt):
        return self.call(endpoint, CANCELLER, 'execution.cancel', attempt_id=attempt)

    def audit(self, endpoint, attempt):
        return self.call(endpoint, AUDITOR, 'execution.audit', attempt_id=attempt)

    def expect_error(self, reason, call, *args, **kwargs):
        with self.assertRaises(Fault) as caught:
            call(*args, **kwargs)
        self.assertEqual(str(caught.exception), reason)
        self.assertIsNone(caught.exception.data)

    def delivery(self, endpoint, *, accept=True, ttl=600):
        with self.client(endpoint, ADMIN, version=REGISTRY) as rpc:
            self.assertEqual(rpc.call('executor.register', request_id=opaque(20), executor_id=EXECUTOR_ID,
                                      bound_principal_id=EXECUTOR, label='Disposable arithmetic'),
                             dict(id=EXECUTOR_ID, revision=1, state='pending'))
        with self.client(endpoint, EXECUTOR, version=REGISTRY) as rpc:
            self.assertEqual(rpc.call('executor.confirm', request_id=opaque(21), executor_id=EXECUTOR_ID,
                                      expected_revision=1)['state'], 'available')
        text = f'Untrusted objective: $(touch {self.sentinel})\npython -c "assert False"'
        with self.client(endpoint, ISSUER, version=REGISTRY) as rpc:
            self.assertEqual(rpc.call('objective.create', request_id=opaque(22), executor_id=EXECUTOR_ID,
                                      objective_id=OBJECTIVE, text=text, ttl_seconds=ttl)['state'], 'created')
            self.assertEqual(rpc.call('objective.offer', request_id=opaque(23), objective_id=OBJECTIVE,
                                      expected_revision=1)['state'], 'offered')
        if accept:
            with self.client(endpoint, EXECUTOR, version=REGISTRY) as rpc:
                self.assertEqual(rpc.call('objective.respond', request_id=opaque(24), objective_id=OBJECTIVE,
                                          expected_revision=2, decision='accept'),
                                 dict(id=OBJECTIVE, revision=3, state='accepted'))
        return text

    def assert_audit(self, endpoint, attempt, states):
        record = self.audit(endpoint, attempt)
        events = record['events']
        self.assertEqual([event['state'] for event in events], states.split())
        self.assertEqual([event['revision'] for event in events], list(range(1, len(events) + 1)))
        self.assertEqual(record['state'], events[-1]['state'])
        self.assertEqual(record['revision'], len(events))
        self.assertEqual([event['result'] for event in events],
                         [5 if event['state'] == 'completed' else None for event in events])
        return record

    def count_attempts(self):
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute('SELECT count(*) FROM execution_attempts').fetchone()[0]

    def test_acceptance_authorization_start_verified_result_and_scoped_audit(self):
        with self.service() as (endpoint, broker):
            text = self.delivery(endpoint)
            self.assertEqual(self.count_attempts(), 0)
            self.expect_error('denied', self.start, endpoint, opaque(99))
            receipt = self.authorize(endpoint)
            attempt = receipt['id']
            self.assertEqual(receipt, dict(id=attempt, state='admitted', revision=1))
            self.assert_audit(endpoint, attempt, 'admitted')
            self.assertEqual(self.start(endpoint, attempt), dict(id=attempt, state='completed', revision=3))
            record = self.assert_audit(endpoint, attempt, 'admitted running completed')
            self.assertEqual((record['authorizer'], record['performer'], record['request_id']),
                             (ISSUER, EXECUTOR, REQUEST))
            self.assertEqual((record['executor_id'], record['objective_id'], record['accepted_revision'],
                              record['operation'], record['expires_unix_ms']),
                             (EXECUTOR_ID, OBJECTIVE, 3, OPERATION, (WALL + 60) * 1000))
            self.assertEqual([item['actor'] for item in record['events']], [ISSUER, EXECUTOR, EXECUTOR])
            self.assertFalse(self.sentinel.exists())
            with self.client(endpoint, ISSUER, version=REGISTRY) as rpc:
                self.assertEqual(rpc.call('objective.status', objective_id=OBJECTIVE)['text'], text)
            with closing(sqlite3.connect(self.database)) as db:
                dump = '\n'.join(db.iterdump())
                for secret in (*self.tokens.values(), *self.verifiers.values()):
                    self.assertNotIn(secret, dump)
                execution_dump = '\n'.join(line for line in dump.splitlines() if line.startswith('INSERT INTO "execution_'))
                self.assertIn('execution_attempts', execution_dump)
                self.assertIn('execution_events', execution_dump)
                self.assertNotIn('touch', execution_dump)
                self.assertNotIn('python', execution_dump)
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_authentication_registry_grants_and_other_principals_do_not_confer_execution(self):
        with self.service(grants=()) as (endpoint, broker):
            self.delivery(endpoint)
            self.expect_error('denied', self.call, endpoint, None, 'execution.authorize', **self.auth_params())
            self.expect_error('denied', self.authorize, endpoint)
            broker.execution.grant(ISSUER, Permission.AUTHORIZE, SCOPE, expires_at=WALL+600)
            broker.execution.grant(OTHER, Permission.PERFORM, SCOPE, expires_at=WALL+600)
            self.expect_error('denied', self.authorize, endpoint)
            broker.execution.grant(EXECUTOR, Permission.PERFORM, SCOPE, expires_at=WALL+600)
            attempt = self.admit(endpoint)
            self.expect_error('denied', self.call, endpoint, OTHER, 'execution.start', attempt_id=attempt)
            self.expect_error('denied', self.call, endpoint, ISSUER, 'execution.cancel', attempt_id=attempt)
            for principal in (None, ISSUER, EXECUTOR, AUDITOR):
                self.expect_error('denied', self.call, endpoint, principal, 'execution.audit', attempt_id=attempt)
            self.assertEqual(self.count_attempts(), 1)

    def test_only_exact_executor_objective_and_accepted_revision_are_eligible(self):
        with self.service() as (endpoint, broker):
            self.delivery(endpoint, accept=False)
            self.expect_error('invalid_state', self.authorize, endpoint)
            with self.client(endpoint, EXECUTOR, version=REGISTRY) as rpc:
                rpc.call('objective.respond', request_id=opaque(24), objective_id=OBJECTIVE,
                         expected_revision=2, decision='accept')
            for proposed in (Scope(opaque(90), OBJECTIVE, 3, OPERATION),
                             Scope(EXECUTOR_ID, opaque(91), 3, OPERATION),
                             Scope(EXECUTOR_ID, OBJECTIVE, 2, OPERATION)):
                for principal, permission in EXECUTION_GRANTS[:2]:
                    broker.execution.grant(principal, permission, proposed, expires_at=WALL+600)
                self.expect_error('stale_revision' if proposed.accepted_revision == 2 else 'denied',
                                  self.authorize, endpoint, executor_id=proposed.executor_id,
                                  objective_id=proposed.objective_id, accepted_revision=proposed.accepted_revision)
            with self.assertRaisesRegex(ValueError, 'invalid_execution_grant'):
                broker.execution.grant(ISSUER, Permission.AUTHORIZE, Scope('*', OBJECTIVE, 3, OPERATION),
                                       expires_at=WALL+600)
            self.assertEqual(self.count_attempts(), 0)

    def test_explicit_authorizer_can_be_distinct_from_registry_issuer(self):
        with self.service(grants=EXECUTION_GRANTS[1:]) as (endpoint, broker):
            self.delivery(endpoint)
            broker.execution.grant(OTHER, Permission.AUTHORIZE, SCOPE, expires_at=WALL + 300)
            self.expect_error('denied', self.authorize, endpoint)
            receipt = self.call(endpoint, OTHER, 'execution.authorize', **self.auth_params())
            attempt = receipt['id']
            self.assertEqual(self.start(endpoint, attempt)['state'], 'completed')
            self.assertEqual(self.audit(endpoint, attempt)['authorizer'], OTHER)

    def test_typed_payload_unknown_methods_versions_and_duplicate_keys(self):
        with self.service() as (endpoint, _):
            self.delivery(endpoint)
            with self.client(endpoint, ISSUER) as rpc:
                for changes in (dict(operation='eval'), dict(operation=['add_fixed_constants']), dict(args=[2, 3]),
                                dict(principal_id=ISSUER), dict(accepted_revision=True),
                                dict(ttl_seconds=1.0), dict(ttl_seconds=301), dict(request_id='x')):
                    with self.subTest(changes=changes):
                        self.expect_error('invalid_params', rpc.call, 'execution.authorize',
                                          **self.auth_params(**changes))
                self.expect_error('invalid_params', rpc.call, 'execution.authorize')
                self.expect_error('invalid_params', rpc.call, 'execution.start', attempt_id=REQUEST, result=5)
                self.expect_error('method_not_found', rpc.call, 'execution.publish', attempt_id=REQUEST)
                self.expect_error('method_not_found', rpc.call, 'objective.status', objective_id=OBJECTIVE)
                self.expect_error('method_not_found', rpc.call, 'snapshot', session='session')
            for version in ('execution/2', SESSION):
                with self.client(endpoint, version=version) as rpc:
                    with self.assertRaises(EOFError):
                        rpc.call('execution.authorize', **self.auth_params())
            with self.client(endpoint, ISSUER, version=REGISTRY) as rpc:
                self.expect_error('method_not_found', rpc.call, 'execution.authorize', **self.auth_params())
            for bad in (b'{"attempt_id":"x","attempt_id":"y"}', b'{},"params":{}', b'{"attempt_id":NaN}'):
                with self.client(endpoint, ISSUER) as rpc:
                    rpc.channel.sock.sendall(b'{"jsonrpc":"2.0","version":"execution/1","id":2,'
                                             b'"method":"execution.start","params":' + bad + b'}\n')
                    with self.assertRaises(EOFError):
                        rpc.channel.receive(WAIT)
            self.assertEqual(self.count_attempts(), 0)

    def test_historical_registry_socket_does_not_expose_execution(self):
        with serve_registry(self.root, Identities(), self.verifiers, create=True) as (endpoint, _):
            with self.client(endpoint) as rpc:
                with self.assertRaises(EOFError):
                    rpc.call('auth', credential=self.tokens[ISSUER])
            with self.client(endpoint, ISSUER, version=REGISTRY) as rpc:
                self.expect_error('method_not_found', rpc.call, 'execution.authorize', **self.auth_params())

    def test_idempotent_authorization_and_simultaneous_start_dispatch_once(self):
        with self.service() as (endpoint, _), ThreadPoolExecutor(2) as pool:
            self.delivery(endpoint)
            barrier = Barrier(2)

            def authorize():
                with self.client(endpoint, ISSUER) as rpc:
                    barrier.wait(WAIT)
                    return rpc.call('execution.authorize', **self.auth_params())

            requests = [pool.submit(authorize) for _ in range(2)]
            replies = [future.result(WAIT) for future in requests]
            self.assertEqual(replies[0], replies[1])
            attempt = replies[0]['id']
            self.assertEqual(self.count_attempts(), 1)
            self.expect_error('request_conflict', self.authorize, endpoint, ttl_seconds=61)
            self.expect_error('request_conflict', self.authorize, endpoint, executor_id=opaque(93))
            began, release = Event(), Event()

            def operation():
                began.set()
                if not release.wait(WAIT):
                    raise TimeoutError
                return 2 + 3

            with patch('experiments.execution_lab._add_fixed_constants', side_effect=operation) as add:
                first = pool.submit(self.start, endpoint, attempt)
                try:
                    self.assertTrue(began.wait(WAIT))
                    self.assert_audit(endpoint, attempt, 'admitted running')
                    self.assertEqual(self.start(endpoint, attempt)['state'], 'running')
                finally:
                    release.set()
                self.assertEqual(first.result(WAIT)['state'], 'completed')
                self.assertEqual(self.start(endpoint, attempt)['state'], 'completed')
                add.assert_called_once_with()
            self.assertEqual(self.admit(endpoint), attempt)
            self.assertEqual(self.authorize(endpoint)['state'], 'completed')
            self.assert_audit(endpoint, attempt, 'admitted running completed')

    def test_authorization_loses_to_revocation_and_regrant_is_a_new_generation(self):
        with self.service() as (endpoint, broker):
            self.delivery(endpoint)
            broker.execution.revoke(ISSUER, Permission.AUTHORIZE, SCOPE)
            self.expect_error('denied', self.authorize, endpoint)
            self.assertEqual(self.count_attempts(), 0)
            broker.execution.grant(ISSUER, Permission.AUTHORIZE, SCOPE, expires_at=WALL+70)
            attempt = self.admit(endpoint)
            broker.execution.revoke(ISSUER, Permission.AUTHORIZE, SCOPE)
            self.expect_error('denied', self.authorize, endpoint)
            broker.execution.grant(ISSUER, Permission.AUTHORIZE, SCOPE, expires_at=WALL+70)
            self.assertEqual(self.start(endpoint, attempt)['state'], 'revoked')
            self.assertEqual(self.admit(endpoint), attempt)
            self.assert_audit(endpoint, attempt, 'admitted revoked')

    def test_authorization_commit_wins_before_revocation(self):
        with self.service() as (endpoint, broker), ThreadPoolExecutor(2) as pool:
            self.delivery(endpoint)
            committing, release, revoking = Event(), Event(), Event()
            commit = broker.registry._commit

            def delay_commit(db):
                if not committing.is_set():
                    committing.set()
                    if not release.wait(WAIT):
                        raise TimeoutError
                return commit(db)

            def revoke():
                revoking.set()
                broker.execution.revoke(ISSUER, Permission.AUTHORIZE, SCOPE)

            with patch.object(broker.registry, '_commit', side_effect=delay_commit):
                request = pool.submit(self.authorize, endpoint)
                try:
                    self.assertTrue(committing.wait(WAIT))
                    revocation = pool.submit(revoke)
                    self.assertTrue(revoking.wait(WAIT))
                finally:
                    release.set()
                receipt = request.result(WAIT)
                revocation.result(WAIT)
            self.assertEqual(receipt['state'], 'admitted')
            self.assert_audit(endpoint, receipt['id'], 'admitted revoked')

    def test_cancellation_and_revocation_before_start(self):
        with self.service() as (endpoint, broker):
            self.delivery(endpoint)
            cancelled = self.admit(endpoint)
            revoked = self.admit(endpoint, request_id=opaque(94))
            self.assertEqual(self.cancel(endpoint, cancelled)['state'], 'cancelled')
            broker.execution.revoke(ISSUER, Permission.AUTHORIZE, SCOPE)
            with patch('experiments.execution_lab._add_fixed_constants') as add:
                self.assertEqual(self.start(endpoint, cancelled)['state'], 'cancelled')
                self.assertEqual(self.start(endpoint, revoked)['state'], 'revoked')
                add.assert_not_called()
            self.assert_audit(endpoint, cancelled, 'admitted cancelled')
            self.assert_audit(endpoint, revoked, 'admitted revoked')

    def test_publication_loses_to_cancel_revoke_expiry_and_identity_rotation(self):
        for ending in ('cancelled', 'revoked', 'expired', 'rotation', 'unavailable'):
            with self.subTest(ending=ending), TemporaryDirectory(prefix='loop-d2a-race-') as directory:
                self.root = Path(directory)
                self.clock = WALL
                with self.service() as (endpoint, broker), ThreadPoolExecutor(1) as pool:
                    self.delivery(endpoint)
                    attempt = self.admit(endpoint)
                    began, release = Event(), Event()

                    def operation():
                        began.set()
                        if not release.wait(WAIT):
                            raise TimeoutError
                        return 2 + 3

                    with patch('experiments.execution_lab._add_fixed_constants', side_effect=operation) as add:
                        task = pool.submit(self.start, endpoint, attempt)
                        try:
                            self.assertTrue(began.wait(WAIT))
                            self.assert_audit(endpoint, attempt, 'admitted running')
                            if ending == 'cancelled':
                                self.assertEqual(self.cancel(endpoint, attempt)['state'], ending)
                            elif ending == 'revoked':
                                broker.execution.revoke(EXECUTOR, Permission.PERFORM, SCOPE)
                            elif ending == 'expired':
                                self.clock = WALL+60
                            elif ending == 'rotation':
                                broker.access.rotate(EXECUTOR, sha256(token_urlsafe(32).encode()).hexdigest())
                            else:
                                self.change_executor(endpoint, broker, ExecutorAction.SUSPEND, revision=2)
                        finally:
                            release.set()
                        state = 'revoked' if ending in ('rotation', 'unavailable') else ending
                        self.assertEqual(task.result(WAIT)['state'], state)
                        add.assert_called_once_with()
                    self.assert_audit(endpoint, attempt, f'admitted running {state}')

    def test_confirmed_publication_wins_against_concurrent_cancellation_and_revocation(self):
        with self.service() as (endpoint, broker), ThreadPoolExecutor(3) as pool:
            self.delivery(endpoint)
            attempt = self.admit(endpoint)
            publishing, release, cancelling, revoking = Event(), Event(), Event(), Event()
            commit = broker.registry._commit

            def pause_publication(db):
                if db.execute("SELECT 1 FROM execution_events WHERE state='completed'").fetchone():
                    publishing.set()
                    if not release.wait(WAIT):
                        raise TimeoutError
                commit(db)

            def cancel():
                cancelling.set()
                return canceller.call('execution.cancel', attempt_id=attempt)

            def revoke():
                revoking.set()
                broker.execution.revoke(EXECUTOR, Permission.PERFORM, SCOPE)

            with self.client(endpoint, CANCELLER) as canceller, \
                    patch.object(broker.registry, '_commit', side_effect=pause_publication):
                execution = pool.submit(self.start, endpoint, attempt)
                try:
                    self.assertTrue(publishing.wait(WAIT))
                    cancellation = pool.submit(cancel)
                    revocation = pool.submit(revoke)
                    self.assertTrue(cancelling.wait(WAIT))
                    self.assertTrue(revoking.wait(WAIT))
                finally:
                    release.set()
                self.assertEqual(execution.result(WAIT)['state'], 'completed')
                self.assertEqual(cancellation.result(WAIT)['state'], 'completed')
                revocation.result(WAIT)
            self.assert_audit(endpoint, attempt, 'admitted running completed')
            self.expect_error('denied', self.authorize, endpoint)

    def test_expiration_before_start_and_expiry_crossing_precommit(self):
        with self.service() as (endpoint, _):
            self.delivery(endpoint)
            elapsed = self.admit(endpoint, ttl_seconds=1)
            crossing = self.admit(endpoint, request_id=opaque(92), ttl_seconds=2)
            self.clock = WALL+1
            self.expect_error('authorization_expired', self.start, endpoint, elapsed)
            self.expect_error('authorization_expired', self.authorize, endpoint, ttl_seconds=1)
            append = ExecutionTransaction.append

            def advance_clock(tx, attempt, previous, state, **kwargs):
                event = append(tx, attempt, previous, state, **kwargs)
                if state == 'running':
                    self.clock = WALL+2
                return event

            with patch.object(ExecutionTransaction, 'append', advance_clock), \
                    patch('experiments.execution_lab._add_fixed_constants') as add:
                self.expect_error('authorization_expired', self.start, endpoint, crossing)
                add.assert_not_called()
            for attempt in (elapsed, crossing):
                self.assert_audit(endpoint, attempt, 'admitted expired')

    def test_objective_deadline_and_grant_deadline_bound_authorization(self):
        with self.service(grants=EXECUTION_GRANTS[1:]) as (endpoint, broker):
            self.delivery(endpoint, ttl=20)
            broker.execution.grant(ISSUER, Permission.AUTHORIZE, SCOPE, expires_at=WALL+10)
            attempt = self.admit(endpoint)
            self.assertEqual(self.audit(endpoint, attempt)['expires_unix_ms'], (WALL+10)*1000)
            self.clock = WALL+10
            self.expect_error('authorization_expired', self.authorize, endpoint)
            self.expect_error('authorization_expired', self.start, endpoint, attempt)
            broker.execution.revoke(ISSUER, Permission.AUTHORIZE, SCOPE)
            broker.execution.grant(ISSUER, Permission.AUTHORIZE, SCOPE, expires_at=WALL+100)
            second = self.admit(endpoint, request_id=opaque(86))
            self.assertEqual(self.audit(endpoint, second)['expires_unix_ms'], (WALL+20)*1000)
            self.clock = WALL+20
            self.expect_error('objective_expired', self.authorize, endpoint, request_id=opaque(87))
            self.expect_error('authorization_expired', self.start, endpoint, second)

    def change_executor(self, endpoint, broker, action, *, revision):
        with self.client(endpoint, ADMIN, version=REGISTRY) as rpc:
            # Existing trusted Registry management, deliberately absent from the wire methods.
            with broker.access._lock:
                binding = next(binding for binding in broker.access._bindings.values()
                               if binding.connection.id == rpc.authenticated_connection)
            broker.registry.transition_executor(RegistryRequest(binding.connection, None, None),
                                                opaque(100+revision), EXECUTOR_ID, revision, action)

    def test_executor_revision_and_availability_are_rechecked(self):
        with self.service() as (endpoint, broker):
            self.delivery(endpoint)
            attempt = self.admit(endpoint)
            self.change_executor(endpoint, broker, ExecutorAction.SUSPEND, revision=2)
            self.expect_error('executor_unavailable', self.authorize, endpoint, request_id=opaque(87))
            self.change_executor(endpoint, broker, ExecutorAction.RESUME, revision=3)
            self.assertEqual(self.start(endpoint, attempt)['state'], 'revoked')
            replacement = self.admit(endpoint, request_id=opaque(88))
            self.assertEqual(self.start(endpoint, replacement)['state'], 'completed')

    def test_audit_and_cancel_permissions_are_independently_revocable(self):
        with self.service() as (endpoint, broker):
            self.delivery(endpoint)
            attempt = self.admit(endpoint)
            broker.execution.revoke(CANCELLER, Permission.CANCEL, SCOPE)
            self.expect_error('denied', self.cancel, endpoint, attempt)
            self.assertEqual(self.start(endpoint, attempt)['state'], 'completed')
            broker.execution.revoke(AUDITOR, Permission.AUDIT, SCOPE)
            self.expect_error('denied', self.audit, endpoint, attempt)
            self.assertEqual(self.authorize(endpoint)['state'], 'completed')

    def test_runtime_failure_and_unverified_value_are_sanitized(self):
        with self.service() as (endpoint, _):
            self.delivery(endpoint)
            for index, kwargs in enumerate((dict(side_effect=RuntimeError('Sensitive detail')),
                                            dict(return_value=5.0)), 1):
                attempt = self.admit(endpoint, request_id=opaque(120+index))
                with patch('experiments.execution_lab._add_fixed_constants', **kwargs):
                    self.assertEqual(self.start(endpoint, attempt)['state'], 'failed')
                audit = self.assert_audit(endpoint, attempt, 'admitted running failed')
                self.assertEqual(audit['events'][-1]['reason'], 'operation_failed')
                self.assertNotIn('Sensitive', repr(audit))

    def test_failed_publication_commit_recovers_uncertain_and_completed_commit_survives(self):
        with self.service() as (endpoint, broker):
            self.delivery(endpoint)
            attempt = self.admit(endpoint)
            lost_reply = self.admit(endpoint, request_id=opaque(88))
            pending = self.admit(endpoint, request_id=opaque(89))
            commit = broker.registry._commit
            for index, active in enumerate((attempt, lost_reply)):
                calls = 0

                def fail_publication(db):
                    nonlocal calls
                    calls += 1
                    if calls == 1 or index == 1:
                        commit(db)
                    if calls == 2:
                        raise sqlite3.OperationalError('internal failure')

                with patch.object(broker.registry, '_commit', side_effect=fail_publication):
                    self.expect_error('commit_unknown', self.start, endpoint, active)
            self.assert_audit(endpoint, attempt, 'admitted running')
            self.assert_audit(endpoint, lost_reply, 'admitted running completed')
        with self.service(create=False) as (endpoint, _):
            self.assert_audit(endpoint, attempt, 'admitted running uncertain')
            self.assert_audit(endpoint, lost_reply, 'admitted running completed')
            self.assert_audit(endpoint, pending, 'admitted revoked')
            with patch('experiments.execution_lab._add_fixed_constants') as add:
                self.assertEqual(self.authorize(endpoint)['state'], 'uncertain')
                self.assertEqual(self.start(endpoint, attempt)['state'], 'uncertain')
                self.assertEqual(self.admit(endpoint, request_id=opaque(88)), lost_reply)
                add.assert_not_called()
            new = self.admit(endpoint, request_id=opaque(90))
            self.assertNotIn(new, (attempt, lost_reply, pending))
            self.assertEqual(self.start(endpoint, new)['state'], 'completed')

    def test_regrant_cannot_revive_an_attempt_after_revocation_commit_failure(self):
        with self.service() as (endpoint, broker):
            self.delivery(endpoint)
            attempt = self.admit(endpoint)
            with patch.object(broker.registry, '_commit', side_effect=sqlite3.OperationalError):
                with self.assertRaisesRegex(RegistryError, 'commit_unknown'):
                    broker.execution.revoke(ISSUER, Permission.AUTHORIZE, SCOPE)
            self.assert_audit(endpoint, attempt, 'admitted')
            self.expect_error('denied', self.authorize, endpoint)
            broker.execution.grant(ISSUER, Permission.AUTHORIZE, SCOPE, expires_at=WALL + 200)
            with patch('experiments.execution_lab._add_fixed_constants') as add:
                self.assertEqual(self.start(endpoint, attempt)['state'], 'revoked')
                add.assert_not_called()
            self.assert_audit(endpoint, attempt, 'admitted revoked')

    def test_historical_schema_is_rejected_and_corrupt_execution_history_fails_closed(self):
        with serve_registry(self.root, Identities(), self.verifiers, create=True):
            pass
        (self.root / 'registry.sqlite3').rename(self.database)
        with self.assertRaisesRegex(RegistryError, 'invalid_storage'):
            with self.service(create=False):
                self.fail('accepted a Registry-only schema')
        self.database.unlink()

        with self.service() as (endpoint, _):
            self.delivery(endpoint)
            attempt = self.admit(endpoint)
            self.assertEqual(self.start(endpoint, attempt)['state'], 'completed')
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('DELETE FROM execution_events WHERE attempt_id=? AND revision=2', (attempt,))
            db.commit()
        with self.assertRaisesRegex(RegistryError, 'invalid_storage'):
            with self.service(create=False):
                self.fail('accepted a completion with no durable start')

    def test_hard_stop_after_start_reopens_as_uncertain(self):
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe()
        with parent, child, ThreadPoolExecutor(1) as pool:
            process = context.Process(target=crashable_service, args=(self.root, self.verifiers, child))
            process.start()
            child.close()
            try:
                self.assertTrue(parent.poll(WAIT))
                endpoint = parent.recv()
                self.delivery(endpoint)
                attempt = self.admit(endpoint)
                task = pool.submit(self.start, endpoint, attempt)
                self.assertTrue(parent.poll(WAIT))
                self.assertEqual(parent.recv(), 'running')
            finally:
                if process.is_alive():
                    process.kill()
                process.join(WAIT)
                self.assertFalse(process.is_alive())
                process.close()
            with self.assertRaises(EOFError):
                task.result(WAIT)
        self.assertTrue(endpoint.is_socket())
        endpoint.unlink()  # The fixture owns this path and verified the old process stopped.
        with self.service(create=False) as (endpoint, _):
            record = self.assert_audit(endpoint, attempt, 'admitted running uncertain')
            self.assertEqual(record['events'][-1]['reason'], 'interrupted')
            self.assertEqual(self.admit(endpoint), attempt)
