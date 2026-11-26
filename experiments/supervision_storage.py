# SPDX-License-Identifier: Apache-2.0
"""Ordered supervision ledger layered over the D.2A attempt history."""
from dataclasses import dataclass

from experiments.execution_storage import ExecutionRegistry, ExecutionTransaction, TRANSITIONS, attempt_schema
from experiments.objective_registry import Error, RegistryError
from experiments.registry_rpc import OPAQUE_ID

PLAN = 'add_in_two_stages'
STAGE_RESULTS = (2, 5)
MAX_ADVANCES = 8
# Each advance can be followed by one pause. Reserve room for lifecycle and stage events.
MAX_EVENTS = MAX_ADVANCES * 2 + 7
CONTROL_KINDS = {
    'start': {'running'}, 'pause': {'paused', 'pause_requested'}, 'step': {'step'},
    'continue': {'continue'}, 'cancel': {'cancelled'},
}
ADVANCE_MODES = {'step': 'stepping', 'continue': 'flowing'}
TERMINAL = frozenset(TRANSITIONS['running'])
SCHEMA = f"""CREATE TABLE supervision_events (
    attempt_id TEXT NOT NULL REFERENCES execution_attempts(id),
    revision INTEGER NOT NULL CHECK (revision BETWEEN 1 AND {MAX_EVENTS}),
    kind TEXT NOT NULL,
    at REAL NOT NULL CHECK (at >= 0),
    actor TEXT,
    lifecycle_revision INTEGER,
    stage INTEGER CHECK (stage BETWEEN 1 AND {len(STAGE_RESULTS)}),
    value INTEGER,
    action TEXT,
    request_id TEXT,
    expected_revision INTEGER,
    generation TEXT,
    deadline REAL,
    CHECK ((action IS NULL AND request_id IS NULL AND expected_revision IS NULL
             AND generation IS NULL AND deadline IS NULL) OR
           (action IS NOT NULL AND actor IS NOT NULL AND request_id IS NOT NULL
             AND expected_revision IS NOT NULL AND generation IS NOT NULL AND deadline IS NOT NULL)),
    PRIMARY KEY (attempt_id, revision),
    UNIQUE (attempt_id, actor, request_id),
    FOREIGN KEY (attempt_id, lifecycle_revision) REFERENCES execution_events(attempt_id, revision)
) STRICT"""


def _require(condition):
    if not condition:
        raise RegistryError(Error.INVALID_STORAGE)


@dataclass(frozen=True)
class Command:
    action: str
    request_id: str
    expected_revision: int
    generation: str
    deadline: float


@dataclass(frozen=True)
class Entry:
    revision: int
    kind: str
    at: float
    actor: str | None
    lifecycle_revision: int | None
    stage: int | None
    value: int | None
    command: Command | None

    def receipt(self, attempt):
        return dict(id=attempt.id, revision=self.revision, kind=self.kind)


class Progress:
    """Derive supervision from the small ordered prefix of durable events."""

    def __init__(self, attempt, entries, lifecycle, now):
        self.entries = entries
        self.state = None
        self.mode = None
        self.current_stage = None
        self.completed = 0
        self.driver = None
        self.advances = 0
        self.result = None
        self.reason = None
        self._value = None
        previous_at = 0
        lifecycle_index = 0
        _require(bool(entries))
        for revision, entry in enumerate(entries, 1):
            _require(self.state not in TERMINAL and entry.revision == revision and previous_at <= entry.at <= now)
            previous_at = entry.at
            if entry.actor is not None:
                _require(OPAQUE_ID.fullmatch(entry.actor) is not None)
            if entry.command is not None:
                self._validate_command(entry, attempt)
            if entry.lifecycle_revision is not None:
                _require(lifecycle_index < len(lifecycle))
                event = lifecycle[lifecycle_index]
                lifecycle_index += 1
                self._lifecycle(entry, event, attempt)
            else:
                self._supervision(entry, attempt)
        _require(lifecycle_index == len(lifecycle)
                 and (self.completed < len(STAGE_RESULTS) or self.state == 'completed')
                 and self.advances <= MAX_ADVANCES)

    @property
    def latest(self):
        return self.entries[-1]

    @property
    def value(self):
        return self._value

    def _validate_command(self, entry, attempt):
        command = entry.command
        _require(entry.kind in CONTROL_KINDS.get(command.action, ())
                 and OPAQUE_ID.fullmatch(command.request_id) is not None
                 and OPAQUE_ID.fullmatch(command.generation) is not None
                 and command.expected_revision == entry.revision - 1
                 and entry.at < command.deadline <= attempt.deadline)
        if command.action in ADVANCE_MODES:
            self.advances += 1

    def _lifecycle(self, entry, event, attempt):
        _require((entry.lifecycle_revision, entry.kind, entry.at, entry.actor)
                 == (event.revision, event.state, event.at, event.actor)
                 and entry.stage is None and entry.value is None)
        state = event.state
        if self.state is None:
            _require(state == 'admitted' and entry.command is None)
        else:
            _require(state in TRANSITIONS[self.state])
        if state == 'running':
            _require(entry.command is not None and entry.actor == attempt.performer)
            self.mode = 'paused'
        if state in TERMINAL:
            if state == 'completed':
                _require(self.completed == len(STAGE_RESULTS) and self.current_stage is None
                         and event.result == self.value == STAGE_RESULTS[-1]
                         and self.entries[entry.revision - 2].kind == 'stage_completed'
                         and self.entries[entry.revision - 2].at == entry.at)
            if state in ('failed', 'uncertain'):
                _require(self.current_stage is not None)
            _require((entry.command is not None) == (state == 'cancelled'))
            if state == 'expired':
                self.reason = self._expiry_reason(event, attempt)
            else:
                self.reason = event.reason or (None if state == 'completed' else state)
            self.mode = self.current_stage = self.driver = None
            self.result = event.result
        self.state = state

    def _expiry_reason(self, event, attempt):
        if event.at >= attempt.deadline:
            return 'attempt_expired'
        # The ledger carries the effective deadline of the still-active advance.
        _require(self.driver is not None and self.driver.command.deadline <= event.at)
        return 'advance_expired'

    def _supervision(self, entry, attempt):
        _require(self.state == 'running' and self.completed < len(STAGE_RESULTS))
        kind = entry.kind
        if kind in ADVANCE_MODES:
            _require(self.mode == 'paused' and self.current_stage is None and entry.command is not None)
            self.mode, self.driver = ADVANCE_MODES[kind], entry
        elif kind in ('paused', 'pause_requested'):
            _require(self.mode in ADVANCE_MODES.values() and entry.command is not None)
            _require(kind == ('paused' if self.current_stage is None else 'pause_requested'))
            self.mode = kind
            if kind == 'paused':
                self.driver = None
        else:
            self._stage(entry, attempt)
            return
        _require(entry.stage is None and entry.value is None)

    def _stage(self, entry, attempt):
        _require(entry.command is None and entry.actor == attempt.performer and self.driver is not None
                 and entry.stage == self.completed + 1
                 and entry.at < self.driver.command.deadline)
        if entry.kind == 'dispatched':
            _require(self.mode in ADVANCE_MODES.values() and self.current_stage is None and entry.value is None)
            self.current_stage = entry.stage
        else:
            _require(entry.kind == 'stage_completed' and self.current_stage == entry.stage
                     and entry.value == STAGE_RESULTS[entry.stage - 1])
            self.current_stage = None
            self.completed += 1
            self._value = entry.value
            if self.mode in ('stepping', 'pause_requested'):
                self.mode, self.driver = 'paused', None


class SupervisionTransaction(ExecutionTransaction):
    def append(self, attempt, previous, state, *, actor=None, result=None, reason=None, command=None):
        event = super().append(attempt, previous, state, actor=actor, result=result, reason=reason)
        self.record(attempt, state, actor, lifecycle_revision=event.revision, command=command)
        return event

    def record(self, attempt, kind, actor, *, lifecycle_revision=None, stage=None, value=None, command=None):
        last, = self._db.execute('SELECT max(revision) FROM supervision_events WHERE attempt_id=?',
                                 (attempt.id,)).fetchone()
        revision = (last or 0) + 1
        params = ((command.action, command.request_id, command.expected_revision, command.generation, command.deadline)
                  if command else (None,) * 5)
        self._db.execute('INSERT INTO supervision_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                         (attempt.id, revision, kind, self.now, actor, lifecycle_revision, stage, value, *params))
        return Entry(revision, kind, self.now, actor, lifecycle_revision, stage, value, command)

    def progress(self, attempt, lifecycle=None):
        rows = self._db.execute(
            'SELECT revision, kind, at, actor, lifecycle_revision, stage, value, action, request_id, '
            'expected_revision, generation, deadline FROM supervision_events WHERE attempt_id=? ORDER BY revision',
            (attempt.id,))
        entries = [Entry(*row[:7], Command(*row[7:]) if row[7] is not None else None) for row in rows]
        return Progress(attempt, entries, self.history(attempt) if lifecycle is None else lifecycle, self.now)


class SupervisionRegistry(ExecutionRegistry):
    application_id = 0x4C4F5358
    operation = PLAN
    schema = {**ExecutionRegistry.schema, 'execution_attempts': attempt_schema(PLAN), 'supervision_events': SCHEMA}
    _transaction_type = SupervisionTransaction

    @classmethod
    def _validate_history(cls, attempt, events, tx):
        cls._validate_lifecycle(attempt, events, tx)
        tx.progress(attempt, events)

    def _interrupted_state(self, tx, attempt, previous):
        return 'uncertain' if tx.progress(attempt).current_stage is not None else 'revoked'
