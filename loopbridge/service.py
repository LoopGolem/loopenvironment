# SPDX-License-Identifier: Apache-2.0
"""Local LoopBridge service lifecycle and durable dispatch fence."""
from contextlib import ExitStack, contextmanager
import fcntl
import os
from pathlib import Path
import socket
import stat
import tempfile

from .adapter import Adapter
from .broker import Broker, Server
from .service_diagnostics import Phase
from .service_ingress import IngressLayout, PeerAdmission, bound_listener, managed_ingress_listener

SESSION = 'calculator'
DESKTOP_SESSION = 'desktop'


def private_directory(path, *, create=True):
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise RuntimeError('unsafe_runtime_directory')
    return path


@contextmanager
def directory_lock(root):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


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
def legacy_listener(endpoint, *, backlog=8):
    """Existing V0.7 Unix socket lifecycle, unchanged by D3 opt-in ingress."""
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(endpoint))
        try:
            endpoint.chmod(0o600)
            listener.listen(backlog)
            yield listener
        finally:
            endpoint.unlink(missing_ok=True)


@contextmanager
def serve(root, identities, mode, workspace=None, *, watch_adapter=False, presentation=None,
          ingress_layout=None, ingress_policy=None, session_state=None, startup_progress=None):
    if startup_progress is not None:
        startup_progress(Phase.BROKER_STORAGE)
    if (ingress_layout is None) != (ingress_policy is None):
        raise ValueError('incomplete_ingress_configuration')
    if ingress_layout is not None:
        if (not isinstance(ingress_layout, IngressLayout)
                or not isinstance(ingress_policy, PeerAdmission)
                or ingress_policy.service_uid != os.getuid()
                or ingress_layout.private_root != Path(root)):
            raise ValueError('invalid_ingress_configuration')
    if session_state is not None:
        if mode != 'desktop' or ingress_layout is not None:
            raise ValueError('invalid_private_session_configuration')
        session_state = private_directory(Path(session_state), create=False)
    root = private_directory(Path(root))
    # Persist the runtime directory entry before accepting a journal intent.
    parent_fd = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    # Lock the directory inode for this lifecycle. Start competitors without
    # touching the existing endpoint or pending marker.
    with directory_lock(root):
        if ingress_layout is None:
            sockets = private_directory(root / 'socket')
            endpoint = sockets / 'control.sock'
            if session_state is None and endpoint.is_socket():
                endpoint.unlink()
        else:
            # In hardened-profile experiments, never start the legacy listener
            # alongside the new ingress: an incomplete migration fails closed.
            if os.path.lexists(root / 'socket/control.sock'):
                raise RuntimeError('legacy_endpoint_present')
            endpoint = ingress_layout.public_socket
        broker_options = {}
        if mode == 'desktop':
            from .catalog import CATALOG
            from .desktop_broker import DesktopBroker
            from .teaching import AnnotationStore
            broker_class, session, catalog = DesktopBroker, DESKTOP_SESSION, CATALOG
            broker_options['annotation_store'] = AnnotationStore((session_state or root) / 'annotations.sqlite3')
            broker_options['presentation'] = presentation
        else:
            broker_class, session, catalog = Broker, SESSION, ()
        journal = Journal(session_state or root)
        # Switching modes must not hide an unresolved operation on this runtime.
        legacy = SESSION if session == DESKTOP_SESSION else DESKTOP_SESSION
        if journal.blocked(legacy):
            raise OSError('unresolved_operation_in_other_mode')
        if startup_progress is not None:
            startup_progress(Phase.BROKER_ADAPTER)
        adapter = Adapter(mode, root, workspace)
        try:
            if startup_progress is not None:
                startup_progress(Phase.BROKER_LISTENERS)
            broker = broker_class(identities, {session: adapter}, os.getuid(), journal,
                                  catalog=catalog, workspace=bool(workspace),
                                  ingress_policy=ingress_policy, **broker_options)
            with ExitStack() as stack:
                if session_state is not None:
                    listener = stack.enter_context(bound_listener(endpoint))
                    relay = stack.enter_context(bound_listener(sockets / 'relay.sock'))
                    stack.enter_context(Server(broker, relay, allow_owner=False))
                else:
                    lifecycle = (legacy_listener(endpoint) if ingress_layout is None
                                 else managed_ingress_listener(ingress_layout))
                    listener = stack.enter_context(lifecycle)
                stack.enter_context(Server(broker, listener))
                yield (endpoint, adapter) if watch_adapter else endpoint
        finally:
            adapter.close()
