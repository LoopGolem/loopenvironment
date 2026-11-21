# SPDX-License-Identifier: Apache-2.0
"""Unprivileged fixtures for the dedicated-service administrative bootstrap."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import socket
import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from loopbridge import service_admin as admin
from loopbridge.identity import Identities
from loopbridge.private_session import handle
from loopbridge.protocol import Fault
from loopbridge.service_bootstrap import VerifierRegistry
from loopbridge.service_ingress import ACCESS_ACL, named_user_acl, bound_listener


class AdminFixture(unittest.TestCase):
    def setUp(self):
        self.base = Path(self.enterContext(TemporaryDirectory(prefix='lb-admin-')))
        self.admin = self.base / 'admin'
        self.credentials = self.base / 'credentials'
        self.state = self.base / 'state'
        self.runtime = self.base / 'run'
        for folder in (self.admin, self.credentials, self.state):
            folder.mkdir(mode=0o700)
        self.uid, self.gid = os.geteuid(), os.getegid()

    def initialize(self):
        admin.initialize(self.admin, self.credentials, self.state, self.runtime,
                         self.uid, self.gid, admin_uid=self.uid, admin_gid=self.gid)

    def test_fresh_bootstrap_only_retains_owner_bearer_and_valid_seed(self):
        self.initialize()
        owner = self.admin / admin.OWNER_FILE
        manifest = self.credentials / admin.MANIFEST_FILE
        seed = self.state / admin.REGISTRY_FILE
        self.assertEqual(list(self.admin.iterdir()), [owner])
        self.assertEqual(list(self.credentials.iterdir()), [manifest])
        self.assertEqual(list(self.state.iterdir()), [seed])
        for filename in (owner, manifest, seed):
            info = filename.lstat()
            self.assertEqual((info.st_uid, info.st_gid, info.st_nlink),
                             (self.uid, self.gid, 1))
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
        token = admin.owner_input(owner.read_bytes())
        identities = Identities()
        identities.load_manifest(json.loads(manifest.read_bytes()))
        self.assertEqual(identities.authenticate(token), 'owner')
        self.assertNotIn(token.encode(), manifest.read_bytes())
        registry = VerifierRegistry(self.state)
        self.assertIsNone(registry.manager)
        self.assertEqual(registry.used, set())
        registry.enroll_manager(identities.manifest())
        self.assertEqual(VerifierRegistry(self.state).manager,
                         identities.manifest()['verifiers'])

    def test_second_initialization_leaves_every_file_unchanged(self):
        self.initialize()
        files = [*self.admin.iterdir(), *self.credentials.iterdir(), *self.state.iterdir()]
        before = [(path.read_bytes(), path.stat().st_ino) for path in files]
        with self.assertRaisesRegex(ValueError, 'bootstrap_not_fresh'):
            self.initialize()
        self.assertEqual(before, [(path.read_bytes(), path.stat().st_ino) for path in files])

    def test_preexisting_registry_blocks_all_publication(self):
        seed = self.state / admin.REGISTRY_FILE
        seed.write_text('existing state')
        with self.assertRaisesRegex(ValueError, 'bootstrap_not_fresh'):
            self.initialize()
        self.assertEqual(seed.read_text(), 'existing state')
        self.assertFalse(list(self.admin.iterdir()))
        self.assertFalse(list(self.credentials.iterdir()))

    def test_runtime_even_empty_blocks_fresh_install(self):
        self.runtime.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, 'service_runtime_present'):
            self.initialize()
        self.assertFalse(list(self.admin.iterdir()))

    def test_unsafe_modes_and_acl_refused(self):
        self.admin.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'unsafe_admin_directory'):
            self.initialize()
        self.admin.chmod(0o700)
        other = 65321 if self.uid != 65321 else 65322
        os.setxattr(self.credentials, ACCESS_ACL, named_user_acl(other, 7, 1))
        with self.assertRaisesRegex(ValueError, 'unsafe_admin_directory'):
            self.initialize()
        self.assertFalse(list(self.admin.iterdir()))

    def test_symlink_directory_refused(self):
        self.credentials.rmdir()
        self.credentials.symlink_to(self.admin, target_is_directory=True)
        with self.assertRaises(OSError):
            self.initialize()
        self.assertFalse(list(self.admin.iterdir()))

    def test_partial_publication_preserves_evidence_and_refuses_retry(self):
        original = admin.publish_new

        def fail_manifest(fd, name, data, uid, gid):
            if name == admin.MANIFEST_FILE:
                raise OSError('fixture write failure')
            return original(fd, name, data, uid, gid)

        with patch.object(admin, 'publish_new', side_effect=fail_manifest):
            with self.assertRaises(OSError):
                self.initialize()
        self.assertTrue((self.admin / admin.OWNER_FILE).is_file())
        self.assertFalse(list(self.credentials.iterdir()))
        self.assertFalse(list(self.state.iterdir()))
        with self.assertRaisesRegex(ValueError, 'bootstrap_not_fresh'):
            self.initialize()

    def test_publish_never_replaces_existing_file_or_symlink(self):
        existing = self.admin / 'existing'
        existing.write_bytes(b'old')
        link = self.admin / 'link'
        link.symlink_to(existing)
        with admin.protected_directory(self.admin, self.uid, self.gid) as fd:
            for name in ('existing', 'link'):
                with self.assertRaises(FileExistsError):
                    admin.publish_new(fd, name, b'new', self.uid, self.gid)
        self.assertEqual(existing.read_bytes(), b'old')
        self.assertTrue(link.is_symlink())
        self.assertEqual(set(p.name for p in self.admin.iterdir()), {'existing', 'link'})

    def test_protected_read_rejects_symlink_and_permissive_file(self):
        self.initialize()
        owner = self.admin / admin.OWNER_FILE
        with admin.protected_directory(self.admin, self.uid, self.gid) as fd:
            self.assertEqual(len(admin.read_protected(fd, admin.OWNER_FILE,
                                                     self.uid, self.gid, 44)), 44)
            owner.chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'unsafe_admin_file'):
                admin.read_protected(fd, admin.OWNER_FILE, self.uid, self.gid, 44)
            (self.admin / 'link').symlink_to(owner)
            with self.assertRaises(OSError):
                admin.read_protected(fd, 'link', self.uid, self.gid, 44)

    def test_nonroot_entrypoint_refuses_before_io(self):
        with patch.object(admin.os, 'geteuid', return_value=65534):
            with patch.object(admin, 'initialize') as initialize:
                with self.assertRaisesRegex(ValueError, 'root_administration_required'):
                    admin.admin_initialize(self.uid, self.gid)
                initialize.assert_not_called()

    def test_admin_readiness_uses_only_fixed_child_and_pipe(self):
        self.initialize()
        owner = (self.admin / admin.OWNER_FILE).read_bytes()
        # Simulate root's protected reads without acquiring root in CI.
        directory = admin.protected_directory
        read = admin.read_protected
        with (patch.object(admin, 'ADMIN', self.admin),
              patch.object(admin, 'CREDENTIALS', self.credentials),
              patch.object(admin, 'require_root'),
              patch.object(admin, 'protect_admin_process'),
              patch.object(admin, 'protected_directory',
                           side_effect=lambda p, u, g: directory(p, self.uid, self.gid)),
              patch.object(admin, 'read_protected',
                           side_effect=lambda fd, n, u, g, limit:
                           read(fd, n, self.uid, self.gid, limit)),
              patch.object(admin.subprocess, 'run',
                           return_value=SimpleNamespace(returncode=0)) as launch):
            release = Path('/opt/loopbridge/releases') / ('a' * 40)
            digest = 'b' * 64
            admin.admin_ready(release, digest, 1234, 1234)
            args, kwargs = launch.call_args
            self.assertEqual(args[0][-2:], ['--action', 'ready-client'])
            self.assertEqual(kwargs['input'], owner)
            self.assertNotIn(owner[:-1].decode(), str(args))
            self.assertNotIn(owner[:-1].decode(), str(kwargs['env']))
            self.assertEqual((kwargs['user'], kwargs['group'], kwargs['extra_groups']),
                             (1234, 1234, []))
            self.assertTrue(kwargs['close_fds'])
            self.assertEqual(kwargs['timeout'], 15)
            launch.return_value = SimpleNamespace(returncode=1)
            with self.assertRaisesRegex(ValueError, 'manager_readiness_failed'):
                admin.admin_ready(release, digest, 1234, 1234)

    @contextmanager
    def manager(self, identities, instances=None):
        self.runtime.mkdir(mode=0o700, exist_ok=True)
        endpoint = self.runtime / 'manager.sock'
        with bound_listener(endpoint) as listener, ThreadPoolExecutor(1) as executor:
            listener.settimeout(3)

            def server():
                peer, _ = listener.accept()
                with closing(peer):
                    handle(peer, self.runtime, identities, instances or {},
                           identities.manifest(), True, set())

            future = executor.submit(server)
            try:
                yield
            finally:
                future.result(timeout=5)

    def test_real_socket_auth_and_empty_list_readiness(self):
        identities = Identities()
        tokens = identities.provision()
        with self.manager(identities):
            admin.manager_readiness(self.runtime, tokens['owner'], self.uid, self.gid)

    def test_real_socket_rejects_incorrect_or_nonowner_bearer(self):
        identities = Identities()
        tokens = identities.provision()
        for token in ('invalid', tokens['observer']):
            with self.manager(identities):
                with self.assertRaises(Fault):
                    admin.manager_readiness(self.runtime, token, self.uid, self.gid)

    def test_manager_with_existing_instance_is_not_fresh_ready(self):
        identities = Identities()
        tokens = identities.provision()
        instance = SimpleNamespace(status=lambda: {'id': 'synthetic'})
        with self.manager(identities, {'synthetic': instance}):
            with self.assertRaisesRegex(ValueError, 'manager_not_empty'):
                admin.manager_readiness(self.runtime, tokens['owner'], self.uid, self.gid)

    def test_invalid_owner_input(self):
        for data in (b'', b'a' * 43, b'a' * 44 + b'\n', b'!' * 43 + b'\n'):
            with self.assertRaisesRegex(ValueError, 'invalid_admin_credential'):
                admin.owner_input(data)


if __name__ == '__main__':
    unittest.main()
