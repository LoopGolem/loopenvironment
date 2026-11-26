# SPDX-License-Identifier: Apache-2.0
"""Opt-in cooperative execution on the authenticated LoopBridge laboratory ingress."""
from contextlib import contextmanager
from enum import StrEnum
from time import monotonic, time

from experiments.execution_lab import (SCHEMA as D2A_SCHEMA, Execution, ExecutionLabBroker, Permission,
                                       _expired, _serve_profile, _valid_id)
from experiments.objective_registry import Error, RegistryError
from experiments.registry_rpc import ERROR_CODES, VERSION as REGISTRY_VERSION
from experiments.supervision_storage import (ADVANCE_MODES, MAX_ADVANCES, MAX_EVENTS, PLAN, STAGE_RESULTS,
                                             TERMINAL, Command, SupervisionRegistry)
from loopbridge.authority import fail

VERSION = 'execution/2'


class SupervisionPermission(StrEnum):
    PROGRESS = 'progress'
    PAUSE = 'pause'
    STEP = 'step'
    CONTINUE = 'continue'


CONTROLS = {
    'start': Permission.PERFORM,
    'pause': SupervisionPermission.PAUSE,
    'step': SupervisionPermission.STEP,
    'continue': SupervisionPermission.CONTINUE,
    'cancel': Permission.CANCEL,
}
SCHEMA = {
    'execution.authorize': D2A_SCHEMA['execution.authorize'],
    'execution.status': {'attempt_id'},
    'execution.audit': {'attempt_id'},
    **{f'execution.{action}': {'attempt_id', 'expected_revision', 'request_id'} for action in CONTROLS},
}


def _calculate_stage(stage, previous):
    if stage == 1:
        return 1 + 1
    return previous + 3


class SupervisedExecution(Execution):
    operation = PLAN
    _permission_types = (Permission, SupervisionPermission)

    def _key(self, principal, permission, scope, *, attempt_id=None):
        if type(permission) is SupervisionPermission:
            key = super()._key(principal, permission, scope)
            if not _valid_id(attempt_id):
                raise ValueError('invalid_execution_grant')
            return (*key, attempt_id)
        return super()._key(principal, permission, scope, attempt_id=attempt_id)

    def dispatch(self, connection, method, params):
        try:
            if method not in SCHEMA:
                fail('method_not_found', -32601)
            if params.keys() != SCHEMA[method]:
                fail('invalid_params', -32602)
            if method == 'execution.authorize':
                return self._authorize_request(connection, params)
            attempt_id = params['attempt_id']
            if not _valid_id(attempt_id):
                fail('invalid_params', -32602)
            action = method.removeprefix('execution.')
            with self._access.identity_snapshot() as (resolve, enrolled):
                principal = resolve(connection)
                if principal is None:
                    fail('denied')
                if action in ('status', 'audit'):
                    return self._decide(lambda tx: self._observe(tx, principal, attempt_id, audit=action == 'audit'))
                revision, request_id = params['expected_revision'], params['request_id']
                if type(revision) is not int or not 1 <= revision <= MAX_EVENTS or not _valid_id(request_id):
                    fail('invalid_params', -32602)
                attempt, entry, work = self._decide(lambda tx: self._control(
                    tx, principal, enrolled, attempt_id, action, revision, request_id))
            if work:
                self._work(connection, attempt, entry)
            return entry.receipt(attempt)
        except RegistryError as error:
            code, message = ERROR_CODES[error.code]
            fail(message, code)

    def _admission_receipt(self, tx, attempt, event):
        return tx.progress(attempt).latest.receipt(attempt)

    def _control(self, tx, principal, enrolled, attempt_id, action, revision, request_id):
        attempt = tx.find(attempt_id)
        if attempt is None or (action == 'start' and principal != attempt.performer):
            fail('denied')
        permission = CONTROLS[action]
        grant = self._require_grant(tx, principal, permission, attempt.scope,
                                    attempt_id=attempt.id if type(permission) is SupervisionPermission else None)
        lifecycle = tx.history(attempt)
        progress = tx.progress(attempt, lifecycle)
        for entry in progress.entries:
            command = entry.command
            if command is not None and entry.actor == principal and command.request_id == request_id:
                tx.check_deadline()
                if (command.action, command.expected_revision) != (action, revision):
                    raise RegistryError(Error.REQUEST_CONFLICT)
                return attempt, entry, False

        if progress.latest.revision != revision:
            raise RegistryError(Error.STALE_REVISION)
        if progress.state in TERMINAL:
            raise RegistryError(Error.INVALID_STATE)
        previous = lifecycle[-1]
        active = self._retire_if_inactive(tx, attempt, previous, enrolled)
        if active != previous:
            return attempt, tx.progress(attempt).latest, False
        deadline = min(attempt.deadline, grant.deadline)
        tx.require_before(deadline)
        command = Command(action, request_id, revision, grant.generation, deadline)
        if action == 'cancel':
            tx.append(attempt, previous, 'cancelled', actor=principal, command=command)
        elif action == 'start' and progress.state == 'admitted':
            tx.append(attempt, previous, 'running', actor=principal, command=command)
        else:
            entry = self._supervise(tx, attempt, principal, progress, command)
            return attempt, entry, action in ADVANCE_MODES
        return attempt, tx.progress(attempt).latest, False

    @staticmethod
    def _supervise(tx, attempt, principal, progress, command):
        action = command.action
        if action in ADVANCE_MODES and progress.mode == 'paused':
            if progress.advances >= MAX_ADVANCES:
                raise RegistryError(Error.CAPACITY)
            kind = action
        elif action == 'pause' and progress.mode in ADVANCE_MODES.values():
            kind = 'paused' if progress.current_stage is None else 'pause_requested'
        else:
            raise RegistryError(Error.INVALID_STATE)
        return tx.record(attempt, kind, principal, command=command)

    def _work(self, connection, attempt, driver):
        while True:
            with self._access.identity_snapshot() as (resolve, enrolled):
                stage = self._decide(lambda tx: self._claim(tx, attempt, driver, resolve(connection), enrolled))
            if stage is None:
                return
            index, previous_value = stage
            try:
                result = _calculate_stage(index, previous_value)
            except Exception:
                result = None
            with self._access.identity_snapshot() as (resolve, enrolled):
                keep_going = self._decide(lambda tx: self._finish(
                    tx, attempt, driver, resolve(connection), enrolled, index, result))
            if not keep_going:
                return

    def _valid_driver(self, tx, attempt, driver, principal, enrolled, previous):
        active = self._retire_if_inactive(tx, attempt, previous, enrolled)
        if active != previous:
            return False
        command = driver.command
        key = self._key(driver.actor, CONTROLS[command.action], attempt.scope, attempt_id=attempt.id)
        grant = self._grants.get(key)
        if tx.now >= command.deadline:
            tx.append(attempt, previous, 'expired')
            return False
        if principal != driver.actor or grant is None or grant.generation != command.generation:
            tx.append(attempt, previous, 'revoked')
            return False
        tx.require_before(command.deadline)
        return True

    def _claim(self, tx, attempt, driver, principal, enrolled):
        lifecycle = tx.history(attempt)
        progress = tx.progress(attempt, lifecycle)
        if progress.driver != driver or progress.current_stage is not None:
            return None
        if not self._valid_driver(tx, attempt, driver, principal, enrolled, lifecycle[-1]):
            return None
        stage = progress.completed + 1
        tx.record(attempt, 'dispatched', attempt.performer, stage=stage)
        return stage, progress.value

    def _finish(self, tx, attempt, driver, principal, enrolled, stage, result):
        lifecycle = tx.history(attempt)
        progress = tx.progress(attempt, lifecycle)
        if progress.driver != driver or progress.current_stage != stage:
            return False
        previous = lifecycle[-1]
        if not self._valid_driver(tx, attempt, driver, principal, enrolled, previous):
            return False
        if type(result) is not int or result != STAGE_RESULTS[stage - 1]:
            tx.append(attempt, previous, 'failed', actor=attempt.performer, reason='operation_failed')
            return False
        tx.record(attempt, 'stage_completed', attempt.performer, stage=stage, value=result)
        if stage == len(STAGE_RESULTS):
            tx.append(attempt, previous, 'completed', actor=attempt.performer, result=result)
            return False
        return progress.mode == 'flowing'

    def _observe(self, tx, principal, attempt_id, *, audit):
        attempt = tx.find(attempt_id)
        if attempt is None:
            fail('denied')
        self._require_grant(tx, principal, Permission.AUDIT if audit else SupervisionPermission.PROGRESS,
                            attempt.scope, attempt_id=None if audit else attempt.id)
        progress = tx.progress(attempt)
        snapshot = dict(id=attempt.id, objective_id=attempt.scope.objective_id,
                        accepted_revision=attempt.scope.accepted_revision, plan=attempt.scope.operation,
                        revision=progress.latest.revision, state=progress.state, supervision=progress.mode,
                        current_stage=progress.current_stage, completed_stages=progress.completed,
                        total_stages=len(STAGE_RESULTS), reason=progress.reason,
                        expires_unix_ms=int(attempt.deadline * 1000))
        if audit:
            snapshot.update(executor_id=attempt.scope.executor_id, executor_revision=attempt.executor_revision,
                            authorizer=attempt.authorizer, performer=attempt.performer, request_id=attempt.request_id,
                            result=progress.result,
                            events=[self._event(entry) for entry in progress.entries])
        return snapshot

    @staticmethod
    def _event(entry):
        event = dict(revision=entry.revision, kind=entry.kind, at_unix_ms=int(entry.at * 1000), actor=entry.actor)
        if entry.stage is not None:
            event['stage'] = entry.stage
        if entry.command is not None:
            event.update(action=entry.command.action, request_id=entry.command.request_id,
                         expected_revision=entry.command.expected_revision)
            if entry.command.action in ADVANCE_MODES:
                event['deadline_unix_ms'] = int(entry.command.deadline * 1000)
        return event


class SupervisionLabBroker(ExecutionLabBroker):
    versions = wire_versions = (REGISTRY_VERSION, VERSION)
    _registry_type = SupervisionRegistry
    _execution_type = SupervisedExecution
    _execution_version = VERSION


@contextmanager
def serve_supervision_lab(root, verifiers, *, create=False, wall_clock=time, clock=monotonic):
    """Open the supervised profile on a private disposable Unix socket."""
    with _serve_profile(root, verifiers, SupervisionLabBroker, 'supervised', create, wall_clock, clock) as profile:
        yield profile
