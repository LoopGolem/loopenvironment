# SPDX-License-Identifier: Apache-2.0
"""Pinned read-only activity polling over its own LoopBridge RPC socket."""
from dataclasses import dataclass
from threading import Event
from time import monotonic

from .bridge import BridgeClient, EPOCH, PHASES
from .errors import Error, ShellError

POLL_INTERVAL = 2
# Both Broker profiles permit 62 requests (auth, snapshot and 60 polls).
MAX_POLLS = 60
MAX_CONNECTION_AGE = 170
MAX_EVENTS = 8  # Session.history retention on the current wire contract.
MAX_COUNTER = (1 << 63) - 1
EVENT_KINDS = frozenset((
    'grant.changed', 'grant.revoked', 'state.changed', 'control.changed',
    'control.released', 'control.disconnected', 'control.invalidated',
    'operation.confirmed', 'operation.unknown', 'operation.resolved', 'journal.unavailable',
))


@dataclass(frozen=True)
class ActivityEvent:
    sequence: int
    kind: str
    phase: str
    revision: int


def valid_counter(value):
    return type(value) is int and 0 <= value <= MAX_COUNTER


def require_epoch(value, selected):
    if not isinstance(value, str) or not EPOCH.fullmatch(value):
        raise ShellError(Error.INVALID_RESPONSE)
    if value != selected:
        raise ShellError(Error.EPOCH_CHANGED)


def project_batch(reply, epoch, previous):
    """Validate the entire batch before advancing the cursor or rendering rows."""
    if (not isinstance(reply, dict) or set(reply) != {'epoch', 'cursor', 'events'}
            or not valid_counter(previous)):
        raise ShellError(Error.INVALID_RESPONSE)
    require_epoch(reply.get('epoch'), epoch)
    cursor, events = reply.get('cursor'), reply.get('events')
    if not valid_counter(cursor) or not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ShellError(Error.INVALID_RESPONSE)
    if cursor != previous + len(events):
        raise ShellError(Error.INVALID_RESPONSE)

    projected = []
    for sequence, row in enumerate(events, start=previous + 1):
        if (not isinstance(row, dict) or row.get('source') != 'authority'
                or not valid_counter(row.get('seq')) or row['seq'] != sequence):
            raise ShellError(Error.INVALID_RESPONSE)
        require_epoch(row.get('epoch'), epoch)
        kind, state = row.get('kind'), row.get('state')
        if not isinstance(kind, str) or kind not in EVENT_KINDS or not isinstance(state, dict):
            raise ShellError(Error.INVALID_RESPONSE)
        phase, revision = state.get('phase'), state.get('revision')
        if phase not in PHASES or not valid_counter(revision):
            raise ShellError(Error.INVALID_RESPONSE)
        projected.append(ActivityEvent(sequence, kind, phase, revision))
    return cursor, tuple(projected)


class ActivityClient(BridgeClient):
    def __init__(self, endpoint, expected_uid, selection, *, timeout=3, clock=monotonic):
        super().__init__(endpoint, expected_uid, timeout=timeout)
        self.selection = selection
        self.clock = clock
        self.cancelled = Event()
        self.cursor = None
        self.started = None

    def begin(self, credential):
        self.cursor = None
        self.started = self.clock()
        try:
            self.connect(credential)
            if self.principal != self.selection.principal:
                raise ShellError(Error.AUTHENTICATION)
            snapshot = self._snapshot(self.selection.session)
            require_epoch(snapshot.get('epoch'), self.selection.epoch)
            cursor = snapshot.get('cursor')
            if not valid_counter(cursor):
                self._invalid_response()
            self.cursor = cursor
        except ShellError:
            self.close()
            raise

    def poll(self):
        if self.cursor is None:
            raise ShellError(Error.SNAPSHOT_REQUIRED)
        try:
            row = self._read('events', session=self.selection.session,
                             epoch=self.selection.epoch, cursor=self.cursor)
            cursor, events = project_batch(row, self.selection.epoch, self.cursor)
        except ShellError:
            self.cursor = None
            self.close()
            raise
        self.cursor = cursor
        return events

    def updates(self):
        if self.cursor is None:
            raise ShellError(Error.SNAPSHOT_REQUIRED)
        for _ in range(MAX_POLLS):
            if self.cancelled.is_set():
                return
            if self.clock() - self.started >= MAX_CONNECTION_AGE:
                break
            yield self.poll()
            if self.cancelled.wait(POLL_INTERVAL):
                return
        raise ShellError(Error.REAUTH_REQUIRED)

    def cancel(self):
        self.cancelled.set()
        self.interrupt()

    def _exchange(self, method, params):
        if self.cancelled.is_set():
            raise ShellError(Error.DISCONNECTED)
        return super()._exchange(method, params)
