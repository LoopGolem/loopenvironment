# SPDX-License-Identifier: Apache-2.0
"""Bounded in-memory session authority."""
from dataclasses import dataclass
import secrets
import threading
import time

from .protocol import Fault, History
from .teaching import CAPABILITIES as TEACH_CAPABILITIES

CAPABILITIES = frozenset(('session.discover', 'desktop.observe', 'desktop.control',
                          'identity.admin'))
TARGET = 'calculator.digit7'
MUTATIONS = frozenset(('desktop.control', 'app.launch', 'app.close', 'workspace.write', 'desktop.input', 'web.submit'))
DESKTOP_CAPABILITIES = CAPABILITIES | MUTATIONS | {'workspace.read', 'desktop.capture'} | TEACH_CAPABILITIES


def fail(message, code=-32001):
    raise Fault(code, message)


def duration(value):
    if type(value) not in (int, float) or not 0 < value <= 180:
        fail('invalid_duration', -32602)
    return value


@dataclass
class Grant:
    id: str
    principal: str
    capability: str
    target: str
    issuer: str
    expires: float
    revision: int
    revoked: bool = False


@dataclass
class Lease:
    id: str
    principal: str
    connection: str
    epoch: str
    generation: int
    expires: float


@dataclass
class Handle:
    id: str
    session: str
    epoch: str
    generation: int
    revision: int
    expires: float
    reference: object


class Session:
    def __init__(self, sid, clock=time.monotonic, blocked=False, catalog=(), workspace=False):
        self.id, self.clock = sid, clock
        self.catalog, self.workspace = frozenset(catalog), workspace
        self.capabilities = DESKTOP_CAPABILITIES if self.catalog else CAPABILITIES
        if not workspace:
            self.capabilities = self.capabilities - {'workspace.read', 'workspace.write'}
        self.lock = threading.RLock()  # Per session, never a process-wide adapter lock.
        self.epoch = secrets.token_hex(16)
        self.revision = self.policy_revision = self.generation = 0
        self.phase = 'blocked' if blocked else 'idle'
        self.last_state = None
        self.lease = self.pending = None
        self.grants = {}
        self.history = History(self.epoch, capacity=8)
        for capability in sorted(self.capabilities):
            self._grant('owner', capability, '*', 'lab_bootstrap', 3600)

    def event(self, kind):
        self.revision += 1
        self.history.append(kind, dict(revision=self.revision,
                                     policy_revision=self.policy_revision,
                                     generation=self.generation, phase=self.phase))

    def _grant(self, principal, capability, target, issuer, ttl):
        self.policy_revision += 1
        grant = Grant(secrets.token_hex(16), principal, capability, target, issuer,
                      self.clock() + ttl, self.policy_revision)
        self.grants[grant.id] = grant
        self.event('grant.changed')
        return grant

    def permits(self, principal, capability, target=TARGET):
        return any(g.principal == principal and g.capability == capability and
                   g.target in ('*', target) and not g.revoked and self.clock() < g.expires
                   for g in self.grants.values())

    def expires(self, principal, capability, target=TARGET):
        return max((g.expires for g in self.grants.values()
                    if g.principal == principal and g.capability == capability
                    and not g.revoked and g.target in ('*', target)), default=0)

    def require(self, principal, capability, target=TARGET):
        if not self.permits(principal, capability, target):
            fail('grant_denied')

    def delegate(self, issuer, principal, capability, target, ttl):
        duration(ttl)
        self.require(issuer, 'identity.admin', target)
        if (principal not in ('delegate', 'observer') or capability not in self.capabilities
                or capability == 'identity.admin'
                or (principal == 'observer' and capability in MUTATIONS)):
            fail('invalid_grant', -32602)
        scopes = {'*'}
        if capability.startswith('workspace.'):
            scopes.add('workspace')
        elif self.catalog and capability in ({'desktop.observe', 'desktop.control', 'app.launch', 'app.close', 'desktop.input', 'desktop.capture', 'web.submit'} | TEACH_CAPABILITIES):
            scopes.update('app:' + app for app in self.catalog)
        elif not self.catalog:
            scopes.add(TARGET)
        if target not in scopes:
            fail('invalid_scope', -32602)
        # Admin alone does not mint a capability; delegation is bounded by a live
        # grant of that capability AND administration, including scope and expiry.
        for cap in ('identity.admin', capability):
            if not any(g.principal == issuer and g.capability == cap and not g.revoked and
                       (g.target == '*' or g.target == target) and
                       self.clock() + ttl <= g.expires for g in self.grants.values()):
                fail('delegation_denied')
        if len(self.grants) >= 128:
            fail('grant_limit', -32010)
        return self._grant(principal, capability, target, issuer, ttl)

    def revoke(self, issuer, grant_id):
        grant = self.grants.get(grant_id)
        if grant is None:
            fail('grant_denied')
        self.require(issuer, 'identity.admin', grant.target)
        # A scoped administrator cannot revoke outside its administrative scope.
        grant.revoked = True
        self.policy_revision += 1
        grant.revision = self.policy_revision
        self.event('grant.revoked')
        if (self.lease and self.lease.principal == grant.principal
                and grant.capability in MUTATIONS):
            self.fence('control.invalidated')
        self.refresh()

    def fence(self, reason):
        if self.lease is not None:
            self.lease = None
            self.phase = 'handoff_pending' if self.pending else 'idle'
            self.event(reason)

    def refresh(self):
        lease = self.lease
        if lease and (self.clock() >= lease.expires or
                      not self.can_control(lease.principal)):
            self.fence('control.invalidated')

    def can_control(self, principal):
        return any(g.principal == principal and g.capability in MUTATIONS
                   and not g.revoked and self.clock() < g.expires for g in self.grants.values())

    def acquire(self, principal, connection, ttl):
        duration(ttl)
        self.refresh()
        if not self.can_control(principal):
            fail('grant_denied')
        if self.phase != 'idle' or self.pending:
            fail('control_busy', -32005)
        self.generation += 1
        self.lease = Lease(secrets.token_hex(16), principal, connection, self.epoch,
                           self.generation, self.clock() + ttl)
        self.phase = 'controlled'
        self.event('control.changed')
        return self.lease

    def check_lease(self, principal, connection, lease_id, generation, epoch):
        self.refresh()
        if not self.can_control(principal):
            fail('grant_denied')
        lease = self.lease
        if (self.phase != 'controlled' or lease is None or lease.id != lease_id or
                lease.principal != principal or lease.connection != connection or
                lease.epoch != epoch or lease.generation != generation or type(generation) is not int):
            fail('stale_lease', -32002)
        return lease
