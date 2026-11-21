# SPDX-License-Identifier: Apache-2.0
"""Credential handoff and persistent enrollment for the dedicated Linux service."""
from dataclasses import dataclass
from itertools import combinations
import json
import os
from pathlib import Path
import stat
import tempfile

from .identity import Identities, VERIFIER
from .protocol import unique_object
from .service import Journal, private_directory
from .service_ingress import DEFAULT_ACL, CrossUIDIngress, named_user_acl, read_acl

CREDENTIALS_DIRECTORY = Path('/run/credentials/loopbridge.service')
CREDENTIAL_NAME = 'manager-verifiers.json'
MANIFEST_LIMIT = 4096
REGISTRY_LIMIT = 1024 * 1024
HELPERS = ('effects', 'stream')


def check_systemd_object(fd, directory, service_uid):
    info = os.fstat(fd)
    owner = 5 if directory else 4
    if (not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or not directory and info.st_nlink != 1
            or not os.fstatvfs(fd).f_flag & os.ST_RDONLY):
        raise ValueError('unsafe_systemd_credential')
    if info.st_uid == 0:
        expected_mode = (owner << 6) | (owner << 3)
        expected_acl = named_user_acl(service_uid, owner, owner)
    elif info.st_uid == service_uid:
        expected_mode = owner << 6
        expected_acl = None
    else:
        raise ValueError('unsafe_systemd_credential_owner')
    if stat.S_IMODE(info.st_mode) != expected_mode or read_acl(fd) != expected_acl:
        raise ValueError('unsafe_systemd_credential_access')


def load_systemd_manifest():
    """Only accept the unit's fixed, read-only systemd credential store."""
    directory = CREDENTIALS_DIRECTORY
    if os.environ.get('CREDENTIALS_DIRECTORY') != str(directory):
        raise ValueError('missing_systemd_credentials')
    for parent in directory.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('unsafe_systemd_credential_parent')
    return read_credential_manifest(directory, os.geteuid())


def read_credential_manifest(directory, uid):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        check_systemd_object(fd, True, uid)
        cred = os.open(CREDENTIAL_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(cred, 'rb') as stream:
            check_systemd_object(stream.fileno(), False, uid)
            data = stream.read(MANIFEST_LIMIT + 1)
    finally:
        os.close(fd)
    if len(data) > MANIFEST_LIMIT:
        raise ValueError('systemd_credential_too_large')
    identities = Identities()
    identities.load_manifest(json.loads(data, object_pairs_hook=unique_object))
    return identities.manifest()


class VerifierRegistry:
    """Protected state under the manager's lifetime lock; reserve before launch."""

    def __init__(self, state):
        self.path = state / 'verifiers.json'
        self.failed = False
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600):
                raise ValueError('unsafe_verifier_registry')
            raw = stream.read(REGISTRY_LIMIT + 1)
        if len(raw) > REGISTRY_LIMIT:
            raise ValueError('verifier_registry_full')
        data = json.loads(raw, object_pairs_hook=unique_object)
        if (type(data) is not dict or set(data) != {'version', 'manager', 'used'}
                or type(data['version']) is not int or data['version'] != 1
                or type(data['used']) is not list
                or any(type(value) is not str or not VERIFIER.fullmatch(value) for value in data['used'])
                or len(set(data['used'])) != len(data['used'])):
            raise ValueError('invalid_verifier_registry')
        self.manager = data['manager']
        self.used = set(data['used'])
        if self.manager is None:
            if self.used:
                raise ValueError('invalid_verifier_registry')
        else:
            Identities().load_verifiers(self.manager)
            if not set(self.manager.values()) <= self.used:
                raise ValueError('invalid_verifier_registry')

    def record(self, active, used):
        if self.failed:
            raise OSError('verifier_registry_unavailable')
        data = json.dumps({'version': 1, 'manager': active, 'used': sorted(used)},
                          separators=(',', ':')).encode() + b'\n'
        if len(data) > REGISTRY_LIMIT:
            raise OSError('verifier_registry_full')
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix='.verifiers-', delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                    os.replace(temporary, self.path)
                    Journal(self.path.parent).sync()
                finally:
                    temporary.unlink(missing_ok=True)
        except OSError:
            self.failed = True
            raise
        self.manager, self.used = active, used

    def enroll_manager(self, manifest):
        verifiers = manifest['verifiers']
        if verifiers == self.manager:
            return
        incoming = set(verifiers.values())
        if self.used & incoming:
            raise ValueError('reused_manager_verifier')
        self.record(verifiers, self.used | incoming)

    def reserve_session(self, verifiers):
        if self.used & verifiers:
            return False
        self.record(self.manager, self.used | verifiers)
        return True


@dataclass(frozen=True)
class HardenedService:
    ingress: CrossUIDIngress
    state: Path
    helpers: Path

    def validate(self, runtime):
        if (not isinstance(self.ingress, CrossUIDIngress) or self.ingress.private_root != runtime
                or not isinstance(self.state, Path) or not isinstance(self.helpers, Path)
                or not self.state.is_absolute()
                or self.state.resolve(strict=True) != self.state
                or not self.helpers.is_absolute() or self.helpers.resolve(strict=True) != self.helpers):
            raise ValueError('invalid_hardened_service_layout')
        roots = (runtime, self.state, self.ingress.directory, self.helpers)
        if any(a == b or a in b.parents or b in a.parents for a, b in combinations(roots, 2)):
            raise ValueError('overlapping_hardened_service_paths')
        for path in (runtime, self.state):
            private_directory(path, create=False)
            if path.stat().st_gid != os.getegid() or read_acl(path, DEFAULT_ACL) is not None:
                raise ValueError('unsafe_service_directory')
        self.ingress.validate()
        self.require_helpers()

    def require_helpers(self):
        for name in HELPERS:
            path = self.helpers / name
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
                    or stat.S_IMODE(info.st_mode) != 0o755
                    or not executable_helper(path)):
                raise ValueError('invalid_release_helper')


def executable_helper(path):
    return (path.is_file() and os.access(path, os.X_OK)
            and not os.statvfs(path).f_flag & os.ST_NOEXEC)
