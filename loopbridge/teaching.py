# SPDX-License-Identifier: Apache-2.0
"""Persistent operator data and conservative, evidence-based matching."""
from contextlib import contextmanager
import json
import os
import re
import secrets
import sqlite3
import stat
import time

SCHEMA_VERSION = 1
TEACH_VERSION = '0.1'
CAPABILITIES = frozenset(('teach.read', 'teach.write', 'teach.review', 'teach.delete'))
FIELDS = ('meaning', 'operationHint', 'conditions', 'warnings')


class TeachingError(ValueError):
    pass


def content(params):
    result = {field: params[field].strip() for field in FIELDS}
    if not result['meaning'] or any(len(value.encode('utf-8')) > 480 or
                                    any(ord(char) < 32 and char != '\n' for char in value)
                                    for value in result.values()):
        raise TeachingError('invalid_annotation_content')
    hint = result['operationHint']
    if hint and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', hint):
        raise TeachingError('invalid_operation_hint')
    return result


def compare(saved, candidate):
    """Exact contextual evidence, independent of indexes and coordinates."""
    return saved == candidate


def match_status(matches, complete):
    if matches >= 2:
        return 'ambiguous'
    if not complete or matches == 0:
        return 'unresolved'
    return 'matched'


class AnnotationStore:
    def __init__(self, path):
        self.path = path
        fd = os.open(path, os.O_CREAT | os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
                raise TeachingError('unsafe_annotation_store')
        finally:
            os.close(fd)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version == 0:
                db.execute('''CREATE TABLE annotations (
                    id TEXT NOT NULL, session TEXT NOT NULL, app TEXT NOT NULL,
                    revision INTEGER NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (session, app, id, revision))''')
                db.execute('PRAGMA user_version = 1')
            elif version != SCHEMA_VERSION:
                raise TeachingError('unsupported_annotation_schema')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            db.execute('PRAGMA synchronous = FULL')
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def insert(db, record):
        db.execute('INSERT INTO annotations VALUES (?, ?, ?, ?, ?, ?)',
                   (record['id'], record['session'], record['app'], record['revision'],
                    record['reviewState'], json.dumps(record, ensure_ascii=False)))

    def create(self, session, app, evidence, annotation, principal):
        now = int(time.time())
        record = dict(version=TEACH_VERSION, id=secrets.token_hex(16), session=session,
                      app=app, evidence=evidence, annotation=annotation, revision=1,
                      provenance='operator_annotation', reviewState='operator_supplied',
                      createdAt=now, updatedAt=now, createdBy=principal, updatedBy=principal)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            count = db.execute('SELECT count(DISTINCT id) FROM annotations WHERE session=? AND app=?',
                               (session, app)).fetchone()[0]
            if count >= 128:
                raise TeachingError('annotation_limit')
            self.insert(db, record)
        return record

    @staticmethod
    def latest(db, session, app, key):
        row = db.execute('''SELECT payload FROM annotations WHERE session=? AND app=? AND id=?
                            ORDER BY revision DESC LIMIT 1''', (session, app, key)).fetchone()
        if row is None:
            raise TeachingError('annotation_unavailable')
        return json.loads(row[0])

    def get(self, session, app, key):
        with self.connection() as db:
            record = self.latest(db, session, app, key)
        if record['reviewState'] == 'deleted':
            raise TeachingError('annotation_unavailable')
        return record

    def list(self, session, app, offset):
        with self.connection() as db:
            rows = db.execute('''SELECT payload FROM annotations AS current
                WHERE session=? AND app=? AND state!='deleted'
                AND revision=(SELECT max(revision) FROM annotations AS previous
                    WHERE previous.session=current.session AND previous.app=current.app
                    AND previous.id=current.id)
                ORDER BY id LIMIT 9 OFFSET ?''', (session, app, offset)).fetchall()
        records = [json.loads(row[0]) for row in rows[:8]]
        return dict(annotations=[dict(id=row['id'], revision=row['revision'],
                                      meaning=row['annotation']['meaning'][:80], reviewState=row['reviewState'],
                                      provenance=row['provenance']) for row in records],
                    next=offset + 8 if len(rows) > 8 else None)

    def revise(self, session, app, key, revision, principal, *, annotation=None, review=None):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            record = self.latest(db, session, app, key)
            if record['reviewState'] == 'deleted':
                raise TeachingError('annotation_unavailable')
            if record['revision'] != revision:
                raise TeachingError('annotation_revision_conflict')
            if revision >= 64 and review != 'deleted':
                raise TeachingError('annotation_revision_limit')
            record.update(revision=revision + 1, updatedBy=principal, updatedAt=int(time.time()))
            if annotation is not None:
                record.update(annotation=annotation, reviewState='operator_supplied')
            else:
                record['reviewState'] = review
            self.insert(db, record)
        return record
