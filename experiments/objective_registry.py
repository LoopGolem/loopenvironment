# SPDX-License-Identifier: Apache-2.0
"""Disposable executor and objective contracts. The caller supplies authority."""
from collections import OrderedDict
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field, replace
from enum import Enum, StrEnum, auto
from hashlib import sha256
import re
from threading import Lock
from time import monotonic
from typing import Protocol
from unicodedata import category

IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
MAX_LABEL_BYTES = 128
MAX_TEXT_BYTES = 4096
MAX_TTL_SECONDS = 86_400
MAX_EXECUTORS = 64
MAX_OBJECTIVES = 256
MAX_RECEIPTS = 1024


class Error(StrEnum):
    DENIED = 'denied'
    INVALID_INPUT = 'invalid_input'
    ALREADY_EXISTS = 'already_exists'
    UNAVAILABLE = 'executor_unavailable'
    STALE_REVISION = 'stale_revision'
    INVALID_STATE = 'invalid_state'
    EXPIRED = 'objective_expired'
    REQUEST_CONFLICT = 'request_conflict'
    CAPACITY = 'capacity'


class RegistryError(Exception):
    def __init__(self, code: Error):
        self.code = code
        super().__init__(code.value)


class Permission(Enum):
    REGISTER = auto()
    CONFIRM = auto()
    MANAGE_EXECUTOR = auto()
    READ_EXECUTOR = auto()
    AUTHOR_OBJECTIVE = auto()
    RESPOND_TO_OBJECTIVE = auto()
    READ_OBJECTIVE = auto()


class Authorization(Protocol):
    @property
    def principal(self) -> str: ...

    def permits(self, permission: Permission, executor_id: str) -> bool: ...


class Authority(Protocol):
    def authenticate(self, credential: str) -> AbstractContextManager[Authorization]:
        """Pin live identity and policy through the operation, or raise DENIED.

        The trusted adapter must coordinate credential and policy changes with
        this context. It must not invoke registry operations while authorizing.
        """
        ...


class ExecutorState(StrEnum):
    PENDING = 'pending'
    AVAILABLE = 'available'
    SUSPENDED = 'suspended'
    REVOKED = 'revoked'


class ObjectiveState(StrEnum):
    CREATED = 'created'
    OFFERED = 'offered'
    ACCEPTED = 'accepted'
    DECLINED = 'declined'
    WITHDRAWN = 'withdrawn'
    EXPIRED = 'expired'


class ExecutorAction(Enum):
    CONFIRM = auto()
    SUSPEND = auto()
    RESUME = auto()
    REVOKE = auto()


class ObjectiveAction(Enum):
    OFFER = auto()
    ACCEPT = auto()
    DECLINE = auto()
    WITHDRAW = auto()


EXECUTOR_TRANSITIONS = {
    ExecutorAction.CONFIRM: ((ExecutorState.PENDING,), ExecutorState.AVAILABLE),
    ExecutorAction.SUSPEND: ((ExecutorState.AVAILABLE,), ExecutorState.SUSPENDED),
    ExecutorAction.RESUME: ((ExecutorState.SUSPENDED,), ExecutorState.AVAILABLE),
    ExecutorAction.REVOKE: ((ExecutorState.PENDING, ExecutorState.AVAILABLE, ExecutorState.SUSPENDED),
                            ExecutorState.REVOKED),
}
OPEN = (ObjectiveState.CREATED, ObjectiveState.OFFERED)
RESPONSES = (ObjectiveAction.ACCEPT, ObjectiveAction.DECLINE)
OBJECTIVE_TRANSITIONS = {
    ObjectiveAction.OFFER: ((ObjectiveState.CREATED,), ObjectiveState.OFFERED),
    ObjectiveAction.ACCEPT: ((ObjectiveState.OFFERED,), ObjectiveState.ACCEPTED),
    ObjectiveAction.DECLINE: ((ObjectiveState.OFFERED,), ObjectiveState.DECLINED),
    ObjectiveAction.WITHDRAW: (OPEN, ObjectiveState.WITHDRAWN),
}


@dataclass(frozen=True)
class Executor:
    id: str
    principal: str
    label: str
    registered_by: str
    state: ExecutorState = ExecutorState.PENDING
    revision: int = 1


@dataclass(frozen=True)
class Objective:
    id: str
    executor_id: str
    issuer: str
    text: str = field(repr=False)
    expires_at: float
    changed_by: str | None
    offered: bool = False
    state: ObjectiveState = ObjectiveState.CREATED
    revision: int = 1


@dataclass(frozen=True)
class Receipt:
    id: str
    revision: int
    state: ExecutorState | ObjectiveState


def _validate_ids(*values):
    if any(type(value) is not str or not IDENTIFIER.fullmatch(value) for value in values):
        raise RegistryError(Error.INVALID_INPUT)


def _validate_text(value, limit, *, multiline=False):
    if type(value) is not str or len(value) > limit or not value.strip():
        raise RegistryError(Error.INVALID_INPUT)
    try:
        encoded = value.encode('utf-8')
    except UnicodeEncodeError:
        raise RegistryError(Error.INVALID_INPUT) from None
    if len(encoded) > limit or any(category(char) == 'Cc' and (not multiline or char not in '\n\t')
                                   for char in value):
        raise RegistryError(Error.INVALID_INPUT)
    return encoded


def _valid_revision(value):
    if type(value) is not int or value < 1:
        raise RegistryError(Error.INVALID_INPUT)


def _authorize(actor, permission, executor_id):
    if actor.permits(permission, executor_id) is not True:
        raise RegistryError(Error.DENIED)


def _target_state(record, revision, transition):
    if record.revision != revision:
        raise RegistryError(Error.STALE_REVISION)
    sources, destination = transition
    if record.state not in sources:
        raise RegistryError(Error.INVALID_STATE)
    return destination


class Registry:
    def __init__(self, authority: Authority, *, clock=monotonic):
        self._authority = authority
        self._clock = clock
        self._lock = Lock()
        self._executors = {}
        self._objectives = {}
        self._receipts = OrderedDict()

    @contextmanager
    def _request(self, credential):
        if type(credential) is not str or not 0 < len(credential) <= 128:
            raise RegistryError(Error.DENIED)
        with self._authority.authenticate(credential) as actor, self._lock:
            if type(actor.principal) is not str or not IDENTIFIER.fullmatch(actor.principal):
                raise RegistryError(Error.DENIED)
            yield actor

    def _replay(self, key, signature):
        stored = self._receipts.get(key)
        if stored is not None:
            previous, result = stored
            if previous != signature:
                raise RegistryError(Error.REQUEST_CONFLICT)
            return result
        return None

    def _finish(self, key, signature, record):
        receipt = Receipt(record.id, record.revision, record.state)
        self._receipts[key] = signature, receipt
        if len(self._receipts) > MAX_RECEIPTS:
            self._receipts.popitem(last=False)
        return receipt

    def _executor(self, executor_id):
        record = self._executors.get(executor_id)
        if record is None:
            raise RegistryError(Error.DENIED)
        return record

    def _objective(self, objective_id):
        record = self._objectives.get(objective_id)
        if record is None:
            raise RegistryError(Error.DENIED)
        return record

    def _change_objective(self, record, state, changed_by):
        updated = replace(record, state=state, revision=record.revision + 1, changed_by=changed_by,
                          offered=record.offered or state is ObjectiveState.OFFERED)
        self._objectives[record.id] = updated
        return updated

    def _expire(self, record, now):
        if record.state in OPEN and now >= record.expires_at:
            return self._change_objective(record, ObjectiveState.EXPIRED, None)
        return record

    def register(self, credential, request_id, executor_id, principal, label):
        _validate_ids(request_id, executor_id, principal)
        _validate_text(label, MAX_LABEL_BYTES)
        with self._request(credential) as actor:
            _authorize(actor, Permission.REGISTER, executor_id)
            key = actor.principal, request_id
            signature = 'register', executor_id, principal, label
            if (previous := self._replay(key, signature)) is not None:
                return previous
            if executor_id in self._executors:
                raise RegistryError(Error.ALREADY_EXISTS)
            if len(self._executors) >= MAX_EXECUTORS:
                raise RegistryError(Error.CAPACITY)
            record = Executor(executor_id, principal, label, actor.principal)
            self._executors[executor_id] = record
            return self._finish(key, signature, record)

    def transition_executor(self, credential, request_id, executor_id, revision, action):
        _validate_ids(request_id, executor_id)
        _valid_revision(revision)
        if type(action) is not ExecutorAction:
            raise RegistryError(Error.INVALID_INPUT)
        with self._request(credential) as actor:
            permission = Permission.CONFIRM if action is ExecutorAction.CONFIRM else Permission.MANAGE_EXECUTOR
            _authorize(actor, permission, executor_id)
            record = self._executor(executor_id)
            if action is ExecutorAction.CONFIRM:
                if actor.principal != record.principal:
                    raise RegistryError(Error.DENIED)
                if record.state is ExecutorState.REVOKED:
                    raise RegistryError(Error.UNAVAILABLE)
            key = actor.principal, request_id
            signature = action, executor_id, revision
            if (previous := self._replay(key, signature)) is not None:
                return previous
            state = _target_state(record, revision, EXECUTOR_TRANSITIONS[action])
            updated = replace(record, state=state, revision=record.revision + 1)
            if state is ExecutorState.REVOKED:
                now = self._clock()
                for objective in self._objectives.values():
                    if objective.executor_id == executor_id:
                        objective = self._expire(objective, now)
                        if objective.state in OPEN:
                            self._change_objective(objective, ObjectiveState.WITHDRAWN, actor.principal)
            self._executors[executor_id] = updated
            return self._finish(key, signature, updated)

    def create_objective(self, credential, request_id, objective_id, executor_id, text, ttl_seconds):
        _validate_ids(request_id, objective_id, executor_id)
        encoded = _validate_text(text, MAX_TEXT_BYTES, multiline=True)
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
            raise RegistryError(Error.INVALID_INPUT)
        with self._request(credential) as actor:
            _authorize(actor, Permission.AUTHOR_OBJECTIVE, executor_id)
            if self._executor(executor_id).state is not ExecutorState.AVAILABLE:
                raise RegistryError(Error.UNAVAILABLE)
            key = actor.principal, request_id
            signature = 'create', objective_id, executor_id, sha256(encoded).digest(), ttl_seconds
            if (previous := self._replay(key, signature)) is not None:
                return previous
            if objective_id in self._objectives:
                raise RegistryError(Error.ALREADY_EXISTS)
            if len(self._objectives) >= MAX_OBJECTIVES:
                raise RegistryError(Error.CAPACITY)
            record = Objective(objective_id, executor_id, actor.principal, text,
                               self._clock() + ttl_seconds, actor.principal)
            self._objectives[objective_id] = record
            return self._finish(key, signature, record)

    def transition_objective(self, credential, request_id, objective_id, revision, action):
        _validate_ids(request_id, objective_id)
        _valid_revision(revision)
        if type(action) is not ObjectiveAction:
            raise RegistryError(Error.INVALID_INPUT)
        with self._request(credential) as actor:
            record = self._objective(objective_id)
            executor = self._executor(record.executor_id)
            if action in RESPONSES:
                _authorize(actor, Permission.RESPOND_TO_OBJECTIVE, executor.id)
                if actor.principal != executor.principal or not record.offered:
                    raise RegistryError(Error.DENIED)
            else:
                _authorize(actor, Permission.AUTHOR_OBJECTIVE, executor.id)
                if actor.principal != record.issuer:
                    raise RegistryError(Error.DENIED)
            if action is not ObjectiveAction.WITHDRAW and executor.state is not ExecutorState.AVAILABLE:
                raise RegistryError(Error.UNAVAILABLE)
            key = actor.principal, request_id
            signature = action, objective_id, revision
            if (previous := self._replay(key, signature)) is not None:
                return previous
            record = self._expire(record, self._clock())
            if record.state is ObjectiveState.EXPIRED:
                raise RegistryError(Error.EXPIRED)
            state = _target_state(record, revision, OBJECTIVE_TRANSITIONS[action])
            updated = self._change_objective(record, state, actor.principal)
            return self._finish(key, signature, updated)

    def read_executor(self, credential, executor_id):
        _validate_ids(executor_id)
        with self._request(credential) as actor:
            _authorize(actor, Permission.READ_EXECUTOR, executor_id)
            return self._executor(executor_id)

    def read_objective(self, credential, objective_id):
        _validate_ids(objective_id)
        with self._request(credential) as actor:
            record = self._objective(objective_id)
            executor = self._executor(record.executor_id)
            _authorize(actor, Permission.READ_OBJECTIVE, executor.id)
            is_recipient = (actor.principal == executor.principal and record.offered
                            and executor.state is ExecutorState.AVAILABLE)
            if actor.principal != record.issuer and not is_recipient:
                raise RegistryError(Error.DENIED)
            return self._expire(record, self._clock())

    def list_offers(self, credential, executor_id):
        _validate_ids(executor_id)
        with self._request(credential) as actor:
            _authorize(actor, Permission.READ_OBJECTIVE, executor_id)
            executor = self._executor(executor_id)
            if actor.principal != executor.principal:
                raise RegistryError(Error.DENIED)
            if executor.state is not ExecutorState.AVAILABLE:
                raise RegistryError(Error.UNAVAILABLE)
            now = self._clock()
            offers = []
            for record in self._objectives.values():
                if record.executor_id == executor_id and record.state is ObjectiveState.OFFERED:
                    current = self._expire(record, now)
                    if current.state is ObjectiveState.OFFERED:
                        offers.append(current)
            return tuple(offers)
