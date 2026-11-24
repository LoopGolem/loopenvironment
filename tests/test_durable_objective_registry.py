# SPDX-License-Identifier: Apache-2.0
"""Crash recovery and authorization ordering against real SQLite transactions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from hashlib import sha256
from hmac import compare_digest
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Barrier, Event
import unittest
from unittest.mock import patch

from experiments.durable_objective_registry import (APPLICATION_ID, RECEIPT_RETENTION_SECONDS,
                                                    SCHEMA_VERSION, SQLiteRegistry)
from experiments.objective_registry import (Error, ExecutorAction, ExecutorState, ObjectiveAction,
                                            ObjectiveState, Permission, RegistryError)
from experiments.objective_registry_policy import RegistryPolicy
from loopbridge.authority import Session
from loopbridge.protocol import Fault

ADMIN = 'issuer-lab-secret-d1b'
BOB = 'worker-01-lab-secret-d1b'
EVE = 'worker-02-lab-secret-d1b'
ROTATED = 'worker-01-replacement-d1b'
SUBJECTS = {ADMIN: 'issuer-a', BOB: 'worker-01', EVE: 'worker-02'}
TARGET = 'reviewer-one'
OBJECTIVE = 'review-task'
BASE_WALL = 1_800_000_000
AUTHOR = (Permission.REGISTER, Permission.MANAGE_EXECUTOR, Permission.AUTHOR_OBJECTIVE,
          Permission.READ_EXECUTOR, Permission.READ_OBJECTIVE)
RECIPIENT = (Permission.CONFIRM, Permission.RESPOND_TO_OBJECTIVE,
             Permission.READ_OBJECTIVE, Permission.READ_EXECUTOR)
CONTENT = 'Private objective text with quotes " and UTF-8 café'


def verifier(subjects):
    digests = [(sha256(credential.encode()).digest(), principal) for credential, principal in subjects.items()]

    def verify(credential):
        digest = sha256(credential.encode()).digest()
        return next((principal for stored, principal in digests if compare_digest(digest, stored)), None)

    return verify


def policy(clock, *, include_grants=True):
    result = RegistryPolicy(verifier(SUBJECTS), clock=clock)
    if include_grants:
        for subject, permissions in (('issuer-a', AUTHOR), ('worker-01', RECIPIENT), ('worker-02', RECIPIENT)):
            for permission in permissions:
                result.grant(subject, permission, TARGET, expires_at=200)
    return result


class DurableTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'objectives.sqlite'
        self.wall = BASE_WALL
        self.ticks = 10
        self.policy = policy(lambda: self.ticks)
        self.registry = self.open(create=True)

    def open(self, cls=SQLiteRegistry, authority=None, *, create=False):
        return cls(self.path, self.policy if authority is None else authority,
                   wall_clock=lambda: self.wall, create=create)

    def rows(self, sql, args=()):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(sql, args).fetchall()

    def write_sql(self, sql, args=()):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute(sql, args)
            db.commit()

    def assert_error(self, expected, function, *args):
        with self.assertRaises(RegistryError) as raised:
            function(*args)
        self.assertIs(raised.exception.code, expected)
        self.assertEqual(str(raised.exception), expected.value)

    def register(self):
        self.registry.register(ADMIN, 'register', TARGET, 'worker-01', 'Reviewer one')

    def available(self):
        self.register()
        self.registry.transition_executor(BOB, 'confirm', TARGET, 1, ExecutorAction.CONFIRM)

    def offered(self, text=CONTENT, ttl=60):
        self.available()
        self.registry.create_objective(ADMIN, 'create', OBJECTIVE, TARGET, text, ttl)
        return self.registry.transition_objective(ADMIN, 'offer', OBJECTIVE, 1, ObjectiveAction.OFFER)

    def decision(self, registry=None, key='accept'):
        return (registry or self.registry).transition_objective(BOB, key, OBJECTIVE, 2, ObjectiveAction.ACCEPT)

    def assert_committed(self, state):
        snapshot = self.open().read_objective(ADMIN, OBJECTIVE)
        self.assertIs(snapshot.state, state)
        accepted = state is ObjectiveState.ACCEPTED
        self.assertEqual((snapshot.revision, snapshot.changed_by),
                         (3, 'worker-01') if accepted else (2, 'issuer-a'))
        expected = [(3, 'accepted')] if accepted else []
        self.assertEqual(self.rows("SELECT revision, state FROM receipts WHERE request_id='accept'"), expected)
        self.assertEqual(self.rows("SELECT revision, state FROM audit WHERE record_id=? AND state='accepted'",
                                   (OBJECTIVE,)), expected)

    def test_initial_schema_installation_reopen_and_integrity(self):
        self.assertEqual(self.rows('PRAGMA user_version'), [(SCHEMA_VERSION,)])
        self.assertEqual(self.rows('PRAGMA application_id'), [(APPLICATION_ID,)])
        self.assertEqual(self.rows('PRAGMA journal_mode'), [('delete',)])
        self.assertEqual(self.rows('PRAGMA integrity_check'), [('ok',)])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.offered()
        self.assertEqual(self.open().read_executor(ADMIN, TARGET).revision, 2)
        self.assertEqual(self.rows('SELECT registered_by, changed_by FROM executors'),
                         [('issuer-a', 'worker-01')])
        self.assertEqual(self.rows('PRAGMA foreign_key_check'), [])

    def test_empty_database_requires_explicit_schema_installation(self):
        self.path = self.path.with_name('uninitialized.sqlite')
        self.path.touch(mode=0o600)
        self.assert_error(Error.INVALID_STORAGE, self.open)
        self.assertEqual(self.rows('PRAGMA user_version'), [(0,)])
        self.open(create=True)
        self.assertEqual(self.rows('PRAGMA user_version'), [(SCHEMA_VERSION,)])

    def test_missing_grants_after_restart_fail_closed_even_for_authenticated_subject(self):
        self.offered()
        receipt = self.decision()
        fresh = policy(lambda: self.ticks, include_grants=False)
        self.assert_error(Error.DENIED, self.open(authority=fresh).read_objective, BOB, OBJECTIVE)
        self.assert_error(Error.DENIED, self.decision, self.open(authority=fresh))
        self.assertEqual(self.decision(self.open()), receipt)
        self.assert_committed(ObjectiveState.ACCEPTED)

    def test_individual_principals_do_not_share_identity_or_executor_scope(self):
        self.register()
        self.assert_error(Error.DENIED, self.registry.read_executor, 'worker-01', TARGET)
        self.assert_error(Error.DENIED, self.registry.transition_executor,
                          EVE, 'confirm', TARGET, 1, ExecutorAction.CONFIRM)
        self.assert_error(Error.DENIED, self.registry.create_objective,
                          EVE, 'claim', OBJECTIVE, TARGET, 'I am the owner.', 60)
        self.registry.transition_executor(BOB, 'confirm', TARGET, 1, ExecutorAction.CONFIRM)
        self.registry.create_objective(ADMIN, 'create', OBJECTIVE, TARGET, CONTENT, 60)
        self.registry.transition_objective(ADMIN, 'offer', OBJECTIVE, 1, ObjectiveAction.OFFER)
        self.assert_error(Error.DENIED, self.registry.list_offers, EVE, TARGET)
        with self.assertRaises(RegistryError) as raised:
            self.registry.list_offers(BOB, 'other-executor')
        self.assertIs(raised.exception.code, Error.DENIED)
        (offer,) = self.registry.list_offers(BOB, TARGET)
        self.assertEqual((offer.issuer, offer.text), ('issuer-a', CONTENT))

    def test_duplicate_conflict_and_stale_revision_after_restart(self):
        self.offered()
        original = self.decision()
        self.wall += 5
        reopened = self.open()
        self.assertEqual(self.decision(reopened), original)
        self.assert_error(Error.REQUEST_CONFLICT, reopened.transition_objective,
                          BOB, 'accept', OBJECTIVE, 2, ObjectiveAction.DECLINE)
        self.assert_error(Error.STALE_REVISION, self.decision, reopened, 'different-key')
        self.assert_committed(ObjectiveState.ACCEPTED)

    def test_credential_rotation_keeps_subject_rights_but_invalidates_old_bearer(self):
        self.offered()
        updated = {key: value for key, value in SUBJECTS.items() if key != BOB} | {ROTATED: 'worker-01'}
        self.policy.replace_verifier(verifier(updated))
        self.assert_error(Error.DENIED, self.decision)
        self.assertEqual(self.registry.list_offers(ROTATED, TARGET)[0].id, OBJECTIVE)
        accepted = self.registry.transition_objective(ROTATED, 'accept', OBJECTIVE, 2, ObjectiveAction.ACCEPT)
        self.assertEqual(self.open().transition_objective(
            ROTATED, 'accept', OBJECTIVE, 2, ObjectiveAction.ACCEPT), accepted)

    def test_issuer_grant_revocation_stops_new_mutations_preserving_delivered_offer(self):
        self.offered()
        self.policy.revoke('issuer-a', Permission.AUTHOR_OBJECTIVE, TARGET)
        self.assert_error(Error.DENIED, self.registry.transition_objective,
                          ADMIN, 'withdraw', OBJECTIVE, 2, ObjectiveAction.WITHDRAW)
        self.assert_error(Error.DENIED, self.registry.create_objective,
                          ADMIN, 'new', 'new-objective', TARGET, CONTENT, 60)
        self.assertEqual(self.decision().state, ObjectiveState.ACCEPTED)

    def test_expiry_after_reboot_ignores_monotonic_origin_and_is_saved_once(self):
        self.offered(ttl=10)
        self.ticks = 0
        self.wall += 10
        reopened = self.open(authority=policy(lambda: self.ticks))
        self.assert_error(Error.EXPIRED, self.decision, reopened)
        self.assertEqual(self.rows("SELECT state, revision, changed_by FROM objectives"),
                         [('expired', 3, None)])
        self.wall += 1
        self.assertEqual(self.open().read_objective(ADMIN, OBJECTIVE).revision, 3)
        self.assertEqual(self.rows("SELECT count(*) FROM audit WHERE state='expired'"), [(1,)])
        self.assertEqual(self.rows("SELECT count(*) FROM receipts WHERE request_id='accept'"), [(0,)])

    def test_clock_rollback_and_invalid_wall_fail_conservatively(self):
        self.offered(ttl=10)
        self.wall += 8
        self.registry.read_objective(ADMIN, OBJECTIVE)
        self.wall -= 4
        self.assert_error(Error.CLOCK_UNCERTAIN, self.registry.list_offers, BOB, TARGET)
        self.assert_error(Error.CLOCK_UNCERTAIN, self.open)
        self.wall = float('nan')
        self.assert_error(Error.CLOCK_UNCERTAIN, self.decision)
        self.wall = BASE_WALL + 10
        self.assert_error(Error.EXPIRED, self.decision, self.open())

    def test_forward_step_expires_offer_and_precommit_rollback_rejects(self):
        self.offered(ttl=5)
        base_save = self.registry._save

        def rewind(*params):
            base_save(*params)
            self.wall -= 1

        self.wall += 1
        with patch.object(self.registry, '_save', side_effect=rewind):
            self.assert_error(Error.CLOCK_UNCERTAIN, self.decision)
        self.assert_committed(ObjectiveState.OFFERED)
        self.wall += 100
        self.assert_error(Error.EXPIRED, self.decision)
        self.assertEqual(self.registry.read_objective(ADMIN, OBJECTIVE).state, ObjectiveState.EXPIRED)

    def test_receipts_hold_full_contract_window_and_prune_only_expired(self):
        self.offered()
        expected = self.decision()
        self.wall += RECEIPT_RETENTION_SECONDS - 1
        self.assertEqual(self.decision(self.open()), expected)
        self.assertEqual(self.rows("SELECT count(*) FROM receipts WHERE request_id='accept'"), [(1,)])
        self.wall += 1
        reopened = self.open()
        self.assertEqual(reopened.read_objective(ADMIN, OBJECTIVE).revision, 3)
        self.assertEqual(self.rows("SELECT count(*) FROM receipts"), [(0,)])
        self.assert_error(Error.STALE_REVISION, self.decision, reopened)

    def test_capacity_does_not_evict_live_receipts_and_reserves_terminal_receipts(self):
        with patch('experiments.durable_objective_registry.MAX_RECEIPTS', 4):
            offer = self.offered()
            self.assert_error(Error.CAPACITY, self.decision)
            self.assert_committed(ObjectiveState.OFFERED)
            self.assertEqual(self.registry.transition_objective(
                ADMIN, 'offer', OBJECTIVE, 1, ObjectiveAction.OFFER), offer)
            self.registry.transition_objective(ADMIN, 'withdraw', OBJECTIVE, 2, ObjectiveAction.WITHDRAW)
            self.registry.transition_executor(ADMIN, 'revoke', TARGET, 2, ExecutorAction.REVOKE)
            self.assertEqual(self.open().read_objective(ADMIN, OBJECTIVE).state, ObjectiveState.WITHDRAWN)
            self.assertEqual(self.rows('SELECT terminal, count(*) FROM receipts GROUP BY terminal ORDER BY terminal'),
                             [(0, 4), (1, 2)])

    def test_record_capacity_rolls_back_and_audit_is_bounded(self):
        with patch('experiments.objective_registry.MAX_OBJECTIVES', 1), \
                patch('experiments.durable_objective_registry.MAX_AUDIT', 3):
            self.offered()
            self.assert_error(Error.CAPACITY, self.registry.create_objective,
                              ADMIN, 'new', 'other', TARGET, CONTENT, 60)
            self.decision()
        self.assertEqual(self.rows('SELECT state FROM audit ORDER BY sequence'), [('created',), ('offered',), ('accepted',)])
        self.assertEqual(self.rows("SELECT count(*) FROM receipts WHERE request_id='new'"), [(0,)])

    def test_storage_failure_before_commit_rolls_back_every_record(self):
        self.offered()
        base_save = self.registry._save

        def disk_failure(*args):
            base_save(*args)
            raise sqlite3.OperationalError(CONTENT)

        with patch.object(self.registry, '_save', side_effect=disk_failure):
            self.assert_error(Error.STORAGE_UNAVAILABLE, self.decision)
        self.assert_committed(ObjectiveState.OFFERED)
        self.assertEqual(self.decision(self.open()).state, ObjectiveState.ACCEPTED)

    def test_unknown_commit_requires_retry_and_works_after_durable_commit(self):
        self.offered()
        base_commit = self.registry._commit

        def after_commit(db):
            base_commit(db)
            raise sqlite3.OperationalError(CONTENT)

        with patch.object(self.registry, '_commit', side_effect=after_commit):
            self.assert_error(Error.COMMIT_UNKNOWN, self.decision)
        self.assert_committed(ObjectiveState.ACCEPTED)
        retry = self.decision(self.open())
        self.assertEqual((retry.revision, retry.state), (3, ObjectiveState.ACCEPTED))

    def test_vanished_store_is_not_recreated_during_an_operation(self):
        self.path.unlink()
        self.assert_error(Error.STORAGE_UNAVAILABLE, self.registry.read_executor, ADMIN, TARGET)
        self.assert_error(Error.STORAGE_UNAVAILABLE, self.open)
        self.assertFalse(self.path.exists())

    def test_future_schema_corruption_and_logical_inconsistency_fail_closed(self):
        with TemporaryDirectory() as root:
            root = Path(root)
            damaged = root / 'damaged.sqlite'
            damaged.write_bytes(b'not a registry database')
            damaged.chmod(0o600)
            self.assert_error(Error.INVALID_STORAGE, SQLiteRegistry, damaged, self.policy)
        self.offered()
        self.write_sql('PRAGMA user_version=99')
        self.assert_error(Error.INVALID_STORAGE, self.open)
        self.write_sql(f'PRAGMA user_version={SCHEMA_VERSION}')
        self.write_sql("UPDATE executors SET state='revoked'")
        self.assert_error(Error.INVALID_STORAGE, self.open)
        self.assert_error(Error.INVALID_STORAGE, self.registry.read_objective, BOB, OBJECTIVE)

    def test_untrusted_path_is_rejected(self):
        other = self.path.with_name('symlink.sqlite')
        other.symlink_to(self.path)
        self.assert_error(Error.STORAGE_UNAVAILABLE, SQLiteRegistry, other, self.policy)
        self.path.chmod(0o644)
        self.assert_error(Error.STORAGE_UNAVAILABLE, self.open)
        self.assert_error(Error.STORAGE_UNAVAILABLE, self.registry.read_executor, ADMIN, TARGET)

    def test_live_reader_rejects_invalid_persisted_revision(self):
        self.offered()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('PRAGMA ignore_check_constraints=ON')
            db.execute('UPDATE objectives SET revision=0')
            db.commit()
        self.assert_error(Error.INVALID_STORAGE, self.registry.read_objective, BOB, OBJECTIVE)
        self.assert_error(Error.INVALID_STORAGE, self.open)

    def test_invalid_payload_cannot_leave_a_receipt_or_audit_record(self):
        self.available()
        for payload in ('\0', '\ud800', 'é' * 2049, [], ''):
            self.assert_error(Error.INVALID_INPUT, self.registry.create_objective,
                              ADMIN, 'invalid', OBJECTIVE, TARGET, payload, 60)
        self.assertEqual(self.rows('SELECT count(*) FROM objectives'), [(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM receipts WHERE request_id='invalid'"), [(0,)])
        self.assertEqual(self.rows('SELECT count(*) FROM audit'), [(2,)])

    def test_policy_expiry_at_precommit_rolls_back_staged_decision(self):
        self.offered()
        self.policy.grant('worker-01', Permission.RESPOND_TO_OBJECTIVE, TARGET, expires_at=11)
        save = self.registry._save

        def expire_policy(*arguments):
            save(*arguments)
            self.ticks = 11

        with patch.object(self.registry, '_save', side_effect=expire_policy):
            self.assert_error(Error.DENIED, self.decision)
        self.assert_committed(ObjectiveState.OFFERED)

    def test_policy_revocations_wait_through_commit_and_block_later_replays(self):
        for operation in ('accept', 'withdraw', 'confirm'):
            with self.subTest(operation=operation), TemporaryDirectory() as folder:
                self.path = Path(folder) / 'objectives.sqlite'
                self.policy = policy(lambda: self.ticks)
                self.registry = self.open(create=True)
                if operation == 'confirm':
                    self.register()
                    action = lambda: self.registry.transition_executor(BOB, 'confirm', TARGET, 1, ExecutorAction.CONFIRM)
                    principal, permission = 'worker-01', Permission.CONFIRM
                    query = "SELECT state FROM executors"
                    before, after = 'pending', 'available'
                else:
                    self.offered()
                    if operation == 'accept':
                        action = self.decision
                        principal, permission = 'worker-01', Permission.RESPOND_TO_OBJECTIVE
                        after = 'accepted'
                    else:
                        action = lambda: self.registry.transition_objective(
                            ADMIN, 'withdraw', OBJECTIVE, 2, ObjectiveAction.WITHDRAW)
                        principal, permission = 'issuer-a', Permission.AUTHOR_OBJECTIVE
                        after = 'withdrawn'
                    query = "SELECT state FROM objectives"
                    before = 'offered'
                entered, release, revoking = Event(), Event(), Event()
                save = self.registry._save

                def hold(*args):
                    save(*args)
                    entered.set()
                    if not release.wait(4):
                        raise RuntimeError('test synchronization timed out')

                def revoke():
                    revoking.set()
                    self.policy.revoke(principal, permission, TARGET)

                with patch.object(self.registry, '_save', side_effect=hold), ThreadPoolExecutor(2) as pool:
                    request = pool.submit(action)
                    try:
                        self.assertTrue(entered.wait(3))
                        self.assertEqual(self.rows(query), [(before,)])
                        revocation = pool.submit(revoke)
                        self.assertTrue(revoking.wait(3))
                        self.assertFalse(revocation.done())
                    finally:
                        release.set()
                    self.assertEqual(request.result(timeout=3).state.value, after)
                    revocation.result(timeout=3)
                self.assertEqual(self.rows(query), [(after,)])
                self.assert_error(Error.DENIED, action)

    def test_revocation_winning_before_request_denies_confirmation_and_decision(self):
        self.register()
        self.policy.revoke('worker-01', Permission.CONFIRM, TARGET)
        self.assert_error(Error.DENIED, self.registry.transition_executor,
                          BOB, 'confirm', TARGET, 1, ExecutorAction.CONFIRM)
        self.policy.grant('worker-01', Permission.CONFIRM, TARGET, expires_at=200)
        self.registry.transition_executor(BOB, 'confirm', TARGET, 1, ExecutorAction.CONFIRM)
        self.registry.create_objective(ADMIN, 'create', OBJECTIVE, TARGET, CONTENT, 60)
        self.registry.transition_objective(ADMIN, 'offer', OBJECTIVE, 1, ObjectiveAction.OFFER)
        self.policy.revoke('worker-01', Permission.RESPOND_TO_OBJECTIVE, TARGET)
        self.assert_error(Error.DENIED, self.decision)
        self.assert_committed(ObjectiveState.OFFERED)

    def test_sqlite_serializes_competing_independent_connections(self):
        self.offered()
        other = self.open(authority=policy(lambda: self.ticks))
        start = Barrier(3)

        def attempt(call):
            start.wait(timeout=3)
            try:
                return call().state
            except RegistryError as error:
                return error.code

        def withdraw():
            return other.transition_objective(ADMIN, 'withdraw', OBJECTIVE, 2, ObjectiveAction.WITHDRAW)

        with ThreadPoolExecutor(2) as pool:
            first, second = pool.submit(attempt, self.decision), pool.submit(attempt, withdraw)
            start.wait(timeout=3)
            outcomes = first.result(timeout=3), second.result(timeout=3)
        self.assertIn(outcomes, ((ObjectiveState.ACCEPTED, Error.STALE_REVISION),
                                 (Error.STALE_REVISION, ObjectiveState.WITHDRAWN)))
        record = self.open().read_objective(ADMIN, OBJECTIVE)
        self.assertEqual(record.revision, 3)
        self.assertEqual(self.rows('SELECT count(*) FROM audit WHERE record_id=? AND revision=3', (OBJECTIVE,)), [(1,)])

    def test_content_remains_inert_and_audit_and_receipts_exclude_text_and_secrets(self):
        private = Session('desktop', catalog=('calculator',), workspace=True,
                          extra_capabilities=('desktop.stream',))
        before = private.policy_revision, private.history.seq
        text = CONTENT + "\n$(touch marker)\n__import__('os').system('false')"
        with patch('os.system') as shell, patch('subprocess.Popen') as spawn, patch('builtins.eval') as evaluate:
            self.offered(text)
            self.decision()
            for operation in (shell, spawn, evaluate):
                operation.assert_not_called()
        self.assertEqual(self.open().read_objective(BOB, OBJECTIVE).text, text)
        audit_and_receipts = repr((self.rows('SELECT * FROM audit'), self.rows('SELECT * FROM receipts')))
        self.assertNotIn(CONTENT, audit_and_receipts)
        for secret in SUBJECTS:
            self.assertNotIn(secret.encode(), self.path.read_bytes())
        for scope in ('workspace.read', 'desktop.stream', 'desktop.capture', 'desktop.input', 'desktop.control'):
            self.assertFalse(private.permits('worker-01', scope))
        with self.assertRaisesRegex(Fault, '^grant_denied$'):
            private.acquire('worker-01', 'no-control', ttl=10)
        self.assertEqual((private.policy_revision, private.history.seq), before)
        self.assertIsNone(private.lease)

    def test_abrupt_exit_before_commit(self):
        self.crash('before', 81, ObjectiveState.OFFERED)

    def test_abrupt_exit_during_sqlite_commit_vm(self):
        self.crash('during', 82, None)

    def test_abrupt_exit_after_commit_before_receipt_delivery(self):
        self.crash('after', 83, ObjectiveState.ACCEPTED)

    def crash(self, stage, status, expected_state):
        self.offered()
        run = subprocess.run([sys.executable, '-B', '-c',
                              'import sys; sys.path.insert(0, "tests"); '
                              'from test_durable_objective_registry import crash_worker; '
                              'crash_worker(*sys.argv[1:])', str(self.path), stage],
                             cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=8)
        self.assertEqual(run.returncode, status, run.stderr.decode())
        reopened = self.open()
        outcome = reopened.read_objective(ADMIN, OBJECTIVE).state
        if expected_state is not None:
            self.assertEqual(outcome, expected_state)
        self.assertIn(outcome, (ObjectiveState.OFFERED, ObjectiveState.ACCEPTED))
        self.assert_committed(outcome)
        self.assertEqual(self.decision(reopened).revision, 3)
        self.assert_committed(ObjectiveState.ACCEPTED)


def crash_worker(path, stage):
    class InterruptedRegistry(SQLiteRegistry):
        def _commit(self, db):
            if stage == 'before':
                os._exit(81)
            if stage == 'during':
                db.set_progress_handler(lambda: os._exit(82), 1)
            super()._commit(db)
            if stage == 'after':
                os._exit(83)

    registry = InterruptedRegistry(path, policy(lambda: 10), wall_clock=lambda: BASE_WALL)
    registry.transition_objective(BOB, 'accept', OBJECTIVE, 2, ObjectiveAction.ACCEPT)
