# SPDX-License-Identifier: Apache-2.0
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from loopbridge.service import Journal


class JournalRecovery(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.journal = Journal(self.root)
        self.first = 'a' * 32
        self.second = 'b' * 32

    def restart_blocked(self):
        return Journal(self.root).blocked('desktop')

    def test_write_or_publication_failure_cannot_resolve_unknown(self):
        self.journal.mark('desktop', self.first)
        for api in ('tempfile.mkstemp', 'os.fsync', 'os.replace'):
            with patch('loopbridge.service.' + api, side_effect=OSError):
                with self.assertRaises(OSError):
                    self.journal.clear('desktop')
            self.assertTrue(self.restart_blocked())

    def test_intent_directory_sync_failure_blocks_and_refuses_overwrite(self):
        with patch.object(self.journal, 'sync', side_effect=OSError):
            with self.assertRaises(OSError):
                self.journal.mark('desktop', self.first)
        self.assertTrue(self.restart_blocked())
        with self.assertRaises(OSError):
            self.journal.mark('desktop', self.second)

    def test_failed_resolution_directory_sync_keeps_intent_and_matching_proof(self):
        self.journal.mark('desktop', self.first)
        with patch.object(self.journal, 'sync', side_effect=OSError):
            with self.assertRaises(OSError):
                self.journal.clear('desktop')
        self.assertEqual(self.journal.intent('desktop'), self.first)
        self.assertFalse(self.restart_blocked())  # The independently proved receipt survived.
        (self.root / 'desktop.resolved').unlink()  # Model a crash that lost the rename.
        self.assertTrue(self.restart_blocked())

    def test_failed_removal_never_touches_active_intent(self):
        self.journal.mark('desktop', self.first)
        with patch('loopbridge.service.os.replace', side_effect=OSError), \
             patch('loopbridge.service.os.unlink', side_effect=PermissionError) as remove:
            with self.assertRaises(OSError):
                self.journal.clear('desktop')
        self.assertTrue(Path(remove.call_args.args[0]).name.startswith('.journal-'))
        self.assertTrue(self.restart_blocked())

    def test_abrupt_exit_between_durable_intent_and_resolution(self):
        code = '''
import os, sys
from pathlib import Path
from loopbridge.service import Journal
Journal(Path(sys.argv[1])).mark('desktop', 'a' * 32)
os.kill(os.getpid(), 9)
'''
        proc = subprocess.run([sys.executable, '-B', '-c', code, str(self.root)],
                              check=False, timeout=10)
        self.assertEqual(proc.returncode, -9)
        self.assertTrue(self.restart_blocked())

    def test_old_receipt_cannot_release_new_operation_or_malformed_intent(self):
        self.journal.mark('desktop', self.first)
        self.journal.clear('desktop')
        self.assertFalse(self.restart_blocked())
        self.journal.mark('desktop', self.second)
        self.assertTrue(self.restart_blocked())
        (self.root / 'desktop.pending').write_text('bad record')
        self.assertTrue(self.restart_blocked())

    def test_orphan_receipt_is_inconsistent_and_blocks(self):
        self.journal.mark('desktop', self.first)
        self.journal.clear('desktop')
        (self.root / 'desktop.pending').unlink()
        self.assertTrue(self.restart_blocked())
