# SPDX-License-Identifier: Apache-2.0
"""One explicitly configured private workspace root, addressed through its dirfd."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}')
MAX_TEXT = 3000


class Workspace:
    def __init__(self, root):
        path = Path(root).absolute()
        # Require a canonical path so the editor and dirfd refer to the same root.
        if path.resolve(strict=True) != path:
            raise OSError('noncanonical_workspace')
        self.path = path
        self.fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(self.fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            self.close()
            raise OSError('unsafe_workspace')

    def close(self):
        os.close(self.fd)

    @staticmethod
    def name(name):
        if not NAME.fullmatch(name):
            raise ValueError('invalid_workspace_path')
        return name

    def verify_root(self):
        current = self.path.stat(follow_symlinks=False)
        pinned = os.fstat(self.fd)
        if (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino):
            raise OSError('workspace_changed')

    @contextmanager
    def opened(self, name):
        fd = os.open(self.name(name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=self.fd)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != os.getuid()):
                raise OSError('unsafe_workspace_entry')
            yield fd, info
        finally:
            os.close(fd)

    def file_path(self, name):
        self.verify_root()
        with self.opened(name):
            return str(self.path / name)

    def listing(self, offset):
        entries = []
        with os.scandir(self.fd) as listing:
            for index, entry in enumerate(listing):
                if index >= 512:
                    raise OSError('workspace_entry_limit')
                if not NAME.fullmatch(entry.name):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    entries.append(dict(name=entry.name, kind='directory'))
                elif entry.is_file(follow_symlinks=False) and entry.stat(follow_symlinks=False).st_nlink == 1:
                    entries.append(dict(name=entry.name, kind='file'))
        page = sorted(entries, key=lambda entry: entry['name'])[offset:offset + 16]
        return dict(entries=page, next=offset + len(page) if offset + len(page) < len(entries) else None)

    def read(self, name):
        with self.opened(name) as (fd, info):
            with os.fdopen(os.dup(fd), 'rb') as stream:
                data = stream.read(4097)
            if len(data) > 4096:
                raise ValueError('workspace_size_limit')
        return data.decode('utf-8')

    def prepare(self, name, text):
        if len(text.encode('utf-8')) > MAX_TEXT:
            raise ValueError('workspace_size_limit')
        self.name(name)
        try:
            with self.opened(name):
                pass
        except FileNotFoundError:
            pass
        return name, text

    def write(self, name, text):
        self.prepare(name, text)
        temporary = '.bridge-' + secrets.token_hex(12)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=self.fd)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                output.write(text)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            os.fsync(self.fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=self.fd)
            except FileNotFoundError:
                pass

    def confirm(self, name, expected):
        actual = self.read(name)
        if actual != expected:
            raise OSError('workspace_contents_unconfirmed')
        encoded = actual.encode('utf-8')
        return dict(name=name, bytes=len(encoded), sha256=hashlib.sha256(encoded).hexdigest())
