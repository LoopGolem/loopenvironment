# SPDX-License-Identifier: Apache-2.0
"""Process-local policy boundary for the durable objective registry experiment."""
from contextlib import contextmanager
from threading import Lock
from time import monotonic

from experiments.objective_registry import Error, IDENTIFIER, Permission, RegistryError, _validate_ids


class _AuthorizedRequest:
    def __init__(self, principal, grants, clock, verify):
        self.principal = principal
        self._grants = grants
        self._clock = clock
        self._verify = verify
        self._checked = set()

    def permits(self, permission, executor_id):
        key = self.principal, permission, executor_id
        if self._clock() < self._grants.get(key, float('-inf')):
            self._checked.add(key)
            return True
        return False

    def revalidate(self, *, now=None):
        if self._verify() != self.principal:
            raise RegistryError(Error.DENIED)
        if now is None:
            now = self._clock()
        if any(not now < self._grants[key] for key in self._checked):
            raise RegistryError(Error.DENIED)


class RegistryPolicy:
    """The trusted verifier resolves individual authenticated subjects.

    Policy changes and authentication share a lock held through the database
    transaction. Configuration methods are for the trusted laboratory harness.
    The verifier and clock must be local and must not call back into Registry.
    """

    def __init__(self, verify, *, clock=monotonic, lock=None):
        self._verify = verify
        self._clock = clock
        self._lock = Lock() if lock is None else lock
        self._grants = {}

    @contextmanager
    def authenticate(self, credential):
        with self._lock:
            principal = self._verify(credential)
            if type(principal) is not str or not IDENTIFIER.fullmatch(principal):
                raise RegistryError(Error.DENIED)
            yield _AuthorizedRequest(principal, self._grants, self._clock,
                                     lambda: self._verify(credential))

    def grant(self, principal, permission, executor_id, *, expires_at):
        _validate_ids(principal, executor_id)
        if (type(permission) is not Permission or type(expires_at) not in (int, float)
                or not 0 <= expires_at <= 2**53):
            raise RegistryError(Error.INVALID_INPUT)
        with self._lock:
            self._grants[principal, permission, executor_id] = expires_at

    def revoke(self, principal, permission, executor_id):
        _validate_ids(principal, executor_id)
        if type(permission) is not Permission:
            raise RegistryError(Error.INVALID_INPUT)
        with self._lock:
            self._grants.pop((principal, permission, executor_id), None)

    def replace_grants(self, grants, *, update_identity):
        """Install a validated snapshot under the authorization/commit lock."""
        replacement = dict(grants)
        with self._lock:
            update_identity()
            self._grants = replacement

    def replace_verifier(self, verify):
        with self._lock:
            self._verify = verify
