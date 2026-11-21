# SPDX-License-Identifier: Apache-2.0
"""Local, explicitly authorized bootstrap of a fresh dedicated service.

Production entrypoints are reachable only through the verified installed
launcher. These helpers accept paths for temporary unprivileged tests; the
launcher supplies fixed production locations, never user-selected paths.
"""
from contextlib import contextmanager, ExitStack, closing
import fcntl
import json
import os
from pathlib import Path
import resource
import secrets
import socket
import stat
import subprocess
import sys

from .identity import Identities
from .process_boundary import protect_process, close_bootstrap_stdin
from .protocol import Fault, RPC, unique_object
from .service_ingress import DEFAULT_ACL, peer_uid, read_acl

ADMIN = Path('/var/lib/loopbridge-admin')
CREDENTIALS = Path('/etc/loopbridge/credentials')
STATE = Path('/var/lib/loopbridge')
RUNTIME = Path('/run/loopbridge-private')
OWNER_FILE = 'owner.token'
MANIFEST_FILE = 'manager-verifiers.json'
REGISTRY_FILE = 'verifiers.json'


def protect_admin_process():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    protect_process()


@contextmanager
def protected_directory(path, uid, gid):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid
                or info.st_gid != gid or stat.S_IMODE(info.st_mode) != 0o700
                or read_acl(fd) is not None or read_acl(fd, DEFAULT_ACL) is not None):
            raise ValueError('unsafe_admin_directory')
        yield fd
    finally:
        os.close(fd)


def publish_new(directory, name, data, uid, gid):
    """Publish one exclusively created, synced file without replacing a path."""
    temporary = '.bootstrap-' + secrets.token_hex(16)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchown(output.fileno(), uid, gid)
            os.fchmod(output.fileno(), 0o600)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory,
                follow_symlinks=False)
    finally:
        os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)


def json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode() + b'\n'


def initialize(admin, credentials, state, runtime, service_uid, service_gid,
               *, admin_uid=0, admin_gid=0):
    """Fresh install only; no reset, repair, re-enrollment or overwrite."""
    if os.path.lexists(runtime):
        raise ValueError('service_runtime_present')
    with ExitStack() as stack:
        admin_fd = stack.enter_context(protected_directory(admin, admin_uid, admin_gid))
        cred_fd = stack.enter_context(protected_directory(credentials, admin_uid, admin_gid))
        state_fd = stack.enter_context(protected_directory(state, service_uid, service_gid))
        handles = (admin_fd, cred_fd, state_fd)
        inodes = {(os.fstat(fd).st_dev, os.fstat(fd).st_ino) for fd in handles}
        if len(inodes) != len(handles):
            raise ValueError('overlapping_bootstrap_directories')
        for fd in handles:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if any(os.listdir(fd) for fd in handles) or os.path.lexists(runtime):
            raise ValueError('bootstrap_not_fresh')
        identities = Identities()
        tokens = identities.provision()
        # The manager uses only owner authority. Other required digests are
        # independently generated; the corresponding bearers are not retained.
        publish_new(admin_fd, OWNER_FILE, tokens['owner'].encode() + b'\n',
                    admin_uid, admin_gid)
        publish_new(cred_fd, MANIFEST_FILE, json_bytes(identities.manifest()),
                    admin_uid, admin_gid)
        # Publish the required service-owned seed last. An interrupted install
        # leaves evidence and refuses another initialize; never auto-repair.
        publish_new(state_fd, REGISTRY_FILE,
                    json_bytes({'version': 1, 'manager': None, 'used': []}),
                    service_uid, service_gid)


def read_protected(directory, name, uid, gid, limit):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != uid or info.st_gid != gid
                or stat.S_IMODE(info.st_mode) != 0o600 or read_acl(source.fileno()) is not None):
            raise ValueError('unsafe_admin_file')
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError('oversized_admin_file')
    return data


def owner_input(data):
    if (len(data) != 44 or not data.endswith(b'\n')
            or any(c not in b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-'
                   for c in data[:-1])):
        raise ValueError('invalid_admin_credential')
    return data[:-1].decode('ascii')


@contextmanager
def private_owner(endpoint, token, uid, gid, *, manager=False):
    with protected_directory(endpoint.parent, uid, gid):
        info = endpoint.lstat()
        if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != uid or info.st_gid != gid
                or stat.S_IMODE(info.st_mode) != 0o600 or read_acl(endpoint) is not None):
            raise ValueError('unsafe_private_admin_endpoint')
        with closing(socket.socket(socket.AF_UNIX)) as peer:
            peer.settimeout(3)
            peer.connect(str(endpoint))
            if peer_uid(peer) != uid:
                raise ValueError('unexpected_admin_peer')
            rpc = RPC(peer)
            auth = rpc.call('auth', credential=token)
            if (type(auth) is not dict or auth.get('principal') != 'owner'
                    or manager and auth != {'principal': 'owner'}):
                raise ValueError('unexpected_admin_auth')
            yield rpc


def manager_readiness(runtime, token, service_uid, service_gid):
    """Only two read-only RPCs; no general administrative command forwarding."""
    with private_owner(runtime / 'manager.sock', token, service_uid, service_gid, manager=True) as rpc:
        result = rpc.call('private.list')
        if (type(result) is not dict or set(result) != {'instances'}
                or type(result['instances']) is not list or result['instances']):
            raise ValueError('manager_not_empty')


def require_root():
    if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (0, 0, 0, 0):
        raise ValueError('root_administration_required')


def admin_initialize(uid, gid):
    require_root()
    protect_admin_process()
    initialize(ADMIN, CREDENTIALS, STATE, RUNTIME, uid, gid)


def checked_owner_data(admin_fd):
    data = read_protected(admin_fd, OWNER_FILE, 0, 0, 44)
    with protected_directory(CREDENTIALS, 0, 0) as credential_fd:
        raw = read_protected(credential_fd, MANIFEST_FILE, 0, 0, 4096)
    identities = Identities()
    identities.load_manifest(json.loads(raw, object_pairs_hook=unique_object))
    try:
        if identities.authenticate(owner_input(data)) != 'owner':
            raise ValueError('admin_manifest_mismatch')
    except Fault:
        raise ValueError('admin_manifest_mismatch') from None
    return data


def run_service_client(release, digest, uid, gid, data, action, *,
                       arguments=(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=15):
    # The installed launcher revalidates the exact release in the child.
    # No shell, no inherited supplementary groups, no bearer in argv or env.
    return subprocess.run(
        ['/usr/bin/python3', '-I', '-B', str(release / 'launcher.py'),
         '--manifest-sha256', digest, '--action', action, *arguments],
        input=data, stdout=stdout, stderr=stderr,
        user=uid, group=gid, extra_groups=[], cwd='/',
        env={'PATH': '/usr/bin', 'LANG': 'C.UTF-8'},
        start_new_session=True, close_fds=True, timeout=timeout, check=False)


def admin_ready(release, digest, uid, gid):
    require_root()
    protect_admin_process()
    with protected_directory(ADMIN, 0, 0) as admin_fd:
        data = checked_owner_data(admin_fd)
    try:
        result = run_service_client(release, digest, uid, gid, data, 'ready-client')
    except subprocess.SubprocessError:
        raise ValueError('manager_readiness_failed') from None
    if result.returncode != 0:
        raise ValueError('manager_readiness_failed')


def service_client_token(uid, gid):
    if (not uid or os.getuid() != uid or os.geteuid() != uid
            or os.getgid() != gid or os.getegid() != gid or os.getgroups()):
        raise ValueError('dedicated_admin_client_identity_required')
    protect_admin_process()
    try:
        token = owner_input(sys.stdin.buffer.read(45))
    finally:
        close_bootstrap_stdin()
    return token


def ready_client(uid, gid):
    token = service_client_token(uid, gid)
    try:
        manager_readiness(RUNTIME, token, uid, gid)
    except (Fault, AssertionError, EOFError, KeyError, TypeError):
        raise ValueError('manager_readiness_failed') from None
