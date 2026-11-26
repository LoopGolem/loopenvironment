# SPDX-License-Identifier: Apache-2.0
"""Desktop-side choreography for the fixed D.2B.1 qualification cases."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from hashlib import sha256
import json
from threading import Barrier, Event
from time import monotonic

from experiments.supervision_lab import VERSION
from experiments.supervision_storage import PLAN
from loopbridge.protocol import Fault
from tools.registry_cross_uid import (EXECUTOR, ISSUER, OBJECTIVE, TARGET, QualificationError,
                                      authenticate, connect, denied_rpc, emit, require)

SUPERVISOR, OBSERVER, AUDITOR = (f'{n:032x}' for n in (8, 9, 10))
CASES = ('flow', 'before_dispatch', 'pause_running', 'step_race', 'revoked',
         'advance_expired', 'cancelled', 'attempt_expired', 'interrupted')
TERMINALS = dict(flow='completed', pause_running='completed', revoked='revoked',
                 advance_expired='expired', cancelled='cancelled', attempt_expired='expired')
ABANDONED = dict(before_dispatch='revoked', step_race='revoked', interrupted='uncertain')
EXPECTED_CALLS = dict(zip(CASES, (2, 0, 2, 1, 1, 1, 1, 0, 1)))
ROLES = {ISSUER: 'issuer', EXECUTOR: 'executor', SUPERVISOR: 'supervisor',
         OBSERVER: 'observer', AUDITOR: 'auditor'}
CASE_IDS = {case: f'{200 + index:032x}' for index, case in enumerate(CASES)}
CASE_TTLS = {case: 60 if case == 'attempt_expired' else 300 for case in CASES}
WAIT = 10


def receipt_id(number):
    return f'{number:032x}'


def digest_trails(trails):
    return sha256(json.dumps(trails, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class DesktopFlow:
    def __init__(self, layout, service, pid, credentials):
        self.layout, self.service, self.pid, self.credentials = layout, service, pid, credentials

    @contextmanager
    def rpc(self, principal):
        with connect(self.layout, self.service, self.pid, version=VERSION, timeout=WAIT + 3) as rpc:
            authenticate(rpc, self.credentials[ROLES[principal]], principal)
            yield rpc

    def call(self, principal, method, **params):
        with self.rpc(principal) as rpc:
            return rpc.call('execution.' + method, **params)

    def control(self, action, attempt, revision, request):
        return self.call(EXECUTOR if action == 'start' else SUPERVISOR, action, attempt_id=attempt,
                         expected_revision=revision, request_id=receipt_id(request))

    def status(self, attempt):
        return self.call(OBSERVER, 'status', attempt_id=attempt)

    def audit(self, attempt):
        return self.call(AUDITOR, 'audit', attempt_id=attempt)

    def prepare(self):
        for index, case in enumerate(CASES):
            receipt = self.call(ISSUER, 'authorize', executor_id=TARGET, objective_id=OBJECTIVE,
                                accepted_revision=3, request_id=CASE_IDS[case], operation=PLAN,
                                ttl_seconds=CASE_TTLS[case])
            require(receipt['kind'] == 'admitted', 'independent_admission_failed')
            attempt = receipt['id']
            require(self.control('start', attempt, receipt['revision'], 300 + index)
                    == dict(id=attempt, revision=2, kind='running'), 'start_not_confirmed')
        with self.rpc(ISSUER) as rpc:
            denied_rpc(rpc, 'execution.audit', attempt_id=attempt)
        emit('desktop_prepared', attempts=len(CASES), separate_execution_authorization=True)

    def wait_boundary(self, attempt, *, mode, stage):
        # A trusted gate keeps the audited boundary stable until the operator releases it.
        deadline = monotonic() + WAIT
        while monotonic() < deadline:
            view = self.status(attempt)
            if (view['supervision'], view['current_stage']) == (mode, stage):
                return view
            require(view['state'] == 'running', 'boundary_lost', result='no_go')
            Event().wait(min(0.02, max(0, deadline - monotonic())))
        raise QualificationError('boundary_not_observed')

    def expect(self, attempt, state, completed, *, reason=None):
        trail = self.audit(attempt)
        result = 5 if state == 'completed' else None
        require(result is None or type(trail['result']) is int, 'result_is_not_integer', result='no_go')
        require((trail['state'], trail['completed_stages'], trail['result'], trail['reason'])
                == (state, completed, result, reason), 'unexpected_execution_outcome', result='no_go')
        require([event['revision'] for event in trail['events']] == list(range(1, trail['revision'] + 1)),
                'non_contiguous_audit', result='no_go')
        return trail

    def _paired_step(self, pool, attempt):
        barrier = Barrier(2)

        def run(request):
            barrier.wait(WAIT)
            return self.control('step', attempt, 2, request)

        requests = {pool.submit(run, request): request for request in (61, 62)}
        self.wait_boundary(attempt, mode='stepping', stage=1)
        finished, pending = wait(requests, timeout=WAIT, return_when=FIRST_COMPLETED)
        require(len(finished) == len(pending) == 1, 'step_race_not_serialized', result='no_go')
        try:
            finished.pop().result()
        except Fault as error:
            require(error.message == 'stale_revision', 'unexpected_step_race_refusal')
        else:
            raise QualificationError('duplicate_step_admitted', 'no_go')
        winner = pending.pop()
        replay = self.control('step', attempt, 2, requests[winner])
        require(replay == dict(id=attempt, revision=3, kind='step'), 'live_step_replay_invalid')
        emit('release_required', case='step_race')
        require(winner.result(WAIT) == replay, 'step_replay_changed')
        view = self.status(attempt)
        require((view['state'], view['completed_stages'], view['supervision']) == ('running', 1, 'paused'),
                'step_did_not_return_to_pause', result='no_go')

    def _controlled_case(self, pool, case, attempt):
        action = 'step' if case == 'interrupted' else 'continue'
        future = pool.submit(self.control, action, attempt, 2, 61)
        stage = None if case in ('before_dispatch', 'attempt_expired') else 1
        view = self.wait_boundary(attempt, mode='stepping' if action == 'step' else 'flowing', stage=stage)
        if case in ('before_dispatch', 'pause_running'):
            pause = self.control('pause', attempt, view['revision'], 62)
            require(pause['kind'] == ('paused' if stage is None else 'pause_requested'),
                    'false_pause_acknowledgement', result='no_go')
            if stage is not None:
                paused = self.status(attempt)
                require(paused['supervision'] == 'pause_requested' and paused['current_stage'] == stage,
                        'pause_boundary_not_pending', result='no_go')
        elif case == 'cancelled':
            require(self.control('cancel', attempt, view['revision'], 62)['kind'] == 'cancelled',
                    'cancel_not_confirmed')
        emit('release_required', case=case)
        if case == 'interrupted':
            try:
                future.result(WAIT)
            except (EOFError, ConnectionResetError):
                return
            raise QualificationError('interrupted_dispatch_returned')
        future.result(WAIT)
        if case in ('before_dispatch', 'pause_running'):
            view = self.status(attempt)
            expected = 0 if stage is None else 1
            require((view['state'], view['supervision'], view['completed_stages'], view['current_stage'])
                    == ('running', 'paused', expected, None), 'pause_not_drained', result='no_go')
            if case == 'pause_running':
                self.control('continue', attempt, view['revision'], 63)

    def active(self, attempts):
        for attempt in attempts.values():
            view = self.status(attempt)
            require((view['state'], view['supervision'], view['completed_stages'], view['current_stage'])
                    == ('running', 'paused', 0, None), 'nonzero_initial_progress', result='no_go')

        flow = attempts['flow']
        with self.rpc(OBSERVER) as rpc:
            denied_rpc(rpc, 'execution.audit', attempt_id=flow)
            for action in ('step', 'continue', 'cancel'):
                denied_rpc(rpc, 'execution.' + action, attempt_id=flow,
                           expected_revision=2, request_id=receipt_id(70))
        receipt = self.control('step', flow, 2, 61)
        view = self.status(flow)
        require((view['state'], view['supervision'], view['completed_stages'], view['current_stage'])
                == ('running', 'paused', 1, None), 'step_progress_invalid', result='no_go')
        require(self.control('step', flow, 2, 61) == receipt, 'step_replay_changed')
        self.control('continue', flow, view['revision'], 62)
        self.expect(flow, 'completed', 2)

        with ThreadPoolExecutor(2) as pool:
            for case in CASES[1:-1]:
                if case == 'step_race':
                    self._paired_step(pool, attempts[case])
                else:
                    self._controlled_case(pool, case, attempts[case])

            reasons = dict(revoked='revoked', cancelled='cancelled',
                           advance_expired='advance_expired', attempt_expired='attempt_expired')
            stable = {case: self.expect(attempts[case], state, 2 if state == 'completed' else 0,
                                        reason=reasons.get(case))
                      for case, state in TERMINALS.items()}
            emit('recovery_reference', audit_sha256=digest_trails(stable), result=5,
                 observer_control_denied=True, step_receipt_preserved=True)
            self._controlled_case(pool, 'interrupted', attempts['interrupted'])
        emit('desktop_active_complete', interrupted_dispatch=True, virtual_deadlines_exercised=True)

    def before_regrant(self, attempts):
        with self.rpc(AUDITOR) as rpc:
            denied_rpc(rpc, 'execution.audit', attempt_id=attempts['flow'])
        with self.rpc(SUPERVISOR) as rpc:
            denied_rpc(rpc, 'execution.step', attempt_id=attempts['flow'],
                       expected_revision=2, request_id=receipt_id(61))
        emit('volatile_grants_absent', audit_denied=True, control_denied=True)

    def recovered(self, attempts, audit_sha256):
        stable = {case: self.audit(attempts[case]) for case in TERMINALS}
        require(digest_trails(stable) == audit_sha256, 'terminal_history_changed', result='no_go')
        for case, state in ABANDONED.items():
            self.expect(attempts[case], state, 1 if case == 'step_race' else 0,
                        reason='interrupted' if case == 'interrupted' else 'revoked')
        flow = attempts['flow']
        replay = self.control('step', flow, 2, 61)
        require(replay == dict(id=flow, revision=3, kind='step'), 'durable_receipt_not_reconciled')
        require(self.audit(flow) == stable['flow'], 'receipt_replay_mutated_history', result='no_go')
        emit('desktop_recovered', terminal_history_preserved=True, receipt_reconciled=True,
             interrupted_uncertain=True, both_expiry_causes_preserved=True, result=5)
