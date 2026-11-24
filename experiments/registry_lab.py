# SPDX-License-Identifier: Apache-2.0
"""Opt-in individual identities and Registry RPC on a disposable LoopBridge socket."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from threading import Lock
from time import monotonic, time

from experiments.durable_objective_registry import SQLiteRegistry
from experiments.objective_registry import Error, RegistryError
from experiments.objective_registry_policy import RegistryPolicy
from experiments.registry_rpc import OPAQUE_ID, SCHEMA, VERSION, RegistryRequest, RegistryRPC
from loopbridge.authority import fail
from loopbridge.broker import Connection, Server
from loopbridge.desktop_broker import DesktopBroker
from loopbridge.identity import (PRINCIPALS, VERIFIER, authenticate_credential,
                                 contains_credential)
from loopbridge.service import Journal, directory_lock, private_directory
from loopbridge.service_ingress import bound_listener

CREDENTIAL = re.compile('[A-Za-z0-9_-]{43}')
MAX_PRINCIPALS = 128


@dataclass(frozen=True)
class _Binding:
    connection: Connection
    principal: str
    verifier: bytes = field(repr=False)


class _Access:
    def __init__(self, broker, verifiers, clock):
        self._broker = broker
        self._lock = Lock()
        self._legacy_digests = {bytes.fromhex(value)
                                for value in broker.identities.manifest()['verifiers'].values()}
        if (type(verifiers) is not dict or not 1 <= len(verifiers) <= MAX_PRINCIPALS
                or any(type(subject) is not str or OPAQUE_ID.fullmatch(subject) is None
                       or type(digest) is not str or VERIFIER.fullmatch(digest) is None
                       for subject, digest in verifiers.items())):
            raise ValueError('invalid_registry_verifiers')
        digests = {subject: bytes.fromhex(digest) for subject, digest in verifiers.items()}
        if len(set(digests.values()) | self._legacy_digests) != len(digests) + len(self._legacy_digests):
            raise ValueError('invalid_registry_verifiers')
        self._digests = digests
        self._bindings = {}
        self.policy = RegistryPolicy(self._verify, clock=clock, lock=self._lock)

    def bind(self, connection, params):
        credential = params.pop('credential', None)
        if (params or type(credential) is not str
                or CREDENTIAL.fullmatch(credential) is None
                or not connection.active or not self._broker.ingress_policy.permits(connection.uid)):
            fail('denied')
        with self._lock:
            principal = authenticate_credential(credential, self._digests)
            self._bindings[connection.id] = _Binding(connection, principal, self._digests[principal])
            connection.principal = principal
        return dict(principal=principal, connection=connection.id)

    def unbind(self, connection):
        with self._lock:
            self._bindings.pop(connection.id, None)

    def rotate(self, principal, verifier):
        """Replace a verifier from the trusted laboratory harness."""
        if type(principal) is not str or type(verifier) is not str or not VERIFIER.fullmatch(verifier):
            raise ValueError('invalid_registry_verifier')
        digest = bytes.fromhex(verifier)
        with self._lock:
            if (principal not in self._digests or digest in self._digests.values()
                    or digest in self._legacy_digests):
                raise ValueError('invalid_registry_verifier')
            self._digests[principal] = digest

    def require(self, connection):
        with self._lock:
            if self._bound_principal(connection) is None:
                fail('denied')

    def _bound_principal(self, connection):
        binding = self._bindings.get(connection.id)
        if (binding is None or binding.connection is not connection
                or self._broker.authenticated(connection) != binding.principal
                or self._digests.get(binding.principal) is not binding.verifier):
            return None
        return binding.principal

    def _verify(self, request):
        # RegistryPolicy owns the shared mutex here and through SQLite commit.
        principal = self._bound_principal(request.connection)
        if request.bound_principal is not None and request.bound_principal not in self._digests:
            return None
        if principal is not None and request.content is not None:
            digests = self._legacy_digests.union(self._digests.values())
            if contains_credential(request.content, digests):
                raise RegistryError(Error.INVALID_INPUT)
        return principal


class _BoundRegistry(SQLiteRegistry):
    def _authenticate(self, request):
        if type(request) is not RegistryRequest:
            raise RegistryError(Error.DENIED)
        return self._authority.authenticate(request)


class RegistryLabBroker(DesktopBroker):
    versions = (*DesktopBroker.versions, VERSION)
    wire_versions = (*DesktopBroker.wire_versions, VERSION)

    def __init__(self, identities, adapters, uid, journal, *, verifiers, database,
                 wall_clock, clock, create):
        super().__init__(identities, adapters, uid, journal, clock=clock)
        self.access = _Access(self, verifiers, clock)
        self.registry = _BoundRegistry(database, self.access.policy, wall_clock=wall_clock, create=create)
        self.registry_rpc = RegistryRPC(self.registry, clock)

    def clear(self, connection):
        self.access.unbind(connection)
        super().clear(connection)

    def audit_request(self, connection, version, method, outcome):
        # Registry transitions have their own durable audit. Session readers must
        # not see identities or outcomes from Registry requests.
        if version != VERSION and connection.principal in (None, *PRINCIPALS):
            super().audit_request(connection, version, method, outcome)

    def handle_request(self, connection, version, method, params):
        if version == VERSION:
            if method == 'auth':
                self.clear(connection)
                return self.access.bind(connection, params)
            self.access.require(connection)
            return self.registry_rpc.dispatch(connection, method, params)
        if method != 'auth':
            if connection.principal not in PRINCIPALS:
                fail('denied')
            if method in SCHEMA:
                fail('method_not_found', -32601)
        return super().handle_request(connection, version, method, params)


@contextmanager
def serve_registry(root, identities, verifiers, *, create=False, adapters=None,
                   wall_clock=time, clock=monotonic):
    """Run only when the harness explicitly supplies an existing private directory."""
    root = private_directory(Path(root), create=False)
    endpoint = root / 'registry-lab.sock'
    with directory_lock(root):
        broker = RegistryLabBroker(identities, adapters or {}, os.getuid(), Journal(root),
                                   verifiers=verifiers, database=root / 'registry.sqlite3',
                                   wall_clock=wall_clock, clock=clock, create=create)
        with bound_listener(endpoint) as listener, Server(broker, listener):
            yield endpoint, broker
