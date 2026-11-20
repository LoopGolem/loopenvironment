# SPDX-License-Identifier: Apache-2.0
"""Private output streaming over an authenticated, dedicated Unix connection."""
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import select
import socket
from struct import Struct
import subprocess
import time

from .authority import Grant, fail
from .private_effects import OUTPUT

CAPABILITY = 'desktop.stream'
HELPER = Path('/private/stream')
FORMAT = 'bgrx8888'
HEADER = Struct('!BQQ')  # kind, capture sequence, monotonic nanoseconds
FRAME, HEARTBEAT = 1, 2
STRIDE = OUTPUT[0] * 4
FRAME_BYTES = STRIDE * OUTPUT[1]
IDENTITY = {'privateId', 'epoch'}
SCHEMA = {
    'presentation.describe': {'session'},
    'presentation.open': {'session'} | IDENTITY,
    'presentation.status': {'session', 'stream'} | IDENTITY,
}


@dataclass
class Stream:
    id: str
    connection: str
    principal: str
    grant: Grant
    state: str = 'opening'
    reason: str | None = None
    peer: socket.socket | None = None


class Presentation:
    """One per managed desktop. Records and nonblocking writes share the authority lock."""

    def __init__(self, private_id, helper=HELPER):
        self.private_id = private_id
        self.helper = helper
        self.available = bool(private_id and os.access(helper, os.X_OK))
        self.streams = OrderedDict()
        self.session = None

    def describe(self, session, principal):
        return dict(session=session.id, privateId=self.private_id, epoch=session.epoch,
                    principal=principal, capability=CAPABILITY, authorization='authorized',
                    state='available' if self.available else 'unavailable',
                    reason=None if self.available else 'capture_backend_unavailable',
                    transport='unix_stream_upgrade_v1', format=FORMAT, width=OUTPUT[0],
                    height=OUTPUT[1], stride=STRIDE, input=False)

    def metadata(self, session, stream):
        result = self.describe(session, stream.principal)
        authorization = 'authorized'
        if stream.grant.revoked:
            authorization = 'revoked'
        elif session.clock() >= stream.grant.expires:
            authorization = 'expired'
        result.update(stream=stream.id, state=stream.state, reason=stream.reason,
                      authorization=authorization)
        return result

    def request(self, session, connection, method, params):
        with session.lock:
            if method == 'presentation.status':
                stream = self.streams.get(params['stream'])
                if stream is None or stream.principal != connection.principal:
                    fail('presentation_unavailable', -32006)
                self.require_identity(session, params)
                return self.metadata(session, stream)
            session.require(connection.principal, CAPABILITY, '*')
            if method == 'presentation.describe':
                return self.describe(session, connection.principal)
            self.require_identity(session, params)
            if not self.available:
                fail('presentation_unavailable', -32006)
            if sum(stream.state != 'closed' for stream in self.streams.values()) >= 2:
                fail('presentation_limit', -32010)
            grant = max((g for g in session.grants.values() if g.principal == connection.principal
                         and g.capability == CAPABILITY and g.target == '*'
                         and not g.revoked and session.clock() < g.expires),
                        key=lambda g: g.expires, default=None)
            if grant is None:
                fail('grant_denied')
            if len(self.streams) >= 32:
                oldest_closed = next(key for key, stream in self.streams.items() if stream.state == 'closed')
                del self.streams[oldest_closed]
            stream = Stream(secrets.token_hex(16), connection.id, connection.principal, grant)
            self.streams[stream.id] = stream
            self.session = session
            return self.metadata(session, stream)

    def require_identity(self, session, params):
        if params['privateId'] != self.private_id or params['epoch'] != session.epoch:
            fail('presentation_identity_mismatch', -32002)

    @staticmethod
    def end(stream, reason):
        if stream.state != 'closed':
            stream.state, stream.reason = 'closed', reason
            if stream.peer is not None:
                with suppress(OSError):
                    stream.peer.shutdown(socket.SHUT_RDWR)

    def revoke(self, session, grant_id):
        # Called within the authority lock, before acknowledging revocation.
        if self.session is session:
            for stream in self.streams.values():
                if stream.grant.id == grant_id:
                    self.end(stream, 'revoked')

    def disconnect(self, connection):
        if self.session is not None:
            with self.session.lock:
                for stream in self.streams.values():
                    if stream.connection == connection.id:
                        self.end(stream, 'viewer_disconnected')

    def close(self):
        if self.session is not None:
            with self.session.lock:
                for stream in self.streams.values():
                    self.end(stream, 'session_ended')

    def active(self, stream):
        if stream.grant.revoked:
            self.end(stream, 'revoked')
        elif self.session.clock() >= stream.grant.expires:
            self.end(stream, 'grant_expired')
        return stream.state != 'closed'

    def relay(self, stream, pipe, peer):
        pending = False
        last_write = time.monotonic()
        while True:
            with self.session.lock:
                if not self.active(stream):
                    return stream.reason
            readers = [peer] if pending else [peer, pipe]
            readable, writable, _ = select.select(readers, [peer] if pending else [], [], .1)
            if peer in readable:
                return 'unexpected_media_input' if peer.recv(1) else 'viewer_disconnected'
            if pipe in readable or writable:
                with self.session.lock:
                    if not self.active(stream):
                        return stream.reason
                    try:
                        count = os.splice(pipe, peer.fileno(), 65536,
                                          flags=os.SPLICE_F_NONBLOCK | os.SPLICE_F_MOVE)
                    except BlockingIOError:
                        pending = not pending
                    else:
                        if not count:
                            return 'capture_failed'
                        pending = False
                        stream.state = 'live'
                        last_write = time.monotonic()
            if time.monotonic() - last_write > 4:
                return 'slow_viewer' if pending else 'capture_unresponsive'

    def run(self, connection, stream_id, channel):
        peer = channel.sock
        with self.session.lock:
            stream = self.streams.get(stream_id)
            if stream is None or stream.connection != connection.id or not self.active(stream):
                return
            stream.peer = peer
        process = None
        reason = 'capture_failed'
        try:
            if channel.pending:
                reason = 'unexpected_media_input'
                return
            peer.setblocking(False)
            peer.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 128 * 1024)
            # Give the capture client only the environment needed to connect to private Wayland.
            env = {key: os.environ[key] for key in ('XDG_RUNTIME_DIR', 'WAYLAND_DISPLAY')}
            process = subprocess.Popen([self.helper], stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
            with process.stdout:
                pipe = process.stdout.fileno()
                os.set_blocking(pipe, False)
                reason = self.relay(stream, pipe, peer)
        except (BrokenPipeError, ConnectionResetError):
            reason = 'viewer_disconnected'
        except (OSError, KeyError):
            pass
        finally:
            with self.session.lock:
                self.end(stream, reason)
                stream.peer = None
            if process is not None:
                with suppress(ProcessLookupError):
                    process.kill()
                process.wait()
