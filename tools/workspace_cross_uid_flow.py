# SPDX-License-Identifier: Apache-2.0
"""Operator-side D.2C.2 scenario runner and independent filesystem/SQLite verification."""
from contextlib import closing
from dataclasses import asdict
from hashlib import sha256
import os
import sqlite3
import stat

from experiments.registry_operational import POLICY_FILE
from experiments.registry_rpc import OPAQUE_ID
from experiments.registry_storage import trusted_directory
from experiments.workspace_document import FINAL, MAX_CONTENT, READ_FLAGS, resource_path, stage_name
from experiments.workspace_effect_lab import DATABASE
from loopbridge.service_ingress import DEFAULT_ACL, path_inode, read_acl
from tools.registry_cross_uid import EXECUTOR, ISSUER, QualificationError, check_metadata, require
from tools.workspace_cross_uid_fixture import (AUDIT_FIELDS, CASES, CONTENT, DIGEST, EVENT_FIELDS, NO_CALL,
                                               PROBE_ENTRY, STATE_FIELDS, pins_from_wire)

CODE = {'denied': -32001, 'invalid_params': -32602, 'destination_exists': -32061,
        'authorization_expired': -32060, 'effect_boundary_closed': -32063, 'request_conflict': -32044}
BOUNDED_STATES = {
    ('ready', 'paused', 'none'), ('prepared', 'paused', 'none'), ('dispatched', 'stepping', 'pending'),
    ('cancelled', 'stopped', 'absent'), ('revoked', 'stopped', 'absent'), ('expired', 'stopped', 'absent'),
    ('failed', 'stopped', 'absent'), ('completed', 'stopped', 'confirmed'),
    ('reconciled', 'stopped', 'confirmed'), ('uncertain', 'stopped', 'unknown'),
}


class Verifier:
    """The controller opens named resources and SQLite independently of the broker."""

    def __init__(self, layout, pins, service):
        self.layout, self.service = layout, service
        self.db, self.resources, self.policy = pins_from_wire(pins)

    @staticmethod
    def metadata(info):
        return dict(device=info.st_dev, inode=info.st_ino, uid=info.st_uid, gid=info.st_gid,
                    mode=oct(stat.S_IMODE(info.st_mode)), nlink=info.st_nlink, size=info.st_size)

    def check_private(self):
        with trusted_directory(self.layout.private) as fd:
            info = os.fstat(fd)
            require(path_inode(info) == self.db.directory and read_acl(fd, DEFAULT_ACL) is None,
                    'private_pin_changed')
            check_metadata(info, self.service, 0o700, stat.S_ISDIR, 'private_metadata_changed')

    def read_file(self, fd, name, limit, *, links):
        with os.fdopen(os.open(name, READ_FLAGS, dir_fd=fd), 'rb') as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and (before.st_uid, before.st_gid) == self.service
                    and stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == links
                    and before.st_size <= limit and read_acl(stream.fileno()) is None,
                    'file_protection_changed', result='no_go')
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            named = os.stat(name, dir_fd=fd, follow_symlinks=False)
            snapshot = lambda item: (self.metadata(item), item.st_ctime_ns, item.st_mtime_ns)
            require(snapshot(before) == snapshot(after) == snapshot(named), 'file_changed_during_read')
            return self.metadata(after) | {'sha256': sha256(data).hexdigest()}

    def policy_and_storage(self):
        self.check_private()
        with trusted_directory(self.layout.private) as fd:
            info = self.read_file(fd, POLICY_FILE, 65536, links=1)
            require(info['sha256'] == self.policy.sha256, 'policy_pin_changed')
            with os.fdopen(os.open(DATABASE, READ_FLAGS, dir_fd=fd), 'rb') as db:
                entry = check_metadata(os.fstat(db.fileno()), self.service, 0o600, stat.S_ISREG,
                                       'database_metadata_changed')
                require(path_inode(entry) == self.db.file and entry.st_nlink == 1
                        and db.read(16) == b'SQLite format 3\0', 'database_pin_changed')
        for resource, pin in self.resources.items():
            with trusted_directory(resource_path(self.layout.private, resource)) as fd:
                self.resource_metadata(fd, pin)
        return dict(database=list(self.db.file), private=list(self.db.directory),
                    resources=self.resources, policy=asdict(self.policy))

    def resource_metadata(self, fd, pin):
        info = check_metadata(os.fstat(fd), self.service, 0o700, stat.S_ISDIR, 'resource_metadata_changed')
        require(path_inode(info) == pin and read_acl(fd) is None and read_acl(fd, DEFAULT_ACL) is None,
                'resource_pin_changed')

    def durable(self, name):
        self.check_private()
        spec = CASES[name].scope
        path = self.layout.private / DATABASE
        require(path_inode(path.lstat()) == self.db.file, 'database_pin_changed')
        uri = path.as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
            db.execute('PRAGMA query_only=ON')
            db.row_factory = sqlite3.Row
            entry = db.execute('SELECT * FROM workspace_attempts WHERE id=?', (spec.attempt_id,)).fetchone()
            require(entry is not None, 'durable_attempt_missing')
            rows = db.execute('SELECT * FROM workspace_events WHERE attempt_id=? ORDER BY revision',
                              (spec.attempt_id,)).fetchall()
        require(path_inode(path.lstat()) == self.db.file, 'database_pin_changed')
        require(all(entry['id' if key == 'attempt_id' else key] == value for key, value in asdict(spec).items())
                and entry['authorizer'] == ISSUER and entry['performer'] == EXECUTOR
                and entry['request_id'] == CASES[name].request
                and tuple(entry[key] for key in ('resource_dev', 'resource_ino')) == self.resources[spec.resource_id]
                and entry['size'] == len(CONTENT.encode()) and OPAQUE_ID.fullmatch(entry['operation_id']),
                'durable_attribution_changed', result='no_go')
        require(rows and [row['revision'] for row in rows] == list(range(1, len(rows) + 1)),
                'durable_history_gap')
        return entry, [{key: row[key] for key in EVENT_FIELDS} for row in rows]

    def file(self, name, condition):
        spec = CASES[name].scope
        path = resource_path(self.layout.private, spec.resource_id)
        entry, _ = self.durable(name)
        stage = stage_name(entry['operation_id'])
        with trusted_directory(path) as fd:
            self.resource_metadata(fd, self.resources[spec.resource_id])
            names = os.listdir(fd)
            require(PROBE_ENTRY not in names, 'unexpected_direct_entry', result='no_go')
            if condition == 'empty':
                require(not names, 'unexpected_initial_entry', result='no_go')
                return dict(final=False, staging=False)
            if condition == 'staged':
                require(names == [stage], 'unexpected_preparation_entries', result='no_go')
                info = self.read_file(fd, stage, MAX_CONTENT, links=1)
            else:
                info = self.read_file(fd, FINAL, MAX_CONTENT, links=1 if condition == 'contradiction' else 2)
                if condition == 'contradiction':
                    require(names == [FINAL], 'attribution_observation_present')
                else:
                    expected_names = {FINAL, stage}
                    if name == 'race_winner':
                        loser, _ = self.durable('race_loser')
                        expected_names.add(stage_name(loser['operation_id']))
                    require(set(names) == expected_names, 'unexpected_publication_entries', result='no_go')
                    require(self.read_file(fd, stage, MAX_CONTENT, links=2) == info,
                            'filesystem_attribution_mismatch', result='no_go')
            require((info['device'], info['inode']) == (entry['stage_dev'], entry['stage_ino'])
                    and info['size'] == entry['size'] and info['sha256'] == DIGEST,
                    'filesystem_attribution_mismatch', result='no_go')
        return dict(final=condition != 'staged', staging=condition != 'contradiction',
                    operation=entry['operation_id'], file=info)

    def withdraw_attribution(self, name, budget):
        require(name == 'd3', 'invalid_attribution_fixture')
        before = self.file(name, 'published')
        resource = CASES[name].scope.resource_id
        with trusted_directory(resource_path(self.layout.private, resource)) as fd:
            self.resource_metadata(fd, self.resources[resource])
            budget()
            os.unlink(stage_name(before['operation']), dir_fd=fd)
            os.fsync(fd)
        after = self.file(name, 'contradiction')
        require(after['file'] == before['file'] | {'nlink': 1}, 'contradiction_modified_document',
                result='no_go')
        return after


class Flow:
    def __init__(self, session, evidence):
        self.session, self.emit = session, evidence

    @property
    def verify(self):
        return self.session.verifier

    def rpc(self, actor, name, action, *, revision=0, number=0, variant='exact', error=None, worker=None):
        reply = (worker or self.session.clients[actor]).call(
            op='rpc', case=name, action=action, revision=revision, number=number, variant=variant)
        if error is not None:
            require(reply == {'fault': [CODE[error], error, None]}, 'unexpected_rpc_outcome',
                    result='no_go' if 'result' in reply else 'partial')
            self.emit('rpc_denied', actor=actor, case=name, action=action, error=error, code=CODE[error],
                      variant=variant, request=number, expected_revision=revision)
            return None
        require(reply.keys() == {'result'}, 'expected_rpc_success')
        return reply['result']

    def grant(self, name, mode='all'):
        self.session.admin('grant', name, mode=mode)
        self.emit('exact_grant_profile', case=name, profile=mode)

    def status(self, name, expected):
        view = self.rpc('observer', name, 'status')
        require(view.keys() == STATE_FIELDS and view['id'] == CASES[name].scope.attempt_id
                and expected in BOUNDED_STATES and type(view['revision']) is int, 'invalid_status_view')
        result = tuple(view[key] for key in ('state', 'supervision', 'effect'))
        require(result == expected, 'unexpected_status', result='no_go' if result[2] == 'confirmed' else 'partial')
        self.emit('status', case=name, **view)
        return view['revision']

    def audit(self, name, expected, *, contains=(), excludes=()):
        entry, durable = self.verify.durable(name)
        events = []
        cursor = 0
        for _ in range(12):
            view = self.rpc('auditor', name, 'audit', revision=cursor)
            require(view.keys() == AUDIT_FIELDS and view['scope'] == asdict(CASES[name].scope)
                    and view['operation_id'] == entry['operation_id']
                    and view['authorization_request_id'] == entry['request_id'] and view['authorizer'] == ISSUER
                    and view['performer'] == EXECUTOR and view['size'] == entry['size']
                    and view['id'] == entry['id'] and view['expires_unix_ms'] == int(entry['deadline'] * 1000)
                    and type(view['events']) is list, 'invalid_audit_attribution', result='no_go')
            events.extend(view['events'])
            cursor = view['next_after']
            if cursor is None:
                break
            require(type(cursor) is int and 0 < cursor <= 64, 'invalid_audit_cursor')
        latest = durable[-1]
        kind = [event['kind'] for event in durable]
        if expected[2] == 'confirmed':
            require(kind.count('effect_observed') == kind.count(expected[0]) == 1,
                    'duplicate_or_false_confirmation', result='no_go')
        require(events == durable and tuple(latest[key] for key in ('state', 'supervision', 'effect')) == expected
                and all(view[key] == latest[key] for key in ('revision', 'state', 'supervision', 'effect'))
                and all(item in kind for item in contains) and not any(item in kind for item in excludes),
                'audit_history_mismatch', result='no_go' if view['effect'] == 'confirmed' else 'partial')
        self.emit('audit_verified', case=name, scope=view['scope'], operation=entry['operation_id'],
                  authorizer=ISSUER, performer=EXECUTOR, request=entry['request_id'], events=durable,
                  virtual_expires_ms=view['expires_unix_ms'])
        return entry['operation_id']

    def filesystem(self, name, condition):
        observed = self.verify.file(name, condition)
        self.emit('independent_filesystem', case=name, condition=condition, **observed)
        return observed

    def receipt(self, name, result, kind, revision):
        wanted = dict(id=CASES[name].scope.attempt_id, kind=kind, revision=revision)
        require(result == wanted, 'unexpected_command_receipt')
        self.emit('receipt', case=name, **wanted)
        return result

    def admit(self, name):
        self.receipt(name, self.rpc('issuer', name, 'authorize'), 'admitted', 1)
        self.status(name, ('ready', 'paused', 'none'))
        self.filesystem(name, 'empty')

    def prepare(self, name, *, existing_stage=False):
        self.receipt(name, self.rpc('executor', name, 'step', revision=1, number=1), 'step', 2)
        revision = self.status(name, ('prepared', 'paused', 'none'))
        if not existing_stage:
            self.filesystem(name, 'staged')
        return revision

    def start_publication(self, name, worker=None):
        revision = self.status(name, ('prepared', 'paused', 'none'))
        worker = worker or self.session.clients['executor']
        worker.send(op='rpc', case=name, action='step', revision=revision, number=2, variant='exact')
        return worker, revision

    def await_gate(self, name):
        result = self.session.admin('arrived', name)
        entry, events = self.verify.durable(name)
        require(events[-1]['state'] == 'dispatched' and events[-1]['effect'] == 'pending',
                'durable_dispatch_not_observed')
        self.session.counts(result['proof'], terminal=False)
        self.emit('gate', case=name, edge=CASES[name].gate, operation=entry['operation_id'],
                  durable_dispatch_revision=events[-1]['revision'], virtual_utc=result['virtual_utc'])
        return events[-1]['revision']

    def release(self, name):
        self.session.admin('released', name)

    def finished_call(self, name, pending):
        worker, revision = pending
        result = worker.receive()
        require(result.keys() == {'result'}, 'missing_rpc_receipt')
        return self.receipt(name, result['result'], 'step', revision + 1)

    def registry_and_base(self):
        self.session.ingress(initial=True)
        stages = [('admin', 'register'), ('executor', 'confirm'), ('issuer', 'offer'), ('executor', 'accept')]
        for actor, action in stages:
            self.session.clients[actor].call(op=action)
            self.emit('registry_rpc', actor=actor, action=action)
        self.session.close_client('admin')
        self.rpc('issuer', 'base', 'authorize', error='denied')
        self.grant('base', 'wrong_performer')
        self.rpc('issuer', 'base', 'authorize', error='denied')
        self.grant('base')
        for variant in ('resource', 'revision', 'attempt', 'payload', 'executor', 'capability'):
            self.rpc('issuer', 'base', 'authorize', variant=variant,
                     error='invalid_params' if variant == 'capability' else 'denied')
        self.grant('base', 'wrong_revision')
        self.rpc('issuer', 'base', 'authorize', variant='revision', error='denied')
        for actor in ('other', 'executor'):
            self.rpc(actor, 'base', 'authorize', error='denied')
        self.admit('base')
        for actor, method in [('observer', 'audit'), ('auditor', 'status'), ('executor', 'continue')]:
            self.rpc(actor, 'base', method, revision=1, number=3, error='denied')
        for actor in ('observer', 'auditor'):
            for method in ('step', 'continue', 'cancel', 'pause'):
                self.rpc(actor, 'base', method, revision=1, number=3, error='denied')
        revision = self.prepare('base')
        operation = self.audit('base', ('prepared', 'paused', 'none'), contains=('prepared',), excludes=('dispatched',))
        self.session.direct('base', 'staged', operation)
        self.receipt('base', self.rpc('executor', 'base', 'step', revision=revision, number=2), 'step', revision + 1)
        self.filesystem('base', 'published')
        self.audit('base', ('completed', 'stopped', 'confirmed'),
                   contains=('dispatched', 'effect_observed', 'completed'))
        self.session.direct('base', 'published', operation)

    def supervision(self, name):
        self.grant(name)
        self.admit(name)
        self.prepare(name)
        pending = self.start_publication(name)
        at_revision = self.await_gate(name)
        before = CASES[name].gate == 'before'
        action = name.split('_', 1)[1]
        observed = self.filesystem(name, 'staged' if before else 'published')
        if action in ('pause', 'cancel'):
            receipt = self.rpc('controller', name, action, revision=at_revision, number=3,
                               error=None if before else 'effect_boundary_closed')
            if before:
                self.receipt(name, receipt, action, at_revision + 1)
        else:
            result = self.session.admin('authority', name)
            self.emit('authority_change', case=name, action=action, virtual_utc=result['virtual_utc'])
        self.release(name)
        self.finished_call(name, pending)
        if not before:
            require(self.filesystem(name, 'published') == observed, 'effect_moved_after_link', result='no_go')
            self.audit(name, ('completed', 'stopped', 'confirmed'),
                       contains=('dispatched', 'effect_observed', 'completed'))
        elif action == 'pause':
            revision = self.status(name, ('prepared', 'paused', 'none'))
            self.filesystem(name, 'staged')
            self.session.counts(self.session.admin('snapshot')['proof'], terminal=False,
                                must_be_zero=(name,))
            result = self.rpc('executor', name, 'step', revision=revision, number=4)
            self.receipt(name, result, 'step', revision + 1)
            self.filesystem(name, 'published')
            self.audit(name, ('completed', 'stopped', 'confirmed'), contains=('pause', 'completed'))
        else:
            stopped = dict(cancel='cancelled', revoke='revoked', replace='revoked', expire='expired')
            self.filesystem(name, 'staged')
            self.audit(name, (stopped[action], 'stopped', 'absent'), excludes=('effect_observed', 'completed'))

    def concurrent(self):
        for name in ('race_winner', 'race_loser'):
            self.grant(name)
            self.admit(name)
        self.prepare('race_winner')
        self.prepare('race_loser', existing_stage=True)
        first = self.start_publication('race_winner')
        second = self.start_publication('race_loser', self.session.clients['executor_b'])
        for name in ('race_winner', 'race_loser'):
            self.await_gate(name)
        self.release('race_winner')
        self.finished_call('race_winner', first)
        at_effect = self.filesystem('race_winner', 'published')
        self.release('race_loser')
        self.finished_call('race_loser', second)
        self.audit('race_winner', ('completed', 'stopped', 'confirmed'), contains=('completed',))
        self.audit('race_loser', ('failed', 'stopped', 'absent'), contains=('failed',), excludes=('effect_observed',))
        _, events = self.verify.durable('race_loser')
        require(events[-1]['reason'] == 'destination_exists', 'race_destination_result')
        self.grant('occupied')
        self.rpc('issuer', 'occupied', 'authorize', error='destination_exists')
        require(self.filesystem('race_winner', 'published') == at_effect, 'winning_document_overwritten',
                result='no_go')

    def lost_reply(self):
        name = 'lost'
        self.grant(name)
        self.admit(name)
        revision = self.prepare(name)
        worker = self.session.clients['executor']
        require(worker.call(op='send_only', case=name, action='step', revision=revision,
                            number=2, variant='exact') == {'sent': True}, 'publication_request_not_sent')
        self.await_gate(name)
        at_effect = self.filesystem(name, 'published')
        require(worker.call(op='discard') == {'discarded': True}, 'reply_was_not_discarded')
        self.emit('transport_reply_discarded', case=name, stage='after_link_before_confirmation')
        self.release(name)
        self.session.admin('finished', name)
        _, events = self.verify.durable(name)
        historical = [event for event in events if event['expected_revision'] == revision
                      and event['kind'] == 'step']
        require(len(historical) == 1 and historical[0]['actor'] == EXECUTOR, 'lost_receipt_not_durable')
        self.receipt(name, self.rpc('executor', name, 'step', revision=revision, number=2),
                     'step', historical[0]['revision'])
        self.rpc('executor', name, 'step', revision=revision + 1, number=2, error='request_conflict')
        require(self.filesystem(name, 'published') == at_effect, 'replay_changed_inode', result='no_go')
        self.audit(name, ('completed', 'stopped', 'confirmed'), contains=('completed',))

    def recovery(self, name):
        self.grant(name)
        self.admit(name)
        self.prepare(name)
        pending = self.start_publication(name)
        self.await_gate(name)
        condition = 'staged' if name == 'd2' else 'published'
        before = self.filesystem(name, condition)
        self.session.interrupt(pending[0], name)
        require(self.filesystem(name, condition) == before, 'interruption_changed_document', result='no_go')
        if name == 'd3':
            before = self.verify.withdraw_attribution(name, self.session.window.budget)
            condition = 'contradiction'
            self.emit('attribution_observation_removed', case=name, **before)
        self.session.restart()
        self.session.ingress(initial=False)
        operation = self.audit_after_reissue(name, pending[1])
        require(self.filesystem(name, condition) == before, 'recovery_changed_document', result='no_go')
        if name in ('d1', 'd2'):
            self.session.direct(name, 'restart' if name == 'd1' else 'restart_staged', operation)

    def audit_after_reissue(self, name, revision):
        for actor, action in [('observer', 'status'), ('auditor', 'audit'), ('executor', 'step'),
                              ('controller', 'pause'), ('controller', 'cancel')]:
            self.rpc(actor, name, action, revision=revision, number=2, error='denied')
        self.grant(name, 'status')
        self.rpc('auditor', name, 'audit', error='denied')
        self.rpc('executor', name, 'step', revision=revision, number=2, error='denied')
        expected = ('reconciled', 'stopped', 'confirmed') if name == 'd1' else ('uncertain', 'stopped', 'unknown')
        self.status(name, expected)
        self.grant(name, 'audit')
        operation = self.audit(name, expected, contains=(('reconciled', 'effect_observed') if name == 'd1'
                                                         else ('recovery_uncertain',)))
        _, events = self.verify.durable(name)
        if name != 'd1':
            reason = 'absent' if name == 'd2' else 'conflicting'
            require(events[-1]['reason'] == reason and not any(event['kind'] == 'effect_observed' for event in events),
                    'recovery_evidence_misclassified', result='no_go')
        self.grant(name, 'receipt')
        self.receipt(name, self.rpc('executor', name, 'step', revision=revision, number=2), 'step', revision + 1)
        self.rpc('controller', name, 'cancel', revision=events[-1]['revision'], number=3, error='denied')
        self.session.counts(self.session.admin('snapshot')['proof'], terminal=False, recovery=True)
        return operation

    def fresh(self):
        name = 'fresh'
        self.rpc('issuer', name, 'authorize', error='denied')
        self.grant(name, 'old_identity')
        self.rpc('issuer', name, 'authorize', variant='old_attempt', error='request_conflict')
        self.grant(name)
        self.rpc('issuer', name, 'authorize', variant='old_request', error='request_conflict')
        self.admit(name)
        revision = self.prepare(name)
        self.receipt(name, self.rpc('executor', name, 'step', revision=revision, number=2), 'step', revision + 1)
        self.filesystem(name, 'published')
        self.audit(name, ('completed', 'stopped', 'confirmed'), contains=('completed',))

    def run(self):
        self.registry_and_base()
        for name in CASES:
            if name.startswith(('pre_', 'post_')):
                self.supervision(name)
        self.concurrent()
        self.lost_reply()
        for name in ('d1', 'd2', 'd3'):
            self.recovery(name)
        self.fresh()
        self.session.counts(self.session.admin('snapshot')['proof'], terminal=True)
