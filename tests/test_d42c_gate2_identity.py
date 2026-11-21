# SPDX-License-Identifier: Apache-2.0
"""Exercise the clone identity guard from the D4.2C runbook."""
from pathlib import Path
import subprocess
import sys
import unittest


CLONE_UUID = '10a1d971-aba2-4d2b-b01e-74b7e85f7c26'
CLONE_DMI_UUID = '71d9a110-a2ab-2b4d-b01e-74b7e85f7c26'
SOURCE_UUID = '1fdf7e93-4d4b-4ddd-aa72-ddb41d8b16fc'
SOURCE_DMI_UUID = '937edf1f-4b4d-dd4d-aa72-ddb41d8b16fc'


class Gate2IdentityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runbook = (Path(__file__).resolve().parents[1] / 'docs/design/TRUSTED_SERVICE_SMOKE_D42C.md')
        text = runbook.read_text(encoding='utf-8')
        marker = '''/usr/bin/python3 -I -B - "$DIAG_UUID" "$GUEST_UUID" <<'PY'\n'''
        _, start, snippet = text.partition(marker)
        cls.guard, end, _ = snippet.partition('\nPY\n')
        if not (start and end):
            raise AssertionError('D4.2C clone identity guard is missing from the runbook')

    def check_identity(self, expected, guest):
        return subprocess.run([sys.executable, '-I', '-B', '-', expected, guest],
                              input=self.guard, capture_output=True, text=True, timeout=5, check=False)

    def test_accepts_observed_mixed_endian_uuid(self):
        for guest in (CLONE_DMI_UUID, CLONE_DMI_UUID.upper()):
            with self.subTest(guest=guest):
                result = self.check_identity(CLONE_UUID, guest)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_source_vm_and_altered_clone_uuid(self):
        for guest in (SOURCE_UUID, SOURCE_DMI_UUID, CLONE_DMI_UUID[:-1] + '7'):
            with self.subTest(guest=guest):
                result = self.check_identity(CLONE_UUID, guest)
                self.assertEqual(result.returncode, 1)
                self.assertIn('does not identify the approved clone', result.stderr)

    def test_rejects_direct_match_that_normalizes_to_a_different_uuid(self):
        result = self.check_identity(CLONE_UUID, CLONE_UUID)
        self.assertEqual(result.returncode, 1)
        self.assertIn('does not identify the approved clone', result.stderr)

    def test_rejects_malformed_uuid_on_either_side(self):
        for expected, guest in (('-' * 36, CLONE_DMI_UUID), (CLONE_UUID, ''),
                                (CLONE_UUID, CLONE_DMI_UUID.replace('-', ''))):
            with self.subTest(expected=expected, guest=guest):
                result = self.check_identity(expected, guest)
                self.assertEqual(result.returncode, 1)
                self.assertIn('invalid clone or DMI UUID', result.stderr)
