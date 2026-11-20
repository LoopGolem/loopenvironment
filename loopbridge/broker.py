# SPDX-License-Identifier: Apache-2.0
"""Bounded Unix-socket broker and dispatch coordinator."""
from collections import deque, OrderedDict
from dataclasses import asdict, dataclass, field
import select
import secrets
import socket
import struct
import threading
import time

from .protocol import Fault, VERSION, DeadlineChannel, encode, request
from .authority import Handle, Session, TARGET, fail


@dataclass
class Connection:
    uid: int
    id: str = field(default_factory=lambda: secrets.token_hex(16))
    principal: str | None = None
    active: bool = True
    handle: Handle | None = None
    handles: dict = field(default_factory=OrderedDict)
    snapshots: dict = field(default_factory=dict)
    alive: object = field(default=lambda: True, repr=False)


SCHEMA = {
    'delegate': {'session', 'principal', 'capability', 'target', 'ttl'},
    'revoke': {'session', 'grant'}, 'snapshot': {'session'},
    'discover': set(), 'capabilities': {'session'}, 'audit': {'session'}, 'acquire': {'session', 'ttl'},
    'release': {'session', 'lease', 'generation', 'epoch'},
    'invoke7': {'session', 'lease', 'generation', 'epoch', 'reference'},
    'events': {'session', 'epoch', 'cursor'},
}


class Broker:
    schema = SCHEMA
    versions = ('0.1', '0.2', '0.3', '0.4', '0.5', VERSION)
    connection_limits = (30, 180, 64)

    def __init__(self, identities, adapters, uid, journal, clock=time.monotonic,
                 catalog=(), workspace=False, extra_capabilities=()):
        self.identities, self.adapters, self.uid, self.clock = identities, adapters, uid, clock
        self.journal = journal
        self.sessions = {sid: Session(sid, clock, journal.blocked(sid), catalog, workspace,
                                      extra_capabilities) for sid in adapters}
        self.io = {sid: threading.Lock() for sid in adapters}
        self.audit = deque(maxlen=32)
        self.audit_lock = threading.Lock()
        self.operations = {sid: OrderedDict() for sid in adapters}

    def clear(self, connection):
        connection.handle = None
        connection.handles.clear()
        connection.snapshots.clear()
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
        if method not in self.schema:
            fail('method_not_found', -32601)
        if set(params) != self.schema[method]:
            fail('invalid_params', -32602)
        # Bound strings before dictionary lookups and never reflect request data.
        if any(not isinstance(v, str) or len(v) > (3000 if k in ('text', 'meaning', 'conditions', 'warnings') else 512 if k == 'url' else 128)
               for k, v in params.items()
               if k not in ('ttl', 'cursor', 'generation', 'offset', 'depth', 'value', 'revision', 'index', 'x', 'y')):
            fail('invalid_params', -32602)
        if method == 'discover':
            permitted = []
            for sid, session in self.sessions.items():
                with session.lock:
                    if session.permits(principal, 'session.discover'):
                        permitted.append(sid)
            if not permitted:
                fail('grant_denied')
            return dict(sessions=sorted(permitted))
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
                self.grant_revoked(session, params['grant'])
                return dict(policy_revision=session.policy_revision,
                            pending_effects='not_cancelled' if session.pending else 'none')
            if method == 'acquire':
                return asdict(session.acquire(principal, connection.id, params['ttl']))
            if method == 'release':
                self.lease(session, connection, params)
                session.fence('control.released')
                return dict(phase=session.phase)
            if method == 'capabilities':
                session.require(principal, 'session.discover')
                return dict(capabilities=self.capabilities(session, principal))
            if method == 'audit':
                session.require(principal, 'identity.admin', '*')
                with self.audit_lock:
                    return dict(entries=list(self.audit))
            if method == 'events':
                self.require_events(session, principal)
                if connection.snapshots.get(session.id) != session.epoch:
                    fail('snapshot_required', -32004)
                try:
                    events = session.history.since(params['epoch'], params['cursor'])
                except Fault:
                    connection.snapshots.pop(session.id, None)
                    connection.handle = None
                    connection.handles.clear()
                    raise
                return dict(events=events, cursor=session.history.seq, epoch=session.epoch)
        if method == 'snapshot':
            return self.snapshot(session, connection)
        if method == 'invoke7':
            return self.invoke(session, connection, params)
        return self.extended(session, connection, method, params)

    def require_events(self, session, principal):
        session.require(principal, 'desktop.observe')

    def grant_revoked(self, session, grant_id):
        pass

    def upgrade(self, connection, method, result, channel):
        return False

    def extended(self, session, connection, method, params):
        fail('method_not_found', -32601)

    def lease(self, session, connection, params):
        principal = self.authenticated(connection)
        return session.check_lease(principal, connection.id, params['lease'],
                                   params['generation'], params['epoch'])

    @staticmethod
    def capabilities(session, principal):
        return sorted(cap for cap in session.capabilities
                      if any(session.permits(principal, cap, scope)
                             for scope in ('*', TARGET, 'workspace',
                                           *('app:' + app for app in session.catalog))))

    def snapshot(self, session, connection):
        with session.lock:
            session.require(self.authenticated(connection), 'desktop.observe')
            connection.handle = None
            epoch, revision = session.epoch, session.revision
        adapter = self.adapters[session.id]
        with self.io[session.id]:
            try:
                state, reference = adapter.call('snapshot')
                if len(encode(state)) > 4096:
                    raise ValueError('state_limit')
            except Exception:
                fail('target_unavailable', -32006)
        with session.lock:
            session.refresh()
            principal = self.authenticated(connection)
            session.require(principal, 'desktop.observe')
            if (epoch, revision) != (session.epoch, session.revision):
                fail('snapshot_required', -32004)
            if session.last_state != state:
                session.last_state = state
                session.event('state.changed')
            connection.handle = Handle(secrets.token_hex(16), session.id, session.epoch, session.generation,
                                       session.revision, self.clock() + 10, reference)
            connection.snapshots[session.id] = session.epoch
            return dict(session=session.id, epoch=session.epoch, revision=session.revision,
                        policy_revision=session.policy_revision, generation=session.generation,
                        phase=session.phase, capabilities=self.capabilities(session, principal),
                        application='org.gnome.Calculator', source=adapter.source,
                        element=dict(role='button', name='7', action='click',
                                     reference=connection.handle.id),
                        state=state, cursor=session.history.seq)

    def invoke(self, session, connection, params):
        with session.lock:
            self.lease(session, connection, params)
            session.require(connection.principal, 'desktop.control')
            session.require(connection.principal, 'desktop.observe')
            handle = connection.handle
            if (handle is None or params['reference'] != handle.id or
                    handle.session != session.id or handle.epoch != session.epoch or
                    handle.generation != session.generation or handle.revision != session.revision or
                    self.clock() >= handle.expires):
                fail('stale_reference', -32002)
            connection.handle = None
        result = self.dispatch(session, connection, params, 'prepare', handle.reference,
                               TARGET, 'desktop.control', 'desktop.observe', handle)
        if result['status'] == 'refused':
            fail(result['reason'], -32006)
        return result

    def dispatch(self, session, connection, params, prepare_method, argument, target,
                 capability, observation, handle=None, extra=()):
        with session.lock:
            self.lease(session, connection, params)
            session.require(connection.principal, capability, target)
            if observation:
                session.require(connection.principal, observation, target)
            for extra_cap, extra_target in extra:
                session.require(connection.principal, extra_cap, extra_target)
            if session.pending:
                fail('operation_pending', -32005)
            operation = secrets.token_hex(16)
            session.pending = operation
        principal = connection.principal
        result = dict(status='unknown', operation=operation)
        sent = confirmed = storage_error = False
        adapter = self.adapters[session.id]
        try:
            with self.io[session.id]:
                adapter.call(prepare_method, argument)
                with session.lock:
                    self.lease(session, connection, params)
                    session.require(principal, capability, target)
                    if observation:
                        session.require(principal, observation, target)
                    for extra_cap, extra_target in extra:
                        session.require(principal, extra_cap, extra_target)
                    if handle and (session.revision != handle.revision or self.clock() >= handle.expires):
                        fail('stale_reference', -32002)
                    # Persist uncertainty before submitting any Desktop RPC.
                    self.journal.mark(session.id, operation)
                    deadline = min(session.lease.expires, session.expires(principal, capability, target))
                    if observation:
                        deadline = min(deadline, session.expires(principal, observation, target))
                    for extra_cap, extra_target in extra:
                        deadline = min(deadline, session.expires(principal, extra_cap, extra_target))
                    if handle:
                        deadline = min(deadline, handle.expires)
                    if not connection.alive() or self.clock() >= deadline:
                        self.journal.clear(session.id)
                        fail('dispatch_fenced', -32002)
                    sent = True
                    # Worker receives a remaining budget independent of injected test clocks.
                    adapter.call('send', time.monotonic() + max(0, deadline - self.clock()))
                state = adapter.call('confirm')
                evidence = dict(source=adapter.source, state=state)
                if len(encode(evidence)) > 4096:
                    raise ValueError('state_limit')
                with session.lock:
                    if not connection.alive():
                        raise EOFError
                    confirmed = True
                    try:
                        self.journal.clear(session.id)
                    except OSError:
                        storage_error = True
                    read_capability = observation or 'desktop.observe'
                    if not session.permits(principal, read_capability, target):
                        evidence['state'] = None
            result.update(status='confirmed', evidence=evidence)
            if storage_error:
                result['session_blocked'] = True
        except Fault:
            if not sent:
                raise
        except Exception as error:
            if not sent and not self.journal.blocked(session.id):
                result.update(status='refused', reason=getattr(error, 'reason',
                              'target_unavailable_or_changed'))
        finally:
            with session.lock:
                session.pending = None
                session.refresh()
                if confirmed:
                    if prepare_method == 'prepare':
                        session.last_state = state
                    session.event('operation.confirmed')
                if storage_error or (not confirmed and (sent or self.journal.blocked(session.id))):
                    session.lease = None
                    session.phase = 'blocked'
                    session.event('journal.unavailable' if storage_error else 'operation.unknown')
                if session.phase == 'handoff_pending':
                    session.phase = 'idle'
                    session.event('operation.resolved')
                if result['status'] == 'unknown':
                    result['evidence'] = dict(source=adapter.source, state=None)
                history = self.operations[session.id]
                history[operation] = (principal, result['status'])
                if len(history) > 32:
                    history.popitem(last=False)
        return result

    def serve_connection(self, sock):
        idle_timeout, lifetime, request_limit = self.connection_limits
        try:
            _, uid, _ = struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        except OSError:
            sock.close()
            return
        connection = Connection(uid)
        poll = select.poll()
        hangup = select.POLLRDHUP | select.POLLHUP | select.POLLERR
        poll.register(sock, hangup)

        def alive():
            return not poll.poll(0)

        connection.alive = alive
        channel = DeadlineChannel(sock)
        sock.settimeout(idle_timeout)
        last_id = -1
        deadline = time.monotonic() + lifetime
        try:
            for _ in range(request_limit):
                if time.monotonic() >= deadline:
                    break
                value = channel.receive(min(idle_timeout, max(.001, deadline - time.monotonic())))
                rid, method, params = request(value)
                if rid <= last_id:
                    fail('replay_request', -32600)
                last_id = rid
                try:
                    if value['version'] not in self.versions:
                        fail('unsupported_version', -32600)
                    result = self.handle(connection, method, params)
                    reply = dict(jsonrpc='2.0', version=value['version'], id=rid, result=result)
                    outcome = result.get('status', 'ok')
                except Fault as error:
                    reply = dict(jsonrpc='2.0', version=value['version'], id=rid, error=dict(code=error.code, message=error.message))
                    outcome = error.message
                with self.audit_lock:
                    self.audit.append(dict(method=method if method in self.schema or method == 'auth' else 'unknown',
                                           principal=connection.principal, outcome=outcome))
                channel.send(reply)
                if 'result' in reply and self.upgrade(connection, method, result, channel):
                    break
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
            if self.stop.is_set() or len(self.workers) >= 8:
                sock.close()
                continue
            self.sockets.append(sock)
            t = threading.Thread(target=self.broker.serve_connection, args=(sock,))
            self.workers.append(t)
            t.start()

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()
        for sock in self.sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for thread in self.workers:
            thread.join()
