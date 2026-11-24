# SPDX-License-Identifier: Apache-2.0
"""Local read-only client for a pinned private presentation."""
from contextlib import closing, suppress
import re
import socket
from threading import Event

from .presentation import CAPABILITY, FORMAT, FRAME, FRAME_BYTES, HEADER, HEARTBEAT, STRIDE
from .private_effects import OUTPUT
from .protocol import Fault, RPC
from .service_ingress import peer_uid

PRIVATE_ID = re.compile(r'[a-f0-9]{16}')
STREAM_ID = re.compile(r'[a-f0-9]{32}')
REASONS = frozenset(('revoked', 'grant_expired', 'session_ended', 'viewer_disconnected',
                     'capture_failed', 'capture_unresponsive', 'slow_viewer', 'unexpected_media_input'))


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

    @staticmethod
    def _matches(row, expected):
        return isinstance(row, dict) and all(key in row and type(row[key]) is type(value)
                                             and row[key] == value for key, value in expected.items())

    def connect(self):
        rpc = self._connect_rpc(self.peer, 5)
        principal = self._authenticate(rpc)
        if self.expected_principal is not None and principal != self.expected_principal:
            raise Fault(-32001, 'presentation_principal_mismatch')

        # LoopShell already pins session and epoch on its console connection.
        # Resolve the private ID on this independently authenticated connection.
        expected = dict(principal=principal, width=OUTPUT[0], height=OUTPUT[1],
                        stride=STRIDE, format=FORMAT, input=False, capability=CAPABILITY,
                        authorization='authorized', transport='unix_stream_upgrade_v1')
        if self.identity['privateId'] is None:
            row = rpc.call('presentation.describe', session=self.identity['session'])
            if not self._matches(row, dict(expected, session=self.identity['session'])):
                raise ValueError('invalid_presentation_response')
            if row.get('epoch') != self.identity['epoch']:
                raise Fault(-32002, 'presentation_identity_mismatch')
            private_id = row.get('privateId')
            if not isinstance(private_id, str) or not PRIVATE_ID.fullmatch(private_id):
                raise ValueError('invalid_presentation_response')
            if row.get('state') == 'unavailable':
                raise Fault(-32006, 'presentation_unavailable')
            if row.get('state') != 'available':
                raise ValueError('invalid_presentation_response')
            self.identity['privateId'] = private_id
        row = rpc.call('presentation.open', **self.identity)
        if not self._matches(row, dict(expected, **self.identity, state='opening')):
            raise ValueError('presentation_identity_or_format_mismatch')
        stream = row.get('stream')
        if not isinstance(stream, str) or not STREAM_ID.fullmatch(stream):
            raise ValueError('invalid_presentation_response')
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
                yield sequence, timestamp, self.read(FRAME_BYTES)
            else:
                raise ValueError('invalid_media_header')

    def reason(self):
        if self.metadata is None:
            return 'presentation_unavailable'
        with closing(socket.socket(socket.AF_UNIX)) as peer:
            try:
                rpc = self._connect_rpc(peer, 1)
                if self._authenticate(rpc) != self.metadata['principal']:
                    return 'presentation_principal_mismatch'
                stream = self.metadata['stream']
                row = rpc.call('presentation.status', **self.identity, stream=stream)
                expected = dict(**self.identity, stream=stream, principal=self.metadata['principal'])
                if not self._matches(row, expected):
                    return 'session_ended_or_unreachable'
                reason = row.get('reason')
                return reason if isinstance(reason, str) and reason in REASONS else 'connection_lost'
            except Fault as error:
                if error.message == 'presentation_identity_mismatch':
                    return error.message
                return 'session_ended_or_unreachable'
            except (OSError, EOFError, ValueError, TypeError, KeyError, AssertionError, AttributeError):
                return 'session_ended_or_unreachable'
