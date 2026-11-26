# SPDX-License-Identifier: Apache-2.0
"""Pinned SQLite history for D.2C.1. No payload bytes enter this schema."""
from contextlib import closing, contextmanager
from dataclasses import astuple, dataclass
import sqlite3

from experiments.durable_objective_registry import _storage_error
from experiments.execution_storage import Target
from experiments.objective_registry import Error, RegistryError
from experiments.registry_lab import _BoundRegistry
from experiments.workspace_document import CAPABILITY, MAX_CONTENT

MAX_TTL = 300
MAX_ATTEMPTS = 128
MAX_COMMANDS = 16
AUDIT_PAGE = 12
OPEN = frozenset(('ready', 'preparing', 'prepared', 'dispatched'))

SCHEMA = {
    'workspace_attempts': f"""CREATE TABLE workspace_attempts (
        id TEXT NOT NULL PRIMARY KEY CHECK (length(id) = 32),
        executor_id TEXT NOT NULL REFERENCES executors(id),
        objective_id TEXT NOT NULL REFERENCES objectives(id),
        accepted_revision INTEGER NOT NULL CHECK (accepted_revision >= 1),
        capability TEXT NOT NULL CHECK (capability = '{CAPABILITY}'),
        resource_id TEXT NOT NULL CHECK (length(resource_id) = 32),
        digest TEXT NOT NULL CHECK (length(digest) = 64),
        operation_id TEXT NOT NULL UNIQUE CHECK (length(operation_id) = 32),
        authorizer TEXT NOT NULL,
        performer TEXT NOT NULL,
        executor_revision INTEGER NOT NULL CHECK (executor_revision >= 1),
        request_id TEXT NOT NULL,
        ttl_seconds INTEGER NOT NULL CHECK (ttl_seconds BETWEEN 1 AND {MAX_TTL}),
        deadline REAL NOT NULL CHECK (deadline >= 0),
        authorizer_generation TEXT NOT NULL,
        performer_generation TEXT NOT NULL,
        resource_dev INTEGER NOT NULL,
        resource_ino INTEGER NOT NULL,
        size INTEGER NOT NULL CHECK (size BETWEEN 1 AND {MAX_CONTENT}),
        stage_dev INTEGER,
        stage_ino INTEGER,
        CHECK ((stage_dev IS NULL) = (stage_ino IS NULL)),
        UNIQUE (authorizer, request_id)
    ) STRICT""",
    'workspace_events': """CREATE TABLE workspace_events (
        attempt_id TEXT NOT NULL REFERENCES workspace_attempts(id),
        revision INTEGER NOT NULL CHECK (revision >= 1),
        at REAL NOT NULL CHECK (at >= 0),
        actor TEXT,
        kind TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN (
            'ready', 'preparing', 'prepared', 'dispatched', 'completed', 'reconciled',
            'cancelled', 'revoked', 'expired', 'failed', 'interrupted', 'uncertain')),
        supervision TEXT NOT NULL CHECK (supervision IN (
            'paused', 'stepping', 'flowing', 'pause_requested', 'stopped')),
        effect TEXT NOT NULL CHECK (effect IN ('none', 'absent', 'pending', 'observed', 'confirmed', 'unknown')),
        reason TEXT,
        request_id TEXT,
        expected_revision INTEGER,
        PRIMARY KEY (attempt_id, revision),
        UNIQUE (attempt_id, actor, request_id),
        CHECK ((request_id IS NULL) = (expected_revision IS NULL)),
        CHECK (request_id IS NULL OR actor IS NOT NULL)
    ) STRICT""",
}


@dataclass(frozen=True)
class Scope:
    attempt_id: str
    executor_id: str
    objective_id: str
    accepted_revision: int
    capability: str
    resource_id: str
    digest: str


@dataclass(frozen=True)
class Attempt:
    scope: Scope
    operation_id: str
    authorizer: str
    performer: str
    executor_revision: int
    request_id: str
    ttl_seconds: int
    deadline: float
    authorizer_generation: str
    performer_generation: str
    resource_dev: int
    resource_ino: int
    size: int
    stage_dev: int | None = None
    stage_ino: int | None = None

    @classmethod
    def from_row(cls, row):
        return cls(Scope(*row[:7]), *row[7:])

    @property
    def id(self):
        return self.scope.attempt_id

    @property
    def resource_pin(self):
        return self.resource_dev, self.resource_ino

    @property
    def stage_pin(self):
        return self.stage_dev, self.stage_ino


@dataclass(frozen=True)
class Event:
    revision: int
    at: float
    actor: str | None
    kind: str
    state: str
    supervision: str
    effect: str
    reason: str | None
    request_id: str | None
    expected_revision: int | None

    def receipt(self, attempt):
        return dict(id=attempt.id, revision=self.revision, kind=self.kind)


class DeadlinePassed(Exception):
    pass


EVENT_COLUMNS = 'revision, at, actor, kind, state, supervision, effect, reason, request_id, expected_revision'


class Transaction:
    def __init__(self, db, check, wall, now):
        self.db = db
        self.check_storage = check
        self.wall = wall
        self.now = now
        self.deadline = float('inf')

    def sample(self):
        self.now = self.wall(self.now)
        return self.now

    def finish(self):
        self.check_storage()
        now = self.sample()
        if now >= self.deadline:
            raise DeadlinePassed
        self.db.execute('UPDATE registry_clock SET last_wall=? WHERE id=1', (now,))

    def target(self, objective_id):
        row = self.db.execute(
            'SELECT e.id, e.principal, e.state, e.revision, o.state, o.revision, o.expires_at '
            'FROM objectives o JOIN executors e ON o.executor_id=e.id WHERE o.id=?',
            (objective_id,)).fetchone()
        return Target(*row) if row else None

    def _attempt(self, clause, values):
        row = self.db.execute('SELECT * FROM workspace_attempts WHERE ' + clause, values).fetchone()
        return Attempt.from_row(row) if row else None

    def find(self, attempt_id):
        return self._attempt('id=?', (attempt_id,))

    def find_request(self, authorizer, request_id):
        return self._attempt('authorizer=? AND request_id=?', (authorizer, request_id))

    def attempts(self):
        rows = self.db.execute('SELECT * FROM workspace_attempts LIMIT ?', (MAX_ATTEMPTS + 1,)).fetchall()
        if len(rows) > MAX_ATTEMPTS:
            raise RegistryError(Error.INVALID_STORAGE)
        return [Attempt.from_row(row) for row in rows]

    def admit(self, attempt):
        if self.db.execute('SELECT count(*) FROM workspace_attempts').fetchone()[0] >= MAX_ATTEMPTS:
            raise RegistryError(Error.CAPACITY)
        values = (*astuple(attempt.scope), *astuple(attempt)[1:])
        self.db.execute('INSERT INTO workspace_attempts VALUES (' + ','.join('?' for _ in values) + ')', values)
        return self.event(attempt, None, 'admitted', 'ready', actor=attempt.authorizer, supervision='paused',
                          effect='none')

    def prepared(self, attempt, pin):
        self.db.execute('UPDATE workspace_attempts SET stage_dev=?, stage_ino=? WHERE id=?', (*pin, attempt.id))

    def latest(self, attempt):
        row = self.db.execute(f'SELECT {EVENT_COLUMNS} FROM workspace_events WHERE attempt_id=? '
                              'ORDER BY revision DESC LIMIT 1', (attempt.id,)).fetchone()
        if row is None:
            raise RegistryError(Error.INVALID_STORAGE)
        return Event(*row)

    def command(self, attempt, actor, request_id):
        row = self.db.execute(f'SELECT {EVENT_COLUMNS} FROM workspace_events WHERE attempt_id=? '
                              'AND actor=? AND request_id=?', (attempt.id, actor, request_id)).fetchone()
        return Event(*row) if row else None

    def check_command_capacity(self, attempt, action):
        count, = self.db.execute('SELECT count(*) FROM workspace_events WHERE attempt_id=? '
                                 'AND request_id IS NOT NULL', (attempt.id,)).fetchone()
        # Keep a pause and a cancellation available after the last allowed advance.
        reserved = {'pause': 1, 'cancel': 0}.get(action, 2)
        if count >= MAX_COMMANDS - reserved:
            raise RegistryError(Error.CAPACITY)

    def history(self, attempt, after):
        rows = self.db.execute(f'SELECT {EVENT_COLUMNS} FROM workspace_events WHERE attempt_id=? AND revision>? '
                               'ORDER BY revision LIMIT ?', (attempt.id, after, AUDIT_PAGE))
        return [Event(*row) for row in rows]

    def event(self, attempt, previous, kind, state, *, actor=None, supervision='stopped',
              effect='absent', reason=None, request_id=None, expected_revision=None):
        revision = 1 if previous is None else previous.revision + 1
        event = Event(revision, self.now, actor, kind, state, supervision, effect,
                      reason, request_id, expected_revision)
        self.db.execute('INSERT INTO workspace_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (attempt.id, *astuple(event)))
        return event


class WorkspaceRegistry(_BoundRegistry):
    application_id = 0x4C4F5745
    schema = {**_BoundRegistry.schema, **SCHEMA}

    def _prepare_commit(self, db, revalidate):
        now = self._wall(self._decision_time)
        revalidate(now=now)
        self._write_watermark(db, now)

    @contextmanager
    def workspace_transaction(self, *, write=True):
        """Caller holds the shared Registry identity mutex on all live paths."""
        committing = False
        try:
            with self._lock, closing(self._connect()) as db:
                db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                self._check_schema(db)
                tx = Transaction(db, self._check_storage, self._wall, self._wall(self._watermark(db)))
                yield tx
                if write:
                    tx.finish()
                    committing = True
                    self._commit(db)
        except DeadlinePassed:
            raise RegistryError(Error.EXPIRED) from None
        except sqlite3.Error as error:
            if committing:
                raise RegistryError(Error.COMMIT_UNKNOWN) from None
            raise _storage_error(error) from None
        except OSError:
            raise RegistryError(Error.COMMIT_UNKNOWN if committing else Error.STORAGE_UNAVAILABLE) from None
