# SPDX-License-Identifier: Apache-2.0
"""Cooperative execution through real LoopBridge RPC and SQLite commits."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing, contextmanager, redirect_stderr, redirect_stdout
from hashlib import sha256
from io import StringIO
import json
import multiprocessing
from pathlib import Path
from secrets import token_urlsafe
import socket
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier, Event
import unittest
from unittest.mock import patch

from experiments.execution_lab import Permission, VERSION as D2A, serve_execution_lab
from experiments.execution_storage import Scope
from experiments.objective_registry import Permission as Delivery, RegistryError
from experiments.registry_rpc import VERSION as REGISTRY
from experiments.supervision_lab import (VERSION, SupervisedExecution, SupervisionPermission as Control,
                                       _calculate_stage, serve_supervision_lab)
from experiments.supervision_storage import MAX_ADVANCES, PLAN, SupervisionTransaction
from loopbridge.protocol import DeadlineChannel, Fault, RPC
from tools.supervised_execution import main as client_main

WAIT = 8
WALL = 1_780_000_000


def opaque(number):
    return f'{number:032x}'


ADMIN, ISSUER, EXECUTOR, SUPERVISOR, OBSERVER, AUDITOR = map(opaque, range(1, 7))
TARGET, OBJECTIVE, SECOND = map(opaque, (10, 11, 12))
SCOPE = Scope(TARGET, OBJECTIVE, 3, PLAN)


def configure(broker):
    for principal, permission in ((ADMIN, Delivery.REGISTER), (ISSUER, Delivery.AUTHOR_OBJECTIVE),
                                  (ISSUER, Delivery.READ_OBJECTIVE), (EXECUTOR, Delivery.CONFIRM),
                                  (EXECUTOR, Delivery.RESPOND_TO_OBJECTIVE)):
        broker.access.policy.grant(principal, permission, TARGET, expires_at=WALL + 1000)
    for principal, permission in ((ISSUER, Permission.AUTHORIZE), (EXECUTOR, Permission.PERFORM),
                                  (SUPERVISOR, Permission.CANCEL), (AUDITOR, Permission.AUDIT)):
        broker.execution.grant(principal, permission, SCOPE, expires_at=WALL + 1000)


def configure_attempt(broker, attempt):
    for principal, permission in ((SUPERVISOR, Control.PAUSE), (SUPERVISOR, Control.STEP),
                                  (SUPERVISOR, Control.CONTINUE), (OBSERVER, Control.PROGRESS)):
        broker.execution.grant(principal, permission, SCOPE, expires_at=WALL + 1000, attempt_id=attempt)


def crashable(root, verifiers, guardian):
    def blocked_stage(*args):
        guardian.send(args)
        Event().wait()

    with serve_supervision_lab(root, verifiers, create=True, wall_clock=lambda: WALL) as (endpoint, broker):
        configure(broker)
        with patch('experiments.supervision_lab._calculate_stage', side_effect=blocked_stage):
            guardian.send(endpoint)
            configure_attempt(broker, guardian.recv())
            guardian.send('configured')
            guardian.recv()


class SupervisedExecutionRPC(unittest.TestCase):
    def setUp(self):
        root = TemporaryDirectory(prefix='loop-d2b-')
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        self.db = self.root / 'supervised.sqlite3'
        self.clock = WALL
        self.tokens = {principal: token_urlsafe(32) for principal in (ADMIN, ISSUER, EXECUTOR, SUPERVISOR, OBSERVER, AUDITOR)}
        self.verifiers = {principal: sha256(token.encode()).hexdigest() for principal, token in self.tokens.items()}
        self.sentinel = self.root / 'untrusted'

    @contextmanager
    def service(self, *, create=True, attempt_ids=()):
        with serve_supervision_lab(self.root, self.verifiers, create=create,
                                   wall_clock=lambda: self.clock) as (endpoint, broker):
            configure(broker)
            for attempt in attempt_ids:
                configure_attempt(broker, attempt)
            self.broker = broker
            self.assertEqual(endpoint.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)
            yield endpoint, broker
        self.assertFalse(endpoint.exists())

    @contextmanager
    def client(self, endpoint, principal, version=VERSION):
        with socket.socket(socket.AF_UNIX) as peer:
            peer.connect(str(endpoint))
            rpc = RPC(peer, version, timeout=2 * WAIT)
            if principal is not None:
                self.assertEqual(rpc.call('auth', credential=self.tokens[principal])['principal'], principal)
            yield rpc

    def call(self, endpoint, principal, method, **params):
        with self.client(endpoint, principal) as rpc:
            return rpc.call(f'execution.{method}', **params)

    def control(self, endpoint, action, attempt, revision, request, principal=None):
        if principal is None:
            principal = EXECUTOR if action == 'start' else SUPERVISOR
        return self.call(endpoint, principal, action, attempt_id=attempt,
                         expected_revision=revision, request_id=opaque(request))

    def status(self, endpoint, attempt):
        return self.call(endpoint, OBSERVER, 'status', attempt_id=attempt)

    def audit(self, endpoint, attempt):
        trail = self.call(endpoint, AUDITOR, 'audit', attempt_id=attempt)
        self.assertEqual([event['revision'] for event in trail['events']], list(range(1, trail['revision'] + 1)))
        return trail

    def assert_recovers_with_only_audit(self, attempt, expected):
        with patch('experiments.supervision_lab._calculate_stage') as stage, \
                serve_supervision_lab(self.root, self.verifiers,
                                      wall_clock=lambda: self.clock) as (endpoint, broker):
            self.fault('denied', self.audit, endpoint, attempt)
            broker.execution.grant(AUDITOR, Permission.AUDIT, SCOPE, expires_at=WALL + 1000)
            self.assertEqual(self.audit(endpoint, attempt), expected)
            self.fault('denied', self.status, endpoint, attempt)
            self.fault('denied', self.control, endpoint, 'continue', attempt, expected['revision'], 99)
            stage.assert_not_called()

    def shorten_advance_grant(self, broker, attempt, permission):
        broker.execution.revoke(SUPERVISOR, permission, SCOPE, attempt_id=attempt)
        broker.execution.grant(SUPERVISOR, permission, SCOPE,
                               expires_at=WALL + 5, attempt_id=attempt)

    def fault(self, reason, action, *args, **kwargs):
        with self.assertRaisesRegex(Fault, f'^{reason}$'):
            action(*args, **kwargs)

    def register(self, endpoint):
        with self.client(endpoint, ADMIN, REGISTRY) as rpc:
            rpc.call('executor.register', request_id=opaque(20), executor_id=TARGET,
                     bound_principal_id=EXECUTOR, label='cooperative')
        with self.client(endpoint, EXECUTOR, REGISTRY) as rpc:
            rpc.call('executor.confirm', request_id=opaque(21), executor_id=TARGET, expected_revision=1)

    def accept(self, endpoint, objective=OBJECTIVE):
        key = 30 if objective == OBJECTIVE else 40
        with self.client(endpoint, ISSUER, REGISTRY) as rpc:
            rpc.call('objective.create', request_id=opaque(key), executor_id=TARGET, objective_id=objective,
                     text=f'Untrusted text: $(touch {self.sentinel})', ttl_seconds=600)
            rpc.call('objective.offer', request_id=opaque(key + 1), objective_id=objective, expected_revision=1)
        with self.client(endpoint, EXECUTOR, REGISTRY) as rpc:
            rpc.call('objective.respond', request_id=opaque(key + 2), objective_id=objective,
                     expected_revision=2, decision='accept')

    def admitted(self, endpoint, *, objective=OBJECTIVE, ttl=120, operation=PLAN, request=50):
        return self.call(endpoint, ISSUER, 'authorize', request_id=opaque(request),
                         executor_id=TARGET, objective_id=objective, accepted_revision=3,
                         operation=operation, ttl_seconds=ttl)

    def ready(self, endpoint, *, ttl=120, enable=None):
        self.register(endpoint)
        self.accept(endpoint)
        receipt = self.admitted(endpoint, ttl=ttl)
        self.assertEqual(receipt['kind'], 'admitted')
        attempt = receipt['id']
        if enable is None:
            configure_attempt(self.broker, attempt)
        else:
            enable(attempt)
        self.assertEqual(self.control(endpoint, 'start', attempt, 1, 60), dict(id=attempt, revision=2, kind='running'))
        return attempt

    def assert_progress(self, endpoint, attempt, *, state='running', mode='paused', done=0, current=None):
        view = self.status(endpoint, attempt)
        self.assertEqual((view['state'], view['supervision'], view['completed_stages'], view['current_stage']),
                         (state, mode, done, current))
        self.assertEqual(view['total_stages'], 2)
        self.assertNotIn('result', view)
        self.assertNotIn('events', view)
        return view

    def finish_and_check(self, endpoint, attempt, expected_kinds):
        trail = self.audit(endpoint, attempt)
        self.assertEqual([event['kind'] for event in trail['events']], expected_kinds.split())
        self.assertEqual(trail['result'], 5)
        self.assertEqual(trail['state'], 'completed')
        self.assertEqual(trail['completed_stages'], 2)
        self.assertTrue(all(value not in json.dumps(trail) for value in (*self.tokens.values(), *self.verifiers.values())))
        self.assertNotIn(str(self.sentinel), json.dumps(trail))
        self.assertFalse(self.sentinel.exists())

    def test_full_flow_publishes_verified_result_and_trace(self):
        with self.service() as (endpoint, _), patch(
                'experiments.supervision_lab._calculate_stage', wraps=_calculate_stage) as stage:
            attempt = self.ready(endpoint)
            self.assert_progress(endpoint, attempt)
            stage.assert_not_called()
            accepted = self.control(endpoint, 'continue', attempt, 2, 61)
            self.assertEqual(accepted, dict(id=attempt, revision=3, kind='continue'))
            self.assertEqual([call.args for call in stage.call_args_list], [(1, None), (2, 2)])
            self.assert_progress(endpoint, attempt, state='completed', mode=None, done=2)
            self.finish_and_check(endpoint, attempt,
                                  'admitted running continue dispatched stage_completed dispatched stage_completed completed')
            with closing(sqlite3.connect(self.db)) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    @contextmanager
    def gated_work(self):
        waiting, release = Event(), Event()
        original = SupervisedExecution._work

        def work(execution, *args):
            waiting.set()
            if not release.wait(WAIT):
                raise TimeoutError
            return original(execution, *args)

        with patch.object(SupervisedExecution, '_work', work):
            try:
                yield waiting, release
            finally:
                release.set()

    def test_pause_can_win_before_first_dispatch(self):
        with self.service() as (endpoint, _), ThreadPoolExecutor(1) as pool, self.gated_work() as gate:
            attempt = self.ready(endpoint)
            waiting, release = gate
            with patch('experiments.supervision_lab._calculate_stage') as stage:
                run = pool.submit(self.control, endpoint, 'continue', attempt, 2, 61)
                try:
                    self.assertTrue(waiting.wait(WAIT))
                    update = self.assert_progress(endpoint, attempt, mode='flowing')
                    pause = self.control(endpoint, 'pause', attempt, update['revision'], 62)
                    self.assertEqual(pause['kind'], 'paused')
                finally:
                    release.set()
                run.result(WAIT)
                stage.assert_not_called()
            self.assert_progress(endpoint, attempt)
            self.assertEqual(self.control(endpoint, 'continue', attempt, 2, 61)['revision'], 3)
            self.assert_progress(endpoint, attempt)

    @contextmanager
    def gated_stage(self, stage_number=1):
        arrived, release = Event(), Event()

        def run(index, value):
            if index == stage_number:
                arrived.set()
                if not release.wait(WAIT):
                    raise TimeoutError
            return _calculate_stage(index, value)

        with patch('experiments.supervision_lab._calculate_stage', side_effect=run) as stage:
            try:
                yield arrived, release, stage
            finally:
                release.set()

    def test_pending_pause_confirms_at_stage_boundary_then_continue(self):
        with self.service() as (endpoint, _), ThreadPoolExecutor(1) as pool, self.gated_stage() as gate:
            attempt = self.ready(endpoint)
            arrived, release, stage = gate
            flowing = pool.submit(self.control, endpoint, 'continue', attempt, 2, 61)
            self.assertTrue(arrived.wait(WAIT))
            update = self.assert_progress(endpoint, attempt, mode='flowing', current=1)
            pause = self.control(endpoint, 'pause', attempt, update['revision'], 62)
            self.assertEqual(pause['kind'], 'pause_requested')
            self.assert_progress(endpoint, attempt, mode='pause_requested', current=1)
            self.fault('invalid_state', self.control, endpoint, 'continue', attempt, pause['revision'], 63)
            release.set()
            flowing.result(WAIT)
            update = self.assert_progress(endpoint, attempt, done=1)
            stage.assert_called_once_with(1, None)
            self.assertEqual(self.control(endpoint, 'pause', attempt, pause['revision'] - 1, 62), pause)
            self.control(endpoint, 'continue', attempt, update['revision'], 64)
            self.assertEqual([call.args for call in stage.call_args_list], [(1, None), (2, 2)])
            self.finish_and_check(endpoint, attempt,
                                  'admitted running continue dispatched pause_requested stage_completed '
                                  'continue dispatched stage_completed completed')

    def test_concurrent_step_and_replay_dispatch_exactly_one(self):
        with self.service() as (endpoint, _), ThreadPoolExecutor(2) as pool, self.gated_stage() as gate:
            attempt = self.ready(endpoint)
            arrived, release, stage = gate
            barrier = Barrier(2)

            def step(request):
                barrier.wait(WAIT)
                return self.control(endpoint, 'step', attempt, 2, request)

            steps = {pool.submit(step, request): request for request in (61, 62)}
            self.assertTrue(arrived.wait(WAIT))
            rejected, accepted = wait(steps, timeout=WAIT, return_when=FIRST_COMPLETED)
            self.assertEqual((len(rejected), len(accepted)), (1, 1))
            with self.assertRaisesRegex(Fault, '^stale_revision$'):
                rejected.pop().result(WAIT)
            accepted = accepted.pop()
            self.assert_progress(endpoint, attempt, mode='stepping', current=1)
            replay = self.control(endpoint, 'step', attempt, 2, steps[accepted])
            self.assertEqual(replay['kind'], 'step')
            self.fault('request_conflict', self.control, endpoint, 'step', attempt, 3, steps[accepted])
            release.set()
            self.assertEqual(accepted.result(WAIT), replay)
            update = self.assert_progress(endpoint, attempt, done=1)
            stage.assert_called_once_with(1, None)
            self.control(endpoint, 'step', attempt, update['revision'], 63)
            self.assertEqual(stage.call_count, 2)
            self.finish_and_check(endpoint, attempt,
                                  'admitted running step dispatched stage_completed step dispatched stage_completed completed')

    def test_cancel_and_expire_while_paused_prevent_continue(self):
        with self.service() as (endpoint, _), patch('experiments.supervision_lab._calculate_stage') as stage:
            attempt = self.ready(endpoint, ttl=10)
            self.assertEqual(self.control(endpoint, 'cancel', attempt, 2, 61)['kind'], 'cancelled')
            self.assertEqual(self.control(endpoint, 'cancel', attempt, 2, 61)['kind'], 'cancelled')
            self.fault('invalid_state', self.control, endpoint, 'continue', attempt, 3, 62)
            trail = self.audit(endpoint, attempt)
            self.assertIsNone(trail['result'])
            self.assertEqual(trail['reason'], 'cancelled')
            self.clock = WALL + 10
            self.fault('authorization_expired', self.admitted, endpoint, ttl=10)
            stage.assert_not_called()

    def test_expiry_of_attempt_while_paused_is_materialized_by_authorized_continue(self):
        with self.service() as (endpoint, _), patch('experiments.supervision_lab._calculate_stage') as stage:
            attempt = self.ready(endpoint, ttl=10)
            self.clock = WALL + 10
            self.assertEqual(self.control(endpoint, 'continue', attempt, 2, 61)['kind'], 'expired')
            terminal = self.assert_progress(endpoint, attempt, state='expired', mode=None)
            self.fault('invalid_state', self.control, endpoint, 'continue', attempt, terminal['revision'], 62)
            trail = self.audit(endpoint, attempt)
            self.assertEqual(trail['reason'], 'attempt_expired')
            self.assertIsNone(trail['result'])
            stage.assert_not_called()
        self.assert_recovers_with_only_audit(attempt, trail)

    def test_revocation_during_stage_prevents_success_and_more_dispatches(self):
        with self.service() as (endpoint, broker), ThreadPoolExecutor(1) as pool, self.gated_stage() as gate:
            attempt = self.ready(endpoint)
            arrived, release, stage = gate
            running = pool.submit(self.control, endpoint, 'continue', attempt, 2, 61)
            self.assertTrue(arrived.wait(WAIT))
            broker.execution.revoke(EXECUTOR, Permission.PERFORM, SCOPE)
            broker.execution.grant(EXECUTOR, Permission.PERFORM, SCOPE, expires_at=WALL + 1000)
            terminal = self.assert_progress(endpoint, attempt, state='revoked', mode=None)
            self.fault('invalid_state', self.control, endpoint, 'continue', attempt, terminal['revision'], 62)
            release.set()
            running.result(WAIT)
            stage.assert_called_once_with(1, None)
            self.assertIsNone(self.audit(endpoint, attempt)['result'])

    def test_revoked_and_reissued_continue_grant_fences_its_current_driver(self):
        with self.service() as (endpoint, broker), ThreadPoolExecutor(1) as pool, self.gated_stage() as gate:
            attempt = self.ready(endpoint)
            arrived, release, stage = gate
            running = pool.submit(self.control, endpoint, 'continue', attempt, 2, 61)
            self.assertTrue(arrived.wait(WAIT))
            broker.execution.revoke(SUPERVISOR, Control.CONTINUE, SCOPE, attempt_id=attempt)
            self.fault('denied', self.control, endpoint, 'continue', attempt, 2, 61)
            broker.execution.grant(SUPERVISOR, Control.CONTINUE, SCOPE, expires_at=WALL + 1000, attempt_id=attempt)
            release.set()
            running.result(WAIT)
            self.assert_progress(endpoint, attempt, state='revoked', mode=None)
            self.assertIsNone(self.audit(endpoint, attempt)['result'])
            stage.assert_called_once_with(1, None)

    def test_continue_grant_expires_before_first_dispatch(self):
        with self.service() as (endpoint, broker), ThreadPoolExecutor(1) as pool, self.gated_work() as gate:
            attempt = self.ready(endpoint)
            self.shorten_advance_grant(broker, attempt, Control.CONTINUE)
            waiting, release = gate
            with patch('experiments.supervision_lab._calculate_stage') as stage:
                run = pool.submit(self.control, endpoint, 'continue', attempt, 2, 61)
                try:
                    self.assertTrue(waiting.wait(WAIT))
                    self.assert_progress(endpoint, attempt, mode='flowing')
                    self.clock = WALL + 5
                finally:
                    release.set()
                run.result(WAIT)
                stage.assert_not_called()
            trail = self.audit(endpoint, attempt)
            self.assertEqual((trail['state'], trail['reason'], trail['result']),
                             ('expired', 'advance_expired', None))
            self.assertEqual([event['kind'] for event in trail['events']],
                             ['admitted', 'running', 'continue', 'expired'])
        self.assert_recovers_with_only_audit(attempt, trail)

    def test_continue_grant_expires_during_step_boundary(self):
        with self.service() as (endpoint, broker), ThreadPoolExecutor(1) as pool, self.gated_stage() as gate:
            attempt = self.ready(endpoint, ttl=120)
            self.shorten_advance_grant(broker, attempt, Control.CONTINUE)
            arrived, release, stage = gate
            running = pool.submit(self.control, endpoint, 'continue', attempt, 2, 61)
            self.assertTrue(arrived.wait(WAIT))
            self.clock = WALL + 5
            release.set()
            running.result(WAIT)
            view = self.assert_progress(endpoint, attempt, state='expired', mode=None)
            self.assertEqual(view['reason'], 'advance_expired')
            self.fault('authorization_expired', self.control, endpoint, 'continue', attempt, view['revision'], 62)
            self.fault('invalid_state', self.control, endpoint, 'cancel', attempt, view['revision'], 63)
            trail = self.audit(endpoint, attempt)
            self.assertEqual(trail['expires_unix_ms'], (WALL + 120) * 1000)
            self.assertEqual(trail['events'][-1]['at_unix_ms'], (WALL + 5) * 1000)
            self.assertEqual(trail['events'][2]['deadline_unix_ms'], (WALL + 5) * 1000)
            self.assertIsNone(trail['result'])
            stage.assert_called_once_with(1, None)
        self.assert_recovers_with_only_audit(attempt, trail)

    def test_advance_expires_during_final_stage_with_pause_requested(self):
        with self.service() as (endpoint, broker), ThreadPoolExecutor(1) as pool, self.gated_stage(2) as gate:
            attempt = self.ready(endpoint)
            self.shorten_advance_grant(broker, attempt, Control.CONTINUE)
            arrived, release, stage = gate
            running = pool.submit(self.control, endpoint, 'continue', attempt, 2, 61)
            self.assertTrue(arrived.wait(WAIT))
            self.clock = WALL + 4
            view = self.assert_progress(endpoint, attempt, mode='flowing', done=1, current=2)
            receipt = self.control(endpoint, 'pause', attempt, view['revision'], 62)
            self.assertEqual(receipt['kind'], 'pause_requested')
            self.clock = WALL + 5
            release.set()
            running.result(WAIT)
            self.assert_progress(endpoint, attempt, state='expired', mode=None, done=1)
            trail = self.audit(endpoint, attempt)
            self.assertEqual((trail['reason'], trail['result']), ('advance_expired', None))
            self.assertEqual([event['kind'] for event in trail['events'][-2:]], ['pause_requested', 'expired'])
            self.assertEqual(self.control(endpoint, 'pause', attempt, view['revision'], 62), receipt)
            self.assertEqual([call.args for call in stage.call_args_list], [(1, None), (2, 2)])
        self.assert_recovers_with_only_audit(attempt, trail)

    def test_step_grant_expiry_invalidates_its_result(self):
        with self.service() as (endpoint, broker), ThreadPoolExecutor(1) as pool, self.gated_stage() as gate:
            attempt = self.ready(endpoint)
            self.shorten_advance_grant(broker, attempt, Control.STEP)
            arrived, release, stage = gate
            running = pool.submit(self.control, endpoint, 'step', attempt, 2, 61)
            self.assertTrue(arrived.wait(WAIT))
            self.assert_progress(endpoint, attempt, mode='stepping', current=1)
            self.clock = WALL + 5
            release.set()
            self.assertEqual(running.result(WAIT)['kind'], 'step')
            self.assert_progress(endpoint, attempt, state='expired', mode=None)
            trail = self.audit(endpoint, attempt)
            self.assertEqual((trail['reason'], trail['result']), ('advance_expired', None))
            stage.assert_called_once_with(1, None)
        self.assert_recovers_with_only_audit(attempt, trail)

    def test_advance_deadline_wins_during_final_publication_transaction(self):
        with self.service() as (endpoint, broker):
            attempt = self.ready(endpoint)
            self.shorten_advance_grant(broker, attempt, Control.CONTINUE)
            append = SupervisionTransaction.append

            def reach_deadline(tx, attempt, previous, state, **kwargs):
                event = append(tx, attempt, previous, state, **kwargs)
                if state == 'completed':
                    # The result and lifecycle event are staged but still uncommitted.
                    self.clock = WALL + 5
                return event

            with patch.object(SupervisionTransaction, 'append', reach_deadline), patch(
                    'experiments.supervision_lab._calculate_stage', wraps=_calculate_stage) as stage:
                self.control(endpoint, 'continue', attempt, 2, 61)
                self.assertEqual([call.args for call in stage.call_args_list], [(1, None), (2, 2)])
            trail = self.audit(endpoint, attempt)
            self.assertEqual((trail['state'], trail['reason'], trail['result'], trail['completed_stages']),
                             ('expired', 'advance_expired', None, 1))
            self.assertEqual([event['kind'] for event in trail['events'][-2:]], ['dispatched', 'expired'])
        self.assert_recovers_with_only_audit(attempt, trail)

    def test_completed_publication_survives_later_advance_expiry(self):
        with self.service() as (endpoint, broker):
            attempt = self.ready(endpoint)
            self.shorten_advance_grant(broker, attempt, Control.CONTINUE)
            self.clock = WALL + 4
            self.control(endpoint, 'continue', attempt, 2, 61)
            trail = self.audit(endpoint, attempt)
            self.assertEqual((trail['state'], trail['reason'], trail['result']), ('completed', None, 5))
            self.clock = WALL + 5
            self.fault('authorization_expired', self.control, endpoint, 'continue', attempt, 2, 61)
            self.fault('invalid_state', self.control, endpoint, 'cancel', attempt, trail['revision'], 62)
            self.assertEqual(self.audit(endpoint, attempt), trail)
        self.assert_recovers_with_only_audit(attempt, trail)

    def test_control_credential_rotation_fences_running_step(self):
        with self.service() as (endpoint, broker), ThreadPoolExecutor(1) as pool, self.gated_stage() as gate:
            attempt = self.ready(endpoint)
            arrived, release, stage = gate
            running = pool.submit(self.control, endpoint, 'step', attempt, 2, 61)
            self.assertTrue(arrived.wait(WAIT))
            broker.access.rotate(SUPERVISOR, sha256(token_urlsafe(32).encode()).hexdigest())
            release.set()
            running.result(WAIT)
            self.assert_progress(endpoint, attempt, state='revoked', mode=None)
            stage.assert_called_once_with(1, None)

    def test_cancel_during_stage_suppresses_late_result(self):
        with self.service() as (endpoint, _), ThreadPoolExecutor(1) as pool, self.gated_stage() as gate:
            attempt = self.ready(endpoint)
            arrived, release, stage = gate
            running = pool.submit(self.control, endpoint, 'continue', attempt, 2, 61)
            self.assertTrue(arrived.wait(WAIT))
            snapshot = self.status(endpoint, attempt)
            self.control(endpoint, 'cancel', attempt, snapshot['revision'], 62)
            cancelled = self.audit(endpoint, attempt)
            release.set()
            running.result(WAIT)
            self.assertEqual(self.audit(endpoint, attempt), cancelled)
            self.assertIsNone(cancelled['result'])
            stage.assert_called_once_with(1, None)

    def test_independent_grants_exact_scope_stale_revision_and_strict_input(self):
        with self.service() as (endpoint, broker):
            attempt = self.ready(endpoint)
            for caller in (OBSERVER, AUDITOR, ISSUER, EXECUTOR):
                self.fault('denied', self.control, endpoint, 'step', attempt, 2, 61, principal=caller)
            self.fault('denied', self.call, endpoint, None, 'status', attempt_id=attempt)
            self.fault('denied', self.call, endpoint, OBSERVER, 'audit', attempt_id=attempt)
            self.fault('stale_revision', self.control, endpoint, 'step', attempt, 1, 61)
            self.fault('invalid_params', self.call, endpoint, SUPERVISOR, 'step', attempt_id=attempt,
                       expected_revision=2, request_id=opaque(61), principal_id=SUPERVISOR)
            self.fault('invalid_params', self.admitted, endpoint, operation='add_fixed_constants')
            alternate = Scope(TARGET, SECOND, 3, PLAN)
            for principal, permission in ((ISSUER, Permission.AUTHORIZE), (EXECUTOR, Permission.PERFORM)):
                broker.execution.grant(principal, permission, alternate, expires_at=WALL + 100)
            self.accept(endpoint, SECOND)
            other = self.admitted(endpoint, objective=SECOND, request=51)['id']
            self.fault('denied', self.control, endpoint, 'cancel', other, 1, 61)
            self.fault('denied', self.call, endpoint, OBSERVER, 'status', attempt_id=other)
            same_scope = self.admitted(endpoint, request=52)['id']
            self.control(endpoint, 'start', same_scope, 1, 60)
            self.fault('denied', self.control, endpoint, 'step', same_scope, 2, 61)
            self.fault('denied', self.call, endpoint, OBSERVER, 'status', attempt_id=same_scope)
            with self.client(endpoint, None, D2A) as rpc, self.assertRaises(EOFError):
                rpc.call('auth', credential=self.tokens[SUPERVISOR])

    def test_lost_step_reply_reconciles_without_dispatch(self):
        with self.service() as (endpoint, _), patch(
                'experiments.supervision_lab._calculate_stage', wraps=_calculate_stage) as stage:
            attempt = self.ready(endpoint)
            send = DeadlineChannel.send

            def drop_step_reply(channel, payload):
                if payload.get('result', {}).get('kind') == 'step':
                    raise EOFError
                return send(channel, payload)

            with patch.object(DeadlineChannel, 'send', drop_step_reply), self.assertRaises(EOFError):
                self.control(endpoint, 'step', attempt, 2, 61)
            self.assert_progress(endpoint, attempt, done=1)
            self.assertEqual(self.control(endpoint, 'step', attempt, 2, 61)['revision'], 3)
            stage.assert_called_once_with(1, None)

    def test_ambiguous_dispatch_commit_never_replays_the_stage(self):
        with self.service() as (endpoint, broker), patch('experiments.supervision_lab._calculate_stage') as stage:
            attempt = self.ready(endpoint)
            commit = broker.registry._commit

            def lose_commit_ack(db):
                kind, = db.execute('SELECT kind FROM supervision_events WHERE attempt_id=? '
                                   'ORDER BY revision DESC LIMIT 1', (attempt,)).fetchone()
                commit(db)
                if kind == 'dispatched':
                    raise sqlite3.OperationalError

            with patch.object(broker.registry, '_commit', side_effect=lose_commit_ack):
                self.fault('commit_unknown', self.control, endpoint, 'step', attempt, 2, 61)
            self.assert_progress(endpoint, attempt, mode='stepping', current=1)
            self.assertEqual(self.control(endpoint, 'step', attempt, 2, 61)['kind'], 'step')
            stage.assert_not_called()
        with self.service(create=False, attempt_ids=(attempt,)) as (endpoint, _), patch('experiments.supervision_lab._calculate_stage') as stage:
            trail = self.audit(endpoint, attempt)
            self.assertEqual((trail['state'], trail['reason'], trail['result']), ('uncertain', 'interrupted', None))
            self.assertEqual(self.control(endpoint, 'step', attempt, 2, 61)['kind'], 'step')
            stage.assert_not_called()

    def test_process_interruption_during_stage_recovers_uncertain(self):
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe()
        with parent, child, ThreadPoolExecutor(1) as pool:
            process = context.Process(target=crashable, args=(self.root, self.verifiers, child))
            process.start()
            child.close()
            try:
                self.assertTrue(parent.poll(WAIT))
                endpoint = parent.recv()

                def enroll(attempt):
                    parent.send(attempt)
                    self.assertTrue(parent.poll(WAIT))
                    self.assertEqual(parent.recv(), 'configured')

                attempt = self.ready(endpoint, enable=enroll)
                running = pool.submit(self.control, endpoint, 'step', attempt, 2, 61)
                self.assertTrue(parent.poll(WAIT))
                self.assertEqual(parent.recv(), (1, None))
                self.assert_progress(endpoint, attempt, mode='stepping', current=1)
            finally:
                if process.is_alive():
                    process.kill()
                process.join(WAIT)
                self.assertFalse(process.is_alive())
                process.close()
            with self.assertRaises(EOFError):
                running.result(WAIT)
        self.assertTrue(endpoint.is_socket())
        endpoint.unlink()  # Fixture path after verifying process termination.
        with self.service(create=False, attempt_ids=(attempt,)) as (endpoint, _), patch('experiments.supervision_lab._calculate_stage') as stage:
            trail = self.audit(endpoint, attempt)
            self.assertEqual((trail['state'], trail['completed_stages'], trail['result']), ('uncertain', 0, None))
            self.fault('invalid_state', self.control, endpoint, 'continue', attempt, trail['revision'], 62)
            stage.assert_not_called()

    def test_reopen_preserves_completed_history_and_revokes_safe_paused_attempt(self):
        with self.service() as (endpoint, _):
            attempt = self.ready(endpoint)
            self.control(endpoint, 'continue', attempt, 2, 61)
            complete = self.audit(endpoint, attempt)
            pending = self.admitted(endpoint, request=51)['id']
            self.control(endpoint, 'start', pending, 1, 60)
            configure_attempt(self.broker, pending)
            self.control(endpoint, 'step', pending, 2, 61)
            self.assert_progress(endpoint, pending, done=1)
        with serve_supervision_lab(self.root, self.verifiers, wall_clock=lambda: self.clock) as (endpoint, _):
            self.fault('denied', self.audit, endpoint, attempt)
        with self.service(create=False, attempt_ids=(pending,)) as (endpoint, _):
            self.assertEqual(self.audit(endpoint, attempt), complete)
            self.assert_progress(endpoint, pending, state='revoked', mode=None, done=1)

    def registry_status(self, endpoint):
        with self.client(endpoint, ISSUER, REGISTRY) as rpc:
            return rpc.call('objective.status', objective_id=OBJECTIVE)

    def test_cross_protocol_clock_rollback_and_schema_boundaries(self):
        with self.service() as (endpoint, _):
            attempt = self.ready(endpoint)
            self.clock = WALL + 20
            self.status(endpoint, attempt)
            self.clock = WALL + 10
            self.fault('clock_uncertain', self.registry_status, endpoint)
            self.clock = WALL + 40
            self.registry_status(endpoint)
            self.clock = WALL + 30
            self.fault('clock_uncertain', self.status, endpoint, attempt)
        self.clock = WALL + 40
        path = self.root / 'execution.sqlite3'
        self.db.rename(path)
        with self.assertRaisesRegex(RegistryError, '^invalid_storage$'):
            with serve_execution_lab(self.root, self.verifiers, wall_clock=lambda: self.clock):
                self.fail('D.2A accepted the D.2B schema')
        path.rename(self.db)
        with self.service(create=False, attempt_ids=(attempt,)) as (endpoint, _):
            self.assert_progress(endpoint, attempt, state='revoked', mode=None)

    def test_capacity_keeps_terminal_transition_and_audit_available(self):
        with self.service() as (endpoint, _), patch.object(SupervisedExecution, '_work'), \
                patch('experiments.supervision_lab._calculate_stage') as stage:
            attempt = self.ready(endpoint)
            revision = 2
            for index in range(MAX_ADVANCES * 2):
                action = 'continue' if index % 2 == 0 else 'pause'
                receipt = self.control(endpoint, action, attempt, revision, 100 + index)
                revision = receipt['revision']
            self.fault('capacity', self.control, endpoint, 'step', attempt, revision, 200)
            cancelled = self.control(endpoint, 'cancel', attempt, revision, 201)
            self.assertEqual(cancelled['kind'], 'cancelled')
            trail = self.audit(endpoint, attempt)
            self.assertEqual(len(trail['events']), MAX_ADVANCES * 2 + 3)
            self.assertIsNone(trail['result'])
            stage.assert_not_called()

    def test_unverified_stage_does_not_advance_progress_or_publish(self):
        with self.service() as (endpoint, _), patch(
                'experiments.supervision_lab._calculate_stage', return_value=2.0) as stage:
            attempt = self.ready(endpoint)
            self.control(endpoint, 'continue', attempt, 2, 61)
            view = self.assert_progress(endpoint, attempt, state='failed', mode=None)
            self.assertEqual(view['reason'], 'operation_failed')
            self.assertIsNone(self.audit(endpoint, attempt)['result'])
            stage.assert_called_once_with(1, None)

    def backdate_expiry(self, attempt):
        with closing(sqlite3.connect(self.db)) as db:
            for table in ('execution_events', 'supervision_events'):
                column = 'state' if table == 'execution_events' else 'kind'
                cursor = db.execute(f"UPDATE {table} SET at=? WHERE attempt_id=? AND {column}='expired'",
                                    (WALL + 5, attempt))
                self.assertEqual(cursor.rowcount, 1)
            db.commit()
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_false_early_expiry_with_only_consumed_step_is_rejected(self):
        with self.service() as (endpoint, broker):
            attempt = self.ready(endpoint, ttl=120)
            self.shorten_advance_grant(broker, attempt, Control.STEP)
            self.control(endpoint, 'step', attempt, 2, 61)
            paused = self.assert_progress(endpoint, attempt, done=1)
            self.clock = WALL + 120
            self.control(endpoint, 'continue', attempt, paused['revision'], 62)
            self.assertEqual(self.audit(endpoint, attempt)['reason'], 'attempt_expired')
        self.backdate_expiry(attempt)
        with self.assertRaisesRegex(RegistryError, '^invalid_storage$'):
            with self.service(create=False):
                self.fail('accepted expiry based on a consumed step')

    def test_false_early_expiry_with_active_but_unexpired_continue_is_rejected(self):
        with self.service() as (endpoint, _), ThreadPoolExecutor(1) as pool, self.gated_stage() as gate:
            attempt = self.ready(endpoint, ttl=120)
            arrived, release, stage = gate
            running = pool.submit(self.control, endpoint, 'continue', attempt, 2, 61)
            self.assertTrue(arrived.wait(WAIT))
            self.clock = WALL + 120
            release.set()
            running.result(WAIT)
            self.assertEqual(self.audit(endpoint, attempt)['reason'], 'attempt_expired')
            stage.assert_called_once_with(1, None)
        self.backdate_expiry(attempt)
        with self.assertRaisesRegex(RegistryError, '^invalid_storage$'):
            with self.service(create=False):
                self.fail('accepted expiry before the active command deadline')

    def test_tampered_ledger_fails_closed_on_open(self):
        with self.service() as (endpoint, _):
            attempt = self.ready(endpoint)
            self.control(endpoint, 'continue', attempt, 2, 61)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE supervision_events SET kind='paused' WHERE attempt_id=? AND kind='dispatched'",
                       (attempt,))
            db.commit()
        with self.assertRaisesRegex(RegistryError, '^invalid_storage$'):
            with self.service(create=False):
                self.fail('accepted a fabricated pause acknowledgement')

    def reference_client(self, endpoint, principal, *arguments):
        output, errors = StringIO(), StringIO()
        with patch('tools.supervised_execution.getpass', return_value=self.tokens[principal]), \
                redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(client_main(['--socket', str(endpoint), *arguments]), 0)
        self.assertNotIn(self.tokens[principal], output.getvalue() + errors.getvalue())
        return json.loads(output.getvalue())

    def test_reference_client_uses_typed_commands_and_masks_credential(self):
        with self.service() as (endpoint, _):
            attempt = self.ready(endpoint)
            self.assertEqual(self.reference_client(endpoint, OBSERVER, 'status', attempt)['supervision'], 'paused')
            self.assertEqual(self.reference_client(endpoint, SUPERVISOR, 'step', attempt, '2', opaque(61))['kind'],
                             'step')
            self.assertEqual(self.reference_client(endpoint, OBSERVER, 'status', attempt)['completed_stages'], 1)

    def test_reference_client_replays_historical_control_receipts_separately_from_status(self):
        with self.service() as (endpoint, _), ThreadPoolExecutor(1) as pool, self.gated_stage() as gate:
            attempt = self.ready(endpoint)
            arrived, release, stage = gate
            running = pool.submit(self.control, endpoint, 'continue', attempt, 2, 61)
            self.assertTrue(arrived.wait(WAIT))
            before_pause = self.assert_progress(endpoint, attempt, mode='flowing', current=1)
            pause = self.control(endpoint, 'pause', attempt, before_pause['revision'], 62)
            release.set()
            advance = running.result(WAIT)
            paused = self.assert_progress(endpoint, attempt, done=1)
            step = self.control(endpoint, 'step', attempt, paused['revision'], 63)
            for action, revision, request, expected in (
                    ('continue', 2, 61, advance),
                    ('pause', before_pause['revision'], 62, pause),
                    ('step', paused['revision'], 63, step)):
                replay = self.reference_client(endpoint, SUPERVISOR, action, attempt,
                                               str(revision), opaque(request))
                self.assertEqual(replay, expected)
                self.assertEqual(set(replay), {'id', 'revision', 'kind'})
            snapshot = self.reference_client(endpoint, OBSERVER, 'status', attempt)
            self.assertEqual((pause['kind'], snapshot['state'], snapshot['supervision']),
                             ('pause_requested', 'completed', None))
            self.assertGreater(snapshot['revision'], step['revision'])
            self.assertEqual([call.args for call in stage.call_args_list], [(1, None), (2, 2)])
