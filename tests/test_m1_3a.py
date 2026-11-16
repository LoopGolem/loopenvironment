# SPDX-License-Identifier: Apache-2.0
"""Observable authority invariants. Fake adapter records actual dispatches, not policy."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import os
import socket
import threading
from unittest.mock import patch
import unittest

from experiments.m1_2.protocol import Channel, Fault, MAX_FRAME, RPC, encode
from experiments.m1_3a.authority import TARGET
from experiments.m1_3a.broker import Broker, Connection
from experiments.m1_3a.identity import Identities


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now


class RecordingAdapter:
    def __init__(self):
        self.digits, self.sent = '', 0
        self.on_prepare = self.on_send = self.on_confirm = lambda: None

    def snapshot(self):
        return {'display': self.digits}, object()

    def prepare(self, ref):
        self.on_prepare()
        return ref

    def send(self, prepared):
        self.on_send()
        self.sent += 1
        self.digits += '7'

    def confirm(self, prepared):
        self.on_confirm()
        return {'display': self.digits}


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.adapter = Clock(), RecordingAdapter()
        self.identities = Identities()
        self.credentials = self.identities.provision()
        self.broker = Broker(self.identities, {'S': self.adapter, 'T': RecordingAdapter()},
                             os.getuid(), self.clock)
        self.owner, self.delegate, self.observer = [self.connect(p) for p in ('owner', 'delegate', 'observer')]
        self.s = self.broker.sessions['S']

    def connect(self, principal):
        c = Connection(os.getuid())
        self.broker.handle(c, 'auth', dict(credential=self.credentials[principal]))
        return c

    def call(self, c, method, **params):
        if method not in ('auth', 'discover'):
            params.setdefault('session', 'S')
        return self.broker.handle(c, method, params)

    def grant(self, principal='delegate', capability='desktop.control', target=TARGET, ttl=60, session='S'):
        return self.call(self.owner, 'delegate', principal=principal, capability=capability,
                         target=target, ttl=ttl, session=session)['grant']

    def ready(self, c=None):
        c = c or self.delegate
        self.grant(c.principal, 'desktop.observe')
        self.grant(c.principal)
        lease = self.call(c, 'acquire', ttl=30)
        snap = self.call(c, 'snapshot')
        return dict(lease=lease['id'], generation=lease['generation'], epoch=lease['epoch'],
                    reference=snap['reference'])

    def denied(self, operation, message=None):
        with self.assertRaises(Fault) as caught:
            operation()
        if message:
            self.assertEqual(caught.exception.message, message)
        return caught.exception.message

    def test_independent_credentials_and_connections(self):
        self.assertEqual(len(set(self.credentials.values())), 3)
        self.assertTrue(all(len(c) >= 43 for c in self.credentials.values()))
        self.assertEqual(self.delegate.principal, 'delegate')
        self.assertNotEqual(self.delegate.id, self.connect('delegate').id)

    def test_missing_wrong_unenrolled_credentials_uniform_denial(self):
        for params in ({}, {'credential': ''}, {'credential': 'unenrolled'}, {'credential': 'wrong'},
                       {'credential': None}, {'credential': '☃'}, {'credential': '\ud800'}):
            c = Connection(os.getuid())
            self.denied(lambda: self.broker.handle(c, 'auth', params), 'denied')
            self.denied(lambda: self.call(c, 'snapshot'), 'denied')
            self.assertIsNone(c.principal)
        self.assertEqual(self.adapter.sent, 0)

    def test_same_uid_does_not_authenticate(self):
        self.denied(lambda: self.call(Connection(os.getuid()), 'discover'), 'denied')

    def test_wrong_peer_uid_with_valid_credential(self):
        self.denied(lambda: self.call(Connection(os.getuid()+1), 'auth',
                                     credential=self.credentials['owner']), 'denied')

    def test_auth_claims_are_rejected(self):
        for extra in ({'principal_id': 'owner'}, {'human': True}, {'role': 'owner'}, {'agent': False}):
            self.denied(lambda: self.call(self.delegate, 'auth', credential=self.credentials['delegate'], **extra))
            self.assertIsNone(self.delegate.principal)
            self.delegate = self.connect('delegate')

    def test_request_identity_claims_cannot_elevate(self):
        for extra in ({'principal_id': 'owner'}, {'human': True}, {'role': 'owner'}):
            self.denied(lambda: self.call(self.delegate, 'snapshot', **extra), 'invalid_params')
            self.assertEqual(self.delegate.principal, 'delegate')

    def test_invalid_reauth_fences_lease_and_reference(self):
        p = self.ready()
        self.denied(lambda: self.call(self.delegate, 'auth', credential='wrong'))
        self.assertIsNone(self.s.lease)
        self.assertIsNone(self.delegate.handle)
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'denied')
        self.assertEqual(self.adapter.sent, 0)

    def test_reauth_success_also_requires_new_lease_and_snapshot(self):
        p = self.ready()
        self.call(self.delegate, 'auth', credential=self.credentials['delegate'])
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p))

    def test_identity_can_intentionally_authenticate_multiple_connections(self):
        self.ready()
        other = self.connect('delegate')
        self.denied(lambda: self.call(other, 'acquire', ttl=10), 'control_busy')

    def test_observer_can_read_but_cannot_acquire_or_mutate(self):
        self.grant('observer', 'desktop.observe')
        self.assertEqual(self.call(self.observer, 'snapshot')['state'], {'display': ''})
        self.denied(lambda: self.call(self.observer, 'acquire', ttl=10), 'grant_denied')
        self.denied(lambda: self.call(self.observer, 'invoke7', lease='x', generation=0,
                                     epoch=self.s.epoch, reference='x'), 'grant_denied')
        self.assertEqual(self.adapter.sent, 0)

    def test_control_does_not_imply_observation_or_override_or_admin(self):
        self.grant()
        self.call(self.delegate, 'acquire', ttl=10)
        self.denied(lambda: self.call(self.delegate, 'snapshot'), 'grant_denied')
        self.denied(lambda: self.s.begin_simulated_takeover('delegate'), 'grant_denied')
        self.denied(lambda: self.call(self.delegate, 'delegate', principal='observer',
                                     capability='identity.admin', target='*', ttl=10), 'grant_denied')

    def test_delegate_cannot_revoke_other_operator(self):
        g = self.grant('observer', 'desktop.observe')
        self.denied(lambda: self.call(self.delegate, 'revoke', grant=g), 'grant_denied')
        self.assertFalse(self.s.grants[g].revoked)

    def test_admin_delegation_is_explicit_and_bounded(self):
        self.grant(capability='identity.admin', ttl=30)
        self.grant(capability='desktop.observe', ttl=20)
        self.call(self.delegate, 'delegate', principal='observer', capability='desktop.observe', target=TARGET, ttl=10)
        for capability, target, ttl in [('desktop.control', TARGET, 10), ('desktop.observe', '*', 10),
                                        ('desktop.observe', TARGET, 21)]:
            self.denied(lambda: self.call(self.delegate, 'delegate', principal='observer',
                                         capability=capability, target=target, ttl=ttl),
                        'grant_denied' if target == '*' else 'delegation_denied')

    def test_admin_cannot_revoke_wider_scope(self):
        self.grant(capability='identity.admin', target=TARGET)
        g = self.grant('observer', 'desktop.observe', target='*')
        self.denied(lambda: self.call(self.delegate, 'revoke', grant=g), 'grant_denied')

    def test_session_scope_is_not_interchangeable(self):
        p = self.ready()
        self.denied(lambda: self.call(self.delegate, 'acquire', session='T', ttl=10), 'grant_denied')
        self.grant(session='T')
        self.denied(lambda: self.call(self.delegate, 'invoke7', session='T', **p), 'stale_lease')
        self.denied(lambda: self.call(self.delegate, 'snapshot', session='unknown'), 'grant_denied')

    def test_discovery_requires_separate_capability(self):
        self.grant(capability='desktop.observe')
        self.denied(lambda: self.call(self.delegate, 'discover'), 'grant_denied')
        self.grant(capability='session.discover')
        self.assertEqual(self.call(self.delegate, 'discover'), {'sessions': ['S']})

    def test_invalid_target_or_duration_fails_closed(self):
        for target in ('unknown', 'another-window'):
            self.denied(lambda: self.grant(target=target), 'invalid_scope')
        for ttl in (0, -1, True, 181, float('nan'), float('inf'), '10'):
            self.denied(lambda: self.grant(ttl=ttl), 'invalid_duration')

    def test_expired_grant_denies_observation(self):
        self.grant(capability='desktop.observe', ttl=1)
        self.clock.now = 1
        self.denied(lambda: self.call(self.delegate, 'snapshot'), 'grant_denied')

    def test_expired_control_invalidates_lease(self):
        p = self.ready()
        self.clock.now = 60
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'grant_denied')
        self.assertIsNone(self.s.lease)

    def test_expired_lease_denies_new_action(self):
        p = self.ready()
        self.clock.now = 30
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'stale_lease')
        self.assertEqual(self.adapter.sent, 0)

    def test_expired_reference_denies_action(self):
        p = self.ready()
        self.clock.now = 10
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'stale_reference')

    def test_revoke_control_fences_all_connections(self):
        p = self.ready()
        g = next(g.id for g in self.s.grants.values() if g.principal == 'delegate' and g.capability == 'desktop.control')
        self.call(self.owner, 'revoke', grant=g)
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'grant_denied')
        self.denied(lambda: self.call(self.connect('delegate'), 'acquire', ttl=10), 'grant_denied')
        self.assertEqual(self.adapter.digits, '')

    def test_revoke_during_target_validation_prevents_dispatch(self):
        p = self.ready()
        g = next(g.id for g in self.s.grants.values() if g.principal == 'delegate' and g.capability == 'desktop.control')
        self.adapter.on_prepare = lambda: self.call(self.owner, 'revoke', grant=g)
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'grant_denied')
        self.assertEqual(self.adapter.sent, 0)
        self.assertEqual(self.s.phase, 'idle')

    def test_expiry_during_validation_prevents_dispatch(self):
        p = self.ready()
        self.adapter.on_prepare = lambda: setattr(self.clock, 'now', 60)
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p))
        self.assertEqual(self.adapter.sent, 0)

    def test_expiry_after_dispatch_does_not_falsely_cancel(self):
        p = self.ready()
        self.adapter.on_confirm = lambda: setattr(self.clock, 'now', 60)
        self.assertTrue(self.call(self.delegate, 'invoke7', **p)['confirmed'])
        self.assertEqual(self.adapter.digits, '7')
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p))

    def test_one_shot_reference_replay_has_no_second_effect(self):
        p = self.ready()
        self.assertTrue(self.call(self.delegate, 'invoke7', **p)['confirmed'])
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'stale_reference')
        self.assertEqual(self.adapter.digits, '7')

    def test_lease_cannot_be_borrowed_by_same_or_other_identity(self):
        p = self.ready()
        self.denied(lambda: self.call(self.connect('delegate'), 'invoke7', **p), 'stale_lease')
        self.grant('observer')
        self.denied(lambda: self.call(self.observer, 'invoke7', **p), 'stale_lease')
        self.assertEqual(self.adapter.sent, 0)

    def test_snapshot_from_before_acquisition_requires_refresh(self):
        self.grant(capability='desktop.observe')
        self.grant()
        snap = self.call(self.delegate, 'snapshot')
        lease = self.call(self.delegate, 'acquire', ttl=10)
        self.denied(lambda: self.call(self.delegate, 'invoke7', lease=lease['id'],
                                     generation=lease['generation'], epoch=lease['epoch'],
                                     reference=snap['reference']), 'stale_reference')

    def test_reconnect_invalidates_old_lease_and_handle(self):
        p = self.ready()
        self.broker.disconnect(self.delegate)
        self.delegate = self.connect('delegate')
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'stale_lease')
        self.denied(lambda: self.call(self.delegate, 'events', epoch=self.s.epoch, cursor=0), 'snapshot_required')

    def test_disconnect_during_validation_prevents_dispatch(self):
        p = self.ready()
        self.adapter.on_prepare = lambda: self.broker.disconnect(self.delegate)
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'denied')
        self.assertEqual(self.adapter.sent, 0)

    def test_transport_eof_before_dispatch_prevents_action(self):
        p = self.ready()
        self.delegate.alive = lambda: False
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'stale_reference')
        self.assertEqual(self.adapter.sent, 0)

    def test_unknown_or_ambiguous_target_does_not_dispatch(self):
        p = self.ready()
        def ambiguous():
            raise RuntimeError('ambiguous')
        self.adapter.on_prepare = ambiguous
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'target_unavailable_or_ambiguous')
        self.assertEqual(self.adapter.sent, 0)

    def test_unknown_after_dispatch_blocks_and_never_retries(self):
        p = self.ready()
        def unknown():
            raise TimeoutError
        self.adapter.on_confirm = unknown
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'outcome_unknown')
        self.assertEqual(self.s.phase, 'blocked')
        self.denied(lambda: self.call(self.owner, 'acquire', ttl=10), 'control_busy')
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p))
        self.assertEqual(self.adapter.sent, 1)

    def test_restart_changes_epoch_and_rejects_previous_lease(self):
        p = self.ready()
        old = self.s.epoch
        self.call(self.owner, 'restart')
        self.assertNotEqual(old, self.s.epoch)
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'stale_lease')

    def test_old_generation_rejected_after_release_and_acquire(self):
        p = self.ready()
        release = {k: v for k, v in p.items() if k != 'reference'}
        self.call(self.delegate, 'release', **release)
        new = self.call(self.delegate, 'acquire', ttl=10)
        self.assertGreater(new['generation'], p['generation'])
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'stale_lease')

    def test_event_gap_requires_snapshot_and_retention_is_bounded(self):
        snap = self.call(self.owner, 'snapshot')
        for _ in range(10):
            self.grant()
        self.assertEqual(len(self.s.history.items), 8)
        self.denied(lambda: self.call(self.owner, 'events', epoch=snap['epoch'], cursor=snap['cursor']),
                    'gap_snapshot_required')
        self.denied(lambda: self.call(self.owner, 'events', epoch=snap['epoch'], cursor=self.s.history.seq),
                    'snapshot_required')
        fresh = self.call(self.owner, 'snapshot')
        self.assertEqual(self.call(self.owner, 'events', epoch=fresh['epoch'], cursor=fresh['cursor'])['events'], [])

    def test_event_revocation_and_epoch_change(self):
        g = self.grant('observer', 'desktop.observe')
        snap = self.call(self.observer, 'snapshot')
        self.call(self.owner, 'revoke', grant=g)
        self.denied(lambda: self.call(self.observer, 'events', epoch=snap['epoch'], cursor=snap['cursor']), 'grant_denied')
        self.call(self.owner, 'restart')
        self.denied(lambda: self.call(self.owner, 'events', epoch=snap['epoch'], cursor=0), 'snapshot_required')

    def race(self, *operations):
        barrier = threading.Barrier(len(operations))
        def run(op):
            barrier.wait(timeout=2)
            try:
                return op()
            except Fault as e:
                return e.message
        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            return list(executor.map(run, operations))

    def test_simultaneous_acquisitions_have_one_winner(self):
        self.grant()
        self.grant('observer')
        result = self.race(lambda: self.call(self.delegate, 'acquire', ttl=10),
                           lambda: self.call(self.observer, 'acquire', ttl=10))
        self.assertEqual(sum(isinstance(r, dict) for r in result), 1)
        self.assertIn('control_busy', result)

    def test_concurrent_revoke_and_acquire_leave_no_valid_revoked_lease(self):
        g = self.grant()
        self.race(lambda: self.call(self.delegate, 'acquire', ttl=10),
                  lambda: self.call(self.owner, 'revoke', grant=g))
        self.assertIsNone(self.s.lease)
        self.assertFalse(self.s.permits('delegate', 'desktop.control'))

    def test_concurrent_grants_do_not_lose_policy_revisions(self):
        before = self.s.policy_revision
        result = self.race(lambda: self.grant(), lambda: self.grant())
        self.assertEqual(len(set(result)), 2)
        self.assertEqual(self.s.policy_revision, before+2)

    def test_two_concurrent_operations_dispatch_at_most_once(self):
        p = self.ready()
        result = self.race(lambda: self.call(self.delegate, 'invoke7', **p),
                           lambda: self.call(self.delegate, 'invoke7', **p))
        self.assertEqual(self.adapter.sent, 1)
        self.assertEqual(sum(isinstance(r, dict) for r in result), 1)

    def test_release_racing_acquire_preserves_exclusivity(self):
        p = self.ready()
        self.grant('observer')
        self.race(lambda: self.call(self.delegate, 'release', **{k:v for k,v in p.items() if k != 'reference'}),
                  lambda: self.call(self.observer, 'acquire', ttl=10))
        self.assertIn(self.s.phase, ('idle', 'controlled'))
        self.assertTrue(self.s.lease is None or self.s.lease.principal == 'observer')

    def test_revoke_after_dispatch_preserves_pending_until_confirmation(self):
        p = self.ready()
        entered, resume = threading.Event(), threading.Event()
        def pending():
            entered.set()
            if not resume.wait(2):
                raise TimeoutError
        self.adapter.on_confirm = pending
        g = next(g.id for g in self.s.grants.values() if g.principal == 'delegate' and g.capability == 'desktop.control')
        with ThreadPoolExecutor(1) as executor:
            future = executor.submit(self.call, self.delegate, 'invoke7', **p)
            try:
                self.assertTrue(entered.wait(2))
                result = self.call(self.owner, 'revoke', grant=g)
                self.assertEqual(result['pending_effects'], 'not_cancelled')
                self.assertEqual(self.s.phase, 'handoff_pending')
                self.denied(lambda: self.call(self.owner, 'acquire', ttl=10), 'control_busy')
                self.denied(lambda: self.call(self.owner, 'restart'), 'operation_pending')
            finally:
                resume.set()
            self.assertTrue(future.result(2)['confirmed'])
        self.assertEqual(self.s.phase, 'idle')
        self.assertEqual(self.adapter.digits, '7')

    def test_abstract_takeover_waits_for_simulated_barrier(self):
        p = self.ready()
        self.s.pending = 'simulated-not-yet-dispatched'
        generation = self.s.generation
        with self.s.lock:
            self.s.begin_simulated_takeover('owner')
            self.assertEqual(self.s.phase, 'handoff_pending')
            self.assertEqual(self.s.generation, generation)
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p))
        with self.s.lock:
            lease = self.s.finish_simulated_takeover('owner', self.owner.id, 'cancelled_before_dispatch')
        self.assertEqual(lease.generation, generation+1)
        # New controller cannot borrow the old target; a fresh snapshot is required.
        new = dict(lease=lease.id, epoch=lease.epoch, generation=lease.generation, reference=p['reference'])
        self.denied(lambda: self.call(self.owner, 'invoke7', **new), 'stale_reference')
        new['reference'] = self.call(self.owner, 'snapshot')['reference']
        self.assertTrue(self.call(self.owner, 'invoke7', **new)['confirmed'])
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'stale_lease')
        kinds = [e['kind'] for e in self.s.history.items]
        self.assertLess(kinds.index('simulation.cancelled_before_dispatch'), len(kinds)-1-kinds[::-1].index('control.changed'))

    def test_abstract_unknown_barrier_never_confirms(self):
        self.ready()
        self.s.pending = 'simulated-delivery-unknown'
        generation = self.s.generation
        self.s.begin_simulated_takeover('owner')
        self.denied(lambda: self.s.finish_simulated_takeover('owner', self.owner.id, 'unknown'), 'handoff_not_confirmed')
        self.assertEqual(self.s.phase, 'blocked')
        self.assertEqual(self.s.generation, generation)
        self.assertIsNotNone(self.s.pending)

    def test_abstract_delegated_override_requires_control_and_live_grants(self):
        self.grant('observer', 'session.override')
        self.denied(lambda: self.s.begin_simulated_takeover('observer'), 'grant_denied')
        self.grant('observer', 'desktop.control')
        self.s.begin_simulated_takeover('observer')
        lease = self.s.finish_simulated_takeover('observer', self.observer.id, 'completed_before_barrier')
        self.assertEqual(lease.principal, 'observer')

    def test_real_protocol_has_no_takeover_or_arbitrary_adapter_path(self):
        for method in ('takeover', 'raw.dbus', 'SendInput'):
            self.denied(lambda: self.call(self.owner, method), 'method_not_found')

    def test_grant_storage_is_bounded(self):
        for _ in range(128-len(self.s.grants)):
            self.grant()
        self.denied(lambda: self.grant(), 'grant_limit')


    def test_blocked_outcome_cannot_be_cleared_by_logical_restart(self):
        p = self.ready()
        self.adapter.on_confirm = lambda: (_ for _ in ()).throw(TimeoutError())
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'outcome_unknown')
        epoch = self.s.epoch
        self.denied(lambda: self.call(self.owner, 'restart'), 'handoff_not_confirmed')
        self.assertEqual(self.s.epoch, epoch)
        self.assertEqual(self.s.phase, 'blocked')

    def test_snapshot_rechecks_observation_after_external_query(self):
        g = self.grant('observer', 'desktop.observe')
        original = self.adapter.snapshot
        def revoke_during_read():
            result = original()
            self.call(self.owner, 'revoke', grant=g)
            return result
        self.adapter.snapshot = revoke_during_read
        self.denied(lambda: self.call(self.observer, 'snapshot'), 'grant_denied')
        self.assertIsNone(self.observer.handle)

    def test_snapshot_replaces_previous_reference(self):
        p = self.ready()
        self.call(self.delegate, 'snapshot')
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'stale_reference')
        self.assertEqual(self.adapter.sent, 0)

    def test_expiration_allows_fresh_generation_but_no_old_replay(self):
        p = self.ready()
        self.clock.now = 30
        new = self.call(self.delegate, 'acquire', ttl=10)
        self.assertGreater(new['generation'], p['generation'])
        self.denied(lambda: self.call(self.delegate, 'invoke7', **p), 'stale_lease')

    def test_other_session_policy_remains_available_during_slow_adapter(self):
        p = self.ready()
        entered, resume = threading.Event(), threading.Event()
        def slow():
            entered.set()
            if not resume.wait(2):
                raise TimeoutError
        self.adapter.on_prepare = slow
        with ThreadPoolExecutor(1) as executor:
            future = executor.submit(self.call, self.delegate, 'invoke7', **p)
            try:
                self.assertTrue(entered.wait(2))
                lease = self.call(self.owner, 'acquire', session='T', ttl=10)
                self.assertEqual(lease['principal'], 'owner')
                g = next(g.id for g in self.s.grants.values() if g.principal == 'delegate' and g.capability == 'desktop.control')
                self.call(self.owner, 'revoke', grant=g)
            finally:
                resume.set()
            with self.assertRaisesRegex(Fault, 'grant_denied'):
                future.result(2)
        self.assertEqual(self.adapter.sent, 0)

    def test_simulated_barrier_cannot_be_completed_by_other_requester(self):
        self.s.begin_simulated_takeover('owner')
        self.grant('observer', 'session.override')
        self.grant('observer', 'desktop.control')
        self.denied(lambda: self.s.finish_simulated_takeover('observer', self.observer.id,
                    'completed_before_barrier'), 'handoff_not_confirmed')
        self.assertEqual(self.s.phase, 'handoff_pending')


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.identities = Identities()
        self.credentials = self.identities.provision()
        self.broker = Broker(self.identities, {'S': RecordingAdapter()}, os.getuid())
        self.client, server = socket.socketpair()
        self.client.settimeout(2)
        self.worker = threading.Thread(target=self.broker.serve_connection, args=(server, .1, 1))
        self.worker.start()
        self.rpc = RPC(self.client)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.client.close()
        self.worker.join(2)
        self.assertFalse(self.worker.is_alive())

    def test_authenticated_connection_uses_server_identity(self):
        self.assertEqual(self.rpc.call('auth', credential=self.credentials['delegate'])['principal'], 'delegate')
        with self.assertRaisesRegex(Fault, 'invalid_params'):
            self.rpc.call('snapshot', session='S', principal_id='owner')
        with self.assertRaisesRegex(Fault, 'grant_denied'):
            self.rpc.call('snapshot', session='S')

    def test_unknown_method_and_params_are_not_echoed_in_audit(self):
        self.rpc.call('auth', credential=self.credentials['owner'])
        with self.assertRaises(Fault):
            self.rpc.call(self.credentials['delegate'], secret=self.credentials['observer'])
        encoded = json.dumps(list(self.broker.audit))
        self.assertFalse(any(c in encoded for c in self.credentials.values()))

    def test_malformed_envelope_closes_connection(self):
        self.client.sendall(encode({'jsonrpc': '2.0', 'id': True, 'method':'auth', 'params':{}}))
        self.assertEqual(self.client.recv(1), b'')

    def test_oversized_frame_closes_connection(self):
        try:
            self.client.sendall(b'x'*(MAX_FRAME+1))
            self.assertEqual(self.client.recv(1), b'')
        except ConnectionResetError:
            pass

    def test_malformed_json_closes_connection(self):
        self.client.sendall(b'NaN\n')
        self.assertEqual(self.client.recv(1), b'')

    def test_replayed_request_id_closes_connection(self):
        self.rpc.call('auth', credential=self.credentials['owner'])
        self.client.sendall(encode(dict(jsonrpc='2.0', id=1, method='snapshot', params={'session':'S'})))
        self.assertEqual(self.client.recv(1), b'')

    def test_idle_timeout_closes_connection(self):
        self.worker.join(1)
        self.assertFalse(self.worker.is_alive())
        self.assertEqual(self.client.recv(1), b'')

    def test_audit_retention_bounded_under_actual_requests(self):
        for _ in range(3):
            a, b = socket.socketpair()
            worker = threading.Thread(target=self.broker.serve_connection, args=(b,))
            worker.start()
            try:
                rpc = RPC(a)
                rpc.call('auth', credential=self.credentials['owner'])
                for _ in range(59):
                    with self.assertRaises(Fault):
                        rpc.call('unsupported')
            finally:
                a.close()
                worker.join(2)
                self.assertFalse(worker.is_alive())
        self.assertEqual(len(self.broker.audit), 128)

    def test_connection_request_budget_is_enforced(self):
        self.rpc.call('auth', credential=self.credentials['owner'])
        for _ in range(63):
            with self.assertRaises(Fault):
                self.rpc.call('unknown')
        self.assertEqual(self.client.recv(1), b'')

    def test_duplicate_json_fields_close_connection(self):
        self.client.sendall(b'{"jsonrpc":"2.0","id":1,"id":2,"method":"auth","params":{}}\n')
        self.assertEqual(self.client.recv(1), b'')

    def test_absolute_frame_budget_prevents_slow_trickle(self):
        from experiments.m1_3a.protocol import DeadlineChannel
        clock = Clock()
        class SlowSocket:
            def settimeout(self, value):
                pass
            def recv(self, count):
                clock.now += .6
                return b' '
        with patch('experiments.m1_3a.protocol.time.monotonic', clock):
            with self.assertRaises(socket.timeout):
                DeadlineChannel(SlowSocket()).receive(1)
        self.assertLess(clock.now, 2)
