# SPDX-License-Identifier: Apache-2.0
"""Exercise authenticated Registry requests over actual disposable Unix sockets."""
from contextlib import closing, contextmanager
from hashlib import sha256
import multiprocessing
from pathlib import Path
from secrets import token_urlsafe
import socket
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier, Event, Thread
import unittest
from unittest.mock import Mock, patch

from experiments.objective_registry import Permission
from experiments.registry_lab import serve_registry
from experiments.registry_rpc import VERSION
from loopbridge.broker import Server
from loopbridge.desktop_broker import DesktopBroker
from loopbridge.identity import Identities
from loopbridge.protocol import Fault, MAX_FRAME, RPC
from loopbridge.service import Journal
from loopbridge.service_ingress import bound_listener


def identifier(number):
    return f'{number:032x}'


ADMIN, ISSUER, EXECUTOR, OTHER = map(identifier, (1, 2, 3, 4))
TARGET, OTHER_TARGET = map(identifier, (10, 11))
TEXT = 'Preparar revisão. Texto literal: $(touch registry-must-not-run)\n<markup>'
GRANTS = (
    (ADMIN, Permission.REGISTER, TARGET),
    (ADMIN, Permission.REGISTER, OTHER_TARGET),
    (EXECUTOR, Permission.CONFIRM, TARGET),
    (EXECUTOR, Permission.READ_EXECUTOR, TARGET),
    (EXECUTOR, Permission.READ_OBJECTIVE, TARGET),
    (EXECUTOR, Permission.RESPOND_TO_OBJECTIVE, TARGET),
    (ISSUER, Permission.AUTHOR_OBJECTIVE, TARGET),
    (ISSUER, Permission.READ_OBJECTIVE, TARGET),
)


def digest(token):
    return sha256(token.encode()).hexdigest()


def configure(broker, grants=GRANTS):
    for principal, permission, executor in grants:
        broker.access.policy.grant(principal, permission, executor, expires_at=10**10)


def run_child(root, legacy, verifiers, create, grants, guardian):
    identities = Identities()
    identities.load(legacy)
    try:
        with serve_registry(root, identities, verifiers, create=create) as (endpoint, broker):
            configure(broker, grants)
            guardian.send(str(endpoint))
            guardian.recv()
    finally:
        guardian.close()


class TrustedRegistryRPC(unittest.TestCase):
    def setUp(self):
        root = TemporaryDirectory(prefix='loop-registry-')
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        self.database = self.root / 'registry.sqlite3'
        self.identities = Identities()
        self.legacy = self.identities.provision()
        self.credentials = {name: token_urlsafe(32) for name in (ADMIN, ISSUER, EXECUTOR, OTHER)}
        self.verifiers = {name: digest(secret) for name, secret in self.credentials.items()}
        self.wall, self.mono = 1_780_000_000, 10

    @contextmanager
    def server(self, *, create=True, grants=GRANTS, adapters=None):
        with serve_registry(self.root, self.identities, self.verifiers, create=create,
                            wall_clock=lambda: self.wall, clock=lambda: self.mono,
                            adapters=adapters) as (endpoint, broker):
            configure(broker, grants)
            self.assertEqual(endpoint.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)
            yield endpoint, broker
        self.assertFalse(endpoint.exists())

    @contextmanager
    def process(self, *, create, grants=GRANTS):
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe()
        with parent, child:
            service = context.Process(target=run_child, args=(
                self.root, self.legacy, self.verifiers, create, grants, child))
            service.start()
            child.close()
            try:
                self.assertTrue(parent.poll(8), 'broker did not start')
                endpoint = parent.recv()
                yield endpoint, service.pid
            finally:
                if service.is_alive():
                    parent.send('stop')
                service.join(8)
                if service.is_alive():
                    service.terminate()
                    service.join()
                    self.fail('broker did not shut down')
                self.assertEqual(service.exitcode, 0)
                service.close()

    @contextmanager
    def client(self, endpoint, principal=None, *, credential=None, version=VERSION):
        with socket.socket(socket.AF_UNIX) as peer:
            peer.settimeout(4)
            peer.connect(str(endpoint))
            rpc = RPC(peer, version, timeout=4)
            if principal is not None:
                if credential is None:
                    credential = (self.credentials if version == VERSION else self.legacy)[principal]
                self.assertEqual(rpc.call('auth', credential=credential)['principal'], principal)
            yield rpc

    def denied(self, rpc, method, **params):
        self.rpc_error(rpc, method, -32001, 'denied', **params)

    def rpc_error(self, rpc, method, code, message, **params):
        with self.assertRaises(Fault) as caught:
            rpc.call(method, **params)
        self.assertEqual((caught.exception.code, str(caught.exception), caught.exception.data),
                         (code, message, None))

    def bind_executor(self, endpoint):
        with self.client(endpoint, ADMIN) as admin:
            self.assertEqual(admin.call('executor.register', executor_id=TARGET, bound_principal_id=EXECUTOR,
                                        request_id=identifier(20), label='Executor de laboratório'),
                             dict(id=TARGET, revision=1, state='pending'))
        with self.client(endpoint, EXECUTOR) as executor:
            self.assertEqual(executor.call('executor.confirm', executor_id=TARGET, expected_revision=1,
                                            request_id=identifier(21)),
                             dict(id=TARGET, revision=2, state='available'))

    def make_offer(self, rpc, index=30, *, ttl=600, text=TEXT):
        key = identifier(index)
        self.assertEqual(rpc.call('objective.create', objective_id=key, executor_id=TARGET,
                                  request_id=identifier(index + 100), text=text, ttl_seconds=ttl),
                         dict(id=key, revision=1, state='created'))
        self.assertEqual(rpc.call('objective.offer', objective_id=key, request_id=identifier(index + 200),
                                  expected_revision=1),
                         dict(id=key, revision=2, state='offered'))
        return key

    def answer(self, key, *, request=300, decision='accept', revision=2):
        return dict(objective_id=key, decision=decision, expected_revision=revision,
                    request_id=identifier(request))

    def test_process_restart_preserves_objectives_receipt_author_and_audit(self):
        with self.process(create=True) as (endpoint, first_pid):
            self.bind_executor(endpoint)
            with self.client(endpoint, ISSUER) as issuer, self.client(endpoint, EXECUTOR) as executor:
                accepted = self.make_offer(issuer)
                declined = self.make_offer(issuer, 31)
                withdrawn = self.make_offer(issuer, 32)
                self.assertEqual(executor.call('executor.status', executor_id=TARGET),
                                 dict(id=TARGET, revision=2, state='available', label='Executor de laboratório'))
                offers = executor.call('objective.list_offers', executor_id=TARGET, limit=16)
                self.assertEqual([row['id'] for row in offers['items']], [accepted, declined, withdrawn])
                self.assertNotIn('text', offers['items'][0])
                self.assertEqual(executor.call('objective.status', objective_id=accepted)['text'], TEXT)
                reply = executor.call('objective.respond', **self.answer(accepted))
                self.assertEqual(reply, dict(id=accepted, revision=3, state='accepted'))
                self.assertEqual(executor.call('objective.respond', **self.answer(accepted)), reply)
                self.assertEqual(executor.call('objective.respond', **self.answer(declined, request=301,
                                                                                 decision='decline'))['state'],
                                 'declined')
                self.assertEqual(issuer.call('objective.withdraw', objective_id=withdrawn, expected_revision=2,
                                             request_id=identifier(302))['state'], 'withdrawn')
                self.assertEqual(executor.call('objective.list_offers', executor_id=TARGET, limit=16)['items'], [])
        self.assertFalse((self.root / 'registry-lab.sock').exists())
        with self.process(create=False, grants=()) as (endpoint, second_pid):
            self.assertNotEqual(first_pid, second_pid)
            with self.client(endpoint, EXECUTOR) as executor:
                self.denied(executor, 'objective.status', objective_id=accepted)
                self.denied(executor, 'objective.respond', **self.answer(accepted))
        with self.process(create=False) as (endpoint, _):
            with self.client(endpoint) as anonymous, self.client(endpoint, EXECUTOR) as executor:
                self.denied(anonymous, 'objective.status', objective_id=accepted)
                self.assertEqual(executor.call('objective.respond', **self.answer(accepted)), reply)
                for key, state in ((accepted, 'accepted'), (declined, 'declined'), (withdrawn, 'withdrawn')):
                    with self.subTest(state=state):
                        row = executor.call('objective.status', objective_id=key)
                        self.assertEqual((row['state'], row['text'], row['issuer_id']), (state, TEXT, ISSUER))
                self.rpc_error(executor, 'objective.respond', -32044, 'request_conflict',
                               **self.answer(accepted, decision='decline'))
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
            for key, principal in ((accepted, EXECUTOR), (declined, EXECUTOR), (withdrawn, ISSUER)):
                self.assertEqual(db.execute('SELECT changed_by FROM objectives WHERE id=?', (key,)).fetchone(),
                                 (principal,))
                self.assertEqual(db.execute('SELECT actor FROM audit WHERE record_id=? AND revision=3',
                                            (key,)).fetchall(), [(principal,)])
            self.assertEqual(db.execute('SELECT revision,state FROM receipts WHERE principal=? AND request_id=?',
                                        (EXECUTOR, identifier(300))).fetchall(), [(3, 'accepted')])
        for secret in (*self.credentials.values(), *self.legacy.values()):
            self.assertFalse(secret.encode() in self.database.read_bytes())
            self.assertFalse(bytes.fromhex(digest(secret)) in self.database.read_bytes())
        self.assertFalse((Path.cwd() / 'registry-must-not-run').exists())

    def test_wrong_principal_scope_unknown_and_pending_are_denied(self):
        with self.server() as (endpoint, broker):
            with self.client(endpoint, ADMIN) as admin, self.client(endpoint, ISSUER) as issuer, \
                    self.client(endpoint, OTHER) as other:
                self.denied(admin, 'executor.register', executor_id=TARGET, bound_principal_id=identifier(999),
                            request_id=identifier(20), label='Lab')
                self.rpc_error(admin, 'executor.register', -32602, 'invalid_params', executor_id=TARGET,
                               bound_principal_id=EXECUTOR, request_id=identifier(20), label='à' * 65)
                self.rpc_error(admin, 'executor.register', -32602, 'invalid_params', executor_id=TARGET,
                               bound_principal_id=EXECUTOR, request_id=identifier(20), label=self.credentials[OTHER])
                admin.call('executor.register', executor_id=TARGET, bound_principal_id=EXECUTOR,
                           request_id=identifier(20), label='Lab')
                broker.access.policy.grant(OTHER, Permission.CONFIRM, TARGET, expires_at=50)
                self.denied(other, 'executor.confirm', executor_id=TARGET, request_id=identifier(21),
                            expected_revision=1)
                self.rpc_error(issuer, 'objective.create', -32042, 'executor_unavailable',
                               objective_id=identifier(30), executor_id=TARGET, text=TEXT,
                               ttl_seconds=1, request_id=identifier(60))
                with self.client(endpoint, EXECUTOR) as executor:
                    executor.call('executor.confirm', executor_id=TARGET, request_id=identifier(21),
                                  expected_revision=1)
                offer = self.make_offer(issuer)
                for key in (offer, identifier(999)):
                    self.denied(other, 'objective.status', objective_id=key)
                    self.denied(other, 'objective.respond', **self.answer(key))
                broker.access.policy.grant(OTHER, Permission.READ_OBJECTIVE, TARGET, expires_at=50)
                broker.access.policy.grant(OTHER, Permission.RESPOND_TO_OBJECTIVE, TARGET, expires_at=50)
                self.denied(other, 'objective.status', objective_id=offer)
                self.denied(other, 'objective.respond', **self.answer(offer))
                self.denied(other, 'objective.list_offers', executor_id=TARGET, limit=1)
                self.denied(other, 'objective.create', objective_id=identifier(91), executor_id=TARGET,
                            text=TEXT, ttl_seconds=1, request_id=identifier(90))
                for target in (OTHER_TARGET, identifier(998)):
                    self.denied(issuer, 'objective.create', objective_id=identifier(91), executor_id=target,
                                text=TEXT, ttl_seconds=1, request_id=identifier(90))

    def test_same_uid_requires_auth_and_registry_never_dispatches_session_operations(self):
        adapter = Mock(spec=[])
        with self.server(adapters={'desktop': adapter}) as (endpoint, broker):
            self.bind_executor(endpoint)
            session = broker.sessions['desktop']
            grants_before = set(session.grants)
            with self.client(endpoint, ISSUER) as issuer:
                offer = self.make_offer(issuer)
            with self.client(endpoint, EXECUTOR) as actor:
                actor.call('objective.respond', **self.answer(offer))
                self.rpc_error(actor, 'acquire', -32601, 'method_not_found', session='desktop', ttl=10)
                actor.version = '0.6'
                for method, params in (
                    ('discover', {}), ('acquire', dict(session='desktop', ttl=10)),
                    ('window.list', dict(session='desktop', app='firefox')),
                    ('presentation.open', dict(session='desktop', privateId='private', epoch=session.epoch)),
                    ('session.capture', dict(session='desktop')),
                    ('workspace.read', dict(session='desktop', path='document')),
                    ('session.keyboard.type', dict(session='desktop', ref='ref', text='text', lease='guess',
                                                   epoch=session.epoch, generation=1)),
                ):
                    with self.subTest(method=method):
                        self.denied(actor, method, **params)
                self.denied(actor, 'auth', credential=self.credentials[EXECUTOR])
                self.denied(actor, 'discover')
                actor.version = VERSION
                self.denied(actor, 'auth', credential=self.legacy['owner'])
                self.denied(actor, 'executor.status', executor_id=TARGET)
            with self.client(endpoint, 'owner', version='0.6') as owner:
                self.assertEqual(owner.call('discover'), {'sessions': ['desktop']})
                entries = owner.call('audit', session='desktop')['entries']
                self.assertTrue(any(row['method'] == 'discover' for row in entries))
                self.assertFalse(any(row['principal'] in self.credentials
                                     or row['method'].startswith(('executor.', 'objective.'))
                                     for row in entries))
                self.rpc_error(owner, 'executor.status', -32601, 'method_not_found', executor_id=TARGET)
                owner.version = VERSION
                self.denied(owner, 'executor.status', executor_id=TARGET)
                self.denied(owner, 'auth', credential=token_urlsafe(32))
                owner.version = '0.6'
                self.denied(owner, 'discover')
            self.assertIsNone(session.lease)
            self.assertEqual(set(session.grants), grants_before)
            self.assertEqual(adapter.mock_calls, [])

    def test_verifier_collisions_across_principals_and_realms_are_rejected(self):
        duplicate = self.verifiers | {OTHER: self.verifiers[EXECUTOR]}
        historical = self.verifiers | {OTHER: digest(self.legacy['owner'])}
        for verifiers in (duplicate, historical):
            with self.assertRaisesRegex(ValueError, '^invalid_registry_verifiers$'):
                with serve_registry(self.root, self.identities, verifiers, create=True):
                    self.fail('colliding verifiers accepted')
        self.assertFalse(self.database.exists())
        self.assertFalse((self.root / 'registry-lab.sock').exists())

    def test_normal_broker_has_no_registry_wire_version(self):
        broker = DesktopBroker(self.identities, {}, self.root.stat().st_uid, Journal(self.root))
        endpoint = self.root / 'normal.sock'
        with bound_listener(endpoint) as listener, Server(broker, listener):
            with self.client(endpoint) as rpc:
                with self.assertRaises(EOFError):
                    rpc.call('auth', credential=self.credentials[EXECUTOR])
            with self.client(endpoint, 'owner', version='0.6') as rpc:
                self.rpc_error(rpc, 'objective.status', -32601, 'method_not_found', objective_id=TARGET)
        self.assertFalse(self.database.exists())

    def test_rotation_reauth_and_grant_expiry_cover_idempotent_replays(self):
        with self.server() as (endpoint, broker):
            self.bind_executor(endpoint)
            with self.client(endpoint, ISSUER) as issuer:
                offer = self.make_offer(issuer)
            with self.client(endpoint, EXECUTOR) as actor, self.client(endpoint, EXECUTOR) as other:
                expected = actor.call('objective.respond', **self.answer(offer))
                rotated = token_urlsafe(32)
                broker.access.rotate(EXECUTOR, digest(rotated))
                for rpc in (actor, other):
                    self.denied(rpc, 'objective.respond', **self.answer(offer))
                    self.denied(rpc, 'auth', credential=self.credentials[EXECUTOR])
                self.assertEqual(actor.call('auth', credential=rotated)['principal'], EXECUTOR)
                self.assertEqual(actor.call('objective.respond', **self.answer(offer)), expected)
                broker.access.policy.grant(EXECUTOR, Permission.RESPOND_TO_OBJECTIVE, TARGET, expires_at=11)
                self.mono = 11
                self.denied(actor, 'objective.respond', **self.answer(offer))
                self.assertEqual(actor.call('objective.status', objective_id=offer)['state'], 'accepted')
                broker.access.policy.revoke(EXECUTOR, Permission.READ_OBJECTIVE, TARGET)
                self.denied(actor, 'objective.status', objective_id=offer)

    def test_issuer_revocation_blocks_publication_replay_and_withdrawal(self):
        with self.server() as (endpoint, broker):
            self.bind_executor(endpoint)
            with self.client(endpoint, ISSUER) as issuer, self.client(endpoint, EXECUTOR) as actor:
                offer = self.make_offer(issuer)
                draft = issuer.call('objective.create', objective_id=identifier(31), executor_id=TARGET,
                                    text=TEXT, ttl_seconds=10, request_id=identifier(131))
                broker.access.policy.revoke(ISSUER, Permission.AUTHOR_OBJECTIVE, TARGET)
                self.denied(issuer, 'objective.offer', objective_id=draft['id'], expected_revision=1,
                            request_id=identifier(231))
                self.denied(issuer, 'objective.offer', objective_id=offer, expected_revision=1,
                            request_id=identifier(230))
                self.denied(issuer, 'objective.withdraw', objective_id=offer, expected_revision=2,
                            request_id=identifier(330))
                self.assertEqual(actor.call('objective.respond', **self.answer(offer))['state'], 'accepted')
                self.denied(actor, 'objective.status', objective_id=draft['id'])

    def test_schema_limits_and_current_credentials_cannot_be_stored_as_text(self):
        with self.server() as (endpoint, broker):
            self.bind_executor(endpoint)
            with self.client(endpoint, ISSUER) as issuer, self.client(endpoint, EXECUTOR) as actor:
                create = dict(objective_id=identifier(30), executor_id=TARGET, request_id=identifier(100),
                              ttl_seconds=10, text=TEXT)
                for fields in ({'uid': 5}, {'principal': ISSUER}, {'ttl_seconds': True}, {'ttl_seconds': 0},
                               {'ttl_seconds': 86_401}, {'executor_id': 'executor-by-name'}, {'text': 'à' * 1025},
                               {'text': '\x00'}, {'text': ''}, {'text': '\ud800'},
                               {'text': 'prefix' + self.credentials[EXECUTOR] + 'suffix'},
                               {'text': ' ' + self.legacy['owner'] + ' '}):
                    with self.subTest(field=next(iter(fields))):
                        self.rpc_error(issuer, 'objective.create', -32602, 'invalid_params', **(create | fields))
                requested = self.make_offer(issuer, text='à' * 1024)
                self.assertEqual(actor.call('objective.status', objective_id=requested)['text'], 'à' * 1024)
                for bad_revision in (True, 0, 2**53, '2'):
                    self.rpc_error(actor, 'objective.respond', -32602, 'invalid_params',
                                   **self.answer(requested, revision=bad_revision))
                self.rpc_error(actor, 'objective.respond', -32602, 'invalid_params',
                               **self.answer(requested, decision='run'))
                self.rpc_error(actor, 'objective.list_offers', -32602, 'invalid_params', executor_id=TARGET,
                               limit=17)
                self.rpc_error(actor, 'objective.execute', -32601, 'method_not_found', text=TEXT)
                with self.assertRaises(Fault) as caught:
                    issuer.call('objective.create', **(create | {'text': 'a' * MAX_FRAME}))
                self.assertEqual(str(caught.exception), 'frame_limit')
            for secret in (*self.credentials.values(), *self.legacy.values()):
                self.assertFalse(secret in repr(broker.audit))
                self.assertFalse(secret.encode() in self.database.read_bytes())

    def test_bad_frame_and_duplicate_fields_close_real_socket(self):
        with self.server() as (endpoint, _):
            duplicate = (b'{"jsonrpc":"2.0","version":"registry/1","id":1,"method":"auth",'
                         b'"params":{"credential":"first","credential":"second"}}\n')
            for frame in (duplicate, b' ' * MAX_FRAME):
                with socket.socket(socket.AF_UNIX) as peer:
                    peer.settimeout(4)
                    peer.connect(str(endpoint))
                    peer.sendall(frame)
                    self.assertEqual(peer.recv(1), b'')

    def test_pagination_scope_withdrawal_expiry_and_restart(self):
        with self.server() as (endpoint, broker):
            self.bind_executor(endpoint)
            with self.client(endpoint, ISSUER) as issuer, self.client(endpoint, EXECUTOR) as actor:
                first, withdrawn, last = [self.make_offer(issuer, index) for index in (30, 31, 32)]
                original = actor.call('objective.list_offers', executor_id=TARGET, limit=1)
                cursor = original['next_cursor']
                self.assertEqual(original['items'][0]['id'], first)
                self.denied(issuer, 'objective.list_offers', executor_id=TARGET, limit=1, cursor=cursor)
                issuer.call('objective.withdraw', objective_id=withdrawn, request_id=identifier(300),
                            expected_revision=2)
                self.make_offer(issuer, 33)
                page = actor.call('objective.list_offers', executor_id=TARGET, limit=1, cursor=cursor)
                self.assertEqual(([row['id'] for row in page['items']], page['next_cursor']), ([last], None))
                broker.access.policy.revoke(EXECUTOR, Permission.READ_OBJECTIVE, TARGET)
                self.denied(actor, 'objective.list_offers', executor_id=TARGET, limit=1, cursor=cursor)
                configure(broker)
                valid_until_restart = actor.call('objective.list_offers', executor_id=TARGET,
                                                 limit=1)['next_cursor']
                self.mono += 60
                self.rpc_error(actor, 'objective.list_offers', -32051, 'invalid_cursor',
                               executor_id=TARGET, limit=1, cursor=cursor)
        self.mono = 10
        with self.server(create=False) as (endpoint, _), self.client(endpoint, EXECUTOR) as actor:
            self.rpc_error(actor, 'objective.list_offers', -32051, 'invalid_cursor',
                           executor_id=TARGET, limit=1, cursor=valid_until_restart)

    def test_concurrent_accept_and_withdraw_commit_exactly_once(self):
        with self.server() as (endpoint, _):
            self.bind_executor(endpoint)
            with self.client(endpoint, ISSUER) as issuer:
                offer = self.make_offer(issuer)
            barrier = Barrier(2, timeout=4)
            outcomes = {}

            def compete(principal, method, params):
                try:
                    with self.client(endpoint, principal) as rpc:
                        barrier.wait()
                        outcomes[principal] = rpc.call(method, **params)['state']
                except Fault as error:
                    outcomes[principal] = error.message

            workers = (
                Thread(target=compete, args=(EXECUTOR, 'objective.respond', self.answer(offer))),
                Thread(target=compete, args=(ISSUER, 'objective.withdraw',
                                            dict(objective_id=offer, request_id=identifier(301),
                                                 expected_revision=2))),
            )
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(5)
                self.assertFalse(worker.is_alive())
            self.assertIn(set(outcomes.values()),
                          ({'accepted', 'stale_revision'}, {'withdrawn', 'stale_revision'}))
            with closing(sqlite3.connect(self.database)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM audit WHERE record_id=? AND revision=3',
                                            (offer,)).fetchone(), (1,))

    def test_revocation_waits_through_commit_and_denies_new_response_or_replay(self):
        with self.server() as (endpoint, broker):
            self.bind_executor(endpoint)
            with self.client(endpoint, ISSUER) as issuer:
                offer, second = [self.make_offer(issuer, index) for index in (30, 31)]
            with self.client(endpoint, EXECUTOR) as actor:
                commit = broker.registry._commit
                staged, proceed, revoking, revoked = Event(), Event(), Event(), Event()
                received = []

                def pause(db):
                    staged.set()
                    if not proceed.wait(4):
                        raise OSError('timeout in test hook')
                    commit(db)

                def revoke():
                    revoking.set()
                    broker.access.policy.revoke(EXECUTOR, Permission.RESPOND_TO_OBJECTIVE, TARGET)
                    revoked.set()

                def respond():
                    received.append(actor.call('objective.respond', **self.answer(offer)))

                responder = Thread(target=respond)
                revoker = Thread(target=revoke)
                with patch.object(broker.registry, '_commit', side_effect=pause):
                    responder.start()
                    try:
                        self.assertTrue(staged.wait(4))
                        revoker.start()
                        self.assertTrue(revoking.wait(4))
                        self.assertFalse(revoked.wait(.05))
                    finally:
                        proceed.set()
                        responder.join(5)
                        if revoker.ident is not None:
                            revoker.join(5)
                self.assertTrue(revoked.is_set())
                self.assertEqual(received[0]['state'], 'accepted')
                self.denied(actor, 'objective.respond', **self.answer(offer))
                self.denied(actor, 'objective.respond', **self.answer(second, request=301))
                self.assertEqual(actor.call('objective.status', objective_id=second)['state'], 'offered')

    def test_disconnect_before_reply_and_unknown_commit_reconcile_after_reopen(self):
        with self.server() as (endpoint, broker):
            self.bind_executor(endpoint)
            with self.client(endpoint, ISSUER) as issuer:
                disconnected, uncertain = [self.make_offer(issuer, index) for index in (30, 31)]
            committed = broker.registry._commit
            at_commit, proceed, finished = Event(), Event(), Event()

            def pause(db):
                at_commit.set()
                if not proceed.wait(4):
                    raise OSError('timeout in test hook')
                committed(db)
                finished.set()

            with patch.object(broker.registry, '_commit', side_effect=pause):
                with self.client(endpoint, EXECUTOR) as actor:
                    actor.channel.send(dict(jsonrpc='2.0', version=VERSION, id=actor.seq + 1,
                                            method='objective.respond', params=self.answer(disconnected)))
                    try:
                        self.assertTrue(at_commit.wait(4))
                        actor.channel.sock.shutdown(socket.SHUT_RDWR)
                    finally:
                        proceed.set()
                self.assertTrue(finished.wait(4))

            def commit_then_error(db):
                committed(db)
                raise sqlite3.OperationalError('internal storage details')

            with self.client(endpoint, EXECUTOR) as actor:
                with patch.object(broker.registry, '_commit', side_effect=commit_then_error):
                    self.rpc_error(actor, 'objective.respond', -32048, 'commit_unknown',
                                   **self.answer(uncertain, request=301))
        with self.server(create=False) as (endpoint, _), self.client(endpoint, EXECUTOR) as actor:
            for key, request in ((disconnected, 300), (uncertain, 301)):
                self.assertEqual(actor.call('objective.respond', **self.answer(key, request=request)),
                                 dict(id=key, revision=3, state='accepted'))

    def test_wall_rollback_storage_failure_expiry_and_precommit_grant_expiry(self):
        with self.server() as (endpoint, broker):
            self.bind_executor(endpoint)
            with self.client(endpoint, ISSUER) as issuer:
                short = self.make_offer(issuer, ttl=1)
                live = self.make_offer(issuer, 31)
            with self.client(endpoint, EXECUTOR) as actor:
                self.wall -= 1
                self.rpc_error(actor, 'objective.respond', -32049, 'clock_uncertain', **self.answer(live))
                self.wall += 2
                self.rpc_error(actor, 'objective.respond', -32041, 'objective_expired', **self.answer(short))
                with patch.object(broker.registry, '_save', side_effect=OSError('internal path')):
                    self.rpc_error(actor, 'objective.respond', -32046, 'storage_unavailable',
                                   **self.answer(live))
                broker.access.policy.grant(EXECUTOR, Permission.RESPOND_TO_OBJECTIVE, TARGET, expires_at=11)
                save = broker.registry._save

                def save_then_advance(*args):
                    save(*args)
                    self.mono = 11

                with patch.object(broker.registry, '_save', side_effect=save_then_advance):
                    self.denied(actor, 'objective.respond', **self.answer(live))
                self.assertEqual(actor.call('objective.status', objective_id=live)['state'], 'offered')
                configure(broker)
                self.assertEqual(actor.call('objective.respond', **self.answer(live))['state'], 'accepted')
