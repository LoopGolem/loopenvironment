# SPDX-License-Identifier: Apache-2.0
"""Bounded RPC grammar and projections for the experimental objective Registry."""
from collections import OrderedDict
from dataclasses import dataclass, field
import re
from secrets import token_urlsafe
from threading import Lock

from experiments.objective_registry import (Error, ExecutorAction, MAX_LABEL_BYTES, MAX_TTL_SECONDS,
                                            ObjectiveAction, RegistryError, _validate_text)
from loopbridge.authority import fail
from loopbridge.broker import Connection

VERSION = 'registry/1'
OPAQUE_ID = re.compile('[0-9a-f]{32}')
CURSOR = re.compile('[A-Za-z0-9_-]{32}')
MAX_TEXT_BYTES = 2048
MAX_PAGE = 16
MAX_CURSORS = 64
CURSOR_TTL = 60

ERROR_CODES = {
    Error.DENIED: (-32001, 'denied'),
    Error.INVALID_INPUT: (-32602, 'invalid_params'),
    Error.STALE_REVISION: (-32040, 'stale_revision'),
    Error.EXPIRED: (-32041, 'objective_expired'),
    Error.UNAVAILABLE: (-32042, 'executor_unavailable'),
    Error.INVALID_STATE: (-32043, 'invalid_state'),
    Error.REQUEST_CONFLICT: (-32044, 'request_conflict'),
    Error.CAPACITY: (-32045, 'capacity'),
    Error.STORAGE_UNAVAILABLE: (-32046, 'storage_unavailable'),
    Error.INVALID_STORAGE: (-32047, 'invalid_storage'),
    Error.COMMIT_UNKNOWN: (-32048, 'commit_unknown'),
    Error.CLOCK_UNCERTAIN: (-32049, 'clock_uncertain'),
    Error.ALREADY_EXISTS: (-32050, 'already_exists'),
}

SCHEMA = {
    'executor.register': {'request_id', 'executor_id', 'bound_principal_id', 'label'},
    'executor.confirm': {'request_id', 'executor_id', 'expected_revision'},
    'executor.status': {'executor_id'},
    'objective.create': {'request_id', 'objective_id', 'executor_id', 'text', 'ttl_seconds'},
    'objective.offer': {'request_id', 'objective_id', 'expected_revision'},
    'objective.list_offers': {'executor_id', 'limit'},
    'objective.status': {'objective_id'},
    'objective.respond': {'request_id', 'objective_id', 'expected_revision', 'decision'},
    'objective.withdraw': {'request_id', 'objective_id', 'expected_revision'},
}

RESPONSES = {'accept': ObjectiveAction.ACCEPT, 'decline': ObjectiveAction.DECLINE}
OBJECTIVE_ACTIONS = {'objective.offer': ObjectiveAction.OFFER,
                     'objective.withdraw': ObjectiveAction.WITHDRAW}


def _matches(pattern, value):
    return type(value) is str and pattern.fullmatch(value) is not None


def _integer(value, maximum):
    return type(value) is int and 1 <= value <= maximum


def _validate(method, params):
    if method not in SCHEMA:
        fail('method_not_found', -32601)
    fields = SCHEMA[method]
    if method == 'objective.list_offers' and 'cursor' in params:
        fields = fields | {'cursor'}
    if params.keys() != fields:
        fail('invalid_params', -32602)
    for field, value in params.items():
        if field.endswith('_id'):
            valid = _matches(OPAQUE_ID, value)
        elif field == 'expected_revision':
            valid = _integer(value, 2**53 - 1)
        elif field == 'ttl_seconds':
            valid = _integer(value, MAX_TTL_SECONDS)
        elif field == 'limit':
            valid = _integer(value, MAX_PAGE)
        elif field == 'cursor':
            if not _matches(CURSOR, value):
                fail('invalid_cursor', -32051)
            continue
        elif field == 'decision':
            valid = type(value) is str and value in RESPONSES
        else:
            is_text = field == 'text'
            _validate_text(value, MAX_TEXT_BYTES if is_text else MAX_LABEL_BYTES, multiline=is_text)
            continue
        if not valid:
            fail('invalid_params', -32602)


def _receipt(record):
    return dict(id=record.id, state=record.state, revision=record.revision)


def _offer(record):
    return dict(**_receipt(record), executor_id=record.executor_id,
                expires_unix_ms=int(record.expires_at * 1000))


@dataclass(frozen=True)
class _Page:
    subject: tuple[str, str]
    remaining: tuple[str, ...]
    deadline: float


class _Pages:
    def __init__(self, clock):
        self._clock = clock
        self._lock = Lock()
        self._pages = OrderedDict()

    def read(self, principal, executor, offers, *, limit, cursor=None):
        # The caller already checked the current grant and retrieved current offers.
        subject = principal, executor
        by_id = {record.id: record for record in offers}
        with self._lock:
            now = self._clock()
            if cursor is None:
                ids = tuple(by_id)
                deadline = now + CURSOR_TTL
            else:
                page = self._pages.get(cursor)
                if page is None or page.subject != subject or now >= page.deadline:
                    fail('invalid_cursor', -32051)
                ids = tuple(key for key in page.remaining if key in by_id)
                deadline = page.deadline
            next_cursor = None
            if len(ids) > limit:
                next_cursor = token_urlsafe(24)
                self._pages[next_cursor] = _Page(subject, ids[limit:], deadline)
                if len(self._pages) > MAX_CURSORS:
                    self._pages.popitem(last=False)
        return dict(items=[_offer(by_id[key]) for key in ids[:limit]], next_cursor=next_cursor)


@dataclass(frozen=True)
class RegistryRequest:
    connection: Connection
    content: str | None = field(repr=False)
    bound_principal: str | None


class RegistryRPC:
    def __init__(self, registry, clock):
        self._registry = registry
        self._pages = _Pages(clock)

    def dispatch(self, connection, method, params):
        try:
            _validate(method, params)
            request = RegistryRequest(connection, params.get('text', params.get('label')),
                                      params.get('bound_principal_id'))
            return self._dispatch(request, method, params)
        except RegistryError as error:
            code, message = ERROR_CODES[error.code]
            fail(message, code)

    def _dispatch(self, request, method, params):
        registry = self._registry
        executor = params.get('executor_id')
        objective = params.get('objective_id')
        request_id = params.get('request_id')
        revision = params.get('expected_revision')
        if method == 'executor.register':
            record = registry.register(request, request_id, executor, params['bound_principal_id'], params['label'])
        elif method == 'executor.confirm':
            record = registry.transition_executor(request, request_id, executor, revision, ExecutorAction.CONFIRM)
        elif method == 'executor.status':
            record = registry.read_executor(request, executor)
            return dict(**_receipt(record), label=record.label)
        elif method == 'objective.create':
            record = registry.create_objective(request, request_id, objective, executor, params['text'],
                                               params['ttl_seconds'])
        elif method == 'objective.list_offers':
            offers = registry.list_offers(request, executor)
            return self._pages.read(request.connection.principal, executor, offers, limit=params['limit'],
                                    cursor=params.get('cursor'))
        elif method == 'objective.status':
            record = registry.read_objective(request, objective)
            if len(record.text.encode('utf-8')) > MAX_TEXT_BYTES:
                fail('content_limit', -32052)
            return dict(**_offer(record), issuer_id=record.issuer, text=record.text)
        else:
            action = (RESPONSES[params['decision']] if method == 'objective.respond'
                      else OBJECTIVE_ACTIONS[method])
            record = registry.transition_objective(request, request_id, objective, revision, action)
        return _receipt(record)
