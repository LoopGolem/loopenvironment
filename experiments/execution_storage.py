# SPDX-License-Identifier: Apache-2.0
"""Durable attempt and event storage for the isolated D.2A Registry profile."""
from contextlib import closing, contextmanager
from dataclasses import dataclass
import sqlite3

from experiments.durable_objective_registry import _storage_error, _valid_wall
from experiments.objective_registry import Error, RegistryError
from experiments.registry_lab import _BoundRegistry
from experiments.registry_rpc import OPAQUE_ID

OPERATION = 'add_fixed_constants'
MAX_ATTEMPTS = 256
MAX_TTL = 300
MAX_REVISION = 2**53 - 1

TRANSITIONS = {
    'admitted': {'running', 'cancelled', 'revoked', 'expired'},
    'running': {'completed', 'failed', 'cancelled', 'revoked', 'expired', 'uncertain'},
}
SCHEMA = {
    'execution_clock': """CREATE TABLE execution_clock (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        last_wall REAL NOT NULL CHECK (last_wall >= 0)
    ) STRICT""",
    'execution_attempts': f"""CREATE TABLE execution_attempts (
        id TEXT PRIMARY KEY NOT NULL,
        authorizer TEXT NOT NULL,
        performer TEXT NOT NULL,
        request_id TEXT NOT NULL,
        executor_id TEXT NOT NULL REFERENCES executors(id),
        objective_id TEXT NOT NULL REFERENCES objectives(id),
        accepted_revision INTEGER NOT NULL CHECK (accepted_revision BETWEEN 1 AND {MAX_REVISION}),
        operation TEXT NOT NULL CHECK (operation = '{OPERATION}'),
        ttl_seconds INTEGER NOT NULL CHECK (ttl_seconds BETWEEN 1 AND {MAX_TTL}),
        executor_revision INTEGER NOT NULL CHECK (executor_revision BETWEEN 1 AND {MAX_REVISION}),
        deadline REAL NOT NULL CHECK (deadline >= 0),
        authorize_generation TEXT NOT NULL,
        perform_generation TEXT NOT NULL,
        UNIQUE (authorizer, request_id)
    ) STRICT""",
    'execution_events': """CREATE TABLE execution_events (
        attempt_id TEXT NOT NULL REFERENCES execution_attempts(id),
        revision INTEGER NOT NULL CHECK (revision BETWEEN 1 AND 3),
        state TEXT NOT NULL,
        at REAL NOT NULL CHECK (at >= 0),
        actor TEXT,
        result INTEGER,
        reason TEXT,
        PRIMARY KEY (attempt_id, revision),
        CHECK (
            (revision = 1 AND state = 'admitted') OR
            (revision = 2 AND state IN ('running', 'cancelled', 'revoked', 'expired')) OR
            (revision = 3 AND state IN ('completed', 'failed', 'cancelled', 'revoked', 'expired', 'uncertain'))
        ),
        CHECK ((state IN ('admitted', 'running', 'completed', 'failed', 'cancelled')) = (actor IS NOT NULL)),
        CHECK ((state = 'completed' AND result IS 5) OR (state != 'completed' AND result IS NULL)),
        CHECK ((state = 'failed' AND reason IS 'operation_failed') OR
               (state = 'uncertain' AND reason IS 'interrupted') OR
               (state NOT IN ('failed', 'uncertain') AND reason IS NULL))
    ) STRICT""",
}


@dataclass(frozen=True)
class Scope:
    executor_id: str
    objective_id: str
    accepted_revision: int
    operation: str

    def valid(self):
        return (all(type(value) is str and OPAQUE_ID.fullmatch(value)
                    for value in (self.executor_id, self.objective_id))
                and type(self.accepted_revision) is int and 1 <= self.accepted_revision <= MAX_REVISION
                and type(self.operation) is str and self.operation == OPERATION)


@dataclass(frozen=True)
class Attempt:
    id: str
    authorizer: str
    performer: str
    request_id: str
    scope: Scope
    ttl_seconds: int
    executor_revision: int
    deadline: float
    authorize_generation: str
    perform_generation: str

    @classmethod
    def from_row(cls, row):
        return cls(*row[:4], Scope(*row[4:8]), *row[8:])

    def values(self):
        scope = self.scope
        return (self.id, self.authorizer, self.performer, self.request_id, scope.executor_id,
                scope.objective_id, scope.accepted_revision, scope.operation, self.ttl_seconds,
                self.executor_revision, self.deadline, self.authorize_generation, self.perform_generation)


@dataclass(frozen=True)
class Event:
    revision: int
    state: str
    at: float
    actor: str | None
    result: int | None
    reason: str | None

    def receipt(self, attempt):
        return dict(id=attempt.id, state=self.state, revision=self.revision)


@dataclass(frozen=True)
class Target:
    executor_id: str
    principal: str
    executor_state: str
    executor_revision: int
    objective_state: str
    objective_revision: int
    deadline: float


class DeadlinePassed(Exception):
    """The last clock check lost to a deadline before committing."""


class ExecutionTransaction:
    def __init__(self, db, clock, floor):
        self._db = db
        self._clock = clock
        self.now = floor
        self._cutoff = float('inf')
        self._changed = False

    def sample_time(self):
        self.now = self._clock(self.now)
        return self.now

    def require_before(self, deadline):
        self._cutoff = min(self._cutoff, deadline)

    def prepare_commit(self):
        if self._changed:
            self._db.execute('INSERT INTO execution_clock VALUES (1, ?) '
                             'ON CONFLICT(id) DO UPDATE SET last_wall=excluded.last_wall', (self.now,))
        if self.sample_time() >= self._cutoff:
            raise DeadlinePassed

    def target(self, objective_id):
        row = self._db.execute(
            'SELECT e.id, e.principal, e.state, e.revision, o.state, o.revision, o.expires_at '
            'FROM objectives o JOIN executors e ON o.executor_id=e.id WHERE o.id=?',
            (objective_id,)).fetchone()
        return Target(*row) if row else None

    def find(self, attempt_id):
        row = self._db.execute('SELECT * FROM execution_attempts WHERE id=?', (attempt_id,)).fetchone()
        return Attempt.from_row(row) if row else None

    def find_request(self, authorizer, request_id):
        row = self._db.execute('SELECT * FROM execution_attempts WHERE authorizer=? AND request_id=?',
                               (authorizer, request_id)).fetchone()
        return Attempt.from_row(row) if row else None

    def attempts(self):
        rows = self._db.execute('SELECT * FROM execution_attempts LIMIT ?', (MAX_ATTEMPTS + 1,)).fetchall()
        if len(rows) > MAX_ATTEMPTS:
            raise RegistryError(Error.INVALID_STORAGE)
        return [Attempt.from_row(row) for row in rows]

    def history(self, attempt):
        rows = self._db.execute('SELECT revision, state, at, actor, result, reason FROM execution_events '
                                'WHERE attempt_id=? ORDER BY revision', (attempt.id,))
        events = [Event(*row) for row in rows]
        if not events:
            raise RegistryError(Error.INVALID_STORAGE)
        return events

    def admit(self, attempt):
        count, = self._db.execute('SELECT count(*) FROM execution_attempts').fetchone()
        if count >= MAX_ATTEMPTS:
            raise RegistryError(Error.CAPACITY)
        self._db.execute('INSERT INTO execution_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                         attempt.values())
        return self.append(attempt, None, 'admitted', actor=attempt.authorizer)

    def append(self, attempt, previous, state, *, actor=None, result=None, reason=None):
        revision = 1 if previous is None else previous.revision + 1
        event = Event(revision, state, self.now, actor, result, reason)
        self._db.execute('INSERT INTO execution_events VALUES (?, ?, ?, ?, ?, ?, ?)',
                         (attempt.id, revision, state, self.now, actor, result, reason))
        self._changed = True
        return event


class ExecutionRegistry(_BoundRegistry):
    application_id = 0x4C4F4558
    schema = {**_BoundRegistry.schema, **SCHEMA}

    @contextmanager
    def execution_transaction(self):
        """The caller holds the ingress/policy mutex through this transaction."""
        committing = False
        with self._lock:
            try:
                with closing(self._connect()) as db:
                    db.execute('BEGIN IMMEDIATE')
                    self._check_schema(db)
                    row = db.execute('SELECT last_wall FROM execution_clock WHERE id=1').fetchone()
                    if row is not None and not _valid_wall(row[0]):
                        raise RegistryError(Error.INVALID_STORAGE)
                    floor = max(self._watermark(db), row[0] if row else 0)
                    tx = ExecutionTransaction(db, self._wall, self._wall(floor))
                    yield tx
                    tx.prepare_commit()
                    committing = True
                    self._commit(db)
            except sqlite3.Error as error:
                if committing:
                    raise RegistryError(Error.COMMIT_UNKNOWN) from None
                raise _storage_error(error) from None
            except OSError:
                raise RegistryError(Error.COMMIT_UNKNOWN if committing else Error.STORAGE_UNAVAILABLE) from None

    def recover_execution(self):
        with self.execution_transaction() as tx:
            for attempt in tx.attempts():
                events = tx.history(attempt)
                self._validate_history(attempt, events, tx)
                previous = events[-1]
                if previous.state == 'admitted':
                    tx.append(attempt, previous, 'revoked')
                elif previous.state == 'running':
                    tx.append(attempt, previous, 'uncertain', reason='interrupted')

    @staticmethod
    def _validate_history(attempt, events, tx):
        ids = (attempt.id, attempt.authorizer, attempt.performer, attempt.request_id,
               attempt.authorize_generation, attempt.perform_generation)
        first = events[0]
        target = tx.target(attempt.scope.objective_id)
        if (not all(OPAQUE_ID.fullmatch(value) for value in ids) or not attempt.scope.valid()
                or target is None or target.executor_id != attempt.scope.executor_id
                or target.principal != attempt.performer or target.executor_revision < attempt.executor_revision
                or target.objective_revision < attempt.scope.accepted_revision
                or not _valid_wall(attempt.deadline) or attempt.deadline > target.deadline
                or not first.at < attempt.deadline <= first.at + attempt.ttl_seconds
                or first.revision != 1 or first.state != 'admitted' or first.actor != attempt.authorizer):
            raise RegistryError(Error.INVALID_STORAGE)
        for previous, event in zip(events, events[1:]):
            if (event.revision != previous.revision + 1
                    or event.state not in TRANSITIONS.get(previous.state, ())
                    or not previous.at <= event.at <= tx.now
                    or (event.actor is not None and not OPAQUE_ID.fullmatch(event.actor))
                    or (event.state in ('running', 'completed', 'failed')
                        and (event.actor != attempt.performer or event.at >= attempt.deadline))
                    or (event.state == 'expired' and event.at < attempt.deadline)):
                raise RegistryError(Error.INVALID_STORAGE)
        if not _valid_wall(first.at) or first.at > tx.now:
            raise RegistryError(Error.INVALID_STORAGE)
