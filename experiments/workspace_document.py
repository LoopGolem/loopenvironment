# SPDX-License-Identifier: Apache-2.0
"""Fixed D.2C.1 adapter for an enrolled, creation-only workspace document."""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from hashlib import sha256
import os
import stat

from experiments.objective_registry import RegistryError
from experiments.registry_rpc import OPAQUE_ID, _matches
from experiments.registry_storage import private_registry_directory
from loopbridge.authority import fail
from loopbridge.service_ingress import path_inode

CAPABILITY = 'workspace.document.create'
MAX_CONTENT = 1024
FINAL = 'document.txt'
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class ResourceConflict(Exception):
    """A pinned resource or its creation precondition no longer matches."""


class DestinationExists(ResourceConflict):
    """The final name is occupied, including by a symlink."""


def valid_pin(pin):
    return (type(pin) is tuple and len(pin) == 2
            and all(type(value) is int and value >= 0 for value in pin))


def stage_name(operation_id):
    return '.stage-' + operation_id


def resource_path(root, resource_id):
    if not _matches(OPAQUE_ID, resource_id):
        raise ValueError('invalid_workspace_resource_id')
    return root / ('workspace-' + resource_id)


def enroll_workspace(root, resource_id):
    """Trusted bootstrap into a fresh directory. Runtime never creates or repins it."""
    path = resource_path(root, resource_id)
    with private_registry_directory(root) as parent:
        os.mkdir(path.name, mode=0o700, dir_fd=parent.fd)
        with private_registry_directory(path) as resource:
            os.fsync(resource.fd)
            os.fsync(parent.fd)
            return resource.identity


@dataclass(frozen=True)
class Observation:
    evidence: str
    synchronized: bool = False


class DocumentCreate:
    """Fixed adapter. Inspection opens the filesystem names independently of apply()."""

    def __init__(self, root, resources):
        self.root = root
        self.resources = dict(resources)

    @staticmethod
    def validate_request(content):
        if type(content) is str and 0 < len(content) <= MAX_CONTENT and '\0' not in content:
            try:
                data = content.encode('utf-8')
                if len(data) <= MAX_CONTENT:
                    return data
            except UnicodeError:
                pass
        fail('invalid_params', -32602)

    @contextmanager
    def resource(self, resource_id, expected=None):
        pin = self.resources.get(resource_id)
        if pin is None or (expected is not None and pin != expected):
            raise ResourceConflict
        with ExitStack() as stack:
            try:
                directory = stack.enter_context(private_registry_directory(resource_path(self.root, resource_id)))
            except RegistryError:
                raise ResourceConflict from None
            if directory.identity != pin:
                raise ResourceConflict
            yield directory

    @staticmethod
    def _stat(resource, name):
        try:
            return os.stat(name, dir_fd=resource.fd, follow_symlinks=False)
        except FileNotFoundError:
            return None

    @staticmethod
    def _regular(resource, info, links, size):
        return (info is not None and stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_dev == resource.identity[0]
                and info.st_nlink == links and info.st_size == size)

    def require_vacant(self, resource):
        try:
            resource.check()
            if self._stat(resource, FINAL) is not None:
                raise DestinationExists
        except (RegistryError, OSError):
            raise ResourceConflict from None

    def prepare(self, resource, operation_id, data):
        self.require_vacant(resource)
        flags = os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_CREAT | os.O_EXCL
        fd = os.open(stage_name(operation_id), flags, 0o600, dir_fd=resource.fd)
        with os.fdopen(fd, 'wb') as target:
            target.write(data)
            target.flush()
            info = os.fstat(target.fileno())
            if not self._regular(resource, info, 1, len(data)):
                raise ResourceConflict
            os.fsync(target.fileno())
        os.fsync(resource.fd)
        resource.check()
        return path_inode(info)

    @staticmethod
    def _version(info):
        return info.st_ctime_ns, info.st_mtime_ns

    def validate_staged_payload(self, resource, operation_id, stage_pin, size, digest):
        # Read outside the policy lock. The fence checks that this file version is still named.
        try:
            fd = os.open(stage_name(operation_id), READ_FLAGS, dir_fd=resource.fd)
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                if (not self._regular(resource, info, 1, size) or path_inode(info) != stage_pin
                        or sha256(source.read(MAX_CONTENT + 1)).hexdigest() != digest
                        or self._version(os.fstat(source.fileno())) != self._version(info)):
                    raise ResourceConflict
                return self._version(info)
        except OSError:
            raise ResourceConflict from None

    def validate_publication(self, resource, operation_id, stage_pin, size, version):
        self.require_vacant(resource)
        try:
            stage = self._stat(resource, stage_name(operation_id))
        except OSError:
            raise ResourceConflict from None
        if (not self._regular(resource, stage, 1, size) or path_inode(stage) != stage_pin
                or self._version(stage) != version):
            raise ResourceConflict

    @staticmethod
    def apply(resource, operation_id):
        # Linux linkat is atomic and fails if the final name already exists.
        os.link(stage_name(operation_id), FINAL, src_dir_fd=resource.fd,
                dst_dir_fd=resource.fd, follow_symlinks=False)

    def _attributed(self, resource, operation_id, stage_pin, size):
        entries = (self._stat(resource, name) for name in (FINAL, stage_name(operation_id)))
        return all(self._regular(resource, info, 2, size) and path_inode(info) == stage_pin
                   for info in entries)

    def inspect(self, resource, operation_id, stage_pin, size, digest):
        """Observe the final name, operation's retained link, file identity and bytes."""
        resource.check()
        if self._stat(resource, FINAL) is None:
            return Observation('absent')
        if not self._attributed(resource, operation_id, stage_pin, size):
            return Observation('conflicting')
        fd = os.open(FINAL, READ_FLAGS, dir_fd=resource.fd)
        with os.fdopen(fd, 'rb') as source:
            before = os.fstat(source.fileno())
            if (not self._regular(resource, before, 2, size) or path_inode(before) != stage_pin
                    or sha256(source.read(MAX_CONTENT + 1)).hexdigest() != digest):
                return Observation('conflicting')
            if not self._unchanged(resource, source, before, operation_id, stage_pin, size):
                return Observation('conflicting')
            # Observation survives a synchronization error. Recovery may verify again.
            try:
                self.synchronize(resource, source.fileno())
            except OSError:
                return Observation('matching')
            if not self._unchanged(resource, source, before, operation_id, stage_pin, size):
                return Observation('conflicting')
        return Observation('matching', synchronized=True)

    def _unchanged(self, resource, source, before, operation_id, stage_pin, size):
        resource.check()
        after = os.fstat(source.fileno())
        return (self._version(before) == self._version(after)
                and self._attributed(resource, operation_id, stage_pin, size))

    @staticmethod
    def synchronize(resource, fd):
        os.fsync(fd)
        os.fsync(resource.fd)
