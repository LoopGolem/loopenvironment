# SPDX-License-Identifier: Apache-2.0
"""M1.2 envelope/encoding reused; stricter parsing and absolute frame deadline."""
import json
import socket
import time
from experiments.m1_2.protocol import Channel, Fault, MAX_FRAME


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = value
    return result


class DeadlineChannel(Channel):
    def receive(self, budget):
        deadline = time.monotonic() + budget
        while b'\n' not in self.pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout
            self.sock.settimeout(remaining)
            chunk = self.sock.recv(1024)
            if not chunk:
                raise EOFError
            self.pending.extend(chunk)
            if len(self.pending) > MAX_FRAME:
                raise Fault(-32600, 'frame_limit')
        raw, _, rest = self.pending.partition(b'\n')
        self.pending = bytearray(rest)
        try:
            return json.loads(raw, object_pairs_hook=unique_object,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeError, RecursionError):
            raise Fault(-32700, 'parse_error') from None
