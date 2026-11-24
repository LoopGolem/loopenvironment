# SPDX-License-Identifier: Apache-2.0
"""Filesystem checks for the restricted Registry profile on Linux."""
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import stat
from time import time

from experiments.durable_objective_registry import SQLiteRegistry
from experiments.objective_registry import Error, RegistryError
from loopbridge.service_ingress import DEFAULT_ACL, path_inode, read_acl

DATABASE = 'registry.sqlite3'


def _unsafe():
    return RegistryError(Error.STORAGE_UNAVAILABLE)


@contextmanager
def trusted_directory(path):
    """Open each component without following symlinks or trusting writable ancestors."""
    if not isinstance(path, Path) or not path.is_absolute() or '..' in path.parts or len(path.parts) < 2:
        raise _unsafe()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    uid = os.geteuid()
    try:
        fd = os.open('/', flags)
        try:
            for name in path.parts[1:]:
                info = os.fstat(fd)
                sticky_root = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
                if info.st_uid not in (0, uid) or (info.st_mode & 0o022 and not sticky_root):
                    raise _unsafe()
                child = os.open(name, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd
        finally:
            os.close(fd)
    except OSError:
        raise _unsafe() from None


@dataclass(frozen=True)
class DatabasePin:
    directory: tuple[int, int]
    file: tuple[int, int]

    def __post_init__(self):
        if any(type(pair) is not tuple or len(pair) != 2
               or any(type(number) is not int or number < 0 for number in pair)
               for pair in (self.directory, self.file)):
            raise ValueError('invalid_registry_database_pin')


class PrivateRegistryDirectory:
    def __init__(self, path, fd):
        info = os.fstat(fd)
        if (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700
                or read_acl(fd, DEFAULT_ACL) is not None):
            raise _unsafe()
        self.path = path
        self.fd = fd
        self.identity = path_inode(info)

    def stat_file(self, name, *, optional=False):
        try:
            info = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            if optional:
                return None
            raise _unsafe() from None
        except OSError:
            raise _unsafe() from None
        self._check_file(info)
        return info

    def _check_file(self, info):
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or info.st_dev != self.identity[0]):
            raise _unsafe()

    def check(self):
        with trusted_directory(self.path) as fd:
            info = os.fstat(fd)
            if (path_inode(info) != self.identity or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o700 or read_acl(fd, DEFAULT_ACL) is not None):
                raise _unsafe()

    def read(self, name, limit):
        self.check()
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        try:
            fd = os.open(name, flags, dir_fd=self.fd)
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                self._check_file(info)
                if info.st_size > limit:
                    raise _unsafe()
                content = source.read(limit + 1)
                if len(content) > limit or path_inode(self.stat_file(name)) != path_inode(info):
                    raise _unsafe()
            self.check()
            return content
        except OSError:
            raise _unsafe() from None

    def check_database(self, pin):
        self.check()
        if DatabasePin(self.identity, path_inode(self.stat_file(DATABASE))) != pin:
            raise _unsafe()
        self.stat_file(DATABASE + '-journal', optional=True)
        for suffix in ('-wal', '-shm'):
            if self.stat_file(DATABASE + suffix, optional=True) is not None:
                raise _unsafe()


    @contextmanager
    def hold_database(self, pin):
        self.check_database(pin)
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        fd = os.open(DATABASE, flags, dir_fd=self.fd)
        try:
            info = os.fstat(fd)
            self._check_file(info)
            if path_inode(info) != pin.file:
                raise _unsafe()
            yield
        finally:
            os.close(fd)


@contextmanager
def private_registry_directory(path):
    with trusted_directory(path) as fd:
        yield PrivateRegistryDirectory(path, fd)


def initialize_registry_database(path, *, wall_clock=time):
    """Explicit enrollment of a new file. Runtime startup only accepts a pin."""
    with private_registry_directory(path) as directory:
        # Serialize bootstrap against service startup and any other initializer.
        fcntl.flock(directory.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        flags = os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY | os.O_CLOEXEC
        fd = os.open(DATABASE, flags, 0o600, dir_fd=directory.fd)
        try:
            pin = DatabasePin(directory.identity, path_inode(os.fstat(fd)))
            SQLiteRegistry(path / DATABASE, None, wall_clock=wall_clock, create=True,
                           storage_check=lambda: directory.check_database(pin))
            return pin
        finally:
            os.close(fd)
