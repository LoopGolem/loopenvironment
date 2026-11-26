# SPDX-License-Identifier: Apache-2.0
"""Restricted, explicitly provisioned Registry-only profile."""
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
import fcntl
import json
import os
from threading import Lock
from time import monotonic, time

from experiments.durable_objective_registry import MAX_WALL
from experiments.objective_registry import Permission
from experiments.registry_lab import MAX_PRINCIPALS, RegistryLabBroker
from experiments.registry_rpc import OPAQUE_ID, VERSION
from experiments.registry_storage import (DATABASE, DatabasePin, private_registry_directory,
                                          trusted_directory)
from loopbridge.broker import Server
from loopbridge.identity import Identities, VERIFIER
from loopbridge.protocol import unique_object
from loopbridge.service import Journal
from loopbridge.service_ingress import CrossUIDIngress, path_inode

POLICY_FILE = 'policy.json'
MAX_POLICY_BYTES = 128 * 1024
MAX_GRANTS = 1024
MAX_RETIRED = 1024
SCOPES = {
    'registry.executor.register': Permission.REGISTER,
    'registry.executor.confirm': Permission.CONFIRM,
    'registry.executor.read': Permission.READ_EXECUTOR,
    'registry.objective.author': Permission.AUTHOR_OBJECTIVE,
    'registry.objective.read': Permission.READ_OBJECTIVE,
    'registry.objective.respond': Permission.RESPOND_TO_OBJECTIVE,
}


@dataclass(frozen=True)
class PolicyPin:
    generation: int
    sha256: str

    def __post_init__(self):
        if (type(self.generation) is not int or not 1 <= self.generation < 2**53
                or type(self.sha256) is not str or VERIFIER.fullmatch(self.sha256) is None):
            raise ValueError('invalid_registry_policy_pin')


@dataclass(frozen=True)
class _Policy:
    verifiers: dict = field(repr=False)
    disabled: frozenset
    retired: frozenset = field(repr=False)
    grants: dict


def _scope_id(value):
    return type(value) is str and OPAQUE_ID.fullmatch(value) is not None


def _load_policy(directory, pin):
    if type(pin) is not PolicyPin:
        raise ValueError('registry_policy_pin_required')
    raw = directory.read(POLICY_FILE, MAX_POLICY_BYTES)
    if sha256(raw).hexdigest() != pin.sha256:
        raise ValueError('registry_policy_pin_mismatch')
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
        if (type(value) is not dict or value.keys() != {'version', 'generation', 'principals', 'retired_verifiers', 'grants'}
                or type(value['version']) is not int or value['version'] != 1
                or type(value['generation']) is not int or value['generation'] != pin.generation):
            raise ValueError
        principals, entries = value['principals'], value['grants']
        if (type(principals) is not dict or not 1 <= len(principals) <= MAX_PRINCIPALS
                or type(entries) is not list or len(entries) > MAX_GRANTS):
            raise ValueError
        verifiers, disabled = {}, set()
        for subject, verifier in principals.items():
            if not _scope_id(subject):
                raise ValueError
            if verifier is None:
                disabled.add(subject)
            elif type(verifier) is str and VERIFIER.fullmatch(verifier):
                verifiers[subject] = verifier
            else:
                raise ValueError
        retired = value['retired_verifiers']
        if (type(retired) is not list or len(retired) > MAX_RETIRED
                or any(type(digest) is not str or VERIFIER.fullmatch(digest) is None for digest in retired)
                or len(set(retired)) != len(retired)
                or len(set(verifiers.values()) | set(retired)) != len(verifiers) + len(retired)):
            raise ValueError
        grants = {}
        for entry in entries:
            if (type(entry) is not dict or entry.keys() != {'principal', 'scope', 'executor', 'expires_unix'}
                    or not _scope_id(entry['principal']) or entry['principal'] not in verifiers
                    or type(entry['scope']) is not str or entry['scope'] not in SCOPES
                    or not _scope_id(entry['executor'])
                    or type(entry['expires_unix']) is not int or not 1 <= entry['expires_unix'] <= MAX_WALL):
                raise ValueError
            key = entry['principal'], SCOPES[entry['scope']], entry['executor']
            if key in grants:
                raise ValueError
            grants[key] = entry['expires_unix']
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError('invalid_registry_policy') from None
    return _Policy(verifiers, frozenset(disabled), frozenset(retired), grants)


class _RegistryOnlyBroker(RegistryLabBroker):
    versions = wire_versions = (VERSION,)


class RegistryControl:
    """In-process control for an explicitly trusted supervisor."""

    def __init__(self, broker, directory, pin, policy):
        self._lock = Lock()
        self._broker = broker
        self._directory = directory
        self._pin = pin
        self._policy = policy
        self._active = True

    def reload(self, pin):
        with self._lock:
            if not self._active:
                raise ValueError('registry_control_closed')
            if type(pin) is not PolicyPin or pin.generation <= self._pin.generation:
                raise ValueError('registry_policy_generation')
            policy = _load_policy(self._directory, pin)
            previous = self._policy
            retired = previous.retired | {digest for subject, digest in previous.verifiers.items()
                                          if policy.verifiers.get(subject) != digest}
            if (not previous.disabled <= policy.disabled or not retired <= policy.retired
                    or not previous.verifiers.keys() <= policy.verifiers.keys() | policy.disabled):
                raise ValueError('registry_principal_history')
            self._broker.access.replace(policy.verifiers, policy.grants, retired=policy.retired)
            self._policy, self._pin = policy, pin

    def close(self):
        with self._lock:
            self._active = False


@contextmanager
def _prepared_registry(root, admission, database_pin, policy_pin, *, wall_clock, clock,
                       broker_type=_RegistryOnlyBroker, database_name=DATABASE):
    if type(database_pin) is not DatabasePin:
        raise ValueError('registry_database_pin_required')
    with private_registry_directory(root) as directory:
        fcntl.flock(directory.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with directory.hold_database(database_pin, name=database_name):
            policy = _load_policy(directory, policy_pin)
            broker = broker_type(
                Identities(), {}, admission.service_uid, Journal(root), verifiers=policy.verifiers,
                database=root / database_name, wall_clock=wall_clock, clock=clock, create=False,
                ingress_policy=admission, grant_clock=wall_clock,
                storage_check=lambda: directory.check_database(database_pin, name=database_name))
            broker.access.replace(policy.verifiers, policy.grants, retired=policy.retired)
            control = RegistryControl(broker, directory, policy_pin, policy)
            try:
                yield broker, control
            finally:
                control.close()


@contextmanager
def serve_operational_registry(ingress, *, database_pin, policy_pin, wall_clock=time, clock=monotonic):
    """Opt-in. The caller supplies a preprovisioned CrossUIDIngress and trusted pins."""
    with _serve_profile(ingress, database_pin, policy_pin, endpoint_name='registry.sock',
                        database_name=DATABASE, broker_type=_RegistryOnlyBroker,
                        wall_clock=wall_clock, clock=clock) as (endpoint, _, control):
        yield endpoint, control


@contextmanager
def _serve_profile(ingress, database_pin, policy_pin, *, endpoint_name, database_name, broker_type,
                   wall_clock, clock, prepare=None):
    if type(ingress) is not CrossUIDIngress or os.getuid() != os.geteuid():
        raise ValueError('registry_cross_uid_profile_required')
    endpoint = ingress.directory / endpoint_name
    with trusted_directory(ingress.directory) as fd:
        if path_inode(os.fstat(fd)) != ingress.validate():
            raise ValueError('registry_ingress_replaced')
        with _prepared_registry(ingress.private_root, ingress.policy, database_pin, policy_pin,
                                wall_clock=wall_clock, clock=clock, broker_type=broker_type,
                                database_name=database_name) as (broker, control):
            if prepare is not None:
                prepare(broker)
            if path_inode(os.fstat(fd)) != ingress.validate():
                raise ValueError('registry_ingress_replaced')
            with ingress.listen(endpoint) as listener, Server(broker, listener, allow_owner=False):
                yield endpoint, broker, control
