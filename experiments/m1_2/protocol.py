# SPDX-License-Identifier: Apache-2.0
"""Experimental JSON-RPC subset. No stable LoopBridge contract."""
from collections import deque
import json
import socket

MAX_FRAME = 8192


class Fault(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def encode(value):
    raw = json.dumps(value, separators=(',', ':'), allow_nan=False).encode() + b'\n'
    if len(raw) > MAX_FRAME:
        raise Fault(-32600, 'frame_limit')
    return raw


class Channel:
    def __init__(self, sock):
        self.sock, self.pending = sock, bytearray()

    def receive(self):
        while b'\n' not in self.pending:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise EOFError
            self.pending.extend(chunk)
            if len(self.pending) > MAX_FRAME:
                raise Fault(-32600, 'frame_limit')
        raw, _, rest = self.pending.partition(b'\n')
        self.pending = bytearray(rest)
        try:
            return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeError):
            raise Fault(-32700, 'parse_error') from None

    def send(self, value):
        self.sock.sendall(encode(value))


def request(value):
    if (not isinstance(value, dict) or set(value) != {'jsonrpc', 'id', 'method', 'params'}
            or value['jsonrpc'] != '2.0' or type(value['id']) is not int
            or not isinstance(value['method'], str) or not isinstance(value['params'], dict)):
        raise Fault(-32600, 'invalid_request')
    return value['id'], value['method'], value['params']


class History:
    def __init__(self, epoch, capacity=2):
        self.epoch, self.seq = epoch, 0
        self.items = deque(maxlen=capacity)

    def append(self, state):
        self.seq += 1
        self.items.append(dict(epoch=self.epoch, seq=self.seq, kind='state.changed',
                               source='atspi_query', state=state))

    def since(self, epoch, cursor):
        if epoch != self.epoch:
            raise Fault(-32004, 'epoch_changed_snapshot_required')
        if type(cursor) is not int or cursor < 0 or cursor > self.seq:
            raise Fault(-32602, 'invalid_cursor')
        if self.items and cursor < self.items[0]['seq'] - 1:
            raise Fault(-32003, 'gap_snapshot_required')
        return list(e for e in self.items if e['seq'] > cursor)


class RPC:
    def __init__(self, sock):
        self.channel, self.seq = Channel(sock), 0

    def call(self, method, **params):
        self.seq += 1
        self.channel.send(dict(jsonrpc='2.0', id=self.seq, method=method, params=params))
        reply = self.channel.receive()
        if reply.get('id') != self.seq or reply.get('jsonrpc') != '2.0':
            raise AssertionError('invalid_reply')
        if 'error' in reply:
            raise Fault(reply['error']['code'], reply['error']['message'])
        return reply['result']
