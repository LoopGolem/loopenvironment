# SPDX-License-Identifier: Apache-2.0
"""Restricted Registry qualification without privileged provisioning."""
from contextlib import closing, contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
from secrets import token_urlsafe
import shutil
import socket
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic
import unittest
from unittest.mock import patch

from experiments.objective_registry import Error, RegistryError
from experiments.registry_operational import (POLICY_FILE, PolicyPin, _prepared_registry,
                                               serve_operational_registry)
from experiments.registry_rpc import VERSION
from experiments.registry_storage import DATABASE, initialize_registry_database
from loopbridge.broker import Server
from loopbridge.protocol import Fault, RPC
from loopbridge.service_ingress import (ACCESS_ACL, CrossUIDIngress, PeerAdmission, bound_listener,
                                       named_user_acl, peer_uid, read_acl)


def opaque(number):
    return f'{number:032x}'


ADMIN, ISSUER, EXECUTOR, OTHER = map(opaque, range(1, 5))
TARGET, OBJECTIVE = map(opaque, (10, 11))
TEXT = 'Texto inerte: $(touch registry-operational-must-not-run)'
WALL = 1_780_000_000


def verifier(token):
    return sha256(token.encode()).hexdigest()


def grant(subject, scope, *, expires=WALL + 3600):
    return dict(principal=subject, scope='registry.' + scope, executor=TARGET, expires_unix=expires)


class OperationalRegistryTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory(prefix='loop-reg-op-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.private = self.root / 'p'
        self.private.mkdir(mode=0o700)
        self.wall = WALL
        self.database = self.private / DATABASE
        self.database_pin = initialize_registry_database(self.private, wall_clock=lambda: self.wall)
        self.tokens = {p: token_urlsafe(32) for p in (ADMIN, ISSUER, EXECUTOR, OTHER)}
        self.manifest = dict(version=1, generation=1,
                             principals={p: verifier(secret) for p, secret in self.tokens.items()},
                             retired_verifiers=[], grants=[
                                 grant(ADMIN, 'executor.register'),
                                 grant(EXECUTOR, 'executor.confirm'),
                                 grant(EXECUTOR, 'executor.read'),
                                 grant(EXECUTOR, 'objective.read'),
                                 grant(EXECUTOR, 'objective.respond'),
                                 grant(ISSUER, 'objective.author'),
                             ])
        self.pin = self.write(self.manifest)

    def write(self, value, *, raw=None):
        raw = json.dumps(value).encode() if raw is None else raw
        candidate = self.private / 'policy.next'
        fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(raw)
        candidate.replace(self.private / POLICY_FILE)
        return PolicyPin(value['generation'], sha256(raw).hexdigest())

    @contextmanager
    def service(self, pin=None):
        admission = PeerAdmission.local_only(os.getuid())
        with _prepared_registry(self.private, admission, self.database_pin,
                                self.pin if pin is None else pin,
                                wall_clock=lambda: self.wall, clock=monotonic) as (broker, control):
            endpoint = self.root / 'registry.sock'
            with bound_listener(endpoint) as listener, Server(broker, listener, allow_owner=False):
                yield endpoint, broker, control

    @contextmanager
    def client(self, endpoint, principal=None, *, token=None, version=VERSION):
        with socket.socket(socket.AF_UNIX) as sock:
            sock.connect(str(endpoint))
            rpc = RPC(sock, version, timeout=4)
            if principal is not None:
                self.assertEqual(rpc.call('auth', credential=self.tokens[principal] if token is None else token)
                                 ['principal'], principal)
            yield rpc

    def error(self, rpc, error, method, **params):
        with self.assertRaises(Fault) as caught:
            rpc.call(method, **params)
        self.assertEqual((caught.exception.message, caught.exception.data), (error, None))

    def offer(self, endpoint):
        with self.client(endpoint, ADMIN) as rpc:
            self.assertEqual(rpc.call('executor.register', request_id=opaque(20), executor_id=TARGET,
                                      bound_principal_id=EXECUTOR, label='Executor')['state'], 'pending')
        with self.client(endpoint, EXECUTOR) as rpc:
            self.assertEqual(rpc.call('executor.confirm', request_id=opaque(21), executor_id=TARGET,
                                      expected_revision=1)['state'], 'available')
        with self.client(endpoint, ISSUER) as rpc:
            rpc.call('objective.create', request_id=opaque(22), objective_id=OBJECTIVE,
                     executor_id=TARGET, text=TEXT, ttl_seconds=600)
            self.assertEqual(rpc.call('objective.offer', request_id=opaque(23), objective_id=OBJECTIVE,
                                      expected_revision=1)['state'], 'offered')
        return dict(request_id=opaque(24), objective_id=OBJECTIVE, expected_revision=2, decision='accept')

    def test_workflow_restart_retains_receipt_and_preserves_session_separation(self):
        with self.service() as (endpoint, broker, _):
            answer = self.offer(endpoint)
            with self.client(endpoint, OTHER) as rpc:
                self.error(rpc, 'denied', 'objective.respond', **answer)
            with self.client(endpoint, EXECUTOR) as rpc:
                offer = rpc.call('objective.list_offers', executor_id=TARGET, limit=2)['items']
                self.assertEqual([x['id'] for x in offer], [OBJECTIVE])
                reply = rpc.call('objective.respond', **answer)
                self.assertEqual(reply, dict(id=OBJECTIVE, state='accepted', revision=3))
                self.assertEqual(rpc.call('objective.status', objective_id=OBJECTIVE)['text'], TEXT)
                for method in ('acquire', 'session.keyboard.type', 'workspace.read',
                               'presentation.open', 'session.capture', 'window.list', 'objective.execute'):
                    self.error(rpc, 'method_not_found', method)
            self.assertEqual(broker.sessions, {})
            with self.client(endpoint, version='0.6') as rpc:
                with self.assertRaises(EOFError):
                    rpc.call('auth', credential=self.tokens[EXECUTOR])
        with self.service() as (endpoint, _, _), self.client(endpoint, EXECUTOR) as rpc:
            self.assertEqual(rpc.call('objective.respond', **answer), reply)
        self.assertFalse((Path.cwd() / 'registry-operational-must-not-run').exists())
        data = self.database.read_bytes()
        policy = (self.private / POLICY_FILE).read_bytes()
        for token in self.tokens.values():
            self.assertFalse(token.encode() in data or token.encode() in policy)
            self.assertFalse(bytes.fromhex(verifier(token)) in data or verifier(token).encode() in data)

    def test_rotation_disable_and_retirement_survive_reload_and_restart(self):
        new_token = token_urlsafe(32)
        changed = self.manifest['principals'] | {EXECUTOR: verifier(new_token)}
        old_digest = verifier(self.tokens[EXECUTOR])
        with self.service() as (endpoint, _, ctl):
            answer = self.offer(endpoint)
            with self.client(endpoint, EXECUTOR) as old:
                self.error(old, 'denied', 'auth', credential=token_urlsafe(32))
                self.assertEqual(old.call('auth', credential=self.tokens[EXECUTOR])['principal'], EXECUTOR)
                bad_rotation = self.write(self.manifest | dict(generation=2, principals=changed))
                with self.assertRaisesRegex(ValueError, '^registry_principal_history$'):
                    ctl.reload(bad_rotation)
                rotated = self.manifest | dict(generation=2, principals=changed, retired_verifiers=[old_digest])
                ctl.reload(self.write(rotated))
                self.error(old, 'denied', 'objective.respond', **answer)
                self.error(old, 'denied', 'auth', credential=self.tokens[EXECUTOR])
                self.assertEqual(old.call('auth', credential=new_token)['principal'], EXECUTOR)
                with self.client(endpoint, ISSUER) as issuer:
                    self.error(issuer, 'invalid_params', 'objective.create', request_id=opaque(99),
                               objective_id=opaque(90), executor_id=TARGET, ttl_seconds=30,
                               text=self.tokens[EXECUTOR])
                disabled = rotated | dict(generation=3, principals=changed | {EXECUTOR: None},
                                          retired_verifiers=[old_digest, verifier(new_token)],
                                          grants=[g for g in rotated['grants'] if g['principal'] != EXECUTOR])
                disabled_pin = self.write(disabled)
                ctl.reload(disabled_pin)
                self.error(old, 'denied', 'objective.respond', **answer)
                self.error(old, 'denied', 'auth', credential=new_token)
                revived = rotated | dict(generation=4, principals=changed | {EXECUTOR: verifier(token_urlsafe(32))},
                                         retired_verifiers=disabled['retired_verifiers'])
                with self.assertRaisesRegex(ValueError, '^registry_principal_history$'):
                    ctl.reload(self.write(revived))
                self.write(disabled)
        with self.service(disabled_pin) as (endpoint, _, _), self.client(endpoint) as rpc:
            self.error(rpc, 'denied', 'auth', credential=new_token)
        with self.assertRaisesRegex(ValueError, '^registry_policy_pin_mismatch$'):
            with self.service():
                self.fail('old policy pin unexpectedly accepted')

    def test_issuer_grant_removal_keeps_existing_offer(self):
        with self.service() as (endpoint, _, ctl):
            answer = self.offer(endpoint)
            policy = self.manifest | dict(generation=2, grants=[
                g for g in self.manifest['grants'] if g['principal'] != ISSUER])
            with self.client(endpoint, ISSUER) as issuer, self.client(endpoint, EXECUTOR) as executor:
                ctl.reload(self.write(policy))
                self.error(issuer, 'denied', 'objective.offer', request_id=opaque(23),
                           objective_id=OBJECTIVE, expected_revision=1)
                self.error(issuer, 'denied', 'objective.withdraw', request_id=opaque(25),
                           objective_id=OBJECTIVE, expected_revision=2)
                self.assertEqual(executor.call('objective.respond', **answer)['state'], 'accepted')

    def test_policy_reload_serializes_with_accept_and_blocks_replay(self):
        with self.service() as (endpoint, broker, ctl):
            answer = self.offer(endpoint)
            updated = self.manifest | dict(generation=2, grants=[
                g for g in self.manifest['grants'] if g['scope'] != 'registry.objective.respond'])
            new_pin = self.write(updated)
            staged, proceed, publishing, done = Event(), Event(), Event(), Event()
            commit, replace = broker.registry._commit, broker.access.replace
            results = {}

            def pause(db):
                staged.set()
                if not proceed.wait(4):
                    raise OSError
                commit(db)

            def publish(*args, **kwargs):
                publishing.set()
                return replace(*args, **kwargs)

            def revoke():
                ctl.reload(new_pin)
                done.set()

            with self.client(endpoint, EXECUTOR) as rpc:
                def accept():
                    results['reply'] = rpc.call('objective.respond', **answer)

                caller, revoker = Thread(target=accept), Thread(target=revoke)
                with patch.object(broker.registry, '_commit', side_effect=pause), \
                        patch.object(broker.access, 'replace', side_effect=publish):
                    caller.start()
                    try:
                        self.assertTrue(staged.wait(4))
                        revoker.start()
                        self.assertTrue(publishing.wait(4))
                        self.assertFalse(done.wait(.05))
                    finally:
                        proceed.set()
                        caller.join(5)
                        if revoker.ident is not None:
                            revoker.join(5)
                self.assertTrue(done.is_set())
                self.assertEqual(results['reply']['state'], 'accepted')
                self.error(rpc, 'denied', 'objective.respond', **answer)
        with self.service(new_pin) as (endpoint, _, _), self.client(endpoint, EXECUTOR) as rpc:
            self.error(rpc, 'denied', 'objective.respond', **answer)

    def test_expired_grant_at_commit_rolls_back_then_uncertain_commit_reconciles(self):
        self.manifest['grants'][-2]['expires_unix'] = WALL + 1
        pin = self.write(self.manifest)
        with self.service(pin) as (endpoint, broker, ctl):
            answer = self.offer(endpoint)
            save = broker.registry._save

            def advance(*args):
                save(*args)
                self.wall += 1

            with self.client(endpoint, EXECUTOR) as rpc:
                with patch.object(broker.registry, '_save', side_effect=advance):
                    self.error(rpc, 'denied', 'objective.respond', **answer)
                self.assertEqual(rpc.call('objective.status', objective_id=OBJECTIVE)['state'], 'offered')
                grants = [g | {'expires_unix': WALL + 100} for g in self.manifest['grants']]
                refreshed = self.write(self.manifest | dict(generation=2, grants=grants))
                ctl.reload(refreshed)
                commit = broker.registry._commit

                def fault(db):
                    commit(db)
                    raise sqlite3.OperationalError('sensitive internal error')

                with patch.object(broker.registry, '_commit', side_effect=fault):
                    self.error(rpc, 'commit_unknown', 'objective.respond', **answer)
        with self.service(refreshed) as (endpoint, _, _), self.client(endpoint, EXECUTOR) as rpc:
            self.assertEqual(rpc.call('objective.respond', **answer)['revision'], 3)

    def test_missing_symlink_unpinned_and_malformed_provisioning_fail_closed(self):
        admission = PeerAdmission.local_only(os.getuid())
        for database_pin, policy_pin in ((None, self.pin), (self.database_pin, None)):
            with self.assertRaisesRegex(ValueError, 'registry_(database|policy)_pin_required'):
                with _prepared_registry(self.private, admission, database_pin, policy_pin,
                                        wall_clock=lambda: self.wall, clock=monotonic):
                    self.fail('startup without trusted pin')
        manifest = self.private / POLICY_FILE
        old = manifest.read_bytes()
        manifest.unlink()
        with self.assertRaises(RegistryError):
            with self.service():
                self.fail('missing policy accepted')
        target = self.private / 'other'
        target.write_bytes(old)
        target.chmod(0o600)
        manifest.symlink_to(target)
        with self.assertRaises(RegistryError):
            with self.service():
                self.fail('symlinked policy accepted')
        manifest.unlink()
        malformed = [
            b'{"version":1,"version":1}',
            json.dumps(self.manifest | {'grants': self.manifest['grants'] * 2}).encode(),
            json.dumps(self.manifest | {'principals': {ADMIN: self.tokens[ADMIN]}}).encode(),
            json.dumps(self.manifest | {'grants': [grant(ADMIN, 'session.control')]}).encode(),
        ]
        for raw in malformed:
            with self.subTest(size=len(raw)), self.assertRaisesRegex(ValueError, '^invalid_registry_policy$'):
                with self.service(self.write(self.manifest, raw=raw)):
                    self.fail('malformed trusted policy accepted')

    def test_startup_and_live_storage_fail_closed_after_replacement(self):
        with self.service() as (endpoint, _, _):
            self.offer(endpoint)
            saved = self.private / 'original'
            self.database.rename(saved)
            shutil.copy2(saved, self.database)
            with self.client(endpoint, EXECUTOR) as rpc:
                self.error(rpc, 'storage_unavailable', 'executor.status', executor_id=TARGET)
        with self.assertRaisesRegex(RegistryError, '^storage_unavailable$'):
            with self.service():
                self.fail('replacement database accepted')
        self.database.unlink()
        self.database.symlink_to(saved)
        with self.assertRaisesRegex(RegistryError, '^storage_unavailable$'):
            with self.service():
                self.fail('symlinked database accepted')

    def test_unsafe_parent_directory_and_journal_are_rejected(self):
        self.root.chmod(0o770)
        with self.assertRaises(RegistryError):
            with self.service():
                self.fail('writable ancestor accepted')
        self.root.chmod(0o700)
        journal = self.private / (DATABASE + '-journal')
        journal.symlink_to(self.database)
        with self.assertRaises(RegistryError):
            with self.service():
                self.fail('symlinked journal accepted')
        journal.unlink()
        with self.service() as (endpoint, _, _):
            self.offer(endpoint)
            detached = self.root / 'detached'
            self.private.rename(detached)
            self.private.mkdir(mode=0o700)
            with self.client(endpoint, EXECUTOR) as rpc:
                self.error(rpc, 'storage_unavailable', 'executor.status', executor_id=TARGET)

    def test_control_and_database_descriptors_are_bound_to_service_lifetime(self):
        with self.service() as (_, _, control):
            self.assertFalse(os.get_inheritable(control._directory.fd))
            with self.assertRaises(RegistryError):
                with self.service():
                    self.fail('second service acquired the same database')
        with self.assertRaisesRegex(ValueError, '^registry_control_closed$'):
            control.reload(self.pin)

    def test_schema_incompatibility_and_corruption_are_not_repaired(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('PRAGMA user_version=128')
        with self.assertRaisesRegex(RegistryError, '^invalid_storage$'):
            with self.service():
                self.fail('unknown schema accepted')
        self.database.write_bytes(b'broken sqlite content')
        with self.assertRaises(RegistryError) as failure:
            with self.service():
                self.fail('corruption accepted')
        self.assertIn(failure.exception.code, (Error.INVALID_STORAGE, Error.STORAGE_UNAVAILABLE))
        self.assertEqual(self.database.read_bytes(), b'broken sqlite content')

    def test_restore_old_backup_and_policy_does_not_restore_authority(self):
        baseline = self.private / 'quarantine.sqlite'
        old_policy = (self.private / POLICY_FILE).read_bytes()
        with closing(sqlite3.connect(self.database)) as source, closing(sqlite3.connect(baseline)) as backup:
            source.backup(backup)
        baseline.chmod(0o600)
        with closing(sqlite3.connect(baseline.as_uri() + '?mode=ro', uri=True)) as copy:
            self.assertEqual(copy.execute('PRAGMA integrity_check').fetchone(), ('ok',))
            self.assertEqual(copy.execute('SELECT count(*) FROM objectives').fetchone(), (0,))
        with self.service() as (endpoint, _, control):
            answer = self.offer(endpoint)
            with self.client(endpoint, EXECUTOR) as rpc:
                rpc.call('objective.respond', **answer)
            revoked = self.manifest | dict(generation=2, grants=[
                g for g in self.manifest['grants'] if g['principal'] != EXECUTOR])
            new_pin = self.write(revoked)
            control.reload(new_pin)
        self.write(self.manifest, raw=old_policy)
        with self.assertRaisesRegex(ValueError, '^registry_policy_pin_mismatch$'):
            with self.service(new_pin):
                self.fail('restored stale policy accepted')
        self.write(revoked)
        self.database.rename(self.private / 'live-evidence.sqlite')
        baseline.replace(self.database)
        with self.assertRaisesRegex(RegistryError, '^storage_unavailable$'):
            with self.service(new_pin):
                self.fail('restored stale database accepted')

    @unittest.skipIf(os.geteuid() == 0, 'cross-UID candidate excludes a root service')
    def test_ingress_acl_real_kernel_unlisted_uid_and_no_ancillary_data(self):
        public = self.root / 'public'
        public.mkdir(mode=0o700)
        uid = os.geteuid()
        listed = 65534 if uid != 65534 else 65533
        os.setxattr(public, ACCESS_ACL, named_user_acl(listed, 7, 1))
        admission = PeerAdmission(uid, frozenset({listed}))
        ingress = CrossUIDIngress(public, self.private, admission)
        observed = []

        def allowed_by_kernel(sock):
            actual = peer_uid(sock)
            observed.append(actual)
            return actual

        with patch('loopbridge.broker.peer_uid', side_effect=allowed_by_kernel), \
                serve_operational_registry(ingress, database_pin=self.database_pin, policy_pin=self.pin,
                                           wall_clock=lambda: self.wall) as (endpoint, _):
            info = endpoint.stat()
            self.assertEqual((info.st_uid, info.st_mode & 0o777), (uid, 0o620))
            self.assertEqual(read_acl(endpoint), named_user_acl(listed, 6, 2))
            with socket.socket(socket.AF_UNIX) as peer:
                peer.settimeout(4)
                peer.connect(str(endpoint))
                self.assertEqual(peer_uid(peer), uid)
                request = dict(jsonrpc='2.0', version=VERSION, id=1, method='auth',
                               params={'credential': self.tokens[EXECUTOR]})
                peer.sendall(json.dumps(request).encode() + b'\n')
                data = bytearray()
                while not data.endswith(b'\n'):
                    chunk, ancillary, flags, _ = peer.recvmsg(4096, 128)
                    self.assertTrue(chunk)
                    self.assertEqual(ancillary, [])
                    self.assertFalse(flags & socket.MSG_CTRUNC)
                    data.extend(chunk)
                self.assertEqual(json.loads(data)['error']['message'], 'denied')
        self.assertEqual(observed, [uid])
        self.assertFalse(endpoint.exists())
