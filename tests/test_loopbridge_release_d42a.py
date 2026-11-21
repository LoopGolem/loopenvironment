# SPDX-License-Identifier: Apache-2.0
"""Offline verification of the staged release and installed entrypoint."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'deploy/loopbridge/launcher.py'
LAUNCHER = runpy.run_path(str(SOURCE))


class ReleaseVerificationTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(self.enterContext(TemporaryDirectory()))
        self.release = self.base / ('a' * 40)
        self.release.mkdir(mode=0o755)
        for name in LAUNCHER['REQUIRED']:
            path = self.release / name
            path.parent.mkdir(mode=0o755, exist_ok=True)
            if name in LAUNCHER['HELPERS']:
                # Synthetic ELF header used only by the verifier, never executed.
                path.write_bytes(b'\x7fELF\x02\x01' + bytes(12) + b'\x3e\x00')
                path.chmod(0o755)
            elif name == 'launcher.py':
                shutil.copyfile(SOURCE, path)
                path.chmod(0o644)
            else:
                path.write_text('fixture')
                path.chmod(0o644)
        self.manifest = self.release / 'release.json'
        raw = json.dumps(dict(version=1, revision=self.release.name, files=LAUNCHER['inventory'](
            self.release, os.geteuid(), os.getegid()))).encode()
        self.manifest.write_bytes(raw)
        self.manifest.chmod(0o644)
        self.digest = hashlib.sha256(raw).hexdigest()

    def verify(self, digest=None):
        LAUNCHER['verify_release'](self.release, digest or self.digest,
                                  uid=os.geteuid(), gid=os.getegid())

    def test_anchored_manifest_and_complete_inventory(self):
        self.verify()
        with self.assertRaisesRegex(ValueError, 'approved checksum'):
            self.verify('c' * 64)
        (self.release / 'loopbridge/private_session.py').write_text('modified')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.verify()

    def test_rejects_symlink_and_writable_release(self):
        target = self.release / 'loopbridge/unexpected.py'
        target.symlink_to(self.manifest)
        with self.assertRaisesRegex(ValueError, 'unsafe release path'):
            self.verify()
        target.unlink()
        (self.release / 'loopbridge').chmod(0o775)
        with self.assertRaisesRegex(ValueError, 'unsafe release path'):
            self.verify()

    def test_required_helpers_must_exist_be_valid_and_executable(self):
        with patch('os.statvfs', return_value=SimpleNamespace(f_flag=os.ST_NOEXEC)):
            with self.assertRaisesRegex(ValueError, 'non-executable'):
                self.verify()
        helper = self.release / 'helpers/effects'
        helper.write_bytes(b'invalid binary')
        with self.assertRaisesRegex(ValueError, 'non-executable'):
            self.verify()
        helper.unlink()
        with self.assertRaisesRegex(ValueError, 'required release helper is missing'):
            self.verify()

    def test_service_launcher_cannot_run_from_candidate_staging(self):
        completed = subprocess.run(
            [sys.executable, '-I', '-B', str(self.release / 'launcher.py'),
             '--manifest-sha256', self.digest, '--client-uid', '1234'],
            cwd=self.base, capture_output=True, text=True, check=False,
            env={**os.environ, 'PYTHONPATH': str(self.release), 'CREDENTIALS_DIRECTORY': str(self.base)})
        self.assertEqual(completed.returncode, 1)
        self.assertIn('versioned installed release required', completed.stderr)

    def test_administrative_actions_cannot_run_from_staging(self):
        for action in ('verify-installed', 'admin-init', 'admin-ready', 'ready-client'):
            with self.subTest(action=action):
                completed = subprocess.run(
                    [sys.executable, '-I', '-B', str(self.release / 'launcher.py'),
                     '--manifest-sha256', self.digest, '--action', action],
                    cwd=self.base, input=b'', capture_output=True, check=False)
                self.assertEqual(completed.returncode, 1)
                self.assertIn(b'versioned installed release required', completed.stderr)
