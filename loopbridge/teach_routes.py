# SPDX-License-Identifier: Apache-2.0
"""Grant-scoped LoopTeach endpoints, separate from desktop dispatch."""
import json
import sqlite3

from .adapter import Refused, Unavailable
from .authority import fail
from .protocol import Fault, encode
from .teaching import FIELDS, TeachingError, content

BODY = set(FIELDS)
SCHEMA = {
    'teach.create': {'ref'} | BODY,
    'teach.update': {'app', 'annotation', 'revision'} | BODY,
    'teach.delete': {'app', 'annotation', 'revision'},
    'teach.inspect': {'app', 'annotation'},
    'teach.list': {'app', 'offset'},
    'teach.search': {'app', 'query', 'revision', 'offset'},
    'teach.resolve': {'ref', 'annotation'},
    'teach.review': {'app', 'annotation', 'revision', 'decision'},
}
REQUIRED = dict(create='teach.write', update='teach.write', delete='teach.delete',
                inspect='teach.read', list='teach.read', search='teach.read', resolve='teach.read', review='teach.review')
LIVE_METHOD = {'create': 'teach.capture', 'resolve': 'teach.find'}


def acknowledgement(record):
    return {key: record[key] for key in ('id', 'revision', 'reviewState', 'provenance')}


class TeachRoutes:
    def __init__(self, broker, store):
        self.broker, self.store = broker, store

    def authorize(self, session, principal, method, target):
        session.require(principal, REQUIRED[method], target)
        if method in LIVE_METHOD:
            session.require(principal, 'desktop.observe', target)

    def handle(self, session, connection, principal, method, params):
        if self.store is None:
            fail('teaching_unavailable', -32006)
        method = method.removeprefix('teach.')
        try:
            with session.lock:
                app, arguments, handle = self.broker.target(session, connection, params)
                target = 'app:' + app
                self.authorize(session, principal, method, target)
                if method not in LIVE_METHOD:
                    return self.metadata(session.id, app, principal, method, params)
                revision = session.revision
                record = None
                if method == 'resolve':
                    record = self.store.get(session.id, app, params['annotation'])
                    if record['reviewState'] == 'rejected':
                        return dict(status='unresolved', reason='annotation_rejected')
                    arguments['evidence'] = record['evidence']
                else:
                    annotation = content(params)
                    self.limit(annotation, 1900)
            adapter = self.broker.adapters[session.id]
            with self.broker.io[session.id]:
                native = adapter.call('desktop.read', (LIVE_METHOD[method], app, arguments))
                with session.lock:
                    session.refresh()
                    self.authorize(session, principal, method, target)
                    if revision != session.revision or self.broker.clock() >= handle.expires:
                        fail('stale_reference', -32002)
                    if method == 'create':
                        self.limit(native['evidence'], 2300)
                        return acknowledgement(self.store.create(
                            session.id, app, native['evidence'], annotation, principal))
                    current = self.store.get(session.id, app, record['id'])
                    if current['revision'] != record['revision']:
                        fail('annotation_revision_conflict', -32005)
                    if native['status'] == 'matched':
                        element = native['element']
                        element['ref'] = self.broker.bind(session, connection, app, element['ref'])
                        native.update(annotation=record, provenance={
                            'element': 'atspi', 'annotation': 'operator_annotation',
                            'association': 'context_match'})
                    return native
        except TeachingError as error:
            fail(str(error), -32006)
        except Refused as error:
            fail(error.reason, -32006)
        except (Unavailable, OSError, sqlite3.Error):
            fail('teaching_unavailable', -32006)

    def limit(self, data, maximum):
        if self.broker.identities.contains_credential(json.dumps(data, ensure_ascii=False)):
            raise TeachingError('protected_annotation_content')
        try:
            if len(encode(data)) > maximum:
                raise TeachingError('annotation_size_limit')
        except Fault:
            raise TeachingError('annotation_size_limit') from None

    def metadata(self, session, app, principal, method, params):
        if method == 'list':
            return self.store.list(session, app, params['offset'])
        if method == 'search':
            revision = params['revision']
            if type(revision) is not int or not 0 <= revision <= 65:
                raise TeachingError('invalid_annotation_revision')
            return self.store.search(session, app, params['query'].strip(), revision, params['offset'])
        key = params['annotation']
        if method == 'inspect':
            return self.store.get(session, app, key)
        revision = params['revision']
        if type(revision) is not int or not 1 <= revision <= 65:
            raise TeachingError('invalid_annotation_revision')
        arguments = {}
        if method == 'update':
            arguments['annotation'] = content(params)
            self.limit(arguments['annotation'], 1900)
        elif method == 'review':
            decision = params['decision']
            if decision not in ('approved', 'rejected'):
                raise TeachingError('invalid_review_decision')
            arguments['review'] = decision
        else:
            arguments['review'] = 'deleted'
        return acknowledgement(self.store.revise(session, app, key, revision, principal, **arguments))
