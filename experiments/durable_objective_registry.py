# SPDX-License-Identifier: Apache-2.0
"""SQLite storage for the experimental objective registry, outside LoopBridge."""
from contextlib import closing, contextmanager
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import stat
from time import time

from experiments.objective_registry import (Error, Executor, ExecutorAction, ExecutorState,
                                            MAX_EXECUTORS, MAX_LABEL_BYTES, MAX_OBJECTIVES,
                                            MAX_RECEIPTS, MAX_TEXT_BYTES, Objective,
                                            ObjectiveAction, ObjectiveState, OPEN, Receipt,
                                            Registry, RegistryError, _valid_revision,
                                            _validate_ids, _validate_text)

SCHEMA_VERSION = 1
APPLICATION_ID = 0x4C4F424A
RECEIPT_RETENTION_SECONDS = 86_400
MAX_TERMINAL_RECEIPTS = MAX_EXECUTORS + MAX_OBJECTIVES
MAX_AUDIT = 1024
MAX_WALL = 253_402_300_799

SCHEMA = (
    """CREATE TABLE registry_clock (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        last_wall REAL NOT NULL CHECK (last_wall >= 0)
    ) STRICT""",
    """CREATE TABLE executors (
        id TEXT PRIMARY KEY NOT NULL,
        principal TEXT NOT NULL,
        label TEXT NOT NULL CHECK (length(CAST(label AS BLOB)) BETWEEN 1 AND 128),
        registered_by TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('pending', 'available', 'suspended', 'revoked')),
        revision INTEGER NOT NULL CHECK (revision >= 1),
        changed_by TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE objectives (
        id TEXT PRIMARY KEY NOT NULL,
        executor_id TEXT NOT NULL REFERENCES executors(id),
        issuer TEXT NOT NULL,
        text TEXT NOT NULL CHECK (length(CAST(text AS BLOB)) BETWEEN 1 AND 4096),
        expires_at REAL NOT NULL CHECK (expires_at >= 0),
        changed_by TEXT,
        offered INTEGER NOT NULL CHECK (offered IN (0, 1)),
        state TEXT NOT NULL CHECK (state IN ('created', 'offered', 'accepted', 'declined', 'withdrawn', 'expired')),
        revision INTEGER NOT NULL CHECK (revision >= 1),
        CHECK ((state = 'expired') = (changed_by IS NULL)),
        CHECK (state NOT IN ('offered', 'accepted', 'declined') OR offered = 1),
        CHECK (state != 'created' OR offered = 0)
    ) STRICT""",
    """CREATE TABLE receipts (
        principal TEXT NOT NULL,
        request_id TEXT NOT NULL,
        digest BLOB NOT NULL CHECK (length(digest) = 32),
        entity TEXT NOT NULL CHECK (entity IN ('executor', 'objective')),
        record_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision >= 1),
        state TEXT NOT NULL,
        expires_at REAL NOT NULL CHECK (expires_at >= 0),
        terminal INTEGER NOT NULL CHECK (terminal IN (0, 1)),
        PRIMARY KEY (principal, request_id)
    ) STRICT""",
    """CREATE TABLE audit (
        sequence INTEGER PRIMARY KEY,
        at REAL NOT NULL CHECK (at >= 0),
        actor TEXT,
        entity TEXT NOT NULL CHECK (entity IN ('executor', 'objective')),
        record_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision >= 1),
        state TEXT NOT NULL
    ) STRICT""",
)
TABLES = ('registry_clock', 'executors', 'objectives', 'receipts', 'audit')
EXECUTOR_COLUMNS = 'id, principal, label, registered_by, state, revision, changed_by'
OBJECTIVE_COLUMNS = 'id, executor_id, issuer, text, expires_at, changed_by, offered, state, revision'
RECEIPT_COLUMNS = 'principal, request_id, digest, entity, record_id, revision, state, expires_at, terminal'


@dataclass(frozen=True)
class _StoredReceipt:
    digest: bytes
    outcome: Receipt
    expires_at: float
    terminal: bool


def _digest(signature):
    # Include the action type to keep executor and objective actions distinct.
    parts = []
    for value in signature:
        if isinstance(value, Enum):
            parts.append([type(value).__name__, value.name])
        elif isinstance(value, bytes):
            parts.append(value.hex())
        else:
            parts.append(value)
    return sha256(json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode()).digest()


def _valid_wall(value):
    return type(value) in (float, int) and 0 <= value <= MAX_WALL


def _storage_error(error):
    code = getattr(error, 'sqlite_errorcode', 0) & 255
    if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CONSTRAINT):
        return RegistryError(Error.INVALID_STORAGE)
    return RegistryError(Error.STORAGE_UNAVAILABLE)


def _private_file(path, *, create=False):
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        raise RegistryError(Error.STORAGE_UNAVAILABLE)
    if create:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
    metadata = path.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_nlink != 1):
        raise RegistryError(Error.STORAGE_UNAVAILABLE)


class SQLiteRegistry(Registry):
    """Use one bounded SQL transaction per authorized domain operation.

    The database belongs in a trusted private directory. Authorization must
    expose revalidate() and pin policy changes through commit, as RegistryPolicy
    does within its process.
    """

    application_id = APPLICATION_ID
    schema = dict(zip(TABLES, SCHEMA))

    def __init__(self, path, authority, *, wall_clock=time, create=False, storage_check=None):
        super().__init__(authority, clock=lambda: self._decision_time)
        self._wall_clock = wall_clock
        self._decision_time = None
        self._storage_check = storage_check
        self.path = Path(os.path.abspath(path))
        try:
            _private_file(self.path, create=create)
            with closing(self._connect()) as db:
                self._initialize(db, create=create)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            raise RegistryError(Error.STORAGE_UNAVAILABLE) from None
        except sqlite3.Error as error:
            raise _storage_error(error) from None

    def _connect(self):
        if self._storage_check is not None:
            self._storage_check()
        _private_file(self.path)
        # mode=rw prevents silent creation if the evidence database disappears.
        db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=2, isolation_level=None)
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=EXTRA')
            if (db.execute('PRAGMA journal_mode').fetchone() != ('delete',)
                    or db.execute('PRAGMA synchronous').fetchone() != (3,)
                    or db.execute('PRAGMA foreign_keys').fetchone() != (1,)):
                raise RegistryError(Error.STORAGE_UNAVAILABLE)
        except BaseException:
            db.close()
            raise
        return db

    def _wall(self, floor):
        now = self._wall_clock()
        if not _valid_wall(now) or now < floor:
            raise RegistryError(Error.CLOCK_UNCERTAIN)
        return now

    def _initialize(self, db, *, create):
        db.execute('BEGIN IMMEDIATE')
        version, = db.execute('PRAGMA user_version').fetchone()
        app, = db.execute('PRAGMA application_id').fetchone()
        if create and (version, app) == (0, 0) and not db.execute('SELECT 1 FROM sqlite_schema LIMIT 1').fetchone():
            for statement in self.schema.values():
                db.execute(statement)
            db.execute('INSERT INTO registry_clock VALUES (1, ?)', (self._wall(0),))
            db.execute(f'PRAGMA application_id={self.application_id}')
            db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        self._check_schema(db)
        if (db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]
                or db.execute('PRAGMA foreign_key_check').fetchone() is not None):
            raise RegistryError(Error.INVALID_STORAGE)
        now = self._wall(self._watermark(db))
        self._load(db, now)
        self._executors, self._objectives, self._receipts = {}, {}, {}
        if self._storage_check is not None:
            self._storage_check()
        db.commit()

    def _check_schema(self, db):
        if (db.execute('PRAGMA user_version').fetchone() != (SCHEMA_VERSION,)
                or db.execute('PRAGMA application_id').fetchone() != (self.application_id,)):
            raise RegistryError(Error.INVALID_STORAGE)
        objects = db.execute("SELECT type, name, sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'")
        expected = {('table', name, ' '.join(sql.split())) for name, sql in self.schema.items()}
        if {(kind, name, ' '.join(sql.split()) if sql else None) for kind, name, sql in objects} != expected:
            raise RegistryError(Error.INVALID_STORAGE)

    @staticmethod
    def _watermark(db):
        row = db.execute('SELECT last_wall FROM registry_clock WHERE id=1').fetchone()
        if row is None or not _valid_wall(row[0]):
            raise RegistryError(Error.INVALID_STORAGE)
        return row[0]

    def _load(self, db, now):
        self._executors, self._objectives, self._receipts = {}, {}, {}
        try:
            for key, principal, label, author, state, revision, actor in db.execute(
                    f'SELECT {EXECUTOR_COLUMNS} FROM executors LIMIT ?', (MAX_EXECUTORS + 1,)):
                _validate_ids(key, principal, author, actor)
                _validate_text(label, MAX_LABEL_BYTES)
                _valid_revision(revision)
                self._executors[key] = Executor(key, principal, label, author, ExecutorState(state), revision)
            if len(self._executors) > MAX_EXECUTORS:
                raise ValueError

            for key, target, issuer, text, deadline, actor, offered, state, revision in db.execute(
                    f'SELECT {OBJECTIVE_COLUMNS} FROM objectives ORDER BY rowid LIMIT ?', (MAX_OBJECTIVES + 1,)):
                _validate_ids(key, target, issuer)
                if actor is not None:
                    _validate_ids(actor)
                _validate_text(text, MAX_TEXT_BYTES, multiline=True)
                _valid_revision(revision)
                state = ObjectiveState(state)
                executor = self._executors[target]
                if (not _valid_wall(deadline) or offered not in (0, 1)
                        or (state is ObjectiveState.EXPIRED) != (actor is None)
                        or (state is ObjectiveState.CREATED and offered)
                        or (state in (ObjectiveState.OFFERED, ObjectiveState.ACCEPTED, ObjectiveState.DECLINED)
                            and not offered)
                        or (state in OPEN and executor.state is ExecutorState.REVOKED)):
                    raise ValueError
                self._objectives[key] = Objective(key, target, issuer, text, deadline, actor,
                                                  bool(offered), state, revision)
            if len(self._objectives) > MAX_OBJECTIVES:
                raise ValueError

            limit = MAX_RECEIPTS + MAX_TERMINAL_RECEIPTS
            receipt_count = 0
            for actor, key, digest, entity, target, revision, state, until, terminal in db.execute(
                    f'SELECT {RECEIPT_COLUMNS} FROM receipts LIMIT ?', (limit + 1,)):
                receipt_count += 1
                _validate_ids(actor, key, target)
                _valid_revision(revision)
                records, states = ((self._executors, ExecutorState) if entity == 'executor'
                                   else (self._objectives, ObjectiveState))
                record, state = records[target], states(state)
                if (not _valid_wall(until) or type(digest) is not bytes or len(digest) != 32
                        or terminal not in (0, 1) or revision > record.revision
                        or (revision == record.revision and state is not record.state)
                        or (terminal and state not in (ExecutorState.REVOKED, ObjectiveState.WITHDRAWN))):
                    raise ValueError
                if now < until:
                    self._receipts[actor, key] = _StoredReceipt(digest, Receipt(target, revision, state),
                                                               until, bool(terminal))
            if (receipt_count > limit or self._receipt_count(False) > MAX_RECEIPTS
                    or self._receipt_count(True) > MAX_TERMINAL_RECEIPTS):
                raise ValueError
        except (KeyError, ValueError, RegistryError):
            raise RegistryError(Error.INVALID_STORAGE) from None

    def _receipt_count(self, terminal):
        return sum(row.terminal is terminal for row in self._receipts.values())

    def _replay(self, key, signature):
        stored = self._receipts.get(key)
        if stored is not None:
            if stored.digest != _digest(signature):
                raise RegistryError(Error.REQUEST_CONFLICT)
            return stored.outcome
        return None

    def _finish(self, key, signature, record):
        terminal = signature[0] in (ExecutorAction.REVOKE, ObjectiveAction.WITHDRAW)
        limit = MAX_TERMINAL_RECEIPTS if terminal else MAX_RECEIPTS
        if self._receipt_count(terminal) >= limit:
            raise RegistryError(Error.CAPACITY)
        result = Receipt(record.id, record.revision, record.state)
        until = self._decision_time + RECEIPT_RETENTION_SECONDS
        if not _valid_wall(until):
            raise RegistryError(Error.CLOCK_UNCERTAIN)
        self._receipts[key] = _StoredReceipt(_digest(signature), result, until, terminal)
        return result

    def _save(self, db, before_executors, before_objectives, previous_receipts, principal):
        changes = []
        for key, row in self._executors.items():
            if before_executors.get(key) != row:
                db.execute(f'INSERT INTO executors ({EXECUTOR_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?) '
                           'ON CONFLICT(id) DO UPDATE SET state=excluded.state, revision=excluded.revision, '
                           'changed_by=excluded.changed_by',
                           (key, row.principal, row.label, row.registered_by, row.state, row.revision, principal))
                changes.append((principal, 'executor', key, row.revision, row.state))

        for key, row in self._objectives.items():
            if before_objectives.get(key) != row:
                db.execute(f'INSERT INTO objectives ({OBJECTIVE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) '
                           'ON CONFLICT(id) DO UPDATE SET changed_by=excluded.changed_by, offered=excluded.offered, '
                           'state=excluded.state, revision=excluded.revision',
                           (key, row.executor_id, row.issuer, row.text, row.expires_at, row.changed_by,
                            row.offered, row.state, row.revision))
                changes.append((row.changed_by, 'objective', key, row.revision, row.state))

        db.execute('DELETE FROM receipts WHERE expires_at <= ?', (self._decision_time,))
        for (actor, key), row in self._receipts.items():
            if (actor, key) not in previous_receipts:
                receipt = row.outcome
                entity = 'executor' if isinstance(receipt.state, ExecutorState) else 'objective'
                db.execute(f'INSERT INTO receipts ({RECEIPT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                           (actor, key, row.digest, entity, receipt.id, receipt.revision, receipt.state,
                            row.expires_at, row.terminal))

        if changes:
            db.executemany('INSERT INTO audit (at, actor, entity, record_id, revision, state) VALUES (?, ?, ?, ?, ?, ?)',
                           ((self._decision_time, *change) for change in changes))
            db.execute('DELETE FROM audit WHERE sequence <= (SELECT max(sequence) - ? FROM audit)', (MAX_AUDIT,))

    @staticmethod
    def _write_watermark(db, now):
        db.execute('UPDATE registry_clock SET last_wall=? WHERE id=1', (now,))

    def _prepare_commit(self, db, revalidate):
        self._write_watermark(db, self._wall(self._decision_time))
        revalidate()

    def _commit(self, db):
        db.commit()

    @contextmanager
    def _transaction(self, actor):
        revalidate = getattr(actor, 'revalidate', None)
        if not callable(revalidate):
            raise RegistryError(Error.DENIED)
        with self._lock:
            outcome = None
            committing = False
            try:
                with closing(self._connect()) as db:
                    db.execute('BEGIN IMMEDIATE')
                    self._check_schema(db)
                    self._decision_time = self._wall(self._watermark(db))
                    self._load(db, self._decision_time)
                    before_executors, before_objectives = self._executors.copy(), self._objectives.copy()
                    previous_receipts = set(self._receipts)
                    try:
                        yield
                    except RegistryError as error:
                        if error.code is not Error.EXPIRED:
                            raise
                        # The clock transition is legitimate even when the request expired.
                        outcome = error
                    self._save(db, before_executors, before_objectives, previous_receipts, actor.principal)
                    if self._storage_check is not None:
                        self._storage_check()
                    self._prepare_commit(db, revalidate)
                    committing = True
                    self._commit(db)
            except sqlite3.Error as error:
                if committing:
                    raise RegistryError(Error.COMMIT_UNKNOWN) from None
                raise _storage_error(error) from None
            except OSError:
                raise RegistryError(Error.COMMIT_UNKNOWN if committing else Error.STORAGE_UNAVAILABLE) from None
            finally:
                self._executors, self._objectives, self._receipts = {}, {}, {}
                self._decision_time = None
            if outcome is not None:
                raise outcome
