# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, dataclass
from threading import Barrier
import unittest
from unittest.mock import patch

from experiments.objective_registry import (Error, ExecutorAction, ExecutorState,
                                            MAX_LABEL_BYTES, MAX_TEXT_BYTES, MAX_TTL_SECONDS,
                                            ObjectiveAction, ObjectiveState, Permission,
                                            Registry, RegistryError)
from loopbridge.authority import Session
from loopbridge.identity import Identities
from loopbridge.protocol import Fault

ADMIN = 'a' * 43
EXECUTOR = 'b' * 43
OTHER = 'c' * 43
EXECUTOR_ID = 'review-worker'
OBJECTIVE_ID = 'review-record'


@dataclass(frozen=True)
class Scopes:
    principal: str
    grants: frozenset

    def permits(self, permission, executor_id):
        return (permission, executor_id) in self.grants


class LabAuthority:
    """Real lab bearer verification with scope sets held fixed during each race."""
    def __init__(self):
        self.identities = Identities()
        self.identities.load({'owner': ADMIN, 'delegate': EXECUTOR, 'observer': OTHER})
        self.grants = {principal: set() for principal in ('owner', 'delegate', 'observer')}

    @contextmanager
    def authenticate(self, credential):
        try:
            principal = self.identities.authenticate(credential)
        except Fault:
            raise RegistryError(Error.DENIED) from None
        yield Scopes(principal, frozenset(self.grants[principal]))

    def allow(self, principal, *permissions, executor_id=EXECUTOR_ID):
        self.grants[principal].update((permission, executor_id) for permission in permissions)

    def deny(self, principal, permission):
        self.grants[principal].remove((permission, EXECUTOR_ID))


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.authority = LabAuthority()
        self.authority.allow('owner', Permission.REGISTER, Permission.MANAGE_EXECUTOR,
                             Permission.READ_EXECUTOR, Permission.AUTHOR_OBJECTIVE,
                             Permission.READ_OBJECTIVE)
        self.authority.allow('delegate', Permission.CONFIRM, Permission.READ_EXECUTOR,
                             Permission.RESPOND_TO_OBJECTIVE, Permission.READ_OBJECTIVE)
        self.now = 10
        self.registry = Registry(self.authority, clock=lambda: self.now)

    def assert_error(self, code, call, *args):
        with self.assertRaises(RegistryError) as caught:
            call(*args)
        self.assertIs(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code.value)

    def register(self):
        return self.registry.register(ADMIN, 'register', EXECUTOR_ID, 'delegate', 'Reviewer')

    def available(self):
        self.register()
        return self.registry.transition_executor(EXECUTOR, 'confirm', EXECUTOR_ID, 1, ExecutorAction.CONFIRM)

    def draft(self, text='Review the report.', ttl=15):
        self.available()
        return self.registry.create_objective(ADMIN, 'create', OBJECTIVE_ID, EXECUTOR_ID, text, ttl)

    def offered(self, text='Review the report.', ttl=15):
        self.draft(text, ttl)
        return self.registry.transition_objective(ADMIN, 'offer', OBJECTIVE_ID, 1, ObjectiveAction.OFFER)

    def test_authentication_subject_is_verified_and_matches_the_pending_binding(self):
        pending = self.register()
        self.assertEqual((pending.state, pending.revision), (ExecutorState.PENDING, 1))
        self.assertEqual(self.registry.read_executor(EXECUTOR, EXECUTOR_ID).registered_by, 'owner')
        self.assert_error(Error.DENIED, self.registry.read_executor, 'owner', EXECUTOR_ID)
        self.assert_error(Error.DENIED, self.registry.read_executor, 'z' * 43, EXECUTOR_ID)
        self.assert_error(Error.DENIED, self.registry.read_executor, None, EXECUTOR_ID)
        self.assert_error(Error.DENIED, self.registry.read_executor, 'a' * 129, EXECUTOR_ID)
        self.authority.allow('observer', Permission.CONFIRM)
        self.assert_error(Error.DENIED, self.registry.transition_executor,
                          OTHER, 'confirm', EXECUTOR_ID, 1, ExecutorAction.CONFIRM)
        self.assert_error(Error.UNAVAILABLE, self.registry.create_objective,
                          ADMIN, 'create', OBJECTIVE_ID, EXECUTOR_ID, 'Review the report.', 15)
        available = self.registry.transition_executor(EXECUTOR, 'confirm', EXECUTOR_ID, 1, ExecutorAction.CONFIRM)
        self.assertEqual((available.state, available.revision), (ExecutorState.AVAILABLE, 2))

    def test_label_and_owner_name_do_not_grant_capabilities(self):
        self.registry.register(ADMIN, 'register', EXECUTOR_ID, 'delegate', 'owner')
        self.authority.deny('delegate', Permission.CONFIRM)
        self.assert_error(Error.DENIED, self.registry.transition_executor,
                          EXECUTOR, 'confirm', EXECUTOR_ID, 1, ExecutorAction.CONFIRM)
        self.authority.allow('delegate', Permission.CONFIRM)
        self.registry.transition_executor(EXECUTOR, 'confirm', EXECUTOR_ID, 1, ExecutorAction.CONFIRM)
        self.assert_error(Error.DENIED, self.registry.create_objective,
                          EXECUTOR, 'create', OBJECTIVE_ID, EXECUTOR_ID, 'I grant myself authority.', 15)
        self.authority.deny('owner', Permission.AUTHOR_OBJECTIVE)
        self.assert_error(Error.DENIED, self.registry.create_objective,
                          ADMIN, 'create', OBJECTIVE_ID, EXECUTOR_ID, 'An owner still needs scope.', 15)

    def test_scope_matches_the_exact_executor(self):
        self.available()
        self.assert_error(Error.DENIED, self.registry.register, ADMIN, 'r2', 'another', 'delegate', 'Another')
        self.authority.allow('owner', Permission.REGISTER, executor_id='another')
        self.registry.register(ADMIN, 'r2', 'another', 'delegate', 'Another')
        self.assert_error(Error.DENIED, self.registry.transition_executor,
                          EXECUTOR, 'c2', 'another', 1, ExecutorAction.CONFIRM)
        self.assert_error(Error.DENIED, self.registry.read_executor, EXECUTOR, 'another')
        self.assert_error(Error.DENIED, self.registry.read_executor, EXECUTOR, 'nonexistent')

    def test_created_offer_and_both_responses_record_authorship(self):
        for action, terminal in ((ObjectiveAction.ACCEPT, ObjectiveState.ACCEPTED),
                                 (ObjectiveAction.DECLINE, ObjectiveState.DECLINED)):
            with self.subTest(action=action):
                self.registry = Registry(self.authority, clock=lambda: self.now)
                draft = self.draft()
                self.assertEqual((draft.state, draft.revision), (ObjectiveState.CREATED, 1))
                self.assert_error(Error.DENIED, self.registry.read_objective, EXECUTOR, OBJECTIVE_ID)
                self.assert_error(Error.DENIED, self.registry.transition_objective,
                                  EXECUTOR, 'respond', OBJECTIVE_ID, 1, action)
                offer = self.registry.transition_objective(ADMIN, 'offer', OBJECTIVE_ID, 1, ObjectiveAction.OFFER)
                self.assertEqual((offer.state, offer.revision), (ObjectiveState.OFFERED, 2))
                self.assertEqual(self.registry.read_objective(EXECUTOR, OBJECTIVE_ID).expires_at, 25)
                result = self.registry.transition_objective(EXECUTOR, 'respond', OBJECTIVE_ID, 2, action)
                self.assertEqual((result.state, result.revision), (terminal, 3))
                snapshot = self.registry.read_objective(ADMIN, OBJECTIVE_ID)
                self.assertEqual((snapshot.issuer, snapshot.changed_by, snapshot.state),
                                 ('owner', 'delegate', terminal))
                self.assert_error(Error.INVALID_STATE, self.registry.transition_objective,
                                  ADMIN, 'withdraw', OBJECTIVE_ID, 3, ObjectiveAction.WITHDRAW)

    def test_author_and_recipient_binding_is_checked_even_with_scope(self):
        self.offered()
        self.authority.allow('observer', Permission.READ_OBJECTIVE, Permission.AUTHOR_OBJECTIVE,
                             Permission.RESPOND_TO_OBJECTIVE)
        self.assert_error(Error.DENIED, self.registry.read_objective, OTHER, OBJECTIVE_ID)
        self.assert_error(Error.DENIED, self.registry.read_objective, OTHER, 'missing')
        self.assert_error(Error.DENIED, self.registry.transition_objective,
                          OTHER, 'respond', OBJECTIVE_ID, 2, ObjectiveAction.ACCEPT)
        self.assert_error(Error.DENIED, self.registry.transition_objective,
                          OTHER, 'withdraw', OBJECTIVE_ID, 2, ObjectiveAction.WITHDRAW)
        self.authority.deny('delegate', Permission.RESPOND_TO_OBJECTIVE)
        self.assert_error(Error.DENIED, self.registry.transition_objective,
                          EXECUTOR, 'respond', OBJECTIVE_ID, 2, ObjectiveAction.ACCEPT)
        self.assertEqual(self.registry.read_objective(EXECUTOR, OBJECTIVE_ID).state, ObjectiveState.OFFERED)

    def test_recipient_discovers_only_its_current_offers(self):
        self.offered(ttl=10)
        self.registry.create_objective(ADMIN, 'private', 'private', EXECUTOR_ID, 'Draft', 10)
        self.registry.create_objective(ADMIN, 'short', 'short', EXECUTOR_ID, 'Short offer', 1)
        self.registry.transition_objective(ADMIN, 'offer-short', 'short', 1, ObjectiveAction.OFFER)
        self.now = 11
        self.authority.allow('observer', Permission.READ_OBJECTIVE)
        self.assert_error(Error.DENIED, self.registry.list_offers, OTHER, EXECUTOR_ID)
        self.assert_error(Error.DENIED, self.registry.list_offers, ADMIN, EXECUTOR_ID)
        (offer,) = self.registry.list_offers(EXECUTOR, EXECUTOR_ID)
        self.assertEqual((offer.id, offer.text), (OBJECTIVE_ID, 'Review the report.'))
        self.assertEqual(self.registry.read_objective(EXECUTOR, 'short').state, ObjectiveState.EXPIRED)
        self.registry.transition_objective(EXECUTOR, 'accept', offer.id, offer.revision, ObjectiveAction.ACCEPT)
        self.assertEqual(self.registry.list_offers(EXECUTOR, EXECUTOR_ID), ())
        self.registry.transition_executor(ADMIN, 'suspend', EXECUTOR_ID, 2, ExecutorAction.SUSPEND)
        self.assert_error(Error.UNAVAILABLE, self.registry.list_offers, EXECUTOR, EXECUTOR_ID)

    def test_suspend_blocks_receipt_and_resume_reopens_unexpired_offer(self):
        self.offered()
        suspended = self.registry.transition_executor(ADMIN, 'suspend', EXECUTOR_ID, 2, ExecutorAction.SUSPEND)
        self.assertEqual(suspended.state, ExecutorState.SUSPENDED)
        self.assert_error(Error.DENIED, self.registry.read_objective, EXECUTOR, OBJECTIVE_ID)
        self.assert_error(Error.UNAVAILABLE, self.registry.transition_objective,
                          EXECUTOR, 'respond', OBJECTIVE_ID, 2, ObjectiveAction.ACCEPT)
        self.assert_error(Error.UNAVAILABLE, self.registry.create_objective,
                          ADMIN, 'other', 'second', EXECUTOR_ID, 'Other', 15)
        self.assertEqual(self.registry.read_objective(ADMIN, OBJECTIVE_ID).revision, 2)
        resumed = self.registry.transition_executor(ADMIN, 'resume', EXECUTOR_ID, 3, ExecutorAction.RESUME)
        self.assertEqual((resumed.state, resumed.revision), (ExecutorState.AVAILABLE, 4))
        self.assertEqual(self.registry.transition_objective(
            EXECUTOR, 'respond', OBJECTIVE_ID, 2, ObjectiveAction.ACCEPT).state, ObjectiveState.ACCEPTED)

    def test_revocation_retires_pending_executor_and_never_reuses_id(self):
        self.register()
        result = self.registry.transition_executor(ADMIN, 'revoke', EXECUTOR_ID, 1, ExecutorAction.REVOKE)
        self.assertEqual(result.state, ExecutorState.REVOKED)
        self.assert_error(Error.UNAVAILABLE, self.registry.transition_executor,
                          EXECUTOR, 'confirm', EXECUTOR_ID, 1, ExecutorAction.CONFIRM)
        self.assert_error(Error.INVALID_STATE, self.registry.transition_executor,
                          ADMIN, 'resume', EXECUTOR_ID, 2, ExecutorAction.RESUME)
        self.assert_error(Error.ALREADY_EXISTS, self.registry.register,
                          ADMIN, 'register-again', EXECUTOR_ID, 'delegate', 'New name')

    def test_revocation_withdraws_open_records_only_for_its_target(self):
        self.offered(ttl=20)
        self.registry.create_objective(ADMIN, 'draft', 'draft', EXECUTOR_ID, 'Draft', 20)
        self.registry.create_objective(ADMIN, 'expired', 'expired', EXECUTOR_ID, 'Draft', 5)
        self.authority.allow('owner', Permission.REGISTER, Permission.AUTHOR_OBJECTIVE,
                             Permission.READ_OBJECTIVE, executor_id='another')
        self.authority.allow('delegate', Permission.CONFIRM, executor_id='another')
        self.registry.register(ADMIN, 'r2', 'another', 'delegate', 'Another')
        self.registry.transition_executor(EXECUTOR, 'c2', 'another', 1, ExecutorAction.CONFIRM)
        self.registry.create_objective(ADMIN, 'separate', 'separate', 'another', 'Separate', 20)
        self.now = 15
        revoked = self.registry.transition_executor(ADMIN, 'revoke', EXECUTOR_ID, 2, ExecutorAction.REVOKE)
        self.assertEqual(revoked.state, ExecutorState.REVOKED)
        for objective in (OBJECTIVE_ID, 'draft'):
            snapshot = self.registry.read_objective(ADMIN, objective)
            self.assertEqual((snapshot.state, snapshot.changed_by), (ObjectiveState.WITHDRAWN, 'owner'))
            self.assert_error(Error.DENIED, self.registry.read_objective, EXECUTOR, objective)
        self.assertEqual(self.registry.read_objective(ADMIN, 'expired').state, ObjectiveState.EXPIRED)
        self.assertEqual(self.registry.read_objective(ADMIN, 'separate').state, ObjectiveState.CREATED)
        self.assert_error(Error.UNAVAILABLE, self.registry.transition_objective,
                          EXECUTOR, 'respond', OBJECTIVE_ID, 2, ObjectiveAction.ACCEPT)
        self.assert_error(Error.UNAVAILABLE, self.registry.create_objective,
                          ADMIN, 'new', 'third', EXECUTOR_ID, 'New', 20)

    def test_expiration_is_inclusive_recorded_once_and_uses_creation_deadline(self):
        self.draft(ttl=2)
        self.now = 11
        self.registry.transition_objective(ADMIN, 'offer', OBJECTIVE_ID, 1, ObjectiveAction.OFFER)
        self.now = 12
        self.assert_error(Error.EXPIRED, self.registry.transition_objective,
                          EXECUTOR, 'accept', OBJECTIVE_ID, 2, ObjectiveAction.ACCEPT)
        self.now = 100
        first = self.registry.read_objective(EXECUTOR, OBJECTIVE_ID)
        self.assertEqual((first.state, first.revision, first.changed_by),
                         (ObjectiveState.EXPIRED, 3, None))
        self.assertEqual(self.registry.read_objective(ADMIN, OBJECTIVE_ID), first)

    def test_draft_expiry_and_withdrawal_stay_private(self):
        self.draft(ttl=1)
        self.registry.create_objective(ADMIN, 'draft2', 'private-draft', EXECUTOR_ID, 'Private draft', 20)
        self.registry.transition_objective(ADMIN, 'withdraw', 'private-draft', 1, ObjectiveAction.WITHDRAW)
        self.now = 11
        self.assert_error(Error.EXPIRED, self.registry.transition_objective,
                          ADMIN, 'offer', OBJECTIVE_ID, 1, ObjectiveAction.OFFER)
        self.assertEqual(self.registry.read_objective(ADMIN, OBJECTIVE_ID).state, ObjectiveState.EXPIRED)
        for objective in (OBJECTIVE_ID, 'private-draft'):
            self.assert_error(Error.DENIED, self.registry.read_objective, EXECUTOR, objective)

    def test_stale_revision_and_terminal_state_are_distinct(self):
        self.offered()
        self.assert_error(Error.STALE_REVISION, self.registry.transition_executor,
                          ADMIN, 'suspend', EXECUTOR_ID, 1, ExecutorAction.SUSPEND)
        self.assert_error(Error.STALE_REVISION, self.registry.transition_objective,
                          EXECUTOR, 'respond', OBJECTIVE_ID, 1, ObjectiveAction.ACCEPT)
        self.registry.transition_objective(ADMIN, 'withdraw', OBJECTIVE_ID, 2, ObjectiveAction.WITHDRAW)
        self.assert_error(Error.STALE_REVISION, self.registry.transition_objective,
                          EXECUTOR, 'respond', OBJECTIVE_ID, 2, ObjectiveAction.ACCEPT)
        self.assert_error(Error.INVALID_STATE, self.registry.transition_objective,
                          EXECUTOR, 'respond', OBJECTIVE_ID, 3, ObjectiveAction.ACCEPT)
        self.assertEqual(self.registry.read_objective(EXECUTOR, OBJECTIVE_ID).state, ObjectiveState.WITHDRAWN)

    def test_duplicate_returns_original_receipt_under_current_authority(self):
        result = self.offered()
        # An identical create returns the historical revision and deadline stays fixed.
        self.now = 20
        self.assertEqual(self.registry.create_objective(
            ADMIN, 'create', OBJECTIVE_ID, EXECUTOR_ID, 'Review the report.', 15).revision, 1)
        self.assertEqual(self.registry.transition_objective(
            ADMIN, 'offer', OBJECTIVE_ID, 1, ObjectiveAction.OFFER), result)
        self.assertEqual(self.registry.read_objective(EXECUTOR, OBJECTIVE_ID).expires_at, 25)
        args = (EXECUTOR, 'respond', OBJECTIVE_ID, 2, ObjectiveAction.ACCEPT)
        accepted = self.registry.transition_objective(*args)
        self.now = 30
        self.assertEqual(self.registry.transition_objective(*args), accepted)
        self.assert_error(Error.REQUEST_CONFLICT, self.registry.transition_objective,
                          EXECUTOR, 'respond', OBJECTIVE_ID, 2, ObjectiveAction.DECLINE)
        self.authority.deny('delegate', Permission.RESPOND_TO_OBJECTIVE)
        self.assert_error(Error.DENIED, self.registry.transition_objective, *args)
        self.authority.allow('delegate', Permission.RESPOND_TO_OBJECTIVE)
        self.registry.transition_executor(ADMIN, 'revoke', EXECUTOR_ID, 2, ExecutorAction.REVOKE)
        self.assert_error(Error.UNAVAILABLE, self.registry.transition_objective, *args)
        self.assertEqual(self.registry.read_objective(ADMIN, OBJECTIVE_ID).state, ObjectiveState.ACCEPTED)

    def test_duplicate_key_is_principal_scoped_and_signatures_cover_payload(self):
        self.register()
        self.registry.transition_executor(EXECUTOR, 'register', EXECUTOR_ID, 1, ExecutorAction.CONFIRM)
        args = (ADMIN, 'create', OBJECTIVE_ID, EXECUTOR_ID, 'Review', 15)
        self.registry.create_objective(*args)
        for altered in ((ADMIN, 'create', OBJECTIVE_ID, EXECUTOR_ID, 'Other', 15),
                        (ADMIN, 'create', OBJECTIVE_ID, EXECUTOR_ID, 'Review', 16)):
            self.assert_error(Error.REQUEST_CONFLICT, self.registry.create_objective, *altered)
        self.assert_error(Error.REQUEST_CONFLICT, self.registry.transition_objective,
                          ADMIN, 'create', OBJECTIVE_ID, 1, ObjectiveAction.OFFER)
        self.assert_error(Error.ALREADY_EXISTS, self.registry.create_objective,
                          ADMIN, 'other-key', OBJECTIVE_ID, EXECUTOR_ID, 'Review', 15)

    def race(self, *operations):
        barrier = Barrier(len(operations) + 1)

        def run(arguments):
            barrier.wait(timeout=3)
            method, *args = arguments
            try:
                return method(*args).state
            except RegistryError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=len(operations)) as threads:
            work = [threads.submit(run, operation) for operation in operations]
            barrier.wait(timeout=3)
            return [job.result(timeout=3) for job in work]

    def test_concurrent_duplicate_writes_once(self):
        self.offered()
        operation = (self.registry.transition_objective, EXECUTOR, 'x', OBJECTIVE_ID,
                     2, ObjectiveAction.ACCEPT)
        self.assertEqual(self.race(operation, operation), [ObjectiveState.ACCEPTED] * 2)
        self.assertEqual(self.registry.read_objective(ADMIN, OBJECTIVE_ID).revision, 3)

    def test_accept_and_withdraw_serialize_without_lost_update(self):
        self.offered()
        change = self.registry.transition_objective
        accept, withdraw = self.race(
            (change, EXECUTOR, 'accept', OBJECTIVE_ID, 2, ObjectiveAction.ACCEPT),
            (change, ADMIN, 'withdraw', OBJECTIVE_ID, 2, ObjectiveAction.WITHDRAW),
        )
        self.assertIn((accept, withdraw), ((ObjectiveState.ACCEPTED, Error.STALE_REVISION),
                                          (Error.STALE_REVISION, ObjectiveState.WITHDRAWN)))
        result = self.registry.read_objective(ADMIN, OBJECTIVE_ID)
        self.assertEqual(result.revision, 3)
        self.assertEqual(result.state, next(value for value in (accept, withdraw)
                                            if isinstance(value, ObjectiveState)))

    def test_accept_and_revoke_serialize_and_terminal_result_is_retained(self):
        self.offered()
        accept, revoke = self.race(
            (self.registry.transition_objective, EXECUTOR, 'accept', OBJECTIVE_ID, 2, ObjectiveAction.ACCEPT),
            (self.registry.transition_executor, ADMIN, 'revoke', EXECUTOR_ID, 2, ExecutorAction.REVOKE),
        )
        self.assertEqual(revoke, ExecutorState.REVOKED)
        self.assertIn(accept, (ObjectiveState.ACCEPTED, Error.UNAVAILABLE))
        final = self.registry.read_objective(ADMIN, OBJECTIVE_ID)
        expected = ObjectiveState.ACCEPTED if accept is ObjectiveState.ACCEPTED else ObjectiveState.WITHDRAWN
        self.assertEqual((final.state, final.revision), (expected, 3))
        self.assert_error(Error.DENIED, self.registry.read_objective, EXECUTOR, OBJECTIVE_ID)

    def test_withdraw_and_revoke_have_one_objective_transition(self):
        self.offered()
        withdraw, revoke = self.race(
            (self.registry.transition_objective, ADMIN, 'withdraw', OBJECTIVE_ID, 2, ObjectiveAction.WITHDRAW),
            (self.registry.transition_executor, ADMIN, 'revoke', EXECUTOR_ID, 2, ExecutorAction.REVOKE),
        )
        self.assertIn(withdraw, (ObjectiveState.WITHDRAWN, Error.STALE_REVISION))
        self.assertEqual(revoke, ExecutorState.REVOKED)
        result = self.registry.read_objective(ADMIN, OBJECTIVE_ID)
        self.assertEqual((result.state, result.revision), (ObjectiveState.WITHDRAWN, 3))

    def test_expired_receipt_window_cannot_repeat_old_transition(self):
        with patch('experiments.objective_registry.MAX_RECEIPTS', 2):
            self.offered()
            self.registry.transition_objective(EXECUTOR, 'respond', OBJECTIVE_ID, 2, ObjectiveAction.ACCEPT)
            self.registry.transition_executor(ADMIN, 'suspend', EXECUTOR_ID, 2, ExecutorAction.SUSPEND)
            self.registry.transition_executor(ADMIN, 'resume', EXECUTOR_ID, 3, ExecutorAction.RESUME)
            self.assert_error(Error.STALE_REVISION, self.registry.transition_objective,
                              EXECUTOR, 'respond', OBJECTIVE_ID, 2, ObjectiveAction.ACCEPT)
            self.assert_error(Error.ALREADY_EXISTS, self.registry.create_objective,
                              ADMIN, 'create', OBJECTIVE_ID, EXECUTOR_ID, 'Review the report.', 15)
        self.assertEqual(self.registry.read_objective(ADMIN, OBJECTIVE_ID).revision, 3)

    def test_maximum_sizes_terminal_records_and_revocation(self):
        with patch('experiments.objective_registry.MAX_EXECUTORS', 1), \
                patch('experiments.objective_registry.MAX_OBJECTIVES', 1):
            self.available()
            self.authority.allow('owner', Permission.REGISTER, executor_id='second')
            self.assert_error(Error.CAPACITY, self.registry.register,
                              ADMIN, 'register2', 'second', 'delegate', 'Second')
            self.registry.create_objective(ADMIN, 'create', 'first', EXECUTOR_ID, 'a', 15)
            self.assert_error(Error.CAPACITY, self.registry.create_objective,
                              ADMIN, 'create2', 'second', EXECUTOR_ID, 'a', 15)
            self.registry.transition_executor(ADMIN, 'revoke', EXECUTOR_ID, 2, ExecutorAction.REVOKE)
            self.assertEqual(self.registry.read_objective(ADMIN, 'first').state, ObjectiveState.WITHDRAWN)

    def test_malformed_inputs_and_utf8_limits(self):
        for label in ('', ' ', 'é' * (MAX_LABEL_BYTES // 2 + 1), 'bad\x00name', '\ud800', []):
            with self.subTest(label=label):
                self.assert_error(Error.INVALID_INPUT, self.registry.register,
                                  ADMIN, 'register', EXECUTOR_ID, 'delegate', label)
        self.available()
        for bad_id in ('../wrong', 'é', '', 'a' * 65, 1, True):
            self.assert_error(Error.INVALID_INPUT, self.registry.create_objective,
                              ADMIN, 'create', bad_id, EXECUTOR_ID, 'Review', 15)
        for body in ('', '\t\n', '\ud800', 'x\x7fy', 'é' * (MAX_TEXT_BYTES // 2 + 1), {}, None):
            self.assert_error(Error.INVALID_INPUT, self.registry.create_objective,
                              ADMIN, 'create', OBJECTIVE_ID, EXECUTOR_ID, body, 15)
        for ttl in (True, 0, -1, MAX_TTL_SECONDS + 1, 12.0, float('inf')):
            self.assert_error(Error.INVALID_INPUT, self.registry.create_objective,
                              ADMIN, 'create', OBJECTIVE_ID, EXECUTOR_ID, 'Review', ttl)
        accepted = self.registry.create_objective(
            ADMIN, 'create', OBJECTIVE_ID, EXECUTOR_ID, 'é' * (MAX_TEXT_BYTES // 2), MAX_TTL_SECONDS)
        self.assertEqual(accepted.state, ObjectiveState.CREATED)
        for revision, action in ((True, ObjectiveAction.OFFER), (0, ObjectiveAction.OFFER), (1, 'offer')):
            self.assert_error(Error.INVALID_INPUT, self.registry.transition_objective,
                              ADMIN, 'offer', OBJECTIVE_ID, revision, action)

    def test_text_stays_inert_and_acceptance_does_not_touch_session_authority(self):
        private = Session('desktop', clock=lambda: self.now, catalog=('calculator',), workspace=True,
                          extra_capabilities=('desktop.stream',))
        initial = private.policy_revision, private.history.seq, dict(private.grants)
        goal = "Review the report.\n\t$(touch marker)\n__import__('os').system('false')"
        with patch('subprocess.Popen') as process, patch('os.system') as shell, \
                patch('builtins.eval') as evaluate, patch('builtins.exec') as execute, \
                patch('builtins.open') as io:
            self.offered(goal)
            result = self.registry.transition_objective(EXECUTOR, 'respond', OBJECTIVE_ID, 2, ObjectiveAction.ACCEPT)
            for operation in (process, shell, evaluate, execute, io):
                operation.assert_not_called()
        self.assertEqual(result.state, ObjectiveState.ACCEPTED)
        record = self.registry.read_objective(EXECUTOR, OBJECTIVE_ID)
        self.assertEqual(record.text, goal)
        self.assertNotIn('touch marker', repr(record))
        with self.assertRaises(FrozenInstanceError):
            record.text = 'changed'
        capabilities = ('workspace.read', 'workspace.write', 'desktop.stream', 'desktop.capture',
                        'desktop.input', 'desktop.control')
        for capability in capabilities:
            self.assertIn(capability, private.capabilities)
            self.assertFalse(private.permits('delegate', capability))
        with self.assertRaisesRegex(Fault, '^grant_denied$'):
            private.acquire('delegate', 'unprivileged', ttl=10)
        self.assertIsNone(private.lease)
        self.assertEqual((private.policy_revision, private.history.seq, private.grants), initial)
