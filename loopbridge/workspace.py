# SPDX-License-Identifier: Apache-2.0
"""Descriptor-relative native files within one explicitly granted workspace."""
from contextlib import contextmanager
import ctypes
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}')
MAX_TEXT = 3000
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
NO_REPLACE = 1


def mount_id(fd):
    for line in Path(f'/proc/self/fdinfo/{fd}').read_text().splitlines():
        if line.startswith('mnt_id:'):
            return int(line.split(':', 1)[1])
    raise OSError('workspace_mount_id_unavailable')


class Workspace:
    def __init__(self, root):
        path = Path(root).absolute()
        if path.resolve(strict=True) != path:
            raise OSError('noncanonical_workspace')
        self.path = path
        self.fd = os.open(path, DIRECTORY)
        info = os.fstat(self.fd)
        self.device = info.st_dev
        self.mount = mount_id(self.fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            self.close()
            raise OSError('unsafe_workspace')

    def close(self):
        os.close(self.fd)

    @staticmethod
    def components(path):
        parts = path.split('/')
        if len(parts) > 6 or not all(NAME.fullmatch(part) for part in parts):
            raise ValueError('invalid_workspace_path')
        return parts

    def verify_root(self):
        current = self.path.stat(follow_symlinks=False)
        pinned = os.fstat(self.fd)
        if (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino):
            raise OSError('workspace_changed')

    @contextmanager
    def directory(self, parts):
        self.verify_root()
        fd = os.dup(self.fd)
        try:
            for part in parts:
                opened = os.open(part, DIRECTORY, dir_fd=fd)
                os.close(fd)
                fd = opened
                info = os.fstat(fd)
                if (info.st_dev != self.device or mount_id(fd) != self.mount or info.st_uid != os.getuid()
                        or info.st_mode & 0o022):
                    raise OSError('unsafe_workspace_directory')
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def parent(self, path):
        *parts, name = self.components(path)
        with self.directory(parts) as fd:
            yield fd, name

    @contextmanager
    def opened(self, path):
        with self.parent(path) as (parent, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or info.st_uid != os.getuid() or info.st_dev != self.device or mount_id(fd) != self.mount):
                    raise OSError('unsafe_workspace_entry')
                yield fd, info
            finally:
                os.close(fd)

    def file_path(self, name):
        with self.opened(name):
            return str(self.path / name)

    def directory_path(self, path):
        parts = self.components(path) if path else []
        with self.directory(parts):
            return str(self.path.joinpath(*parts))

    def listing(self, offset, path=''):
        entries = []
        with self.directory(self.components(path) if path else []) as fd, os.scandir(fd) as listing:
            for index, entry in enumerate(listing):
                if index >= 512:
                    raise OSError('workspace_entry_limit')
                if not NAME.fullmatch(entry.name):
                    continue
                info = entry.stat(follow_symlinks=False)
                if info.st_dev != self.device or info.st_uid != os.getuid():
                    continue
                if stat.S_ISDIR(info.st_mode):
                    entries.append(dict(name=entry.name, kind='directory'))
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    entries.append(dict(name=entry.name, kind='file'))
        page = sorted(entries, key=lambda entry: entry['name'])[offset:offset + 16]
        return dict(entries=page, next=offset + len(page) if offset + len(page) < len(entries) else None)

    def read(self, name):
        with self.opened(name) as (fd, _):
            with os.fdopen(os.dup(fd), 'rb') as stream:
                data = stream.read(4097)
            if len(data) > 4096:
                raise ValueError('workspace_size_limit')
        return data.decode('utf-8')

    def prepare(self, name, text):
        if len(text.encode('utf-8')) > MAX_TEXT:
            raise ValueError('workspace_size_limit')
        *parts, _ = self.components(name)
        try:
            with self.directory(parts):
                pass
        except FileNotFoundError as error:
            raise ValueError('workspace_directory_unavailable') from error
        try:
            with self.opened(name):
                pass
        except FileNotFoundError:
            pass
        return name, text

    def write(self, path, text):
        self.prepare(path, text)
        temporary = '.bridge-' + secrets.token_hex(12)
        with self.parent(path) as (parent, name):
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as output:
                    output.write(text)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass

    def require_absent(self, path):
        with self.parent(path) as (parent, name):
            try:
                os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return
            raise FileExistsError('workspace_destination_exists')

    def mkdir(self, path):
        with self.parent(path) as (parent, name):
            os.mkdir(name, mode=0o700, dir_fd=parent)
            os.fsync(parent)

    def confirm_directory(self, path):
        self.directory_path(path)
        return dict(name=path, kind='directory', verifier='linux_dirfd')

    def rename(self, source, destination):
        self.require_absent(destination)
        with self.opened(source), self.parent(source) as (before, name), \
                self.parent(destination) as (after, new_name):
            renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
            renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                                  ctypes.c_char_p, ctypes.c_uint]
            renameat2.restype = ctypes.c_int
            if renameat2(before, os.fsencode(name), after, os.fsencode(new_name), NO_REPLACE) != 0:
                raise OSError(ctypes.get_errno(), 'workspace_rename_failed')
            os.fsync(before)
            os.fsync(after)

    def prepare_rename(self, source, destination):
        if not hasattr(ctypes.CDLL(None), 'renameat2'):
            raise OSError('workspace_rename_unsupported')
        value = self.read(source)
        self.require_absent(destination)
        return value

    def confirm_rename(self, source, destination, expected):
        self.require_absent(source)
        return self.confirm(destination, expected)

    def confirm(self, name, expected):
        actual = self.read(name)
        if actual != expected:
            raise OSError('workspace_contents_unconfirmed')
        encoded = actual.encode('utf-8')
        return dict(name=name, bytes=len(encoded), sha256=hashlib.sha256(encoded).hexdigest(),
                    verifier='linux_dirfd_readback')
