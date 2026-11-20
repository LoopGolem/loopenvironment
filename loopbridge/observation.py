# SPDX-License-Identifier: Apache-2.0
"""Read-only, monotonic observation of an already dispatched operation."""
from datetime import datetime, timezone
import re
import time


TERMINAL = {
    'success': 'success', 'succeeded': 'success', 'completed': 'success',
    'failure': 'failure', 'failed': 'failure', 'rejected': 'failure', 'declined': 'failure',
    'unknown': 'unknown', 'unavailable': 'unknown', 'timeout': 'unknown',
    'expired': 'unknown', 'no_offers': 'complete_no_offers', 'nooffers': 'complete_no_offers',
}
PENDING = {'pending', 'queued', 'processing', 'verifying', 'submitting', 'received', 'partial'}


def classify(sample):
    """Return a normalized state from explicit status or generic visible text."""
    if not isinstance(sample, dict):
        return 'unknown'
    status = sample.get('status')
    if isinstance(status, str):
        normalized = status.strip().lower().replace('-', '_').replace(' ', '_')
        if normalized in TERMINAL:
            return TERMINAL[normalized]
        if normalized in PENDING:
            return normalized
    notices = sample.get('notices', ())
    if not isinstance(notices, (list, tuple)):
        return 'pending'
    text = ' '.join(x for x in notices if isinstance(x, str)).lower()
    patterns = (
        (r'\b(verificando|checking|validating).{0,60}(seguran|security|verification|captcha)', 'verifying'),
        (r'\b(enviando|submitting|sending).{0,60}(solicita|request|quote|cotação)', 'submitting'),
        (r'\b(processando|processing)\b', 'processing'),
        (r'\b(recebida|received|registrada|protocolo|protocol|receipt)\b', 'received'),
    )
    for pattern, state in patterns:
        if re.search(pattern, text):
            return state
    return 'pending'


def observe(read, *, timeout, interval=1.0, clock=time.monotonic, sleep=time.sleep, on_change=None):
    """Poll only read(); never retries or re-dispatches the operation."""
    if not 0 < timeout <= 900 or not 0.05 <= interval <= 30:
        raise ValueError('observation_limits_invalid')
    started = clock()
    deadline = started + timeout
    transitions = []
    previous = None
    last = None
    while True:
        now = clock()
        if now >= deadline:
            break
        try:
            sample = read()
            state = classify(sample)
        except (OSError, EOFError):
            state = 'unknown'
        now = clock()
        if now >= deadline:
            break
        last = state
        if state != previous:
            event = {'state': state, 'elapsedSeconds': round(now - started, 3),
                     'observedAt': datetime.now(timezone.utc).isoformat()}
            transitions.append(event)
            if on_change:
                on_change(event)
            previous = state
        if state in TERMINAL.values():
            return {'state': state, 'elapsedSeconds': round(now - started, 3),
                    'transitions': transitions}
        remaining = deadline - clock()
        if remaining <= 0:
            continue
        sleep(min(interval, remaining))
    return {'state': 'unknown', 'reason': 'observation_deadline',
            'lastState': last, 'elapsedSeconds': round(now - started, 3),
            'transitions': transitions}
