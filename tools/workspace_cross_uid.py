# SPDX-License-Identifier: Apache-2.0
"""Prepare or run the fixed D.2C.2 workspace qualification on an approved disposable clone."""
from argparse import ArgumentParser, SUPPRESS
from dataclasses import dataclass
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import resource
from secrets import token_urlsafe
import select
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, monotonic_ns, time, time_ns

from experiments.objective_registry import RegistryError
from experiments.registry_operational import POLICY_FILE
from experiments.registry_storage import trusted_directory
from experiments.workspace_effect_lab import DATABASE
from loopbridge.process_boundary import protect_process
from loopbridge.protocol import unique_object
from loopbridge.service_ingress import ACCESS_ACL, DEFAULT_ACL, named_user_acl, path_inode, read_acl
from tools import registry_cross_uid as registry
from tools.registry_cross_uid import QualificationError, check_metadata, require
from tools.workspace_cross_uid_fixture import (ACTORS, CASES, CHALLENGE, CONTENT, DIVERGENT, HEX, NO_CALL,
                                               OBJECTIVE_TEXT, PROFILE, Layout, Pipe, WAIT, Window,
                                               desktop_control, serve_control)
from tools.workspace_cross_uid_flow import Flow, Verifier

SOURCE = Path(__file__).resolve().parents[1]
SERVICE = (980, 980)
DESKTOP = (1000, 1000)
THIRD = (65534, 65534)
CLONE_DMI = Path('/sys/class/dmi/id/product_uuid')
DMI = re.compile('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
REVISION = re.compile('[0-9a-f]{40}')
SNAPSHOT = re.compile('[A-Za-z0-9][A-Za-z0-9._-]{0,79}')
MAX_WINDOW = 900
MAX_START_AGE = 60
WORKERS = (*ACTORS, 'executor_b', 'invalid')
APPROVAL = 'approval.json'
MARKER = 'fixture.json'
EXECUTION = 'execution.json'
EVIDENCE = 'evidence.jsonl'
INSPECTION = 'inspection.json'
LIFECYCLE = 'lifecycle.json'
SCHEMA = 'workspace-cross-uid/1'
# Close anything the launcher/runtime opened after Popen's close_fds step.
# This runs before importing fixture code or receiving any bootstrap data.
BOOTSTRAP = ('import os, sys; os.closerange(3, os.sysconf("SC_OPEN_MAX")); '
             'sys.path.insert(0, sys.argv.pop(1)); '
             'from tools.workspace_cross_uid import main; raise SystemExit(main())')
# Required fields per event. Alternatives carry the same schema version.
EVENT_FIELDS = {
    'run_started': ('fixture linux_isolation wall_deadline monotonic_deadline',),
    'process_started': ('role pid start_ticks uids gids groups no_new_privileges zero_capabilities',),
    'process_exited': ('role pid start_ticks exit_code',),
    'broker_ready': ('generation pid previous_pid private_fd socket_pin storage_pins',),
    'kernel_ingress': ('generation client_peer service_peer invalid_credential_denied no_ancillary',),
    'non_admitted_peer': ('outcome generation', 'generation peer nominal_errno rpc_code socket_pin'),
    'direct_access': ('case edge outcome', 'case edge outcome executor_pid operation denials'),
    'registry_rpc': ('actor action',),
    'rpc_denied': ('actor case action error code variant request expected_revision',),
    'exact_grant_profile': ('case profile',),
    'status': ('case id revision state supervision effect',),
    'receipt': ('case id kind revision',),
    'audit_verified': ('case authorizer performer request scope operation events virtual_expires_ms',),
    'independent_filesystem': ('case condition final staging', 'case condition final staging operation file'),
    'gate': ('case edge operation durable_dispatch_revision virtual_utc',),
    'authority_change': ('case action virtual_utc',),
    'transport_reply_discarded': ('case stage',),
    'attribution_observation_removed': ('case final staging operation file',),
    'publication_counters': ('generation recovery tracked_operations calls links untracked',
                             'generation recovery tracked_operations calls links untracked expected_zero',
                             'generation recovery tracked_operations calls links untracked total expected_zero'),
    'broker_interrupted': ('case pid signal client_transport',),
    'stale_endpoint_removed': ('generation pid endpoint_pin verified_exit listener_absent',),
    'failure': ('check classification',),
    'execution_finished': ('classification gate_E',),
}


def layout_for(run_id):
    require(registry.RUN_ID.fullmatch(run_id), 'invalid_run_id')
    return Layout(registry.BASE / f'loop-d2c2-{run_id}')


def json_file(path, *, owner, mode=0o444):
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        info = check_metadata(os.fstat(stream.fileno()), owner, mode, stat.S_ISREG, 'unsafe_control_file')
        require(info.st_nlink == 1 and info.st_size <= 32768 and read_acl(stream.fileno()) is None,
                'unsafe_control_file')
        raw = stream.read(32769)
    require(len(raw) <= 32768, 'control_file_limit')
    value = json.loads(raw, object_pairs_hook=unique_object)
    require(type(value) is dict, 'invalid_control_file')
    return value


def write_json(path, value, *, mode=0o444):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    with os.fdopen(os.open(path, flags, mode), 'w') as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def kernel_identity(clone_dmi=None):
    return dict(boot_id=registry.BOOT_ID.read_text().strip(), hostname=socket.gethostname(),
                machine_id=Path('/etc/machine-id').read_text().strip(),
                clone_dmi=CLONE_DMI.read_text().strip().lower() if clone_dmi is None else clone_dmi)


def valid_marker(value, run_id, kernel):
    expected = {'version', 'profile', 'run_id', 'revision', 'archive_sha256', 'snapshot', 'source_dmi',
                'root_pin', 'children', 'sway_before_sha256', 'unit_before_sha256',
                'identities', *kernel}
    require(value.keys() == expected and type(value['version']) is int and value['version'] == 1
            and value['profile'] == PROFILE and value['run_id'] == run_id
            and all(value[field] == item for field, item in kernel.items()), 'fixture_identity_mismatch')
    require(DMI.fullmatch(value['clone_dmi']) and DMI.fullmatch(value['source_dmi'])
            and value['clone_dmi'] != value['source_dmi'] and value['clone_dmi'] != '0' * 8 + '-0000-0000-0000-000000000000'
            and re.fullmatch(r'[0-9a-f]{32}', value['machine_id'])
            and DMI.fullmatch(value['boot_id']) and REVISION.fullmatch(value['revision'])
            and SNAPSHOT.fullmatch(value['snapshot'])
            and all(HEX.fullmatch(value[key]) for key in (
                'archive_sha256', 'sway_before_sha256', 'unit_before_sha256'))
            and value['identities'] == dict(service=list(SERVICE), desktop=list(DESKTOP), third=list(THIRD)),
            'invalid_fixture_manifest')
    return value


def read_marker(layout, run_id):
    check_metadata(registry.BASE.lstat(), (0, 0), 0o755, stat.S_ISDIR, 'unsafe_run_parent')
    root = check_metadata(layout.root.lstat(), (0, 0), 0o755, stat.S_ISDIR, 'unsafe_run_root')
    require(read_acl(layout.root) is None and read_acl(layout.root, DEFAULT_ACL) is None, 'unsafe_run_root_acl')
    value = json_file(layout.root / MARKER, owner=(0, 0))
    marker = valid_marker(value, run_id, kernel_identity(None if os.geteuid() == 0 else value['clone_dmi']))
    require(marker['root_pin'] == list(path_inode(root)), 'fixture_root_replaced')
    require(marker['children'].keys() == {'private', 'ingress', 'challenge'}, 'invalid_fixture_inventory')
    for name in marker['children']:
        path = layout.root / name
        mode = 0o700 if name == 'private' else 0o710
        info = check_metadata(path.lstat(), SERVICE, mode, stat.S_ISDIR, 'unsafe_fixture_directory')
        require(marker['children'][name] == list(path_inode(info)), 'fixture_directory_replaced')
        # Each child can verify only the ACL it is allowed to traverse.
        if os.geteuid() in (0, SERVICE[0]):
            acl = None if name == 'private' else named_user_acl(DESKTOP[0] if name == 'ingress' else THIRD[0], 7, 1)
            require(read_acl(path) == acl and read_acl(path, DEFAULT_ACL) is None, 'unsafe_fixture_acl')
    return marker


def parse_approval(value, marker, *, wall, elapsed, fresh=False):
    require(value.keys() == {'version', 'profile', 'fixture', 'issued_unix', 'issued_monotonic',
                            'expires_unix', 'expires_monotonic'}
            and type(value['version']) is int and value['version'] == 1 and value['profile'] == PROFILE
            and type(value['fixture']) is dict and value['fixture'] == marker, 'approval_identity_mismatch')
    for clock, now in (('unix', wall), ('monotonic', elapsed)):
        issued, expires = value[f'issued_{clock}'], value[f'expires_{clock}']
        require(type(issued) is int and type(expires) is int and 0 < issued <= now < expires
                and 0 < expires - issued <= MAX_WINDOW and (not fresh or now - issued <= MAX_START_AGE),
                'approval_window_invalid')
    require(value['expires_unix'] - value['issued_unix'] == value['expires_monotonic'] - value['issued_monotonic'],
            'approval_window_mismatch')
    return Window(value['expires_unix'], value['expires_monotonic'])


def read_approval(layout, run_id, *, fresh=False):
    marker = read_marker(layout, run_id)
    value = json_file(layout.root / APPROVAL, owner=(0, 0))
    return marker, parse_approval(value, marker, wall=time(), elapsed=monotonic(), fresh=fresh)


def root_only():
    require(os.getuid() == os.geteuid() == os.getgid() == os.getegid() == 0, 'independent_root_operator_required')


def process_record(pid):
    proc = Path(f'/proc/{pid}')
    status = {key: value.split() for line in (proc / 'status').read_text().splitlines()
              if ':' in line for key, value in [line.split(':', 1)]}
    stat_fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
    return dict(pid=pid, start_ticks=int(stat_fields[19]), uids=list(map(int, status['Uid'])),
                gids=list(map(int, status['Gid'])), groups=list(map(int, status['Groups'])),
                no_new_privileges=status['NoNewPrivs'] == ['1'],
                zero_capabilities=all(int(status[field][0], 16) == 0
                                      for field in ('CapInh', 'CapPrm', 'CapEff', 'CapAmb')))


def check_worker_identity(role, real):
    require(not any(os.environ.get(key) for key in registry.GRAPHICAL_ENV), 'graphical_environment_inherited')
    for entry in os.listdir('/proc/self/fd'):
        fd = int(entry)
        try:
            os.fstat(fd)
        except OSError as error:
            if error.errno == errno.EBADF:
                continue
            raise
        require(fd <= 2, 'unexpected_extra_descriptor', result='no_go')
    for fd in (0, 1, 2):
        require(stat.S_ISFIFO(os.fstat(fd).st_mode) and os.readlink(f'/proc/self/fd/{fd}').startswith('pipe:['),
                f'private_pipe_required_{fd}', result='no_go')
    record = process_record(os.getpid())
    require(record['no_new_privileges'] and record['zero_capabilities'], 'worker_privileges', result='no_go')
    if real:
        uid, gid = identity_pair(role)
        require(record['uids'] == [uid] * 4 and record['gids'] == [gid] * 4 and not record['groups'],
                'worker_identity_mismatch', result='no_go')
    return record


def identity_pair(role):
    return SERVICE if role == 'broker' else THIRD if role == 'third' else DESKTOP


def error_check(error):
    if isinstance(error, QualificationError):
        return error.check, error.result
    if isinstance(error, EOFError):
        return 'approval_or_transport_interrupted', 'partial'
    if isinstance(error, KeyboardInterrupt):
        return 'operator_interruption', 'partial'
    if isinstance(error, subprocess.TimeoutExpired):
        return 'subprocess_timeout', 'partial'
    if isinstance(error, RegistryError):
        return 'fixture_storage_validation_failed', 'partial'
    if isinstance(error, sqlite3.DatabaseError):
        return 'fixture_sqlite_error', 'partial'
    if isinstance(error, OSError) and type(error.errno) is int and error.errno > 0:
        return f'fixture_os_error_{error.errno}', 'partial'
    return 'fixture_failure', 'partial'


def worker_main(role, run_id, root, bounds):
    real = bounds is None
    if real:
        require(root is None and os.geteuid() != 0, 'unexpected_worker_context')
        layout = layout_for(run_id)
        _, window = read_approval(layout, run_id)
        # The controller creates this marker exclusively before any worker starts.
        execution = json_file(layout.root / EXECUTION, owner=(0, 0))
        require(execution.keys() == {'controller', 'run_id'} and execution['run_id'] == run_id
                and os.getppid() == execution['controller']['pid']
                and process_record(os.getppid())['uids'] == [0] * 4
                and process_record(os.getppid())['start_ticks'] == execution['controller']['start_ticks'],
                'unapproved_worker_parent')
    else:
        require(root is not None and os.geteuid() != 0 and role != 'third', 'invalid_rehearsal_worker')
        layout = Layout(root)
        window = Window(*bounds)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    protect_process()
    channel = Pipe(0, 1, window)
    try:
        channel.reply(identity=check_worker_identity(role, real))
        startup = channel.receive()
        if role == 'broker':
            serve_control(layout, channel, window, DESKTOP[0] if real else os.geteuid(),
                          THIRD[0] if real else None, startup)
        else:
            desktop_control(layout, channel, window, 'executor' if role == 'executor_b' else role,
                            startup, real=real)
    except (Exception, KeyboardInterrupt) as error:
        check, classification = error_check(error)
        try:
            channel.send(dict(error=check, classification=classification))
        except (EOFError, OSError):
            pass
        return 1
    return 0


class Worker:
    def __init__(self, session, role):
        self.session, self.role = session, role
        args = ['/usr/bin/setpriv', '--no-new-privs', '--inh-caps=-all', '--ambient-caps=-all']
        if session.real:
            uid, gid = identity_pair(role)
            args += [f'--reuid={uid}', f'--regid={gid}', '--clear-groups', '--bounding-set=-all']
        args += ['/usr/bin/python3', '-I', '-S', '-B', '-c', BOOTSTRAP, str(SOURCE),
                 '--run-id', session.run_id, '_worker', role]
        if not session.real:
            args += ['--root', str(session.layout.root), '--bounds', str(session.window.wall_end),
                     str(session.window.monotonic_end)]
        self.process = subprocess.Popen(args, cwd='/', env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        close_fds=True)
        self.pidfd = None
        self.identity = None
        self.exit_recorded = False
        session.workers.append(self)
        self.pidfd = os.pidfd_open(self.process.pid)
        self.pipe = Pipe(self.process.stdout.fileno(), self.process.stdin.fileno(), session.window)
        self.identity = self.receive()['identity']
        require(self.identity == process_record(self.process.pid), 'worker_identity_mismatch', result='no_go')
        if session.real:
            uid, gid = identity_pair(role)
            require(self.identity['uids'] == [uid] * 4 and self.identity['gids'] == [gid] * 4
                    and self.identity['groups'] == [], 'worker_identity_mismatch', result='no_go')
        session.emit('process_started', role=role, **self.identity)

    def send(self, **data):
        self.pipe.send(data)

    def receive(self):
        value = self.pipe.receive()
        if value.keys() == {'error', 'classification'}:
            require(type(value['error']) is str and re.fullmatch('[a-z0-9_]+', value['error'])
                    and value['classification'] in ('partial', 'no_go'), 'invalid_worker_failure')
            raise QualificationError(value['error'], value['classification'])
        require(value.keys() == {'ok'} and type(value['ok']) is dict, 'invalid_worker_reply')
        return value['ok']

    def call(self, **data):
        self.send(**data)
        return self.receive()

    def kill(self, *, qualified=False):
        if self.process.poll() is not None:
            require(not qualified, 'broker_already_exited')
            return
        require(self.pidfd is not None, 'process_handle_unavailable')
        if qualified:
            require(self.role == 'broker' and process_record(self.process.pid) == self.identity,
                    'broker_identity_changed', result='no_go')
        try:
            signal.pidfd_send_signal(self.pidfd, signal.SIGKILL)
        except ProcessLookupError:
            require(not qualified, 'broker_already_exited')

    def finish(self, *, expected=None):
        code = self.process.wait(timeout=WAIT)
        if not self.exit_recorded:
            self.exit_recorded = True
            if self.pidfd is not None:
                require(bool(select.select([self.pidfd], [], [], 0)[0]), 'process_exit_unobserved')
                os.close(self.pidfd)
                self.pidfd = None
            self.process.stdin.close()
            self.process.stdout.close()
            self.process.stderr.close()
            self.session.emit('process_exited', role=self.role, pid=self.process.pid,
                              start_ticks=self.identity['start_ticks'] if self.identity else None, exit_code=code)
        require(expected is None or code == expected, 'unexpected_process_exit')
        return code


def socket_metadata(path, service, client_uid):
    info = check_metadata(path.lstat(), service, 0o620 if client_uid is not None else 0o600,
                          stat.S_ISSOCK, 'socket_metadata_changed')
    acl = named_user_acl(client_uid, 6, 2) if client_uid is not None else None
    require(read_acl(path) == acl, 'socket_acl_changed')
    return path_inode(info)


def listed_unix_endpoint(path):
    with open('/proc/net/unix') as proc:
        return any(line.split(maxsplit=7)[-1].strip() == str(path) for line in proc if line.strip())


def remove_stale_endpoint(path, pin, service, client_uid, *, exited, window=None):
    require(exited and socket_metadata(path, service, client_uid) == pin, 'stale_endpoint_identity_changed')
    require(not listed_unix_endpoint(path), 'unix_endpoint_still_listed')
    try:
        registry.connect_sentinel(path)
    except OSError as error:
        require(error.errno == errno.ECONNREFUSED, 'stale_endpoint_not_proven')
    else:
        raise QualificationError('stale_endpoint_has_live_listener')
    with trusted_directory(path.parent) as directory:
        require(socket_metadata(path, service, client_uid) == pin and not listed_unix_endpoint(path)
                and path_inode(os.stat(path.name, dir_fd=directory, follow_symlinks=False)) == pin,
                'stale_endpoint_identity_changed')
        if window is not None:
            window.budget()
        os.unlink(path.name, dir_fd=directory)


class Evidence:
    def __init__(self, output, *, mode, run_id, secrets=()):
        self.output, self.mode, self.run_id, self.secrets = output, mode, run_id, tuple(secrets)
        self.number = 0

    def __call__(self, event, **fields):
        require(any(fields.keys() == set(shape.split()) for shape in EVENT_FIELDS.get(event, ())),
                'invalid_evidence_event')
        number = self.number + 1
        row = dict(schema=SCHEMA, mode=self.mode, run_id=self.run_id, sequence=number, event=event,
                   wall_unix_ns=time_ns(), monotonic_ns=monotonic_ns(), **fields)
        raw = json.dumps(row, sort_keys=True, allow_nan=False)
        for hidden in (*self.secrets, CONTENT.strip(), DIVERGENT.strip(), OBJECTIVE_TEXT):
            require(hidden not in raw, 'secret_in_evidence', result='no_go')
        self.output.write(raw + '\n')
        self.output.flush()
        self.number = number


class Session:
    def __init__(self, layout, run_id, window, output, *, real, marker=None):
        self.layout, self.run_id, self.window, self.real, self.marker = layout, run_id, window, real, marker
        self.service = SERVICE if real else (os.geteuid(), os.getegid())
        self.uid_acl = DESKTOP[0] if real else None
        self.tokens = {role: token_urlsafe(32) for role in (*ACTORS, 'invalid')}
        if real:
            self.tokens['third'] = self.tokens['other']
        self.verifiers = {subject: sha256(self.tokens[role].encode()).hexdigest() for role, subject in ACTORS.items()}
        self.emit = Evidence(output, mode='actual' if real else 'rehearsal', run_id=run_id,
                             secrets=(*self.tokens.values(), *self.verifiers.values()))
        self.workers, self.clients, self.totals = [], {}, {}
        self.pins = self.broker = self.previous_pid = None
        self.generation = 0
        self.generation_pids = set()

    def start(self):
        if self.real:
            read_marker(self.layout, self.run_id)
        self.generation += 1
        self.broker = Worker(self, 'broker')
        pid = self.broker.process.pid
        require(pid not in self.generation_pids, 'broker_pid_reused', result='no_go')
        self.generation_pids.add(pid)
        self.broker.send(verifiers=self.verifiers, pins=self.pins)
        ready = self.broker.receive()
        require(ready.keys() == {'pins', 'private_fd', 'proof'}
                and type(ready['private_fd']) is int and ready['private_fd'] > 2, 'invalid_broker_startup')
        self.endpoint_pin = socket_metadata(self.layout.endpoint, self.service, self.uid_acl)
        self.private_fd = ready['private_fd']
        if self.pins is None:
            self.pins = ready['pins']
            self.verifier = Verifier(self.layout, self.pins, self.service)
        else:
            require(self.pins == ready['pins'], 'restart_pins_changed', result='no_go')
        storage = self.verifier.policy_and_storage()
        if self.real:
            path = Path(f'/proc/{pid}/fd/{self.private_fd}')
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                require(list(path_inode(os.fstat(fd))) == storage['private'], 'private_descriptor_not_verified')
                require({DATABASE, POLICY_FILE} <= set(os.listdir(fd)), 'private_storage_not_verified')
            finally:
                os.close(fd)
        self.emit('broker_ready', generation=self.generation, pid=pid, previous_pid=self.previous_pid,
                  private_fd=self.private_fd, socket_pin=self.endpoint_pin, storage_pins=storage)
        self.counts(ready['proof'], terminal=False, recovery=True)
        for role in WORKERS:
            if role in ('admin', 'other', 'executor_b') and self.generation > 1:
                continue
            self.clients[role] = self.client(role)

    def client(self, role):
        worker = Worker(self, role)
        token = self.tokens['executor' if role == 'executor_b' else role]
        worker.send(token=token, peer=[self.broker.process.pid, *self.service], private_fd=self.private_fd)
        return worker

    def admin(self, op, name=None, **fields):
        params = fields | ({} if name is None else {'case': name})
        return self.broker.call(op=op, **params)

    def close_client(self, role):
        worker = self.clients.pop(role)
        worker.call(op='stop')
        worker.finish(expected=0)

    def close_clients(self):
        for role in tuple(self.clients):
            self.close_client(role)

    def ingress(self, *, initial):
        executor = self.clients['executor']
        valid = executor.call(op='authenticate')
        invalid = self.clients['invalid'].call(op='authenticate')
        observed = self.admin('snapshot')['proof']['peers']
        client_uid, client_gid = DESKTOP if self.real else self.service
        require([executor.process.pid, client_uid, client_gid] in observed
                and [self.clients['invalid'].process.pid, client_uid, client_gid] in observed
                and valid == invalid == dict(broker_peer=[self.broker.process.pid, *self.service],
                                             uid=client_uid, ancillary=False),
                'kernel_peer_mismatch', result='no_go')
        self.emit('kernel_ingress', generation=self.generation, client_peer=[executor.process.pid, client_uid, client_gid],
                  service_peer=valid['broker_peer'], invalid_credential_denied=True, no_ancillary=True)
        if not self.real:
            self.emit('non_admitted_peer', outcome='NOT RUN', generation=self.generation)
        elif initial:
            self.admin('challenge_begin')
            path = self.layout.challenge / CHALLENGE
            pin = socket_metadata(path, SERVICE, THIRD[0])
            worker = self.client('third')
            result = worker.call(op='third')
            observed = self.admin('snapshot')['proof']['peers']
            require([worker.process.pid, *THIRD] in observed and result['nominal_errno'] in registry.DENIALS
                    and result['rpc_code'] == -32001, 'third_peer_evidence_incomplete')
            worker.call(op='stop')
            worker.finish(expected=0)
            self.admin('challenge_end')
            require(not os.path.lexists(path) and not listed_unix_endpoint(path), 'challenge_endpoint_retained')
            self.emit('non_admitted_peer', generation=self.generation, peer=[worker.process.pid, *THIRD],
                      nominal_errno=result['nominal_errno'], rpc_code=result['rpc_code'], socket_pin=pin)

    def direct(self, name, edge, operation):
        if not self.real:
            self.emit('direct_access', case=name, edge=edge, outcome='NOT RUN')
            return
        self.verifier.policy_and_storage()
        worker = self.clients['executor']
        result = worker.call(op='direct', case=name, edge=edge, operation=operation)
        expected = {'private_traversal', 'private_listing', 'resource_traversal', 'resource_listing',
                    'sqlite_read', 'policy_read', 'proc_private_descriptor', 'staged_file_read'}
        expected |= {'direct_document_create'} if edge in ('staged', 'restart_staged') else {
            'final_read', 'final_open_write', 'additional_entry_create'}
        require(result.keys() == {'denials'} and result['denials'].keys() == expected
                and all(code in registry.DENIALS for code in result['denials'].values()), 'direct_evidence_incomplete')
        self.emit('direct_access', case=name, edge=edge, outcome='denied', executor_pid=worker.process.pid,
                  operation=operation, **result)

    def counts(self, proof, *, terminal, recovery=False, must_be_zero=(), accumulate=False):
        require(proof.keys() == {'untracked', 'operations', 'calls', 'links', 'peers'}
                and proof['untracked'] == 0, 'untracked_publication', result='no_go')
        operations, calls, links = (proof[key] for key in ('operations', 'calls', 'links'))
        require(calls.keys() <= operations.keys() and links.keys() <= calls.keys()
                and all(name in CASES for name in operations.values())
                and len(set(operations.values())) == len(operations), 'untracked_publication', result='no_go')
        require(all(type(value) is int and value == 1 and operations[key] not in NO_CALL
                    and operations[key] not in must_be_zero for key, value in calls.items())
                and all(type(value) is int and value == 1 for value in links.values()),
                'unexpected_publication_count', result='no_go')
        for operation, name in operations.items():
            entry, _ = self.verifier.durable(name)
            require(entry['operation_id'] == operation, 'publication_counter_attribution', result='no_go')
        if recovery:
            require(not calls and not links, 'publication_called_during_recovery', result='no_go')
        total = self.totals.copy()
        for operation, value in calls.items():
            name = operations[operation]
            require(name not in total, 'duplicate_publication', result='no_go')
            if terminal or accumulate:
                require(value == links.get(operation), 'publication_evidence_incomplete')
            total[name] = dict(operation=operation, calls=value, links=links.get(operation, 0))
        if terminal:
            require(total.keys() == CASES.keys() - NO_CALL, 'publication_evidence_incomplete')
        if accumulate:
            self.totals = total
        self.emit('publication_counters', generation=self.generation, recovery=recovery,
                  tracked_operations=operations, calls=calls, links=links, untracked=proof['untracked'],
                  **({'total': total, 'expected_zero': sorted(NO_CALL)} if terminal else
                     {'expected_zero': sorted(must_be_zero)} if must_be_zero else {}))

    def interrupt(self, pending, name):
        identity = self.broker.identity
        self.previous_pid = identity['pid']
        self.counts(self.admin('snapshot')['proof'], terminal=False, accumulate=True)
        self.window.budget()
        self.broker.kill(qualified=True)
        self.broker.finish(expected=-signal.SIGKILL)
        observed = pending.receive()
        require(observed in ({'transport_interrupted': 'eof'}, {'transport_interrupted': 'reset'}),
                'interrupted_publication_returned_success', result='no_go' if 'result' in observed else 'partial')
        self.emit('broker_interrupted', case=name, pid=self.previous_pid, signal=signal.SIGKILL,
                  client_transport=observed['transport_interrupted'])

    def restart(self):
        self.window.budget()
        self.close_clients()
        if self.real:
            read_marker(self.layout, self.run_id)
        remove_stale_endpoint(self.layout.endpoint, self.endpoint_pin, self.service, self.uid_acl,
                              exited=self.broker.process.returncode == -signal.SIGKILL, window=self.window)
        self.emit('stale_endpoint_removed', generation=self.generation, pid=self.previous_pid,
                  endpoint_pin=self.endpoint_pin, verified_exit=True, listener_absent=True)
        self.start()

    def graceful(self):
        self.close_clients()
        self.admin('stop')
        self.broker.finish(expected=0)
        require(not os.path.lexists(self.layout.endpoint) and not listed_unix_endpoint(self.layout.endpoint),
                'active_endpoint_retained')

    def counter_failure(self):
        if self.broker is None or self.broker.process.poll() is not None or not self.window.remaining():
            return None
        try:
            snapshot = self.admin('snapshot')['proof']
            self.counts(snapshot, terminal=False)
        except QualificationError as error:
            return error if error.result == 'no_go' else None
        except (EOFError, OSError, KeyError, TypeError, ValueError, RegistryError, sqlite3.DatabaseError):
            pass
        return None

    def emergency_stop(self):
        complete = True
        for worker in self.workers:
            try:
                worker.kill()
            except (OSError, QualificationError):
                complete = False
        for worker in self.workers:
            try:
                worker.finish()
            except (OSError, QualificationError, subprocess.TimeoutExpired):
                complete = False
        return complete


def run_session(layout, run_id, window, output, *, real, marker=None):
    session = Session(layout, run_id, window, output, real=real, marker=marker)
    session.emit('run_started', fixture=marker, linux_isolation='pending' if real else 'NOT RUN',
                 wall_deadline=window.wall_end, monotonic_deadline=window.monotonic_end)
    result = 'partial'
    try:
        session.start()
        Flow(session, session.emit).run()
        session.graceful()
        result = 'pending_operator_review' if real else 'rehearsal_passed'
    except (Exception, KeyboardInterrupt) as error:
        check, result = error_check(error)
        session.emit('failure', check=check, classification=result)
        counter = session.counter_failure()
        if counter:
            result = 'no_go'
            session.emit('failure', check=counter.check, classification=result)
    finally:
        if not session.emergency_stop():
            session.emit('failure', check='process_stop_unverified', classification='partial')
            if result != 'no_go':
                result = 'partial'
        if real:
            write_json(layout.root / LIFECYCLE, dict(pins=session.pins, processes=[
                dict(role=w.role, identity=w.identity, pid=w.process.pid, exit_code=w.process.returncode)
                for w in session.workers], endpoint_pin=getattr(session, 'endpoint_pin', None)), mode=0o600)
        session.emit('execution_finished', classification=result, gate_E='pending_operator_review' if real else 'NOT RUN')
    return 0 if result in ('pending_operator_review', 'rehearsal_passed') else 1


def rehearse(run_id):
    require(os.geteuid() != 0, 'rehearsal_requires_non_root')
    with TemporaryDirectory(prefix='loop-d2c2-') as path:
        layout = Layout(Path(path))
        layout.private.mkdir(mode=0o700)
        layout.ingress.mkdir(mode=0o700)
        return run_session(layout, run_id, Window(time() + 120, monotonic() + 120), sys.stdout, real=False)


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', default='0000000000000000')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('plan')
    commands.add_parser('rehearse')
    worker = commands.add_parser('_worker', help=SUPPRESS)
    worker.add_argument('role', choices=('broker', *WORKERS, 'third'))
    worker.add_argument('--root', type=Path)
    worker.add_argument('--bounds', nargs=2, type=float)
    from tools.workspace_cross_uid_operator import add_operator_commands, operator_command

    add_operator_commands(commands)
    args = parser.parse_args(argv)
    try:
        layout = layout_for(args.run_id)
        if args.command in (None, 'plan'):
            registry.emit('plan', schema=SCHEMA, status='PREPARED / NOT EXECUTED', run_id=args.run_id,
                          fixture=str(layout.root), broker=list(SERVICE), executor=list(DESKTOP),
                          proposed_non_admitted_peer=list(THIRD), real_cross_uid='NOT RUN')
            return 0
        if args.command == '_worker':
            return worker_main(args.role, args.run_id, args.root, args.bounds)
        if args.command == 'rehearse':
            return rehearse(args.run_id)
        return operator_command(args, layout)
    except (Exception, KeyboardInterrupt) as error:
        check, classification = error_check(error)
        if args.command != '_worker':
            registry.emit('failure', check=check, classification=classification)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
