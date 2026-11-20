# SPDX-License-Identifier: Apache-2.0
"""Local LoopBridge service lifecycle and durable dispatch fence."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import socket
import stat
import tempfile

from .adapter import Adapter
from .broker import Broker, Server

SESSION = 'calculator'
DESKTOP_SESSION = 'desktop'


def private_directory(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise RuntimeError('unsafe_runtime_directory')
    return path


class Journal:
    """Pair a durable intent with an operation-specific resolution receipt."""

    def __init__(self, folder):
        self.folder = folder

    def sync(self):
        fd = os.open(self.folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def read(self, path):
        with path.open('rb') as source:
            value = source.read(34)
        if len(value) != 33 or value[-1:] != b'\n':
            raise OSError('invalid_journal_record')
        token = value[:-1].decode('ascii', errors='replace')
        if any(char not in '0123456789abcdef' for char in token):
            raise OSError('invalid_journal_record')
        return token

    def intent(self, session):
        try:
            return self.read(self.folder / (session + '.pending'))
        except FileNotFoundError:
            return None

    def blocked(self, session):
        try:
            pending = self.intent(session)
            try:
                receipt = self.read(self.folder / (session + '.resolved'))
            except FileNotFoundError:
                receipt = None
            return pending != receipt
        except OSError:
            return True

    def write(self, path, operation):
        # Only an unpublished temporary file can be removed. The authoritative
        # intent is never unlinked, including after successful confirmation.
        fd, name = tempfile.mkstemp(dir=self.folder, prefix='.journal-')
        published = False
        try:
            with os.fdopen(fd, 'w') as output:
                output.write(operation + '\n')
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, path)
            published = True
            self.sync()
        finally:
            if not published:
                os.unlink(name)

    def mark(self, session, operation):
        if self.blocked(session):
            raise OSError('journal_blocked')
        self.write(self.folder / (session + '.pending'), operation)

    def clear(self, session):
        # Called only with independently confirmed state or proved non-dispatch.
        # If the receipt survives an interrupted sync, its matching ID still
        # proves resolution. An absent, malformed or different receipt blocks.
        operation = self.intent(session)
        if operation is None:
            raise OSError('journal_intent_missing')
        self.write(self.folder / (session + '.resolved'), operation)


@contextmanager
def serve(root, identities, mode, workspace=None, *, watch_adapter=False, presentation=None):
    root = private_directory(Path(root))
    # Persist the runtime directory entry before accepting a journal intent.
    parent_fd = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    # Lock the directory inode for this lifecycle. Start competitors without
    # touching the existing endpoint or pending marker.
    lock = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sockets = private_directory(root / 'socket')
        endpoint = sockets / 'control.sock'
        if endpoint.is_socket():
            endpoint.unlink()
        broker_options = {}
        if mode == 'desktop':
            from .catalog import CATALOG
            from .desktop_broker import DesktopBroker
            from .teaching import AnnotationStore
            broker_class, session, catalog = DesktopBroker, DESKTOP_SESSION, CATALOG
            broker_options['annotation_store'] = AnnotationStore(root / 'annotations.sqlite3')
            broker_options['presentation'] = presentation
        else:
            broker_class, session, catalog = Broker, SESSION, ()
        journal = Journal(root)
        # Switching modes must not hide an unresolved operation on this runtime.
        legacy = SESSION if session == DESKTOP_SESSION else DESKTOP_SESSION
        if journal.blocked(legacy):
            raise OSError('unresolved_operation_in_other_mode')
        adapter = Adapter(mode, root, workspace)
        try:
            broker = broker_class(identities, {session: adapter}, os.getuid(), journal,
                                  catalog=catalog, workspace=bool(workspace), **broker_options)
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(endpoint))
                try:
                    endpoint.chmod(0o600)
                    listener.listen(8)
                    with Server(broker, listener):
                        yield (endpoint, adapter) if watch_adapter else endpoint
                finally:
                    endpoint.unlink(missing_ok=True)
        finally:
            adapter.close()
    finally:
        os.close(lock)
