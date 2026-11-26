# SPDX-License-Identifier: Apache-2.0
"""Prepare or exercise the explicitly approved D.2B.1 disposable cross-UID fixture."""
from argparse import ArgumentParser
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
from hmac import digest
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
from threading import Event, Lock
from time import monotonic, time

from experiments.execution_lab import Permission, Scope
from experiments.objective_registry import Error, RegistryError
from experiments.registry_operational import POLICY_FILE, PolicyPin
from experiments.registry_rpc import OPAQUE_ID
from experiments.supervision_lab import SupervisedExecution, SupervisionLabBroker, SupervisionPermission as Control
from experiments.supervision_operational import DATABASE, ENDPOINT, _serve_supervision, initialize_supervision_database
from experiments.supervision_storage import PLAN, SupervisionRegistry
from loopbridge.authority import fail
from loopbridge.protocol import Fault, unique_object
from loopbridge.service_ingress import CrossUIDIngress, PeerAdmission, named_user_acl, read_acl
from tools import registry_cross_uid as registry
from tools.registry_cross_uid import (EXECUTOR, ISSUER, OBJECTIVE, OTHER, TARGET, ControlInput, QualificationError,
                                      authenticate, check_denied, check_layout, check_metadata,
                                      check_process, connect, connect_sentinel, denied_rpc, emit, open_readonly,
                                      parse_pin, publish_policy, require, sentinel_resources, serialize_pin)
from tools.supervision_cross_uid_flow import (AUDITOR, CASE_IDS, CASE_TTLS, CASES, EXPECTED_CALLS, OBSERVER, SUPERVISOR,
                                              DesktopFlow, WAIT)

PROFILE = 'supervision-d2b1'
MACHINE_ID = Path('/etc/machine-id')
HEX = re.compile('[0-9a-f]{64}')
SCOPE = Scope(TARGET, OBJECTIVE, 3, PLAN)
BEFORE_DISPATCH = {'before_dispatch', 'attempt_expired'}
RESTART_OFFSET = 60


@dataclass(frozen=True)
class Approval(registry.Approval):
    expires_monotonic: int


@dataclass(frozen=True)
class Layout(registry.Layout):
    @property
    def endpoint(self):
        return self.ingress / ENDPOINT


def run_layout(run_id):
    require(type(run_id) is str and registry.RUN_ID.fullmatch(run_id) is not None, 'invalid_run_id')
    return Layout(registry.BASE / f'loop-supervision-d2b1-{run_id}')


def parse_approval(raw, run_id, *, boot_id, now, elapsed, hostname, machine_id):
    try:
        data = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError, RecursionError):
        raise QualificationError('invalid_approval') from None
    expected = {'version', 'profile', 'run_id', 'boot_id', 'hostname', 'machine_id',
                'expires_unix', 'expires_monotonic', 'service', 'desktop'}
    require(type(data) is dict and data.keys() == expected and data['profile'] == PROFILE
            and data['hostname'] == hostname and data['machine_id'] == machine_id
            and type(machine_id) is str and OPAQUE_ID.fullmatch(machine_id) is not None,
            'invalid_approval')
    limit = data['expires_monotonic']
    require(type(limit) is int and elapsed < limit <= elapsed + registry.MAX_WINDOW, 'approval_window_invalid')
    core = {key: data[key] for key in ('version', 'run_id', 'boot_id', 'expires_unix', 'service', 'desktop')}
    approval = registry.parse_approval(json.dumps(dict(core, third=None)), run_id, boot_id=boot_id, now=now)
    return Approval(approval.run_id, approval.service, approval.desktop, approval.third, approval.expires, limit)


def read_approval(layout, run_id):
    def parse(raw, run_id, **kernel):
        return parse_approval(raw, run_id, **kernel, elapsed=monotonic(), hostname=socket.gethostname(),
                              machine_id=MACHINE_ID.read_text().strip())

    return registry.read_approval(layout, run_id, parser=parse)


class Window:
    """Bound the real run by both the approved wall deadline and elapsed time."""

    def __init__(self, deadline, *, monotonic_deadline, wall=time, elapsed=monotonic):
        self.deadline, self.wall, self.elapsed = deadline, wall, elapsed
        self.end = monotonic_deadline

    def remaining(self):
        return max(0, min(self.deadline - self.wall(), self.end - self.elapsed()))


class LabClock:
    """Forward-only virtual UTC so deadline proofs require no timed sleeps."""

    def __init__(self, expires, *, restart):
        self.base = expires - registry.MAX_WINDOW
        self.offset = RESTART_OFFSET if restart else 0

    def __call__(self):
        return self.base + self.offset


class AbandonStage(BaseException):
    """Leave a committed dispatch outstanding on a controlled fixture stop."""


class Gates:
    def __init__(self, window):
        self.window = window
        self.stopping = Event()
        self.arrived = {case: Event() for case in CASES[1:]}
        self.release = {case: Event() for case in CASES[1:]}
        self.calls = dict.fromkeys(CASES, 0)
        self.case_by_attempt = {}
        self.lock = Lock()

    def count(self, case):
        if case is not None:
            with self.lock:
                self.calls[case] += 1

    def wait(self, case):
        self.arrived[case].set()
        if (not self.release[case].wait(min(WAIT, self.window.remaining()))
                or self.stopping.is_set() or not self.window.remaining()):
            raise AbandonStage

    def abort(self):
        self.stopping.set()
        for gate in self.release.values():
            gate.set()


def broker_class(gates):
    class FixtureExecution(SupervisedExecution):
        def _work(self, connection, attempt, driver):
            try:
                case = gates.case_by_attempt.get(attempt.id)
                if case in BEFORE_DISPATCH:
                    gates.wait(case)
                super()._work(connection, attempt, driver)
            except AbandonStage:
                raise EOFError from None

        def _run_stage(self, attempt, index, previous_value):
            if gates.stopping.is_set() or not gates.window.remaining():
                raise AbandonStage
            result = super()._run_stage(attempt, index, previous_value)
            case = gates.case_by_attempt.get(attempt.id)
            gates.count(case)
            if index == 1 and case in gates.release and case not in BEFORE_DISPATCH:
                gates.wait(case)
            return result

        def _valid_driver(self, *args, **kwargs):
            if gates.stopping.is_set() or not gates.window.remaining():
                raise AbandonStage
            return super()._valid_driver(*args, **kwargs)

    class FixtureRegistry(SupervisionRegistry):
        def _commit(self, db):
            if gates.stopping.is_set() or not gates.window.remaining():
                raise RegistryError(Error.DENIED)
            super()._commit(db)

    class FixtureBroker(SupervisionLabBroker):
        _execution_type = FixtureExecution
        _registry_type = FixtureRegistry

        def handle_request(self, connection, version, method, params):
            if gates.stopping.is_set() or not gates.window.remaining():
                fail('denied')
            return super().handle_request(connection, version, method, params)

    return FixtureBroker


def credentials_from_seed(seed, run_id):
    labels = ('admin', 'issuer', 'executor', 'other', 'invalid',
              'supervisor', 'observer', 'auditor')
    return {label: urlsafe_b64encode(digest(seed, f'{PROFILE}/{run_id}/{label}'.encode(), 'sha256'))
            .rstrip(b'=').decode('ascii') for label in labels}


def policy_bytes(credentials, expires):
    policy = json.loads(registry.policy_bytes(credentials, 1, expires))
    for principal, label in ((SUPERVISOR, 'supervisor'), (OBSERVER, 'observer'), (AUDITOR, 'auditor')):
        policy['principals'][principal] = sha256(credentials[label].encode()).hexdigest()
    return json.dumps(policy, sort_keys=True, separators=(',', ':')).encode()


def grant_base(broker, expires):
    for principal, permission in ((ISSUER, Permission.AUTHORIZE), (EXECUTOR, Permission.PERFORM),
                                  (SUPERVISOR, Permission.CANCEL), (AUDITOR, Permission.AUDIT)):
        broker.execution.grant(principal, permission, SCOPE, expires_at=expires)


def lookup_attempts(broker, *, paused=False):
    with broker.access.identity_snapshot(), broker.registry.execution_transaction() as tx:
        attempts = {}
        for case, request_id in CASE_IDS.items():
            attempt = tx.find_request(ISSUER, request_id)
            require(attempt is not None and attempt.scope == SCOPE and attempt.performer == EXECUTOR
                    and attempt.ttl_seconds == CASE_TTLS[case], 'approved_attempt_missing')
            if paused:
                status = tx.progress(attempt)
                require((status.state, status.mode, status.completed, status.current_stage)
                        == ('running', 'paused', 0, None), 'attempt_not_cleanly_paused')
            attempts[case] = attempt.id
        return attempts


def arm(broker, gates, clock, expires):
    attempts = lookup_attempts(broker, paused=True)
    gates.case_by_attempt = {attempt: case for case, attempt in attempts.items()}
    for case, attempt in attempts.items():
        for principal, permission in ((SUPERVISOR, Control.PAUSE), (SUPERVISOR, Control.STEP),
                                      (SUPERVISOR, Control.CONTINUE), (OBSERVER, Control.PROGRESS)):
            deadline = clock.base + 5 if case == 'advance_expired' and permission is Control.CONTINUE else expires
            broker.execution.grant(principal, permission, SCOPE, expires_at=deadline, attempt_id=attempt)
    return attempts


def broker_control(channel, broker, gates, clock, expires, *, restart):
    attempts = None
    next_release = iter(CASES[1:])
    recovered = False
    while gates.window.remaining():
        raw = channel.line(gates.window.remaining())
        if not gates.window.remaining():
            return 'approval_expired'
        if raw is None:
            return 'control_closed'
        if raw == b'stop':
            return 'requested'
        if restart:
            require(raw == b'reissue' and not recovered, 'unexpected_control_message')
            recovered = True
            retained = lookup_attempts(broker)
            broker.execution.grant(AUDITOR, Permission.AUDIT, SCOPE, expires_at=expires)
            broker.execution.grant(SUPERVISOR, Control.STEP, SCOPE,
                                   expires_at=expires, attempt_id=retained['flow'])
            emit('recovery_grants_reissued', audit=True, historical_step=True)
        elif attempts is None:
            require(raw == b'arm', 'unexpected_control_message')
            attempts = arm(broker, gates, clock, expires)
            emit('fixture_armed', attempts=attempts)
        else:
            case = next(next_release, None)
            require(case is not None and raw == f'release {case}'.encode(), 'unexpected_control_message')
            require(gates.arrived[case].wait(min(WAIT, gates.window.remaining())), 'trusted_gate_not_reached')
            if not gates.window.remaining():
                return 'approval_expired'
            if case == 'interrupted':
                return 'interrupted_pending_dispatch'
            if case == 'revoked':
                broker.execution.revoke(SUPERVISOR, Control.CONTINUE, SCOPE, attempt_id=attempts[case])
            elif case in ('advance_expired', 'attempt_expired'):
                with broker.access.identity_snapshot():
                    clock.offset = 5 if case == 'advance_expired' else RESTART_OFFSET
            gates.release[case].set()
    return 'approval_expired'


def serve(layout, approval, channel, credentials, *, restart, original_pin, window):
    require(not any(layout.ingress.iterdir()), 'ingress_not_fresh')
    clock, gates = LabClock(approval.expires, restart=restart), Gates(window)
    raw = policy_bytes(credentials, approval.expires)
    if restart:
        require({item.name for item in layout.private.iterdir()} <= {DATABASE, DATABASE + '-journal', POLICY_FILE},
                'unexpected_private_artifact')
        pin = parse_pin(original_pin)
    else:
        require(original_pin is None and not any(layout.private.iterdir()), 'private_not_fresh')
        pin = initialize_supervision_database(layout.private, wall_clock=clock)
        publish_policy(layout.private, raw, initial=True)

    ingress = CrossUIDIngress(layout.ingress, layout.private,
                              PeerAdmission(approval.service[0], frozenset({approval.desktop[0]})))
    def prepare(broker):
        require(window.remaining() > 0, 'approval_window_invalid')
        if not restart:
            grant_base(broker, approval.expires)

    with sentinel_resources(layout.private) as fd:
        with _serve_supervision(ingress, pin, PolicyPin(1, sha256(raw).hexdigest()), wall_clock=clock,
                                clock=monotonic, broker_type=broker_class(gates),
                                prepare=prepare) as (endpoint, broker, _):
            try:
                for item in (DATABASE, POLICY_FILE):
                    check_metadata((layout.private / item).lstat(), approval.service, 0o600,
                                   stat.S_ISREG, 'unsafe_private_artifact')
                emit('broker_ready', phase='restart' if restart else 'initial', run_id=approval.run_id,
                     broker_pid=os.getpid(), broker_uid=os.geteuid(), broker_gid=os.getegid(),
                     admitted_uid=approval.desktop[0], sentinel_fd=fd, database_pin=serialize_pin(pin),
                     endpoint=str(endpoint))
                reason = broker_control(channel, broker, gates, clock, approval.expires, restart=restart)
            finally:
                # Release every waiting worker before the Server joins and unbinds.
                gates.abort()
    require(not os.path.lexists(layout.endpoint) and not os.path.lexists(layout.private / registry.PRIVATE_SOCKET),
            'socket_cleanup_failed')
    require(reason != 'interrupted_pending_dispatch' or gates.calls == EXPECTED_CALLS,
            'unexpected_dispatch_count', result='no_go')
    require(not restart or not any(gates.calls.values()), 'dispatch_during_recovery', result='no_go')
    emit('broker_stopped', reason=reason, run_id=approval.run_id, dispatch_calls=gates.calls,
         sockets_removed=True, sentinel_closed=True, database_retained=True)


def probe(layout, approval, credentials, pid, sentinel_fd):
    info = check_metadata(layout.endpoint.lstat(), approval.service, 0o620, stat.S_ISSOCK,
                          'unsafe_ingress_socket')
    require(read_acl(layout.endpoint) == named_user_acl(approval.desktop[0], 6, 2),
            'unexpected_socket_acl')
    with connect(layout, approval.service, pid) as rpc:
        denied_rpc(rpc, 'auth', credential=credentials['invalid'])
        authenticate(rpc, credentials['other'], OTHER)
        denied_rpc(rpc, 'executor.status', executor_id=TARGET)
    emit('kernel_peer_verified', broker_pid=pid, broker_uid=approval.service[0], broker_gid=approval.service[1],
         desktop_uid=os.geteuid(), invalid_credential_denied=True, ungranted_principal_denied=True,
         socket_mode=oct(stat.S_IMODE(info.st_mode)))
    check_denied('private_traversal', lambda: os.stat(layout.private / registry.PRIVATE_SOCKET))
    check_denied('private_listing', lambda: os.listdir(layout.private))
    check_denied('sqlite_read', lambda: open_readonly(layout.private / DATABASE))
    check_denied('manifest_read', lambda: open_readonly(layout.private / POLICY_FILE))
    check_denied('sentinel_socket_connect', lambda: connect_sentinel(layout.private / registry.PRIVATE_SOCKET))
    check_denied('sentinel_descriptor_open', lambda: open_readonly(Path(f'/proc/{pid}/fd/{sentinel_fd}')))
    emit('isolation_probes_complete', direct_denials=6, no_ancillary_data=True)


def parse_attempts(raw):
    require(type(raw) is str and len(raw) <= 1024, 'invalid_attempt_references')
    try:
        references = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, RecursionError):
        raise QualificationError('invalid_attempt_references') from None
    require(type(references) is dict and set(references) == set(CASES)
            and all(type(item) is str and OPAQUE_ID.fullmatch(item) is not None for item in references.values())
            and len(set(references.values())) == len(CASES), 'invalid_attempt_references')
    return references


def desktop(layout, approval, credentials, args):
    require(args.broker_pid > 1 and args.sentinel_fd > 2, 'invalid_sentinel_metadata')
    client = DesktopFlow(layout, approval.service, args.broker_pid, credentials)
    if args.phase == 'prepare':
        require(args.attempts is None and args.audit_sha256 is None and args.previous_pid is None,
                'unexpected_recovery_references')
        probe(layout, approval, credentials, args.broker_pid, args.sentinel_fd)
        registry.initial_flow(layout, approval.service, args.broker_pid, credentials,
                              label='Executor sintético D.2B.1',
                              text='Objetivo sintético D.2B.1. Texto inerte: $(fixture-never-executes).')
        client.prepare()
        return
    attempts = parse_attempts(args.attempts)
    if args.phase == 'active':
        require(args.audit_sha256 is None and args.previous_pid is None, 'unexpected_recovery_references')
        client.active(attempts)
        return
    require(type(args.previous_pid) is int and args.previous_pid > 1 and args.previous_pid != args.broker_pid,
            'broker_pid_was_not_replaced')
    if args.phase == 'before-regrant':
        require(args.audit_sha256 is None, 'unexpected_recovery_references')
        probe(layout, approval, credentials, args.broker_pid, args.sentinel_fd)
        client.before_regrant(attempts)
    else:
        require(type(args.audit_sha256) is str and HEX.fullmatch(args.audit_sha256) is not None,
                'invalid_audit_reference')
        client.recovered(attempts, args.audit_sha256)


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', default='0000000000000000')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('plan')
    broker = commands.add_parser('broker')
    broker.add_argument('--phase', choices=('initial', 'restart'), required=True)
    broker.add_argument('--database-pin')
    client = commands.add_parser('desktop')
    client.add_argument('--phase', choices=('prepare', 'active', 'before-regrant', 'recovered'), required=True)
    client.add_argument('--broker-pid', type=int, required=True)
    client.add_argument('--sentinel-fd', type=int, required=True)
    client.add_argument('--previous-pid', type=int)
    client.add_argument('--attempts')
    client.add_argument('--audit-sha256')
    args = parser.parse_args(argv)
    try:
        layout = run_layout(args.run_id)
        if args.command in (None, 'plan'):
            emit('plan', profile=PROFILE, status='PREPARED / NOT EXECUTED', root=str(layout.root),
                 endpoint=str(layout.endpoint), provisioning='separate_operator_approval_required')
            return 0
        approval = read_approval(layout, args.run_id)
        role = 'service' if args.command == 'broker' else 'desktop'
        check_process(approval, role)
        check_layout(layout, approval, check_acl=True)
        window = Window(approval.expires, monotonic_deadline=approval.expires_monotonic)
        channel = ControlInput(0)
        credentials = credentials_from_seed(channel.seed(), args.run_id)
        require(window.remaining() > 0, 'approval_window_invalid')
        if role == 'service':
            signal.signal(signal.SIGTERM, registry.interrupt)
            serve(layout, approval, channel, credentials, restart=args.phase == 'restart',
                  original_pin=args.database_pin, window=window)
        else:
            desktop(layout, approval, credentials, args)
        return 0
    except QualificationError as error:
        emit('qualification_failed', check=error.check, result=error.result)
        return 2 if error.result == 'no_go' else 1
    except (OSError, EOFError, ValueError, RegistryError, Fault, AssertionError,
            AttributeError, KeyError, IndexError, TypeError):
        emit('qualification_failed', check='fixture_or_transport_failure', result='partial')
        return 1
    except KeyboardInterrupt:
        emit('qualification_failed', check='interrupted', result='partial')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
