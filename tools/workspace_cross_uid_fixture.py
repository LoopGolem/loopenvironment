# SPDX-License-Identifier: Apache-2.0
"""Fixed scenarios, process roles and instrumentation for D.2C.2."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import select
import socket
import stat
from threading import Event, Lock
from time import monotonic, time

from experiments.registry_operational import POLICY_FILE, PolicyPin, _prepared_registry, _serve_profile
from experiments.registry_lab import CREDENTIAL
from experiments.registry_rpc import OPAQUE_ID, VERSION as REGISTRY
from experiments.workspace_document import (CAPABILITY, FINAL, MAX_CONTENT, READ_FLAGS,
                                            DocumentCreate, enroll_workspace, resource_path, stage_name)
from experiments.workspace_effect_lab import (DATABASE, ENDPOINT, VERSION, WorkspaceBroker, WorkspaceEffects,
                                              initialize_workspace_database)
from experiments.workspace_effect_storage import Scope
from loopbridge.authority import fail
from loopbridge.broker import Server
from loopbridge.protocol import Fault, unique_object
from loopbridge.service_ingress import (ACCESS_ACL, CrossUIDIngress, PeerAdmission, bound_listener, named_user_acl,
                                       peer_identity)
from tools import registry_cross_uid as registry
from tools.registry_cross_uid import ADMIN, EXECUTOR, ISSUER, OBJECTIVE, OTHER, TARGET, require

WAIT = 8
VIRTUAL_START = 2_000_000_000
VIRTUAL_LIMIT = VIRTUAL_START + 1200
PROFILE = 'workspace-d2c2'
CONTENT = 'D.2C.2 synthetic workspace document.\n'
DIGEST = sha256(CONTENT.encode()).hexdigest()
DIVERGENT = 'D.2C.2 divergent synthetic document.\n'
OBJECTIVE_TEXT = 'D.2C.2 synthetic objective.'
PROBE_ENTRY = '.direct-access-probe'
CHALLENGE = 'peer-challenge.sock'
HEX = re.compile(r'[0-9a-f]{64}')


def opaque(number):
    return f'{number:032x}'


CONTROLLER, OBSERVER, AUDITOR = map(opaque, (71, 72, 73))
ACTORS = dict(admin=ADMIN, issuer=ISSUER, executor=EXECUTOR, controller=CONTROLLER,
              observer=OBSERVER, auditor=AUDITOR, other=OTHER)
GRANTS = ((ISSUER, 'authorize'), (EXECUTOR, 'perform'), (EXECUTOR, 'step'),
          (CONTROLLER, 'pause'), (CONTROLLER, 'cancel'), (CONTROLLER, 'continue'),
          (OBSERVER, 'status'), (AUDITOR, 'audit'))
CASE_NAMES = ('base', 'pre_pause', 'pre_cancel', 'pre_revoke', 'pre_replace', 'pre_expire',
              'post_pause', 'post_cancel', 'post_revoke', 'post_expire',
              'race_winner', 'race_loser', 'occupied', 'lost', 'd1', 'd2', 'd3', 'fresh')


@dataclass(frozen=True)
class Case:
    scope: Scope
    request: str
    gate: str | None


def build_cases():
    cases = {}
    for index, name in enumerate(CASE_NAMES, 1):
        resource = (cases['race_winner'].scope.resource_id if name in ('race_loser', 'occupied')
                    else opaque(100 + index))
        request = opaque(300 + index)
        gate = ('before' if name.startswith('pre_') or name in ('race_winner', 'race_loser', 'd2')
                else 'after' if name.startswith('post_') or name in ('lost', 'd1', 'd3') else None)
        cases[name] = Case(Scope(opaque(200 + index), TARGET, OBJECTIVE, 3, CAPABILITY, resource, DIGEST),
                           request, gate)
    return cases


CASES = build_cases()
RESOURCES = frozenset(case.scope.resource_id for case in CASES.values()) | {opaque(199)}
BY_ATTEMPT = {case.scope.attempt_id: name for name, case in CASES.items()}
NO_CALL = {'pre_cancel', 'pre_revoke', 'pre_replace', 'pre_expire', 'race_loser', 'occupied', 'd2'}
STATE_FIELDS = {'id', 'revision', 'state', 'supervision', 'effect'}
AUDIT_FIELDS = STATE_FIELDS | {'scope', 'operation_id', 'authorizer', 'performer', 'authorization_request_id',
                               'size', 'expires_unix_ms', 'events', 'next_after'}
EVENT_FIELDS = {'revision', 'at', 'actor', 'kind', 'state', 'supervision', 'effect', 'reason',
                'request_id', 'expected_revision'}


@dataclass(frozen=True)
class Layout(registry.Layout):
    @property
    def endpoint(self):
        return self.ingress / ENDPOINT

    @property
    def challenge(self):
        return self.root / 'challenge'


class Window:
    def __init__(self, wall_end, monotonic_end, *, wall=time, elapsed=monotonic):
        self.wall_end, self.monotonic_end = wall_end, monotonic_end
        self.wall, self.elapsed = wall, elapsed

    def remaining(self):
        return max(0, min(self.wall_end - self.wall(), self.monotonic_end - self.elapsed()))

    def budget(self):
        left = self.remaining()
        if left <= 0:
            raise EOFError('approval_expired')
        return min(WAIT, left)


class CapabilityClock:
    def __init__(self, window, restart):
        self.window = window
        self.utc = VIRTUAL_START + (10 if restart else 0)

    def __call__(self):
        self.window.budget()
        return self.utc


class Pipe:
    """Private, bounded, newline-framed control. The two roles get different pipes."""
    LIMIT = 32768

    def __init__(self, read_fd, write_fd, window):
        self.reader, self.writer, self.window = read_fd, write_fd, window
        self.pending = bytearray()

    def send(self, data):
        raw = json.dumps(data, sort_keys=True, allow_nan=False).encode() + b'\n'
        require(len(raw) <= self.LIMIT, 'control_frame_limit')
        deadline = monotonic() + self.window.budget()
        while raw:
            left = min(deadline - monotonic(), self.window.remaining())
            if left <= 0 or not select.select([], [self.writer], [], left)[1]:
                raise EOFError('control_write_timeout')
            raw = raw[os.write(self.writer, raw[:4096]):]

    def receive(self, *, idle=False):
        deadline = monotonic() + (self.window.remaining() if idle else self.window.budget())
        while b'\n' not in self.pending:
            left = min(deadline - monotonic(), self.window.remaining())
            if left <= 0 or not select.select([self.reader], [], [], left)[0]:
                raise EOFError('control_read_timeout')
            raw = os.read(self.reader, 4096)
            if not raw:
                raise EOFError('control_closed')
            self.pending.extend(raw)
            require(len(self.pending) <= self.LIMIT, 'control_frame_limit')
        raw, _, rest = self.pending.partition(b'\n')
        self.pending = bytearray(rest)
        self.window.budget()
        value = json.loads(raw, object_pairs_hook=unique_object)
        require(type(value) is dict, 'invalid_control_frame')
        return value

    def reply(self, **result):
        self.send(dict(ok=result))


class Instrumentation:
    def __init__(self, window):
        self.window = window
        self.arrived = {name: Event() for name in CASES}
        self.release = {name: Event() for name in CASES}
        self.finished = {name: Event() for name in CASES}
        self.stopping = Event()
        self.lock = Lock()
        self.operations = {}
        self.calls = {}
        self.links = {}
        self.untracked = 0
        self.peers = set()

    def wait(self, event):
        require(event.wait(self.window.budget()) and not self.stopping.is_set(), 'gate_not_reached')
        self.window.budget()

    def gate(self, name, edge):
        if name is None or CASES[name].gate != edge or self.release[name].is_set():
            return
        self.arrived[name].set()
        if not self.release[name].wait(self.window.budget()) or self.stopping.is_set():
            raise EOFError('gate_abandoned')
        self.window.budget()

    def track(self, attempt):
        name = BY_ATTEMPT.get(attempt.id)
        if name:
            with self.lock:
                require(self.operations.setdefault(attempt.operation_id, name) == name,
                        'operation_attribution_changed', result='no_go')
        return name

    def count(self, operation):
        with self.lock:
            if operation not in self.operations:
                self.untracked += 1
                raise ValueError('untracked_publication')
            self.calls[operation] = self.calls.get(operation, 0) + 1

    def linked(self, operation):
        with self.lock:
            self.links[operation] = self.links.get(operation, 0) + 1

    def snapshot(self):
        with self.lock:
            return dict(operations=dict(self.operations), calls=dict(self.calls), links=dict(self.links),
                        untracked=self.untracked, peers=sorted(self.peers))

    def abort(self):
        self.stopping.set()
        for gate in self.release.values():
            gate.set()


def instrumented_broker(proof):
    class Adapter(DocumentCreate):
        def prepare(self, resource, operation_id, data):
            proof.window.budget()
            return super().prepare(resource, operation_id, data)

        def synchronize(self, resource, fd):
            proof.window.budget()
            super().synchronize(resource, fd)

        def apply(self, resource, operation_id):
            # Count actual adapter calls. Neither gate runs between the final
            # capability clock sample and linkat under the authority mutex.
            proof.count(operation_id)
            proof.window.budget()
            super().apply(resource, operation_id)
            proof.linked(operation_id)

    class Effects(WorkspaceEffects):
        def _boundary(self, connection, attempt, driver, resource, version):
            proof.gate(proof.track(attempt), 'before')
            return super()._boundary(connection, attempt, driver, resource, version)

        def _inspect(self, attempt):
            if attempt.id in self._crossed:
                proof.gate(BY_ATTEMPT.get(attempt.id), 'after')
            proof.window.budget()
            return super()._inspect(attempt)

        def _publish(self, connection, attempt, driver):
            super()._publish(connection, attempt, driver)
            name = BY_ATTEMPT.get(attempt.id)
            if name:
                proof.finished[name].set()

    class Broker(WorkspaceBroker):
        def configure_workspace(self, root, resources):
            self.effects = Effects(self.registry, self.access, Adapter(root, resources))
            self.effects.recover()

        def serve_connection(self, sock, *, allow_owner=True):
            with proof.lock:
                proof.peers.add(peer_identity(sock))
            super().serve_connection(sock, allow_owner=allow_owner)

        def handle_request(self, connection, version, method, params):
            if proof.stopping.is_set() or not proof.window.remaining():
                fail('denied')
            return super().handle_request(connection, version, method, params)

    return Broker


def policy_bytes(verifiers):
    require(type(verifiers) is dict and verifiers.keys() == set(ACTORS.values())
            and all(type(item) is str and HEX.fullmatch(item) for item in verifiers.values()), 'invalid_verifiers')
    grants = [(ADMIN, 'executor.register'), (EXECUTOR, 'executor.confirm'),
              (EXECUTOR, 'objective.read'), (EXECUTOR, 'objective.respond'), (ISSUER, 'objective.author')]
    return json.dumps(dict(version=1, generation=1, principals=verifiers, retired_verifiers=[], grants=[
        dict(principal=actor, scope='registry.' + verb, executor=TARGET, expires_unix=VIRTUAL_LIMIT)
        for actor, verb in grants]), sort_keys=True, separators=(',', ':')).encode()


def pins_to_wire(db, resources, policy):
    return dict(database=asdict(db), resources=resources, policy=asdict(policy))


def pins_from_wire(value):
    require(type(value) is dict and value.keys() == {'database', 'resources', 'policy'}
            and value['resources'].keys() == RESOURCES, 'invalid_fixture_pins')
    db = registry.DatabasePin(**{name: tuple(pin) for name, pin in value['database'].items()})
    resources = {key: tuple(pin) for key, pin in value['resources'].items()}
    require(all(len(pin) == 2 and all(type(item) is int and item >= 0 for item in pin)
                for pin in resources.values()), 'invalid_resource_pins')
    return db, resources, PolicyPin(**value['policy'])


@contextmanager
def broker_service(layout, window, verifiers, original, *, desktop_uid, third_uid=None):
    proof = Instrumentation(window)
    clock = CapabilityClock(window, original is not None)
    raw = policy_bytes(verifiers)
    expected = PolicyPin(1, sha256(raw).hexdigest())
    if original is None:
        require(not any(layout.private.iterdir()), 'private_fixture_not_empty')
        resources = {resource: enroll_workspace(layout.private, resource) for resource in sorted(RESOURCES)}
        db = initialize_workspace_database(layout.private, wall_clock=clock)
        registry.publish_policy(layout.private, raw, initial=True)
    else:
        db, resources, pinned_policy = pins_from_wire(original)
        require(expected == pinned_policy, 'policy_pin_changed')
    for resource, pin in resources.items():
        with DocumentCreate(layout.private, resources).resource(resource, pin):
            pass
    service = os.geteuid()

    def configure(broker):
        broker.configure_workspace(layout.private, resources)

    broker_type = instrumented_broker(proof)
    if third_uid is not None:
        ingress = CrossUIDIngress(layout.ingress, layout.private, PeerAdmission(service, frozenset({desktop_uid})))
        profile = _serve_profile(ingress, db, expected, endpoint_name=ENDPOINT, database_name=DATABASE,
                                 wall_clock=clock, clock=monotonic, broker_type=broker_type, prepare=configure)
    else:
        @contextmanager
        def local():
            with _prepared_registry(layout.private, PeerAdmission.local_only(service), db, expected,
                                    wall_clock=clock, clock=monotonic, broker_type=broker_type,
                                    database_name=DATABASE) as (broker, control):
                configure(broker)
                with bound_listener(layout.endpoint) as listener, Server(broker, listener, allow_owner=False):
                    yield layout.endpoint, broker, control

        profile = local()

    with profile as (_, broker, _):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        fd = os.open(layout.private, flags)
        try:
            yield broker, clock, proof, pins_to_wire(db, resources, expected), fd
        finally:
            proof.abort()
            os.close(fd)


@contextmanager
def challenge_listener(layout, broker, third_uid):
    path = layout.challenge / CHALLENGE

    def prepare(endpoint):
        os.setxattr(endpoint, ACCESS_ACL, named_user_acl(third_uid, 6, 2), follow_symlinks=False)

    with bound_listener(path, prepare) as listener, Server(broker, listener, allow_owner=False):
        yield


def grant_case(broker, clock, name, mode):
    scope = CASES[name].scope
    if mode == 'wrong_performer' and name == 'base':
        entries = ((ISSUER, 'authorize'), (OTHER, 'perform'))
    elif mode == 'wrong_revision' and name == 'base':
        scope = replace(scope, accepted_revision=2)
        entries = GRANTS[:2]
    elif mode == 'all':
        if name == 'base':
            broker.effects.revoke(OTHER, 'perform', scope)
        entries = GRANTS
    elif mode == 'status' and name in ('d1', 'd2', 'd3'):
        entries = ((OBSERVER, 'status'),)
    elif mode == 'audit' and name in ('d1', 'd2', 'd3'):
        entries = ((AUDITOR, 'audit'),)
    elif mode == 'receipt' and name in ('d1', 'd2', 'd3'):
        entries = ((EXECUTOR, 'step'),)
    elif mode == 'old_identity' and name == 'fresh':
        old = CASES['d1'].scope
        scope = Scope(old.attempt_id, scope.executor_id, scope.objective_id, scope.accepted_revision,
                      scope.capability, scope.resource_id, scope.digest)
        entries = GRANTS[:2]
    else:
        raise ValueError('invalid_grant_command')
    for actor, permission in entries:
        deadline = clock.utc + 1 if name.endswith('_expire') and permission == 'perform' else VIRTUAL_LIMIT
        broker.effects.grant(actor, permission, scope, expires_at=deadline)


def serve_control(layout, channel, window, desktop_uid, third_uid, startup):
    require(startup.keys() == {'verifiers', 'pins'}, 'invalid_service_bootstrap')
    with broker_service(layout, window, startup['verifiers'], startup['pins'],
                        desktop_uid=desktop_uid, third_uid=third_uid) as (broker, clock, proof, pins, fd):
        channel.reply(pins=pins, private_fd=fd, proof=proof.snapshot())
        challenge = None
        try:
            while True:
                command = channel.receive(idle=True)
                op, name, value = admin_command(command)
                if op == 'stop':
                    channel.reply(proof=proof.snapshot())
                    return
                if op == 'challenge_begin':
                    require(challenge is None and third_uid is not None, 'invalid_challenge_state')
                    candidate = challenge_listener(layout, broker, third_uid)
                    candidate.__enter__()
                    challenge = candidate
                elif op == 'challenge_end':
                    require(challenge is not None, 'invalid_challenge_state')
                    challenge.__exit__(None, None, None)
                    challenge = None
                elif op == 'grant':
                    grant_case(broker, clock, name, value)
                elif op == 'arrived':
                    proof.wait(proof.arrived[name])
                elif op == 'released':
                    require(proof.arrived[name].is_set(), 'gate_not_reached')
                    proof.release[name].set()
                elif op == 'finished':
                    proof.wait(proof.finished[name])
                elif op == 'authority':
                    require(proof.arrived[name].is_set() and not proof.release[name].is_set(),
                            'authority_change_outside_gate')
                    scope = CASES[name].scope
                    if name.endswith('_revoke'):
                        broker.effects.revoke(EXECUTOR, 'perform', scope)
                    elif name == 'pre_replace':
                        broker.effects.grant(EXECUTOR, 'perform', scope, expires_at=VIRTUAL_LIMIT)
                    else:
                        with broker.access.identity_snapshot():
                            clock.utc += 1
                channel.reply(proof=proof.snapshot(), virtual_utc=clock.utc)
        finally:
            if challenge is not None:
                challenge.__exit__(None, None, None)


def admin_command(command):
    op = command.get('op')
    if command.keys() == {'op'} and op in ('stop', 'snapshot', 'challenge_begin', 'challenge_end'):
        return op, None, None
    name = command.get('case')
    require(type(name) is str and name in CASES, 'invalid_admin_case')
    if op == 'grant' and command.keys() == {'op', 'case', 'mode'}:
        return op, name, command['mode']
    if command.keys() == {'op', 'case'}:
        if op in ('arrived', 'released', 'finished') and CASES[name].gate:
            return op, name, None
        if op == 'authority' and name in ('pre_revoke', 'pre_replace', 'pre_expire', 'post_revoke', 'post_expire'):
            return op, name, None
    raise ValueError('invalid_admin_command')


def request(name, action, revision, number, variant):
    spec = CASES[name]
    if action == 'authorize':
        params = asdict(spec.scope)
        del params['digest']
        params.update(content=CONTENT, request_id=spec.request, ttl_seconds=240)
        changes = {
            'exact': {}, 'resource': {'resource_id': opaque(199)}, 'revision': {'accepted_revision': 2},
            'attempt': {'attempt_id': opaque(299)}, 'capability': {'capability': 'workspace.document.edit'},
            'payload': {'content': DIVERGENT}, 'executor': {'executor_id': opaque(98)},
            'old_attempt': {'attempt_id': CASES['d1'].scope.attempt_id},
            'old_request': {'request_id': CASES['d1'].request},
        }
        require(variant in changes and (not variant.startswith('old_') or name == 'fresh'), 'invalid_scope_variant')
        return params | changes[variant]
    require(variant == 'exact', 'invalid_scope_variant')
    params = {'attempt_id': spec.scope.attempt_id}
    if action == 'audit':
        params['after_revision'] = revision
    elif action not in ('status', 'audit'):
        params.update(expected_revision=revision, request_id=opaque(900 + number))
    return params


ROLE_ACTIONS = dict(issuer={'authorize'}, executor={'step', 'continue', 'authorize'}, controller={'pause', 'cancel', 'continue'},
                    observer={'status', 'audit', 'step', 'pause', 'cancel', 'continue'},
                    auditor={'audit', 'status', 'step', 'pause', 'cancel', 'continue'}, other={'authorize'})


def validate_rpc_command(role, command):
    name, action = command.get('case'), command.get('action')
    require(command.keys() == {'op', 'case', 'action', 'revision', 'number', 'variant'}
            and command['op'] in ('rpc', 'send_only')
            and type(name) is str and name in CASES and type(action) is str
            and action in ROLE_ACTIONS.get(role, set())
            and type(command['revision']) is int and 0 <= command['revision'] <= 64
            and type(command['number']) is int and 0 <= command['number'] <= 32
            and type(command['variant']) is str, 'invalid_rpc_command')
    require(command['op'] != 'send_only' or (role, name, action) == ('executor', 'lost', 'step'),
            'invalid_lost_reply_command')
    return f'effect.{action}', request(name, action, command['revision'], command['number'], command['variant'])


def connect(layout, peer, window, *, version=VERSION):
    return registry.connect(layout, tuple(peer[1:]), peer[0], timeout=window.budget(), version=version)


def registry_stage(layout, peer, window, role, token, op):
    with connect(layout, peer, window, version=REGISTRY) as rpc:
        registry.authenticate(rpc, token, ACTORS[role])
        if (role, op) == ('admin', 'register'):
            result = rpc.call('executor.register', executor_id=TARGET, bound_principal_id=EXECUTOR,
                              label='D.2C.2 synthetic executor', request_id=opaque(17))
            require(result == dict(id=TARGET, state='pending', revision=1), 'registration_failed')
        elif (role, op) == ('executor', 'confirm'):
            result = rpc.call('executor.confirm', executor_id=TARGET, expected_revision=1, request_id=opaque(18))
            require(result == dict(id=TARGET, state='available', revision=2), 'confirmation_failed')
        elif (role, op) == ('issuer', 'offer'):
            result = rpc.call('objective.create', objective_id=OBJECTIVE, executor_id=TARGET,
                              text=OBJECTIVE_TEXT, ttl_seconds=900, request_id=opaque(19))
            require(result == dict(id=OBJECTIVE, state='created', revision=1), 'objective_creation_failed')
            result = rpc.call('objective.offer', objective_id=OBJECTIVE, expected_revision=1, request_id=opaque(20))
            require(result == dict(id=OBJECTIVE, state='offered', revision=2), 'offer_failed')
        elif (role, op) == ('executor', 'accept'):
            require(rpc.call('objective.respond', **registry.ANSWER) == registry.EXPECT_RECEIPT, 'acceptance_failed')
        else:
            raise ValueError('invalid_registry_command')


def denied(check, operation):
    try:
        operation()
    except OSError as error:
        require(error.errno in registry.DENIALS, check)
        return error.errno
    raise registry.QualificationError(check, 'no_go')


def access_probes(layout, case, edge, operation_id, private_fd, peer):
    path = resource_path(layout.private, CASES[case].scope.resource_id)
    probes = {
        'private_traversal': lambda: os.stat(layout.private / DATABASE),
        'private_listing': lambda: os.listdir(layout.private),
        'resource_traversal': lambda: os.stat(os.fspath(path) + '/.'),
        'resource_listing': lambda: os.listdir(path),
        'sqlite_read': lambda: registry.open_readonly(layout.private / DATABASE),
        'policy_read': lambda: registry.open_readonly(layout.private / POLICY_FILE),
        'proc_private_descriptor': lambda: registry.open_readonly(Path(f'/proc/{peer[0]}/fd/{private_fd}')),
    }
    if edge in ('staged', 'published', 'restart', 'restart_staged'):
        stage = path / stage_name(operation_id)
        probes['staged_file_read'] = lambda: registry.open_readonly(stage)
    if edge in ('staged', 'restart_staged'):
        probes['direct_document_create'] = lambda: create_probe(path / FINAL)
    if edge in ('published', 'restart'):
        probes.update(final_read=lambda: registry.open_readonly(path / FINAL),
                      final_open_write=lambda: os.close(os.open(path / FINAL, os.O_WRONLY | os.O_NOFOLLOW)))
    if edge in ('published', 'restart'):
        probes['additional_entry_create'] = lambda: create_probe(path / PROBE_ENTRY)
    return {name: denied(name, operation) for name, operation in probes.items()}


def create_probe(path):
    os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))


def desktop_control(layout, channel, window, role, startup, *, real):
    require(startup.keys() == {'token', 'peer', 'private_fd'}
            and type(startup['token']) is str and CREDENTIAL.fullmatch(startup['token']),
            'invalid_client_bootstrap')
    token, peer, private_fd = (startup[key] for key in ('token', 'peer', 'private_fd'))
    pending = None
    try:
        while True:
            command = channel.receive(idle=True)
            op = command.get('op')
            if command.keys() == {'op'} and op == 'stop':
                channel.reply()
                return
            if command.keys() == {'op'} and op == 'discard':
                require(pending is not None and role == 'executor', 'missing_pending_reply')
                pending.__exit__(None, None, None)
                pending = None
                channel.reply(discarded=True)
                continue
            require(pending is None, 'pending_reply_not_discarded')
            if command.keys() == {'op'} and op in ('register', 'confirm', 'offer', 'accept'):
                registry_stage(layout, peer, window, role, token, op)
                channel.reply()
            elif command.keys() == {'op'} and op == 'authenticate':
                with connect(layout, peer, window) as rpc:
                    if role == 'invalid':
                        registry.denied_rpc(rpc, 'auth', credential=token)
                    else:
                        registry.authenticate(rpc, token, ACTORS[role])
                channel.reply(broker_peer=peer, uid=os.geteuid(), ancillary=False)
            elif command.keys() == {'op'} and role == 'third' and op == 'third' and real:
                result = denied('non_admitted_uid_nominal_acl', lambda: registry.connect_sentinel(layout.endpoint))
                alternate = Endpoint(layout.challenge / CHALLENGE)
                with connect(alternate, peer, window) as rpc:
                    registry.denied_rpc(rpc, 'auth', credential=token)
                channel.reply(nominal_errno=result, rpc_code=-32001)
            elif op == 'direct' and role == 'executor' and real:
                require(command.keys() == {'op', 'case', 'edge', 'operation'}
                        and (command['case'], command['edge']) in (
                            ('base', 'staged'), ('base', 'published'), ('d1', 'restart'), ('d2', 'restart_staged'))
                        and type(command['operation']) is str and OPAQUE_ID.fullmatch(command['operation']),
                        'invalid_direct_probe')
                observed = access_probes(layout, command['case'], command['edge'], command['operation'],
                                         private_fd, peer)
                channel.reply(denials=observed)
            else:
                method, params = validate_rpc_command(role, command)
                if op == 'send_only':
                    candidate = connect(layout, peer, window)
                    rpc = candidate.__enter__()
                    pending = candidate
                    registry.authenticate(rpc, token, ACTORS[role])
                    rpc.channel.send(dict(jsonrpc='2.0', version=VERSION, id=rpc.seq + 1,
                                          method=method, params=params))
                    channel.reply(sent=True)
                else:
                    with connect(layout, peer, window) as rpc:
                        registry.authenticate(rpc, token, ACTORS[role])
                        try:
                            result = rpc.call(method, **params)
                        except EOFError:
                            channel.reply(transport_interrupted='eof')
                        except ConnectionResetError:
                            channel.reply(transport_interrupted='reset')
                        except Fault as error:
                            channel.reply(fault=[error.code, error.message, error.data])
                        else:
                            channel.reply(result=result)
    finally:
        if pending is not None:
            pending.__exit__(None, None, None)


@dataclass(frozen=True)
class Endpoint:
    endpoint: Path
