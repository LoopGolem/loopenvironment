# SPDX-License-Identifier: Apache-2.0
"""Diagnostic safety tests, not mocks or evidence of a compositor barrier."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import unittest

from experiments.m1_2.protocol import Fault
from experiments.m1_3b.diagnose import fault, input_summary, stop_child


class DiagnosticTests(unittest.TestCase):
    def test_input_inventory_drops_identifiers_focus_and_keymap(self):
        summary = input_summary([dict(type='keyboard', identifier='private-device', name='private-name',
            xkb_active_layout_name='private-keymap', libinput={'send_events': 'enabled'})],
            [dict(name='private-seat', focus=12345, devices=[{'identifier':'private-device'}], capabilities=3)])
        text = json.dumps(summary)
        self.assertNotIn('private-', text)
        self.assertNotIn('12345', text)
        self.assertEqual(summary['seats'][0]['device_count'], 1)
        self.assertTrue(summary['devices'][0]['libinput'])

    def test_fault_does_not_accept_success(self):
        with self.assertRaisesRegex(AssertionError, 'operation_not_denied'):
            fault(lambda: {'confirmed': True}, 'denied')

    def test_fault_does_not_echo_unexpected_error_payload(self):
        def operation():
            raise Fault(-1, 'private-error-data')
        with self.assertRaisesRegex(AssertionError, '^unexpected_fault$'):
            fault(operation, 'denied')

    def test_expected_fault_is_preserved(self):
        def operation():
            raise Fault(-32005, 'control_busy')
        self.assertEqual(fault(operation, 'control_busy'), 'control_busy')

    def test_supervised_child_stops_and_continues_via_pidfd(self):
        # Real Linux process/pipe and signals. No compositor, AT-SPI or barrier mock.
        child = subprocess.Popen(['/usr/bin/python3', '-I', '-c',
            'import sys; sys.stdin.readline(); print("continued", flush=True)'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        pidfd = os.pidfd_open(child.pid)
        try:
            stop_child(child, pidfd)
            state = Path(f'/proc/{child.pid}/stat').read_text().rsplit(')',1)[1].split()[0]
            self.assertEqual(state, 'T')
            child.stdin.write(b'go\n')
            child.stdin.flush()
            self.assertFalse(select.select([child.stdout], [], [], 0)[0])
            signal.pidfd_send_signal(pidfd, signal.SIGCONT)
            stdout, _ = child.communicate(timeout=2)
            self.assertEqual(stdout, b'continued\n')
            self.assertEqual(child.returncode, 0)
        finally:
            try:
                signal.pidfd_send_signal(pidfd, signal.SIGCONT)
            except ProcessLookupError:
                pass
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=2)
            child.stdin.close()
            child.stdout.close()
            os.close(pidfd)
