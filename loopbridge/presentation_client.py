# SPDX-License-Identifier: Apache-2.0
"""Local read-only client for a pinned private presentation."""
from contextlib import closing, suppress
import re
import socket
from threading import Event, Lock
from time import monotonic_ns

from .presentation import CAPABILITY, FORMAT, FRAME, FRAME_BYTES, HEADER, HEARTBEAT, STRIDE
from .private_effects import OUTPUT
from .protocol import Fault, RPC
from .service_ingress import peer_uid

PRIVATE_ID = re.compile(r'[a-f0-9]{16}')
EPOCH = re.compile(r'[a-f0-9]{32}')
STREAM_ID = re.compile(r'[a-f0-9]{32}')
REASONS = frozenset(('revoked', 'grant_expired', 'session_ended', 'viewer_disconnected',
                     'capture_failed', 'capture_unresponsive', 'slow_viewer', 'unexpected_media_input'))


def matches(row, expected):
    return isinstance(row, dict) and all(key in row and type(row[key]) is type(value)
                                         and row[key] == value for key, value in expected.items())


def presentation_pin(row, session, principal):
    expected = dict(session=session, principal=principal, width=OUTPUT[0], height=OUTPUT[1],
                    stride=STRIDE, format=FORMAT, input=False, capability=CAPABILITY,
                    authorization='authorized', transport='unix_stream_upgrade_v1')
    if not matches(row, expected):
        raise ValueError('invalid_presentation_response')
    epoch, private_id = row.get('epoch'), row.get('privateId')
    if (not isinstance(epoch, str) or not EPOCH.fullmatch(epoch)
            or not isinstance(private_id, str) or not PRIVATE_ID.fullmatch(private_id)):
        raise ValueError('invalid_presentation_response')
    return epoch, private_id


class LiveConnection:
    def __init__(self, endpoint, token, session, private_id, epoch, *, expected_peer_uid=None,
                 expected_principal=None):
        self.endpoint, self.token = str(endpoint), token
        self.expected_peer_uid = expected_peer_uid
        self.expected_principal = expected_principal
        self.identity = dict(session=session, privateId=private_id, epoch=epoch)
        self.peer = socket.socket(socket.AF_UNIX)
        self.metadata = None
        self.channel = None
        self.cancelled = Event()
        self.diagnostic_lock = Lock()
        self.diagnostic_peer = None
        self.packet_probe = None

    def _connect_rpc(self, peer, timeout):
        peer.settimeout(timeout)
        peer.connect(self.endpoint)
        if self.expected_peer_uid is not None and peer_uid(peer) != self.expected_peer_uid:
            raise ValueError('unexpected_presentation_peer')
        return RPC(peer, timeout=timeout)

    def _authenticate(self, rpc):
        token = self.token
        if self.cancelled.is_set() or token is None:
            raise EOFError
        row = rpc.call('auth', credential=token)
        principal = row.get('principal') if isinstance(row, dict) else None
        if principal not in ('observer', 'delegate', 'owner'):
            raise ValueError('invalid_presentation_response')
        return principal

    def connect(self):
        if self.cancelled.is_set():
            raise EOFError
        rpc = self._connect_rpc(self.peer, 5)
        principal = self._authenticate(rpc)
        if self.expected_principal is not None and principal != self.expected_principal:
            raise Fault(-32001, 'presentation_principal_mismatch')

        # LoopShell already pins session and epoch on its console connection.
        # Resolve the private ID on this independently authenticated connection.
        if self.identity['privateId'] is None:
            row = rpc.call('presentation.describe', session=self.identity['session'])
            epoch, private_id = presentation_pin(row, self.identity['session'], principal)
            if row.get('state') not in ('available', 'unavailable'):
                raise ValueError('invalid_presentation_response')
            if epoch != self.identity['epoch']:
                raise Fault(-32002, 'presentation_identity_mismatch')
            if row.get('state') == 'unavailable':
                raise Fault(-32006, 'presentation_unavailable')
            self.identity['privateId'] = private_id
        if self.cancelled.is_set():
            raise EOFError
        row = rpc.call('presentation.open', **self.identity)
        epoch, private_id = presentation_pin(row, self.identity['session'], principal)
        stream = row.get('stream')
        if row.get('state') != 'opening' or not isinstance(stream, str) or not STREAM_ID.fullmatch(stream):
            raise ValueError('invalid_presentation_response')
        if (epoch, private_id) != (self.identity['epoch'], self.identity['privateId']):
            raise Fault(-32002, 'presentation_identity_mismatch')
        self.metadata = row
        self.channel = rpc.channel
        self.peer.settimeout(5)
        return row

    def interrupt(self):
        with suppress(OSError):
            self.peer.shutdown(socket.SHUT_RDWR)

    def cancel(self):
        self.cancelled.set()
        self.token = None
        self.interrupt()
        with self.diagnostic_lock:
            if self.diagnostic_peer is not None:
                with suppress(OSError):
                    self.diagnostic_peer.shutdown(socket.SHUT_RDWR)

    def release(self):
        # Called only by the reader after it has finished with the socket.
        self.token = None
        self.channel = None
        self.peer.close()

    def read(self, length):
        data = bytearray(length)
        prefix = self.channel.pending
        offset = min(length, len(prefix))
        data[:offset] = prefix[:offset]
        del prefix[:offset]
        while offset < length:
            count = self.peer.recv_into(memoryview(data)[offset:])
            if not count:
                raise EOFError
            offset += count
        return bytes(data)

    def packets(self):
        latest = 0
        while True:
            kind, sequence, timestamp = HEADER.unpack(self.read(HEADER.size))
            if kind == HEARTBEAT and sequence == latest:
                yield sequence, timestamp, None
            elif kind == FRAME and sequence == latest + 1:
                latest = sequence
                probe = self.packet_probe
                header = monotonic_ns() if probe is not None else 0
                data = self.read(FRAME_BYTES)
                if probe is not None:
                    probe('wire', sequence, timestamp, header, monotonic_ns())
                yield sequence, timestamp, data
            else:
                raise ValueError('invalid_media_header')

    def reason(self):
        if self.metadata is None:
            return 'presentation_unavailable'
        with closing(socket.socket(socket.AF_UNIX)) as peer:
            with self.diagnostic_lock:
                if self.cancelled.is_set():
                    return 'connection_lost'
                self.diagnostic_peer = peer
            try:
                rpc = self._connect_rpc(peer, 1)
                if self._authenticate(rpc) != self.metadata['principal']:
                    return 'presentation_principal_mismatch'
                stream = self.metadata['stream']
                row = rpc.call('presentation.status', **self.identity, stream=stream)
                expected = dict(**self.identity, stream=stream, principal=self.metadata['principal'])
                if not matches(row, expected) or row.get('state') != 'closed':
                    return 'session_ended_or_unreachable'
                reason = row.get('reason')
                return reason if isinstance(reason, str) and reason in REASONS else 'connection_lost'
            except Fault as error:
                if error.code == -32002 and error.message == 'presentation_identity_mismatch':
                    return error.message
                return 'session_ended_or_unreachable'
            except (OSError, EOFError, ValueError, TypeError, KeyError, AssertionError, AttributeError):
                return 'session_ended_or_unreachable'
            finally:
                with self.diagnostic_lock:
                    self.diagnostic_peer = None
