# SPDX-License-Identifier: Apache-2.0
"""Trusted Calculator adapter. Does not implement takeover or physical cancellation."""
import time
from experiments.m1_1 import semantic as m1
from experiments.m1_2.broker import Fixture


class Calculator:
    def __init__(self):
        self.fixture = Fixture()

    def snapshot(self):
        return self.fixture.read(), self.fixture.reference(10)

    def prepare(self, ref):
        if not ref.valid or time.monotonic() >= ref.deadline:
            raise m1.Rejected('expired_reference')
        before = self.fixture.read()
        m1.validate(ref, self.fixture.process, self.fixture.pidfd, self.fixture.desktop)
        index, _ = m1.click_index(ref.node)
        action = ref.node.queryAction()
        return before, ref, action, index

    def send(self, prepared):
        _, ref, action, index = prepared
        if not ref.valid or time.monotonic() >= ref.deadline:
            raise m1.Rejected('expired_reference')
        ref.invalidate()
        if not action.doAction(index):
            raise m1.Rejected('action_not_accepted')

    def confirm(self, prepared):
        before = prepared[0]
        def confirmed():
            after = self.fixture.read()
            changed = [p for p in before if after.get(p) != before[p]]
            if set(before) != set(after) or len(changed) != 1 or after[changed[0]] != before[changed[0]] + '7':
                raise m1.Rejected('result_not_confirmed')
            return after
        return m1.wait_for(confirmed, timeout=3)

    def close(self):
        self.fixture.close()
