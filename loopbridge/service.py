# SPDX-License-Identifier: Apache-2.0
"""Local LoopBridge service lifecycle and durable dispatch fence."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import socket
import stat

from .adapter import Adapter
from .broker import Broker, Server

SESSION = 'calculator'


def private_directory(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise RuntimeError('unsafe_runtime_directory')
    return path


class Journal:
    """A surviving marker means delivery may still be pending."""
    def __init__(self, folder):
        self.folder = folder

    def sync(self):
        fd = os.open(self.folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def blocked(self, session):
        try:
            (self.folder / (session + '.pending')).lstat()
        except FileNotFoundError:
            return False
        except OSError:
            return True
        return True

    def mark(self, session, operation):
        path = self.folder / (session + '.pending')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            output.write(operation + '\n')
            output.flush()
            os.fsync(output.fileno())
        self.sync()

    def clear(self, session):
        (self.folder / (session + '.pending')).unlink()
        self.sync()


@contextmanager
def serve(root, identities, mode):
    root = private_directory(Path(root))
    # Lock the directory inode for this lifecycle. Start competitors without
    # touching the existing endpoint or pending marker.
    lock = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sockets = private_directory(root / 'socket')
        endpoint = sockets / 'control.sock'
        if endpoint.is_socket():
            endpoint.unlink()
        adapter = Adapter(mode)
        try:
            broker = Broker(identities, {SESSION: adapter}, os.getuid(), Journal(root))
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(endpoint))
                try:
                    endpoint.chmod(0o600)
                    listener.listen(8)
                    with Server(broker, listener):
                        yield endpoint
                finally:
                    endpoint.unlink(missing_ok=True)
        finally:
            adapter.close()
    finally:
        os.close(lock)
