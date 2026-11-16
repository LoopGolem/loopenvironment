# SPDX-License-Identifier: Apache-2.0
"""Bounded in-memory session authority. Only the explicit simulator can hand off."""
from dataclasses import dataclass
import math
import secrets
import threading
import time

from experiments.m1_2.protocol import Fault, History

CAPABILITIES = frozenset(('session.discover', 'desktop.observe', 'desktop.control',
                          'session.override', 'identity.admin', 'desktop.capture',
                          'app.teach', 'app.profile.read'))
TARGET = 'calculator.digit7'


def fail(message, code=-32001):
    raise Fault(code, message)


def duration(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 180:
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
    epoch: str
    generation: int
    revision: int
    expires: float
    reference: object


class Session:
    def __init__(self, sid, clock=time.monotonic):
        self.id, self.clock = sid, clock
        self.lock = threading.RLock()  # Per session, never a process-wide adapter lock.
        self.epoch = secrets.token_hex(16)
        self.revision = self.policy_revision = self.generation = 0
        self.phase, self.lease, self.pending = 'idle', None, None
        self.grants = {}
        self.history = History(self.epoch, capacity=8)
        for capability in CAPABILITIES:
            self._grant('owner', capability, '*', 'lab_fixture', 180)

    def event(self, kind):
        self.revision += 1
        self.history.append(dict(kind=kind, revision=self.revision,
                                 policy_revision=self.policy_revision, generation=self.generation,
                                 phase=self.phase))
        self.history.items[-1]['kind'] = kind
        self.history.items[-1]['source'] = 'authority'

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

    def require(self, principal, capability, target=TARGET):
        if not self.permits(principal, capability, target):
            fail('grant_denied')

    def delegate(self, issuer, principal, capability, target, ttl):
        duration(ttl)
        self.require(issuer, 'identity.admin', target)
        if principal not in ('owner', 'delegate', 'observer') or capability not in CAPABILITIES:
            fail('invalid_grant', -32602)
        if target not in ('*', TARGET):
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
        self.refresh()

    def fence(self, reason):
        if self.lease is not None:
            self.lease = None
            self.phase = 'handoff_pending' if self.pending else 'idle'
            self.event(reason)

    def refresh(self):
        lease = self.lease
        if lease and (self.clock() >= lease.expires or
                      not self.permits(lease.principal, 'desktop.control')):
            self.fence('control.invalidated')

    def acquire(self, principal, connection, ttl):
        duration(ttl)
        self.refresh()
        self.require(principal, 'desktop.control')
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
        self.require(principal, 'desktop.control')
        lease = self.lease
        if (self.phase != 'controlled' or lease is None or lease.id != lease_id or
                lease.principal != principal or lease.connection != connection or
                lease.epoch != epoch or lease.generation != generation or type(generation) is not int):
            fail('stale_lease', -32002)
        return lease

    def restart(self):
        if self.phase == 'blocked':
            fail('handoff_not_confirmed', -32006)
        if self.pending:
            fail('operation_pending', -32005)
        self.epoch = secrets.token_hex(16)
        self.lease, self.phase, self.generation = None, 'idle', 0
        self.history = History(self.epoch, capacity=8)
        self.event('session.restarted')

    def begin_simulated_takeover(self, principal):
        self.refresh()
        self.require(principal, 'session.override')
        self.require(principal, 'desktop.control')
        if self.phase == 'blocked':
            fail('handoff_not_confirmed', -32006)
        if self.phase == 'handoff_pending':
            fail('control_busy', -32005)
        self.simulated_requester = principal
        self.lease = None
        self.phase = 'handoff_pending'
        self.event('simulation.handoff_pending')

    def finish_simulated_takeover(self, principal, connection, resolution):
        if self.phase != 'handoff_pending' or getattr(self, 'simulated_requester', None) != principal:
            fail('handoff_not_confirmed', -32006)
        if resolution not in ('completed_before_barrier', 'cancelled_before_dispatch'):
            self.phase = 'blocked'
            self.event('simulation.handoff_unknown')
            fail('handoff_not_confirmed', -32006)
        self.require(principal, 'session.override')
        self.require(principal, 'desktop.control')
        self.pending = None
        self.phase = 'idle'
        self.event('simulation.' + resolution)
        return self.acquire(principal, connection, 10)
