# SPDX-License-Identifier: Apache-2.0
"""Concurrent, bounded Unix-socket laboratory broker; no real takeover endpoint."""
from collections import deque
from dataclasses import asdict, dataclass, field
import select
import secrets
import socket
import struct
import threading
import time

from experiments.m1_2.protocol import Fault, request
from experiments.m1_3a.protocol import DeadlineChannel
from experiments.m1_3a.authority import Handle, Session, TARGET, fail


@dataclass
class Connection:
    uid: int
    id: str = field(default_factory=lambda: secrets.token_hex(16))
    principal: str | None = None
    active: bool = True
    handle: Handle | None = None
    snapshot_epoch: str | None = None
    alive: object = field(default=lambda: True, repr=False)


SCHEMA = {
    'delegate': {'session', 'principal', 'capability', 'target', 'ttl'},
    'revoke': {'session', 'grant'}, 'snapshot': {'session'},
    'discover': set(), 'acquire': {'session', 'ttl'},
    'release': {'session', 'lease', 'generation', 'epoch'},
    'invoke7': {'session', 'lease', 'generation', 'epoch', 'reference'},
    'events': {'session', 'epoch', 'cursor'}, 'restart': {'session'},
}


class Broker:
    def __init__(self, identities, adapters, uid, clock=time.monotonic):
        self.identities, self.adapters, self.uid, self.clock = identities, adapters, uid, clock
        self.sessions = {sid: Session(sid, clock) for sid in adapters}
        self.io = {sid: threading.Lock() for sid in adapters}
        self.audit = deque(maxlen=128)

    def clear(self, connection):
        connection.handle = None
        connection.snapshot_epoch = None
        for session in self.sessions.values():
            with session.lock:
                if session.lease and session.lease.connection == connection.id:
                    session.fence('control.disconnected')
        connection.principal = None

    def disconnect(self, connection):
        self.clear(connection)
        connection.active = False

    def authenticated(self, connection):
        if not connection.active or connection.uid != self.uid or connection.principal is None:
            fail('denied')
        return connection.principal

    def handle(self, connection, method, params):
        if method == 'auth':
            self.clear(connection)  # Every reauth attempt drops old authority first.
            if (set(params) != {'credential'} or connection.uid != self.uid or not connection.active):
                fail('denied')
            connection.principal = self.identities.authenticate(params['credential'])
            return dict(principal=connection.principal, connection=connection.id)
        principal = self.authenticated(connection)
        if method not in SCHEMA:
            fail('method_not_found', -32601)
        if set(params) != SCHEMA[method]:
            fail('invalid_params', -32602)
        # Bound strings before dictionary lookups and never reflect request data.
        if any(not isinstance(v, str) or len(v) > 128 for k, v in params.items()
               if k not in ('ttl', 'cursor', 'generation')):
            fail('invalid_params', -32602)
        if method == 'discover':
            permitted = []
            for sid, session in self.sessions.items():
                with session.lock:
                    if session.permits(principal, 'session.discover'):
                        permitted.append(sid)
            if not permitted:
                fail('grant_denied')
            return dict(sessions=permitted)
        session = self.sessions.get(params['session'])
        if session is None:
            fail('grant_denied')
        with session.lock:
            session.refresh()
            if method == 'delegate':
                g = session.delegate(principal, params['principal'], params['capability'],
                                     params['target'], params['ttl'])
                return dict(grant=g.id, policy_revision=session.policy_revision)
            if method == 'revoke':
                session.revoke(principal, params['grant'])
                return dict(policy_revision=session.policy_revision,
                            pending_effects='not_cancelled' if session.pending else 'none')
            if method == 'acquire':
                return asdict(session.acquire(principal, connection.id, params['ttl']))
            if method == 'release':
                self.lease(session, connection, params)
                session.fence('control.released')
                return dict(phase=session.phase)
            if method == 'restart':
                session.require(principal, 'identity.admin', '*')
                session.restart()
                return dict(epoch=session.epoch)
            if method == 'events':
                session.require(principal, 'desktop.observe')
                if connection.snapshot_epoch != session.epoch:
                    fail('snapshot_required', -32004)
                try:
                    events = session.history.since(params['epoch'], params['cursor'])
                except Fault:
                    connection.snapshot_epoch = None
                    connection.handle = None
                    raise
                return dict(events=events, cursor=session.history.seq, epoch=session.epoch)
        if method == 'snapshot':
            return self.snapshot(session, connection)
        return self.invoke(session, connection, params)

    def lease(self, session, connection, params):
        principal = self.authenticated(connection)
        return session.check_lease(principal, connection.id, params['lease'],
                                   params['generation'], params['epoch'])

    def snapshot(self, session, connection):
        with session.lock:
            session.require(self.authenticated(connection), 'desktop.observe')
            connection.handle = None
            epoch, revision = session.epoch, session.revision
        adapter = self.adapters[session.id]
        with self.io[session.id]:
            state, reference = adapter.snapshot()
        with session.lock:
            session.refresh()
            principal = self.authenticated(connection)
            session.require(principal, 'desktop.observe')
            if (epoch, revision) != (session.epoch, session.revision):
                fail('snapshot_required', -32004)
            connection.handle = Handle(secrets.token_hex(16), session.epoch, session.generation,
                                       session.revision, self.clock() + 10, reference)
            connection.snapshot_epoch = session.epoch
            return dict(session=session.id, epoch=session.epoch, revision=session.revision,
                        policy_revision=session.policy_revision, generation=session.generation,
                        phase=session.phase, controller=session.lease.principal if session.lease else None,
                        capabilities=sorted(c for c in ('session.discover', 'desktop.observe',
                            'desktop.control', 'session.override', 'identity.admin')
                            if session.permits(principal, c)), reference=connection.handle.id,
                        state=state, cursor=session.history.seq)

    def invoke(self, session, connection, params):
        with session.lock:
            self.lease(session, connection, params)
            h = connection.handle
            if (h is None or params['reference'] != h.id or h.epoch != session.epoch or
                    h.generation != session.generation or h.revision != session.revision or
                    self.clock() >= h.expires):
                fail('stale_reference', -32002)
            if session.pending:
                fail('operation_pending', -32005)
            operation = secrets.token_hex(16)
            session.pending = operation
            connection.handle = None  # One use, even on timeout or rejection; never auto retry.
        sent = False
        adapter = self.adapters[session.id]
        try:
            # Lifecycle/ambiguity queries can block; no policy lock held here.
            with self.io[session.id]:
                prepared = adapter.prepare(h.reference)
                with session.lock:
                    self.lease(session, connection, params)
                    if (not connection.alive() or self.clock() >= h.expires or
                            session.revision != h.revision or session.pending != operation):
                        fail('stale_reference', -32002)
                    # Linearization boundary for revocation vs dispatch. Only the
                    # bounded doAction call runs under this per-session lock.
                    sent = True
                    adapter.send(prepared)
                state = adapter.confirm(prepared)
            with session.lock:
                session.refresh()
                session.event('operation.confirmed')
            return dict(confirmed=True, state=state)
        except Fault:
            raise
        except Exception:
            fail('outcome_unknown' if sent else 'target_unavailable_or_ambiguous', -32006)
        finally:
            with session.lock:
                session.pending = None
                if sent and 'state' not in locals():
                    session.lease = None
                    session.phase = 'blocked'
                    session.event('operation.unknown')
                elif session.phase == 'handoff_pending':
                    session.phase = 'idle'
                    session.event('operation.resolved')

    def serve_connection(self, sock, idle_timeout=30, lifetime=180):
        try:
            _, uid, _ = struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        except OSError:
            sock.close()
            return
        connection = Connection(uid)
        def alive():
            if select.select([sock], [], [], 0)[0]:
                return bool(sock.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT))
            return True
        connection.alive = alive
        channel = DeadlineChannel(sock)
        sock.settimeout(idle_timeout)
        last_id = -1
        deadline = time.monotonic() + lifetime
        try:
            for _ in range(64):
                if time.monotonic() >= deadline:
                    break
                value = channel.receive(min(idle_timeout, max(.001, deadline - time.monotonic())))
                rid, method, params = request(value)
                if rid <= last_id:
                    fail('replay_request', -32600)
                last_id = rid
                try:
                    result = self.handle(connection, method, params)
                    reply, outcome = dict(jsonrpc='2.0', id=rid, result=result), 'ok'
                except Fault as error:
                    reply = dict(jsonrpc='2.0', id=rid, error=dict(code=error.code, message=error.message))
                    outcome = error.message
                self.audit.append(dict(method=method if method in SCHEMA or method == 'auth' else 'unknown',
                                       principal=connection.principal, outcome=outcome))
                channel.send(reply)
        except (EOFError, OSError, Fault, ValueError, RecursionError):
            pass  # Malformed transport closes the connection; no payload is logged.
        finally:
            self.disconnect(connection)
            sock.close()


class Server:
    """At most eight peers; finite connection budget, managed lifetime in the runner."""
    def __init__(self, broker, listener):
        self.broker, self.listener = broker, listener
        self.stop = threading.Event()
        self.workers, self.sockets = [], []
        self.thread = threading.Thread(target=self.run)

    def __enter__(self):
        self.thread.start()
        return self

    def run(self):
        while not self.stop.is_set():
            if not select.select([self.listener], [], [], .05)[0]:
                continue
            sock, _ = self.listener.accept()
            self.workers = [t for t in self.workers if t.is_alive()]
            self.sockets = [s for s in self.sockets if s.fileno() >= 0]
            if len(self.workers) >= 8:
                sock.close()
                continue
            self.sockets.append(sock)
            t = threading.Thread(target=self.broker.serve_connection, args=(sock,))
            self.workers.append(t)
            t.start()

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(2)
        for sock in self.sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for thread in self.workers:
            thread.join(10)
        if any(t.is_alive() for t in self.workers):
            raise RuntimeError('broker_worker_timeout')
