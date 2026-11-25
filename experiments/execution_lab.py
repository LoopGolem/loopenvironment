# SPDX-License-Identifier: Apache-2.0
"""Opt-in first executor: authenticated, typed arithmetic and durable decisions."""
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
from secrets import token_hex
from time import monotonic, time

from experiments.durable_objective_registry import _valid_wall
from experiments.execution_storage import (Attempt, DeadlinePassed, ExecutionRegistry, MAX_TTL,
                                           Scope, TRANSITIONS)
from experiments.objective_registry import Error, RegistryError
from experiments.registry_lab import RegistryLabBroker
from experiments.registry_rpc import ERROR_CODES, OPAQUE_ID, VERSION as REGISTRY_VERSION
from loopbridge.authority import fail
from loopbridge.broker import Server
from loopbridge.identity import Identities
from loopbridge.service import Journal, directory_lock, private_directory
from loopbridge.service_ingress import bound_listener

VERSION = 'execution/1'
MAX_GRANTS = 1024
SCHEMA = {
    'execution.authorize': {'request_id', 'executor_id', 'objective_id', 'accepted_revision',
                            'operation', 'ttl_seconds'},
    'execution.start': {'attempt_id'},
    'execution.cancel': {'attempt_id'},
    'execution.audit': {'attempt_id'},
}


class Permission(StrEnum):
    AUTHORIZE = 'authorize'
    PERFORM = 'perform'
    CANCEL = 'cancel'
    AUDIT = 'audit'


@dataclass(frozen=True)
class Grant:
    generation: str
    deadline: float


def _valid_id(value):
    return type(value) is str and OPAQUE_ID.fullmatch(value) is not None


def _expired():
    fail('authorization_expired', -32060)


def _add_fixed_constants():
    return 2 + 3


class Execution:
    """Every policy decision holds ingress identity and exact grants stable."""

    def __init__(self, registry, access):
        self._registry = registry
        self._access = access
        self._grants = {}

    @staticmethod
    def _key(principal, permission, scope):
        if (not _valid_id(principal) or type(permission) is not Permission
                or type(scope) is not Scope or not scope.valid()):
            raise ValueError('invalid_execution_grant')
        return principal, permission, scope

    def grant(self, principal, permission, scope, *, expires_at):
        """Trusted fixture control. Grant management is outside RPC."""
        key = self._key(principal, permission, scope)
        if not _valid_wall(expires_at):
            raise ValueError('invalid_execution_grant')
        with self._access.identity_snapshot() as (_, enrolled):
            if not enrolled(principal) or key in self._grants or len(self._grants) >= MAX_GRANTS:
                raise ValueError('invalid_execution_grant')
            self._grants[key] = Grant(token_hex(16), expires_at)

    def revoke(self, principal, permission, scope):
        key = self._key(principal, permission, scope)
        with self._access.identity_snapshot():
            grant = self._grants.pop(key, None)
            if grant is None or permission not in (Permission.AUTHORIZE, Permission.PERFORM):
                return
            with self._registry.execution_transaction() as tx:
                for attempt in tx.attempts():
                    fixed_grant = ((attempt.authorizer, attempt.authorize_generation)
                                   if permission is Permission.AUTHORIZE
                                   else (attempt.performer, attempt.perform_generation))
                    if attempt.scope != scope or fixed_grant != (principal, grant.generation):
                        continue
                    previous = tx.history(attempt)[-1]
                    if previous.state in TRANSITIONS:
                        state = 'expired' if tx.sample_time() >= attempt.deadline else 'revoked'
                        tx.append(attempt, previous, state)

    def _require_grant(self, tx, principal, permission, scope):
        grant = self._grants.get((principal, permission, scope))
        if grant is None:
            fail('denied')
        if tx.now >= grant.deadline:
            _expired()
        tx.require_before(grant.deadline)
        return grant

    def _decide(self, decision):
        # If a checked bound expires during SQLite work, discard the uncommitted
        # decision and observe the expired authority under the same policy mutex.
        for _ in range(2):
            try:
                with self._registry.execution_transaction() as tx:
                    return decision(tx)
            except DeadlinePassed:
                continue
        _expired()

    def dispatch(self, connection, method, params):
        try:
            if method not in SCHEMA:
                fail('method_not_found', -32601)
            if params.keys() != SCHEMA[method]:
                fail('invalid_params', -32602)
            if method == 'execution.authorize':
                scope = Scope(params['executor_id'], params['objective_id'],
                              params['accepted_revision'], params['operation'])
                request_id, ttl = params['request_id'], params['ttl_seconds']
                if not scope.valid() or not _valid_id(request_id) or type(ttl) is not int or not 1 <= ttl <= MAX_TTL:
                    fail('invalid_params', -32602)
                with self._access.identity_snapshot() as (resolve, enrolled):
                    principal = resolve(connection)
                    if principal is None:
                        fail('denied')
                    return self._decide(lambda tx: self._authorize(tx, principal, enrolled, scope, request_id, ttl))

            attempt_id = params['attempt_id']
            if not _valid_id(attempt_id):
                fail('invalid_params', -32602)
            with self._access.identity_snapshot() as (resolve, enrolled):
                principal = resolve(connection)
                if principal is None:
                    fail('denied')
                if method == 'execution.audit':
                    return self._decide(lambda tx: self._audit(tx, principal, attempt_id))
                if method == 'execution.cancel':
                    return self._decide(lambda tx: self._cancel(tx, principal, enrolled, attempt_id))
                attempt, event, run = self._decide(lambda tx: self._start(tx, principal, enrolled, attempt_id))
            if event.state == 'expired':
                _expired()
            if not run:
                return event.receipt(attempt)

            try:
                result = _add_fixed_constants()
            except Exception:
                result = None
            with self._access.identity_snapshot() as (resolve, enrolled):
                return self._decide(lambda tx: self._publish(
                    tx, attempt, enrolled, resolve(connection) == principal, result))
        except RegistryError as error:
            code, message = ERROR_CODES[error.code]
            fail(message, code)

    def _authorize(self, tx, principal, enrolled, scope, request_id, ttl):
        previous = tx.find_request(principal, request_id)
        if previous is not None and (previous.scope, previous.ttl_seconds) != (scope, ttl):
            raise RegistryError(Error.REQUEST_CONFLICT)
        authority = self._require_grant(tx, principal, Permission.AUTHORIZE, scope)
        target = tx.target(scope.objective_id)
        if target is None or target.executor_id != scope.executor_id or not enrolled(target.principal):
            fail('denied')
        performer = self._require_grant(tx, target.principal, Permission.PERFORM, scope)
        if target.executor_state != 'available':
            raise RegistryError(Error.UNAVAILABLE)
        if tx.now >= target.deadline:
            raise RegistryError(Error.EXPIRED)
        if target.objective_state != 'accepted':
            raise RegistryError(Error.INVALID_STATE)
        if target.objective_revision != scope.accepted_revision:
            raise RegistryError(Error.STALE_REVISION)
        if previous is not None:
            if tx.now >= previous.deadline:
                _expired()
            tx.require_before(previous.deadline)
            event = tx.history(previous)[-1]
            event = self._retire_if_inactive(tx, previous, event, enrolled)
            return event.receipt(previous)
        deadline = min(tx.now + ttl, authority.deadline, performer.deadline, target.deadline)
        tx.require_before(deadline)
        attempt = Attempt(token_hex(16), principal, target.principal, request_id, scope, ttl,
                          target.executor_revision, deadline, authority.generation, performer.generation)
        return tx.admit(attempt).receipt(attempt)

    def _retire_if_inactive(self, tx, attempt, event, enrolled):
        if event.state not in TRANSITIONS:
            return event
        target = tx.target(attempt.scope.objective_id)
        if tx.sample_time() >= attempt.deadline:
            return tx.append(attempt, event, 'expired')
        authorizer = self._grants.get((attempt.authorizer, Permission.AUTHORIZE, attempt.scope))
        performer = self._grants.get((attempt.performer, Permission.PERFORM, attempt.scope))
        if (target is None or target.executor_id != attempt.scope.executor_id
                or target.principal != attempt.performer or target.executor_revision != attempt.executor_revision
                or target.executor_state != 'available' or target.objective_state != 'accepted'
                or target.objective_revision != attempt.scope.accepted_revision
                or not enrolled(attempt.authorizer) or not enrolled(attempt.performer)
                or authorizer is None or authorizer.generation != attempt.authorize_generation
                or performer is None or performer.generation != attempt.perform_generation):
            return tx.append(attempt, event, 'revoked')
        return event

    def _start(self, tx, principal, enrolled, attempt_id):
        attempt = tx.find(attempt_id)
        if attempt is None or principal != attempt.performer:
            fail('denied')
        grant = self._grants.get((principal, Permission.PERFORM, attempt.scope))
        if grant is None:
            fail('denied')
        previous = tx.history(attempt)[-1]
        event = self._retire_if_inactive(tx, attempt, previous, enrolled)
        if tx.now >= min(grant.deadline, attempt.deadline):
            if event.state == 'expired':
                # Commit a newly discovered expiry before returning the denial.
                return attempt, event, False
            _expired()
        tx.require_before(min(grant.deadline, attempt.deadline))
        if event.state != 'admitted':
            return attempt, event, False
        return attempt, tx.append(attempt, event, 'running', actor=principal), True

    def _publish(self, tx, attempt, enrolled, binding_valid, result):
        previous = tx.history(attempt)[-1]
        event = self._retire_if_inactive(tx, attempt, previous, enrolled)
        if event.state != 'running':
            return event.receipt(attempt)
        if not binding_valid:
            return tx.append(attempt, event, 'revoked').receipt(attempt)
        tx.require_before(attempt.deadline)
        if type(result) is int and result == 5:
            return tx.append(attempt, event, 'completed', actor=attempt.performer, result=result).receipt(attempt)
        return tx.append(attempt, event, 'failed', actor=attempt.performer, reason='operation_failed').receipt(attempt)

    def _cancel(self, tx, principal, enrolled, attempt_id):
        attempt = tx.find(attempt_id)
        if attempt is None:
            fail('denied')
        self._require_grant(tx, principal, Permission.CANCEL, attempt.scope)
        previous = tx.history(attempt)[-1]
        event = self._retire_if_inactive(tx, attempt, previous, enrolled)
        if event.state in TRANSITIONS:
            tx.require_before(attempt.deadline)
            event = tx.append(attempt, event, 'cancelled', actor=principal)
        return event.receipt(attempt)

    def _audit(self, tx, principal, attempt_id):
        attempt = tx.find(attempt_id)
        if attempt is None:
            fail('denied')
        self._require_grant(tx, principal, Permission.AUDIT, attempt.scope)
        events = tx.history(attempt)
        return dict(**events[-1].receipt(attempt), executor_id=attempt.scope.executor_id,
                    executor_revision=attempt.executor_revision, objective_id=attempt.scope.objective_id,
                    accepted_revision=attempt.scope.accepted_revision, operation=attempt.scope.operation,
                    authorizer=attempt.authorizer, performer=attempt.performer, request_id=attempt.request_id,
                    expires_unix_ms=int(attempt.deadline * 1000),
                    events=[dict(revision=event.revision, state=event.state, actor=event.actor,
                                 at_unix_ms=int(event.at * 1000), result=event.result, reason=event.reason)
                            for event in events])


class ExecutionLabBroker(RegistryLabBroker):
    versions = wire_versions = (REGISTRY_VERSION, VERSION)
    _registry_type = ExecutionRegistry

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        with self.access.identity_snapshot():
            self.registry.recover_execution()
        self.execution = Execution(self.registry, self.access)

    def audit_request(self, connection, version, method, outcome):
        # Both protocols keep separate durable domain histories.
        return None

    def handle_request(self, connection, version, method, params):
        if version == VERSION:
            if method == 'auth':
                self.clear(connection)
                return self.access.bind(connection, params)
            return self.execution.dispatch(connection, method, params)
        return super().handle_request(connection, version, method, params)


@contextmanager
def serve_execution_lab(root, verifiers, *, create=False, wall_clock=time, clock=monotonic):
    """Explicit local profile with no adapters, session routes, or installed service."""
    if not verifiers:
        raise ValueError('invalid_execution_verifiers')
    root = private_directory(Path(root), create=False)
    endpoint = root / 'execution-lab.sock'
    with directory_lock(root):
        broker = ExecutionLabBroker(Identities(), {}, os.getuid(), Journal(root), verifiers=verifiers,
                                    database=root / 'execution.sqlite3', wall_clock=wall_clock,
                                    clock=clock, grant_clock=wall_clock, create=create)
        with bound_listener(endpoint) as listener, Server(broker, listener, allow_owner=False):
            yield endpoint, broker
