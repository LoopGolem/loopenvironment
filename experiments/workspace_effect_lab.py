# SPDX-License-Identifier: Apache-2.0
"""Opt-in LoopBridge supervision and recovery for one mediated filesystem effect."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
import os
from secrets import token_hex
from time import monotonic, time

from experiments.durable_objective_registry import _valid_wall
from experiments.objective_registry import Error, RegistryError
from experiments.registry_lab import RegistryLabBroker
from experiments.registry_operational import _prepared_registry, _serve_profile
from experiments.registry_rpc import ERROR_CODES, OPAQUE_ID, RegistryRequest, VERSION as REGISTRY, _integer, _matches
from experiments.registry_storage import _initialize_database
from experiments.workspace_document import (CAPABILITY, DestinationExists, DocumentCreate, Observation,
                                            ResourceConflict, valid_pin)
from experiments.workspace_effect_storage import AUDIT_PAGE, MAX_TTL, OPEN, Attempt, Scope, WorkspaceRegistry
from loopbridge.authority import fail
from loopbridge.broker import Server
from loopbridge.service_ingress import CrossUIDIngress, PeerAdmission, bound_listener

VERSION = 'workspace-effect/1'
DATABASE = 'workspace-effect.sqlite3'
ENDPOINT = 'workspace-effect.sock'
MAX_RESOURCES = 64
MAX_GRANTS = 1024
REVISION_MAX = 2**53 - 1
COMMANDS = frozenset(('step', 'continue', 'pause', 'cancel'))
ADVANCE = frozenset(('step', 'continue'))
PERMISSIONS = COMMANDS | {'authorize', 'perform', 'status', 'audit'}
SCOPE_FIELDS = {'attempt_id', 'executor_id', 'objective_id', 'accepted_revision', 'capability', 'resource_id'}
SCHEMA = {
    'effect.authorize': SCOPE_FIELDS | {'request_id', 'ttl_seconds', 'content'},
    'effect.status': {'attempt_id'},
    'effect.audit': {'attempt_id', 'after_revision'},
    **{f'effect.{command}': {'attempt_id', 'expected_revision', 'request_id'} for command in COMMANDS},
}


def _validate(method, params):
    if method not in SCHEMA:
        fail('method_not_found', -32601)
    if params.keys() != SCHEMA[method]:
        fail('invalid_params', -32602)
    for name, value in params.items():
        if name == 'content':
            continue
        if name == 'capability':
            valid = type(value) is str and value == CAPABILITY
        elif name == 'ttl_seconds':
            valid = _integer(value, MAX_TTL)
        elif name == 'after_revision':
            valid = type(value) is int and 0 <= value <= REVISION_MAX
        elif name.endswith('_revision'):
            valid = _integer(value, REVISION_MAX)
        else:
            valid = _matches(OPAQUE_ID, value)
        if not valid:
            fail('invalid_params', -32602)


@dataclass(frozen=True)
class Grant:
    generation: str
    deadline: float


@dataclass(frozen=True)
class Driver:
    actor: str
    action: str
    grant: Grant


class WorkspaceEffects:
    def __init__(self, registry, access, adapter):
        self.registry, self.access, self.adapter = registry, access, adapter
        self._grants = {}
        self._payloads = {}
        self._drivers = {}
        self._crossed = set()

    def grant(self, principal, permission, scope, *, expires_at):
        """Trusted, process-local provisioning. Replacement always fences the old generation."""
        if type(scope) is not Scope or permission not in PERMISSIONS or not _valid_wall(expires_at):
            raise ValueError('invalid_workspace_grant')
        _validate('effect.authorize', dict(attempt_id=scope.attempt_id, executor_id=scope.executor_id,
                                          objective_id=scope.objective_id, accepted_revision=scope.accepted_revision,
                                          capability=scope.capability, resource_id=scope.resource_id,
                                          request_id=scope.attempt_id, ttl_seconds=1, content=None))
        if (type(scope.digest) is not str or len(scope.digest) != 64
                or not all(char in '0123456789abcdef' for char in scope.digest)
                or scope.resource_id not in self.adapter.resources):
            raise ValueError('invalid_workspace_grant')
        key = principal, permission, scope
        with self.access.identity_snapshot() as (_, enrolled):
            if not enrolled(principal) or (key not in self._grants and len(self._grants) >= MAX_GRANTS):
                raise ValueError('invalid_workspace_grant')
            self._grants[key] = Grant(token_hex(16), expires_at)

    def revoke(self, principal, permission, scope):
        with self.access.identity_snapshot():
            self._grants.pop((principal, permission, scope), None)

    def _grant(self, tx, principal, permission, scope):
        grant = self._grants.get((principal, permission, scope))
        if grant is None:
            fail('denied')
        if tx.now >= grant.deadline:
            fail('authorization_expired', -32060)
        tx.deadline = min(tx.deadline, grant.deadline)
        return grant

    def dispatch(self, connection, method, params):
        _validate(method, params)
        command = method.removeprefix('effect.')
        try:
            if command == 'authorize':
                return self._admit(connection, params)
            attempt_id = params['attempt_id']
            if command in ('status', 'audit'):
                return self._observe(connection, command, attempt_id, params.get('after_revision'))
            receipt, driver = self._command(connection, command, attempt_id, params)
            if driver is not None:
                self._work(connection, attempt_id, driver)
            return receipt
        except RegistryError as error:
            if error.code is Error.EXPIRED:
                fail('authorization_expired', -32060)
            code, message = ERROR_CODES[error.code]
            fail(message, code)

    def _admit(self, connection, params):
        data = self.adapter.validate_request(params['content'])
        scope = Scope(params['attempt_id'], params['executor_id'], params['objective_id'], params['accepted_revision'],
                      params['capability'], params['resource_id'], sha256(data).hexdigest())
        request_id, ttl = params['request_id'], params['ttl_seconds']
        with self.access.identity_snapshot() as (_, enrolled):
            actor = self.access._verify(RegistryRequest(connection, params['content'], None))
            if actor is None:
                fail('denied')
            with self.registry.workspace_transaction() as tx:
                authorizer = self._grant(tx, actor, 'authorize', scope)
                target = tx.target(scope.objective_id)
                if (target is None or target.executor_id != scope.executor_id or not enrolled(target.principal)
                        or target.executor_state != 'available' or target.objective_state != 'accepted'
                        or target.objective_revision != scope.accepted_revision):
                    fail('denied')
                performer = self._grant(tx, target.principal, 'perform', scope)
                tx.deadline = min(tx.deadline, target.deadline)
                old = tx.find_request(actor, request_id)
                if old is not None:
                    if (old.scope, old.ttl_seconds, old.size) != (scope, ttl, len(data)):
                        fail('request_conflict', -32044)
                    return tx.history(old, 0)[0].receipt(old)
                if tx.find(scope.attempt_id) is not None:
                    fail('request_conflict', -32044)
                try:
                    with self.adapter.resource(scope.resource_id) as resource:
                        self.adapter.require_vacant(resource)
                        pin = resource.identity
                except DestinationExists:
                    fail('destination_exists', -32061)
                except (ResourceConflict, RegistryError, OSError):
                    fail('resource_unavailable', -32062)
                deadline = min(tx.deadline, tx.now + ttl)
                tx.deadline = deadline
                attempt = Attempt(scope, token_hex(16), actor, target.principal, target.executor_revision,
                                  request_id, ttl, deadline, authorizer.generation, performer.generation,
                                  *pin, len(data))
                receipt = tx.admit(attempt).receipt(attempt)
            self._payloads[attempt.id] = data
            return receipt

    @staticmethod
    def _lookup(tx, bound, connection, attempt_id):
        actor = bound(connection)
        attempt = tx.find(attempt_id) if actor is not None else None
        if attempt is None:
            fail('denied')
        return actor, attempt

    def _observe(self, connection, permission, attempt_id, after):
        with self.access.identity_snapshot() as (bound, _), self.registry.workspace_transaction(write=False) as tx:
            actor, attempt = self._lookup(tx, bound, connection, attempt_id)
            self._grant(tx, actor, permission, attempt.scope)
            event = tx.latest(attempt)
            view = dict(id=attempt_id, revision=event.revision, state=event.state,
                        supervision=event.supervision, effect=event.effect)
            if permission == 'audit':
                events = tx.history(attempt, after)
                view.update(scope=asdict(attempt.scope), operation_id=attempt.operation_id,
                            authorizer=attempt.authorizer, performer=attempt.performer,
                            authorization_request_id=attempt.request_id, size=attempt.size,
                            expires_unix_ms=int(attempt.deadline * 1000),
                            events=[asdict(row) for row in events],
                            next_after=events[-1].revision if len(events) == AUDIT_PAGE
                            and events[-1].revision < event.revision else None)
            if tx.sample() >= tx.deadline:
                fail('authorization_expired', -32060)
            return view

    def _command(self, connection, action, attempt_id, params):
        with self.access.identity_snapshot() as (bound, _):
            with self.registry.workspace_transaction() as tx:
                actor, attempt = self._lookup(tx, bound, connection, attempt_id)
                grant = self._grant(tx, actor, action, attempt.scope)
                request_id, revision = params['request_id'], params['expected_revision']
                old = tx.command(attempt, actor, request_id)
                if old is not None:
                    if (old.kind, old.expected_revision) != (action, revision):
                        fail('request_conflict', -32044)
                    return old.receipt(attempt), None
                previous = tx.latest(attempt)
                if revision != previous.revision:
                    fail('stale_revision', -32040)
                if previous.state not in OPEN:
                    fail('invalid_state', -32043)
                if attempt.id in self._crossed:
                    fail('effect_boundary_closed', -32063)
                state, mode, effect = previous.state, previous.supervision, previous.effect
                if action in ADVANCE:
                    if state not in ('ready', 'prepared') or mode != 'paused' or attempt.id in self._drivers:
                        fail('invalid_state', -32043)
                    mode = 'stepping' if action == 'step' else 'flowing'
                elif action == 'cancel':
                    state, mode, effect = 'cancelled', 'stopped', 'absent'
                elif state == 'preparing':
                    mode = 'pause_requested'
                else:
                    state = 'prepared' if state == 'dispatched' else state
                    mode, effect = 'paused', 'none'
                tx.check_command_capacity(attempt, action)
                event = tx.event(attempt, previous, action, state, actor=actor, supervision=mode, effect=effect,
                                 request_id=request_id, expected_revision=revision)
            driver = None
            if action in ADVANCE:
                driver = self._drivers[attempt.id] = Driver(actor, action, grant)
            if action == 'cancel':
                self._payloads.pop(attempt.id, None)
            return event.receipt(attempt), driver

    def _blocked(self, tx, attempt, driver, connection, bound, enrolled):
        """Decide eligibility anew. The final wall-clock sample follows the resource checks."""
        auth = self._grants.get((attempt.authorizer, 'authorize', attempt.scope))
        perform = self._grants.get((attempt.performer, 'perform', attempt.scope))
        advance = self._grants.get((driver.actor, driver.action, attempt.scope))
        target = tx.target(attempt.scope.objective_id)
        if (bound(connection) != driver.actor or not connection.alive()
                or not enrolled(attempt.authorizer) or not enrolled(attempt.performer)
                or auth is None or auth.generation != attempt.authorizer_generation
                or perform is None or perform.generation != attempt.performer_generation or advance != driver.grant):
            return 'revoked'
        if (target is None or (target.executor_id, target.principal, target.executor_state, target.executor_revision,
                               target.objective_state, target.objective_revision)
                != (attempt.scope.executor_id, attempt.performer, 'available', attempt.executor_revision,
                    'accepted', attempt.scope.accepted_revision)):
            return 'revoked'
        if tx.sample() >= min(auth.deadline, perform.deadline, advance.deadline, attempt.deadline, target.deadline):
            return 'expired'
        return None

    def _claim(self, connection, attempt_id, driver):
        with self.access.identity_snapshot() as (bound, enrolled), self.registry.workspace_transaction() as tx:
            attempt = tx.find(attempt_id)
            current = tx.latest(attempt)
            if current.state not in ('ready', 'prepared') or current.supervision not in ('stepping', 'flowing'):
                return None
            blocked = self._blocked(tx, attempt, driver, connection, bound, enrolled)
            if blocked:
                tx.event(attempt, current, blocked, blocked, reason='authority_before_effect')
                self._payloads.pop(attempt.id, None)
                return None
            preparing = current.state == 'ready'
            state = 'preparing' if preparing else 'dispatched'
            tx.event(attempt, current, state, state, actor=driver.actor, supervision=current.supervision,
                     effect='none' if preparing else 'pending')
            return attempt, preparing

    def _work(self, connection, attempt_id, driver):
        try:
            claimed = self._claim(connection, attempt_id, driver)
            if claimed is None:
                return
            attempt, preparing = claimed
            if preparing:
                if not self._prepare(connection, attempt, driver):
                    return
                claimed = self._claim(connection, attempt_id, driver)
                if claimed is None:
                    return
                attempt, _ = claimed
            self._publish(connection, attempt, driver)
        finally:
            with self.access.identity_snapshot():
                self._drivers.pop(attempt_id)

    def _prepare(self, connection, attempt, driver):
        with self.access.identity_snapshot():
            data = self._payloads.pop(attempt.id, None)
        if data is None:
            self._fail_before(attempt, 'preparing', 'failed', 'payload_unavailable')
            return False
        try:
            with self.adapter.resource(attempt.scope.resource_id, attempt.resource_pin) as resource:
                pin = self.adapter.prepare(resource, attempt.operation_id, data)
        except DestinationExists:
            self._fail_before(attempt, 'preparing', 'failed', 'destination_exists')
            return False
        except (ResourceConflict, RegistryError, OSError):
            self._fail_before(attempt, 'preparing', 'failed', 'preparation_failed')
            return False
        with self.access.identity_snapshot() as (bound, enrolled), self.registry.workspace_transaction() as tx:
            current = tx.latest(attempt)
            if current.state != 'preparing':
                return False
            blocked = self._blocked(tx, attempt, driver, connection, bound, enrolled)
            if blocked:
                tx.event(attempt, current, blocked, blocked, reason='authority_before_effect')
                return False
            paused = current.supervision != 'flowing'
            tx.prepared(attempt, pin)
            tx.event(attempt, current, 'prepared', 'prepared', supervision='paused' if paused else 'flowing',
                     effect='none')
            return not paused

    def _fail_before(self, attempt, phase, state, reason):
        with self.access.identity_snapshot(), self.registry.workspace_transaction() as tx:
            current = tx.latest(attempt)
            if current.state == phase:
                tx.event(attempt, current, state, state, reason=reason)

    def _publish(self, connection, attempt, driver):
        try:
            with self.adapter.resource(attempt.scope.resource_id, attempt.resource_pin) as resource:
                version = self.adapter.validate_staged_payload(resource, attempt.operation_id, attempt.stage_pin,
                                                               attempt.size, attempt.scope.digest)
                blocked, apply_error = self._boundary(connection, attempt, driver, resource, version)
        except DestinationExists:
            self._fail_before(attempt, 'dispatched', 'failed', 'destination_exists')
            return
        except (ResourceConflict, OSError):
            self._fail_before(attempt, 'dispatched', 'failed', 'resource_unavailable')
            return
        if blocked:
            if blocked != 'stopped':
                self._fail_before(attempt, 'dispatched', blocked, 'authority_before_effect')
            return
        conflict = apply_error == 'destination_exists'
        observed = None if conflict else self._inspect(attempt)
        with self.access.identity_snapshot():
            with self.registry.workspace_transaction() as tx:
                current = tx.latest(attempt)
                if conflict:
                    tx.event(attempt, current, 'failed', 'failed', reason='destination_exists')
                else:
                    self._finish_effect(tx, attempt, current, observed, apply_error=apply_error)
            self._crossed.remove(attempt.id)

    def _boundary(self, connection, attempt, driver, resource, version):
        with self.access.identity_snapshot() as (bound, enrolled), \
                self.registry.workspace_transaction(write=False) as tx:
            if tx.latest(attempt).state != 'dispatched':
                return 'stopped', None
            self.adapter.validate_publication(resource, attempt.operation_id, attempt.stage_pin, attempt.size, version)
            tx.check_storage()
            blocked = self._blocked(tx, attempt, driver, connection, bound, enrolled)
            if blocked:
                return blocked, None
            # The policy mutex still excludes Registry changes, grant changes and
            # control commands. No sync, hashing or external worker occupies it.
            self._crossed.add(attempt.id)
            try:
                self.adapter.apply(resource, attempt.operation_id)
            except FileExistsError:
                return None, 'destination_exists'
            except OSError:
                return None, 'publication_error'
            return None, None

    def _inspect(self, attempt):
        try:
            with self.adapter.resource(attempt.scope.resource_id, attempt.resource_pin) as resource:
                return self.adapter.inspect(resource, attempt.operation_id, attempt.stage_pin,
                                            attempt.size, attempt.scope.digest)
        except (ResourceConflict, RegistryError, OSError):
            return Observation('unavailable')

    @staticmethod
    def _finish_effect(tx, attempt, previous, observed, *, apply_error=None, recovering=False):
        matched = observed.evidence == 'matching'
        if apply_error and not matched:
            previous = tx.event(attempt, previous, 'publication_error', previous.state, effect='pending')
        if matched:
            previous = tx.event(attempt, previous, 'effect_observed', previous.state,
                                effect='observed', reason=apply_error)
        if observed.synchronized:
            state = 'reconciled' if recovering else 'completed'
            tx.event(attempt, previous, state, state, effect='confirmed')
        else:
            reason = 'sync_unconfirmed' if matched else observed.evidence
            tx.event(attempt, previous, 'recovery_uncertain' if recovering else 'uncertain', 'uncertain',
                     effect='observed' if matched else 'unknown', reason=reason)

    def recover(self):
        """Before ingress opens. Inspect or synchronize evidence, never apply an operation."""
        with self.registry.workspace_transaction(write=False) as tx:
            pending = [(attempt, tx.latest(attempt)) for attempt in tx.attempts()]
        for attempt, current in pending:
            if current.state in ('dispatched', 'uncertain'):
                observed = self._inspect(attempt)
                if current.state == 'uncertain' and not observed.synchronized:
                    continue  # Retain the prior uncertainty and its evidence.
                with self.registry.workspace_transaction() as tx:
                    self._finish_effect(tx, attempt, current, observed, recovering=True)
            elif current.state in OPEN:
                with self.registry.workspace_transaction() as tx:
                    tx.event(attempt, current, 'interrupted', 'interrupted', reason='before_dispatch')


class WorkspaceBroker(RegistryLabBroker):
    versions = wire_versions = (REGISTRY, VERSION)
    _registry_type = WorkspaceRegistry

    def configure_workspace(self, root, resources):
        self.effects = WorkspaceEffects(self.registry, self.access, DocumentCreate(root, resources))
        self.effects.recover()

    def audit_request(self, connection, version, method, outcome):
        # The workspace ledger contains bounded, sanitized decisions.
        pass

    def handle_request(self, connection, version, method, params):
        if version == VERSION and method != 'auth':
            self.access.require(connection)
            return self.effects.dispatch(connection, method, params)
        return super().handle_request(connection, REGISTRY, method, params)


def initialize_workspace_database(root, *, wall_clock=time):
    return _initialize_database(root, DATABASE, WorkspaceRegistry, wall_clock)


@contextmanager
def serve_workspace(root, *, resources, database_pin, policy_pin, ingress=None,
                    wall_clock=time, clock=monotonic):
    """Profile with pinned storage and explicit local or preprovisioned cross-UID ingress."""
    if (not 1 <= len(resources) <= MAX_RESOURCES
            or any(not _matches(OPAQUE_ID, key) or not valid_pin(pin) for key, pin in resources.items())):
        raise ValueError('invalid_workspace_resources')

    def configure(broker):
        broker.configure_workspace(root, resources)

    if ingress is not None:
        if type(ingress) is not CrossUIDIngress or ingress.private_root != root:
            raise ValueError('invalid_workspace_ingress')
        with _serve_profile(ingress, database_pin, policy_pin, endpoint_name=ENDPOINT,
                            database_name=DATABASE, broker_type=WorkspaceBroker, prepare=configure,
                            wall_clock=wall_clock, clock=clock) as (endpoint, broker, control):
            yield endpoint, broker.effects, control
    else:
        endpoint = root / ENDPOINT
        with _prepared_registry(root, PeerAdmission.local_only(os.geteuid()), database_pin, policy_pin,
                                wall_clock=wall_clock, clock=clock, broker_type=WorkspaceBroker,
                                database_name=DATABASE) as (broker, control):
            configure(broker)
            with bound_listener(endpoint) as listener, Server(broker, listener, allow_owner=False):
                yield endpoint, broker.effects, control
