# SPDX-License-Identifier: Apache-2.0
"""Local read-only client for a pinned private presentation."""
from contextlib import closing
import socket

from .presentation import CAPABILITY, FORMAT, FRAME, FRAME_BYTES, HEADER, HEARTBEAT, STRIDE
from .private_effects import OUTPUT
from .protocol import Fault, RPC
from .service_ingress import peer_uid


class LiveConnection:
    def __init__(self, endpoint, token, session, private_id, epoch, *, expected_peer_uid=None):
        self.endpoint, self.token = str(endpoint), token
        self.expected_peer_uid = expected_peer_uid
        self.identity = dict(session=session, privateId=private_id, epoch=epoch)
        self.peer = socket.socket(socket.AF_UNIX)
        self.metadata = None
        self.channel = None

    def _connect_rpc(self, peer, connect_timeout):
        peer.settimeout(connect_timeout)
        peer.connect(self.endpoint)
        if self.expected_peer_uid is not None and peer_uid(peer) != self.expected_peer_uid:
            raise ValueError('unexpected_presentation_peer')
        return RPC(peer)

    def connect(self):
        rpc = self._connect_rpc(self.peer, 5)
        principal = rpc.call('auth', credential=self.token)['principal']
        self.metadata = rpc.call('presentation.open', **self.identity)
        expected = dict(**self.identity, principal=principal, width=OUTPUT[0], height=OUTPUT[1],
                        stride=STRIDE, format=FORMAT, input=False, capability=CAPABILITY,
                        authorization='authorized', state='opening', transport='unix_stream_upgrade_v1')
        if any(self.metadata.get(key) != value for key, value in expected.items()):
            raise ValueError('presentation_identity_or_format_mismatch')
        self.channel = rpc.channel
        self.peer.settimeout(5)
        return self.metadata

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
                rpc.call('auth', credential=self.token)
                row = rpc.call('presentation.status', **self.identity, stream=self.metadata['stream'])
                return row['reason'] or 'connection_lost'
            except (OSError, Fault, EOFError, ValueError, KeyError, AssertionError):
                return 'session_ended_or_unreachable'
