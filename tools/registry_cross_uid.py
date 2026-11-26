# SPDX-License-Identifier: Apache-2.0
"""Prepare or exercise the disposable D.1C.3 Registry fixture.

The driver has no privilege-changing operations. Each execution role needs an
independently provisioned, root-owned approval and runs as an unprivileged UID.
"""
from argparse import ArgumentParser
from array import array
from base64 import urlsafe_b64encode
from contextlib import closing, contextmanager
from dataclasses import dataclass
import errno
from hashlib import sha256
from hmac import digest
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import stat
from time import monotonic, time

from experiments.objective_registry import RegistryError
from experiments.registry_operational import POLICY_FILE, PolicyPin, serve_operational_registry
from experiments.registry_rpc import VERSION
from experiments.registry_storage import DATABASE, DatabasePin, initialize_registry_database
from loopbridge.protocol import Fault, RPC, unique_object
from loopbridge.service_ingress import (DEFAULT_ACL, CrossUIDIngress, PeerAdmission, bound_listener,
                                       named_user_acl, peer_identity, read_acl)

BASE = Path('/run')
BOOT_ID = Path('/proc/sys/kernel/random/boot_id')
RUN_ID = re.compile('[0-9a-f]{16}')
SEED = re.compile(b'[0-9a-f]{64}')
PIN = re.compile(r'[0-9]{1,20}:[0-9]{1,20}:[0-9]{1,20}:[0-9]{1,20}')
MAX_APPROVAL = 2048
MAX_WINDOW = 1800
GRAPHICAL_ENV = ('DISPLAY', 'WAYLAND_DISPLAY', 'WAYLAND_SOCKET', 'SWAYSOCK',
                 'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR')
PRIVATE_SOCKET = 'registry-sentinel.sock'
DENIALS = {errno.EACCES, errno.EPERM}
ADMIN, ISSUER, EXECUTOR, OTHER, TARGET, OBJECTIVE = (f'{n:032x}' for n in range(1, 7))
ANSWER_ID = '00000000000000000000000000000015'
ANSWER = dict(request_id=ANSWER_ID, objective_id=OBJECTIVE, expected_revision=2, decision='accept')
EXPECT_RECEIPT = dict(id=OBJECTIVE, state='accepted', revision=3)
FIXTURE_TEXT = 'Objetivo sintético D.1C.3. Texto inerte: $(fixture-never-executes).'


class QualificationError(Exception):
    def __init__(self, check, result='partial'):
        self.check, self.result = check, result
        super().__init__(check)


def require(value, check, *, result='partial'):
    if not value:
        raise QualificationError(check, result)


def emit(event, **details):
    print(json.dumps(dict(event=event, **details), sort_keys=True), flush=True)


@dataclass(frozen=True)
class Approval:
    run_id: str
    service: tuple[int, int]
    desktop: tuple[int, int]
    third: tuple[int, int] | None
    expires: int


@dataclass(frozen=True)
class Layout:
    root: Path

    @property
    def private(self):
        return self.root / 'private'

    @property
    def ingress(self):
        return self.root / 'ingress'

    @property
    def endpoint(self):
        return self.ingress / 'registry.sock'


def run_layout(run_id):
    require(RUN_ID.fullmatch(run_id) is not None, 'invalid_run_id')
    return Layout(BASE / ('loop-registry-d1c3-' + run_id))


def parse_approval(raw, run_id, *, boot_id, now):
    try:
        entry = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError, RecursionError):
        raise QualificationError('invalid_approval') from None
    fields = {'version', 'run_id', 'boot_id', 'expires_unix', 'service', 'desktop', 'third'}
    require(type(entry) is dict and entry.keys() == fields and type(entry['version']) is int
            and entry['version'] == 1 and entry['run_id'] == run_id and entry['boot_id'] == boot_id,
            'invalid_approval')
    expires = entry['expires_unix']
    require(type(expires) is int and now < expires <= now + MAX_WINDOW, 'approval_window_invalid')
    pairs = [entry['service'], entry['desktop']]
    if entry['third'] is not None:
        pairs.append(entry['third'])
    require(all(type(pair) is list and len(pair) == 2 and
                all(type(n) is int and 0 < n < 0xffffffff for n in pair) for pair in pairs),
            'invalid_identity')
    require(len({pair[0] for pair in pairs}) == len(pairs), 'uids_must_be_distinct')
    return Approval(run_id, tuple(pairs[0]), tuple(pairs[1]), tuple(pairs[2]) if len(pairs) == 3 else None,
                    expires)


def check_metadata(info, owner, mode, kind, check):
    require(kind(info.st_mode) and (info.st_uid, info.st_gid) == owner
            and stat.S_IMODE(info.st_mode) == mode, check)
    return info


def read_approval(layout, run_id, *, parser=parse_approval):
    check_metadata(BASE.lstat(), (0, 0), 0o755, stat.S_ISDIR, 'unsafe_run_parent')
    check_metadata(layout.root.lstat(), (0, 0), 0o755, stat.S_ISDIR, 'unsafe_run_root')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    with os.fdopen(os.open(layout.root / 'approval.json', flags), 'rb') as source:
        approval = check_metadata(os.fstat(source.fileno()), (0, 0), 0o444, stat.S_ISREG, 'unsafe_approval')
        require(approval.st_nlink == 1 and approval.st_size <= MAX_APPROVAL, 'unsafe_approval')
        raw = source.read(MAX_APPROVAL + 1)
    require(len(raw) <= MAX_APPROVAL, 'unsafe_approval')
    return parser(raw, run_id, boot_id=BOOT_ID.read_text().strip(), now=time())


def check_identity(expected, uid, euid, gid, egid, groups):
    require(expected is not None and uid == euid == expected[0] and gid == egid == expected[1]
            and not set(groups) - {gid}, 'wrong_process_identity')


def check_privileges(status):
    fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
    require(fields.get('NoNewPrivs', '').strip() == '1'
            and all(re.fullmatch('0+', fields.get(name, '').strip()) is not None
                    for name in ('CapEff', 'CapPrm', 'CapAmb')), 'unexpected_process_privileges')


def check_process(approval, role):
    check_identity(getattr(approval, role), os.getuid(), os.geteuid(), os.getgid(), os.getegid(), os.getgroups())
    require(not any(os.environ.get(name) for name in GRAPHICAL_ENV), 'inherited_graphical_environment')
    check_privileges(Path('/proc/self/status').read_text())
    for entry in os.listdir('/proc/self/fd'):
        fd = int(entry)
        try:
            info = os.fstat(fd)
        except OSError as error:
            if error.errno == errno.EBADF:  # The descriptor used by listdir itself.
                continue
            raise
        require(fd <= 2 and not stat.S_ISSOCK(info.st_mode), 'inherited_descriptor')


def check_layout(layout, approval, *, check_acl):
    check_metadata(layout.private.lstat(), approval.service, 0o700, stat.S_ISDIR, 'unsafe_private')
    check_metadata(layout.ingress.lstat(), approval.service, 0o710, stat.S_ISDIR, 'unsafe_ingress')
    if check_acl:
        require(read_acl(layout.ingress) == named_user_acl(approval.desktop[0], 7, 1)
                and read_acl(layout.ingress, DEFAULT_ACL) is None, 'unexpected_ingress_acl')


class ControlInput:
    """Bounded anonymous input. The service also exits when the approval expires."""

    def __init__(self, fd):
        self.fd = fd
        self.buffer = bytearray()
        require(stat.S_ISFIFO(os.fstat(fd).st_mode)
                and os.readlink(f'/proc/self/fd/{fd}').startswith('pipe:['), 'anonymous_pipe_required')

    def line(self, seconds):
        deadline = monotonic() + seconds
        while b'\n' not in self.buffer:
            remaining = deadline - monotonic()
            if remaining <= 0 or not select.select([self.fd], [], [], remaining)[0]:
                return None
            block = os.read(self.fd, 128)
            if not block:
                require(not self.buffer, 'truncated_control_message')
                return None
            self.buffer.extend(block)
            require(len(self.buffer) <= 256, 'control_message_limit')
        line, _, tail = self.buffer.partition(b'\n')
        self.buffer = bytearray(tail)
        require(len(line) <= 64, 'control_message_limit')
        return bytes(line)

    def seed(self):
        line = self.line(10)
        require(line is not None and SEED.fullmatch(line) is not None, 'invalid_fixture_seed')
        return bytes.fromhex(line.decode('ascii'))


def tokens(seed, run_id):
    labels = ('admin', 'issuer', 'executor', 'executor_rotated', 'other', 'invalid')
    return {label: urlsafe_b64encode(digest(seed, f'd1c3/{run_id}/{label}'.encode(), 'sha256'))
            .rstrip(b'=').decode('ascii') for label in labels}


def policy_bytes(credentials, generation, expires):
    old = sha256(credentials['executor'].encode()).hexdigest()
    executor = 'executor' if generation == 1 else 'executor_rotated'
    principals = {p: sha256(credentials[label].encode()).hexdigest()
                  for p, label in ((ADMIN, 'admin'), (ISSUER, 'issuer'), (EXECUTOR, executor), (OTHER, 'other'))}
    grants = [(ADMIN, 'executor.register'), (EXECUTOR, 'executor.confirm'),
              (EXECUTOR, 'objective.read'), (EXECUTOR, 'objective.respond')]
    if generation == 1:
        grants.append((ISSUER, 'objective.author'))
    entries = [dict(principal=p, scope='registry.' + scope, executor=TARGET, expires_unix=expires)
               for p, scope in grants]
    return json.dumps(dict(version=1, generation=generation, principals=principals, grants=entries,
                           retired_verifiers=[] if generation == 1 else [old]),
                      sort_keys=True, separators=(',', ':')).encode()


def publish_policy(directory, raw, *, initial):
    path = directory / POLICY_FILE
    temporary = path if initial else directory / 'policy.next'
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    with os.fdopen(os.open(temporary, flags, 0o600), 'wb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    if not initial:
        temporary.replace(path)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def serialize_pin(pin):
    return ':'.join(str(n) for n in (*pin.directory, *pin.file))


def parse_pin(raw):
    require(type(raw) is str and PIN.fullmatch(raw) is not None, 'invalid_database_pin')
    parts = tuple(map(int, raw.split(':')))
    return DatabasePin(parts[:2], parts[2:])


@contextmanager
def sentinel_resources(private):
    with bound_listener(private / PRIVATE_SOCKET) as listener:
        fd = os.memfd_create('d1c3-fixture-sentinel', os.MFD_CLOEXEC)
        try:
            os.write(fd, b'd1c3 synthetic descriptor\n')
            require(not os.get_inheritable(listener.fileno()) and not os.get_inheritable(fd)
                    and stat.S_ISREG(os.fstat(fd).st_mode), 'unsafe_sentinel')
            yield fd
        finally:
            os.close(fd)


def serve(layout, approval, channel, credentials, *, phase, original_pin):
    require(not any(layout.ingress.iterdir()), 'ingress_not_fresh')
    if phase == 'initial':
        require(original_pin is None and not any(layout.private.iterdir()), 'private_not_fresh')
        initial = policy_bytes(credentials, 1, approval.expires)
        database_pin = initialize_registry_database(layout.private)
        publish_policy(layout.private, initial, initial=True)
        generation = 1
    else:
        require(set(child.name for child in layout.private.iterdir()) <=
                {DATABASE, DATABASE + '-journal', POLICY_FILE}, 'unexpected_private_artifact')
        database_pin = parse_pin(original_pin)
        generation = 2
    pin = PolicyPin(generation, sha256(policy_bytes(credentials, generation, approval.expires)).hexdigest())
    admission = PeerAdmission(approval.service[0], frozenset({approval.desktop[0]}))
    ingress = CrossUIDIngress(layout.ingress, layout.private, admission)
    with sentinel_resources(layout.private) as fd:
        with serve_operational_registry(ingress, database_pin=database_pin, policy_pin=pin) as (endpoint, control):
            database = check_metadata((layout.private / DATABASE).lstat(), approval.service, 0o600,
                                      stat.S_ISREG, 'unsafe_fixture_database')
            manifest = check_metadata((layout.private / POLICY_FILE).lstat(), approval.service, 0o600,
                                      stat.S_ISREG, 'unsafe_fixture_manifest')
            emit('broker_ready', phase=phase, broker_uid=os.geteuid(), broker_gid=os.getegid(),
                 broker_pid=os.getpid(), admitted_uid=approval.desktop[0], sentinel_fd=fd, endpoint=str(endpoint),
                 database_pin=serialize_pin(database_pin), database_mode=oct(stat.S_IMODE(database.st_mode)),
                 manifest_mode=oct(stat.S_IMODE(manifest.st_mode)), private_mode='0o700')
            while time() < approval.expires:
                command = channel.line(min(MAX_WINDOW, approval.expires - time()))
                if command in (b'stop', None):
                    break
                require(command == b'restrict' and generation == 1, 'invalid_broker_transition')
                raw = policy_bytes(credentials, 2, approval.expires)
                publish_policy(layout.private, raw, initial=False)
                control.reload(PolicyPin(2, sha256(raw).hexdigest()))
                generation = 2
                emit('policy_restricted', generation=generation)
    require(not os.path.lexists(layout.endpoint) and not os.path.lexists(layout.private / PRIVATE_SOCKET),
            'socket_cleanup_failed')
    emit('broker_stopped', phase=phase, sockets_removed=True, database_retained=True)


class JsonSocket:
    """Reject ancillary data and close received descriptors even in a failing test."""

    def __init__(self, peer):
        self.peer = peer

    def settimeout(self, timeout):
        self.peer.settimeout(timeout)

    def sendall(self, raw):
        self.peer.sendall(raw)

    def recv(self, size):
        data, ancillary, flags, _ = self.peer.recvmsg(size, 4096, socket.MSG_CMSG_CLOEXEC)
        for level, kind, raw in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                fds = array('i')
                fds.frombytes(raw[:len(raw) - len(raw) % fds.itemsize])
                for fd in fds:
                    os.close(fd)
        require(not ancillary and not flags & socket.MSG_CTRUNC, 'unexpected_ancillary_data', result='no_go')
        return data


@contextmanager
def connect(layout, service, pid, *, version=VERSION, timeout=4):
    with socket.socket(socket.AF_UNIX) as peer:
        peer.settimeout(timeout)
        peer.connect(str(layout.endpoint))
        require(peer_identity(peer) == (pid, *service), 'unexpected_broker_identity', result='no_go')
        yield RPC(JsonSocket(peer), version, timeout=timeout)


def authenticate(rpc, token, principal):
    require(rpc.call('auth', credential=token).get('principal') == principal,
            'unexpected_principal', result='no_go')


def denied_rpc(rpc, method, **params):
    try:
        rpc.call(method, **params)
    except Fault as error:
        require((error.code, error.message, error.data) == (-32001, 'denied', None), 'unexpected_rpc_error')
        return
    raise QualificationError('unauthorized_rpc_succeeded', 'no_go')


def check_denied(check, operation):
    try:
        operation()
    except OSError as error:
        require(error.errno in DENIALS, check)
        emit('direct_access', check=check, outcome='denied', errno=error.errno)
        return
    raise QualificationError(check, 'no_go')


def open_readonly(path):
    os.close(os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK))


def connect_sentinel(path):
    with socket.socket(socket.AF_UNIX) as peer:
        peer.settimeout(4)
        peer.connect(str(path))


def exercise(layout, approval, credentials, *, phase, pid, sentinel_fd):
    info = check_metadata(layout.endpoint.lstat(), approval.service, 0o620, stat.S_ISSOCK,
                          'unsafe_ingress_socket')
    require(read_acl(layout.endpoint) == named_user_acl(approval.desktop[0], 6, 2),
            'unexpected_socket_acl')
    with connect(layout, approval.service, pid) as rpc:
        denied_rpc(rpc, 'auth', credential=credentials['invalid'])
        authenticate(rpc, credentials['other'], OTHER)
        denied_rpc(rpc, 'executor.status', executor_id=TARGET)
    emit('kernel_peer_verified', broker_uid=approval.service[0], broker_pid=pid, peer_uid=os.geteuid(),
         socket_mode=oct(stat.S_IMODE(info.st_mode)), named_acl_uid=approval.desktop[0])
    check_denied('private_traversal', lambda: os.stat(layout.private / PRIVATE_SOCKET))
    check_denied('private_listing', lambda: os.listdir(layout.private))
    check_denied('sqlite_read', lambda: open_readonly(layout.private / DATABASE))
    check_denied('manifest_read', lambda: open_readonly(layout.private / POLICY_FILE))
    check_denied('sentinel_socket_connect', lambda: connect_sentinel(layout.private / PRIVATE_SOCKET))
    check_denied('sentinel_descriptor_open', lambda: open_readonly(Path(f'/proc/{pid}/fd/{sentinel_fd}')))
    if phase == 'initial':
        initial_flow(layout, approval.service, pid, credentials)
    else:
        restricted_flow(layout, approval.service, pid, credentials)
    emit('desktop_flow', phase=phase, authenticated=True, invalid_credential_denied=True,
         ungranted_principal_denied=True, no_ancillary_data=True,
         grant_revoked=phase != 'initial', old_credential_denied=phase != 'initial',
         receipt_revision=EXPECT_RECEIPT['revision'])


def restricted_flow(layout, service, pid, credentials):
    with connect(layout, service, pid) as rpc:
        denied_rpc(rpc, 'auth', credential=credentials['executor'])
        authenticate(rpc, credentials['issuer'], ISSUER)
        denied_rpc(rpc, 'objective.withdraw', objective_id=OBJECTIVE, expected_revision=3,
                   request_id='00000000000000000000000000000016')
    with connect(layout, service, pid) as rpc:
        authenticate(rpc, credentials['executor_rotated'], EXECUTOR)
        require(rpc.call('objective.status', objective_id=OBJECTIVE).get('state') == 'accepted',
                'persisted_state_missing')
        require(rpc.call('objective.respond', **ANSWER) == EXPECT_RECEIPT, 'receipt_not_recovered')


def initial_flow(layout, service, pid, credentials, *, label='Executor sintético D.1C.3',
                 text=FIXTURE_TEXT):
    def request_id(n):
        return f'{n:032x}'

    with connect(layout, service, pid) as rpc:
        authenticate(rpc, credentials['admin'], ADMIN)
        result = rpc.call('executor.register', executor_id=TARGET, bound_principal_id=EXECUTOR,
                          label=label, request_id=request_id(17))
        require(result == dict(id=TARGET, state='pending', revision=1), 'registration_failed')
    with connect(layout, service, pid) as rpc:
        authenticate(rpc, credentials['executor'], EXECUTOR)
        result = rpc.call('executor.confirm', executor_id=TARGET, expected_revision=1, request_id=request_id(18))
        require(result == dict(id=TARGET, state='available', revision=2), 'confirmation_failed')
    with connect(layout, service, pid) as rpc:
        authenticate(rpc, credentials['issuer'], ISSUER)
        result = rpc.call('objective.create', objective_id=OBJECTIVE, executor_id=TARGET,
                          text=text, ttl_seconds=900, request_id=request_id(19))
        require(result == dict(id=OBJECTIVE, state='created', revision=1), 'objective_creation_failed')
        result = rpc.call('objective.offer', objective_id=OBJECTIVE, expected_revision=1, request_id=request_id(20))
        require(result == dict(id=OBJECTIVE, state='offered', revision=2), 'offer_failed')
    with connect(layout, service, pid) as rpc:
        authenticate(rpc, credentials['executor'], EXECUTOR)
        offers = rpc.call('objective.list_offers', executor_id=TARGET, limit=16)['items']
        require(len(offers) == 1 and offers[0]['id'] == OBJECTIVE, 'offer_missing')
        require(rpc.call('objective.status', objective_id=OBJECTIVE)['text'] == text, 'fixture_text_changed')
        require(rpc.call('objective.respond', **ANSWER) == EXPECT_RECEIPT, 'acceptance_failed')
    emit('objective_workflow', registration=True, confirmation=True, offer=True, acceptance=True)


def interrupt(_number, _frame):
    raise KeyboardInterrupt


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', default='0000000000000000')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('plan')
    broker = commands.add_parser('broker')
    broker.add_argument('--phase', choices=('initial', 'restart'), required=True)
    broker.add_argument('--database-pin')
    desktop = commands.add_parser('desktop')
    desktop.add_argument('--phase', choices=('initial', 'restricted', 'recovered'), required=True)
    desktop.add_argument('--broker-pid', type=int, required=True)
    desktop.add_argument('--sentinel-fd', type=int, required=True)
    commands.add_parser('third')
    args = parser.parse_args(argv)
    try:
        layout = run_layout(args.run_id)
        if args.command in (None, 'plan'):
            emit('plan', status='PREPARED / NOT EXECUTED', root=str(layout.root),
                 endpoint=str(layout.endpoint), provisioning='external_operator_approval_required')
            return 0
        approval = read_approval(layout, args.run_id)
        role = {'broker': 'service', 'desktop': 'desktop', 'third': 'third'}[args.command]
        check_process(approval, role)
        check_layout(layout, approval, check_acl=role != 'third')
        if role == 'third':
            check_denied('third_uid_connect', lambda: connect_sentinel(layout.endpoint))
            emit('third_uid', uid=os.geteuid(), connection_denied=True)
        else:
            channel = ControlInput(0)
            credentials = tokens(channel.seed(), args.run_id)
            if role == 'service':
                signal.signal(signal.SIGTERM, interrupt)
                serve(layout, approval, channel, credentials, phase=args.phase, original_pin=args.database_pin)
            else:
                require(args.broker_pid > 1 and args.sentinel_fd > 2, 'invalid_sentinel_metadata')
                exercise(layout, approval, credentials, phase=args.phase, pid=args.broker_pid,
                         sentinel_fd=args.sentinel_fd)
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
