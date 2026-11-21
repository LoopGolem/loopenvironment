# SPDX-License-Identifier: Apache-2.0
"""D3 unprivileged lifecycle tests against real local Unix sockets."""
import os
from pathlib import Path
import socket
import stat
import tempfile
import unittest

from loopbridge.authority import TARGET
from loopbridge.identity import Identities
from loopbridge.protocol import Fault, RPC
from loopbridge.service import serve
from loopbridge.service_ingress import IngressLayout, PeerAdmission


class ManagedIngressLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lb-d3-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.private_root = self.base / 'private'
        self.ingress_dir = self.base / 'ingress'
        self.ingress_dir.mkdir(mode=0o700)
        self.layout = IngressLayout(self.ingress_dir / 'control.sock', self.private_root)
        self.policy = PeerAdmission.local_only(os.getuid())
        self.identities = Identities()
        self.tokens = self.identities.provision()

    def service(self, *, identities=None, policy=None, layout=None):
        return serve(
            self.private_root, identities or self.identities, 'fixture',
            ingress_layout=layout or self.layout,
            ingress_policy=policy or self.policy,
        )

    @staticmethod
    def rpc(endpoint):
        peer = socket.socket(socket.AF_UNIX)
        peer.settimeout(3)
        try:
            peer.connect(str(endpoint))
            return peer, RPC(peer)
        except BaseException:
            peer.close()
            raise

    def test_authorized_operation_and_cleanup_without_legacy_socket(self):
        endpoint = self.layout.public_socket
        with self.service() as selected:
            self.assertEqual(selected, endpoint)
            info = selected.lstat()
            self.assertTrue(stat.S_ISSOCK(info.st_mode))
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
            self.assertEqual(info.st_uid, os.getuid())
            self.assertFalse((self.private_root / 'socket/control.sock').exists())

            owner_socket, owner = self.rpc(selected)
            observer_socket, observer = self.rpc(selected)
            try:
                self.assertEqual(owner.call('auth', credential=self.tokens['owner'])
                                 ['principal'], 'owner')
                self.assertEqual(observer.call('auth', credential=self.tokens['observer'])
                                 ['principal'], 'observer')
                with self.assertRaisesRegex(Fault, '^grant_denied$'):
                    observer.call('discover')
                owner.call('delegate', session='calculator', principal='observer',
                           capability='session.discover', target=TARGET, ttl=60)
                self.assertEqual(observer.call('discover')['sessions'], ['calculator'])
            finally:
                observer_socket.close()
                owner_socket.close()
        self.assertFalse(endpoint.exists())
        self.assertTrue(self.private_root.exists())
        self.assertTrue(self.ingress_dir.exists())

    def test_unauthenticated_and_unlisted_kernel_peer_are_denied(self):
        with self.service(policy=PeerAdmission(os.getuid(), frozenset({os.getuid() + 1000}))) as endpoint:
            sock, peer = self.rpc(endpoint)
            try:
                with self.assertRaisesRegex(Fault, '^denied$'):
                    peer.call('auth', credential=self.tokens['owner'])
            finally:
                sock.close()

        with self.service() as endpoint:
            sock, peer = self.rpc(endpoint)
            try:
                with self.assertRaisesRegex(Fault, '^denied$'):
                    peer.call('discover')
                with self.assertRaisesRegex(Fault, '^denied$'):
                    peer.call('auth', credential='incorrect')
            finally:
                sock.close()

    def test_conflicting_live_endpoint_is_not_deleted(self):
        endpoint = self.layout.public_socket
        with socket.socket(socket.AF_UNIX) as incumbent:
            incumbent.bind(str(endpoint))
            try:
                with self.assertRaises(OSError):
                    with self.service():
                        self.fail('replaced existing listener')
                self.assertTrue(endpoint.is_socket())
                self.assertFalse((self.private_root / 'socket/control.sock').exists())
            finally:
                endpoint.unlink()

    def test_competing_service_preserves_original_endpoint_and_authority(self):
        with self.service() as endpoint:
            original = endpoint.lstat().st_ino
            with self.assertRaises(BlockingIOError):
                with self.service():
                    self.fail('second service acquired same private root')
            self.assertEqual(endpoint.lstat().st_ino, original)
            sock, peer = self.rpc(endpoint)
            try:
                self.assertEqual(peer.call('auth', credential=self.tokens['owner'])
                                 ['principal'], 'owner')
            finally:
                sock.close()

    def test_unsafe_or_missing_ingress_parent_fails_without_fallback(self):
        endpoint = self.layout.public_socket
        self.ingress_dir.chmod(0o755)
        try:
            with self.assertRaisesRegex(ValueError, '^unsafe_ingress_directory$'):
                with self.service():
                    self.fail('started on permissive parent')
        finally:
            self.ingress_dir.chmod(0o700)
        self.assertFalse(endpoint.exists())
        self.assertFalse((self.private_root / 'socket/control.sock').exists())

        missing = IngressLayout(self.base / 'missing/control.sock', self.private_root)
        with self.assertRaises(FileNotFoundError):
            with self.service(layout=missing):
                self.fail('auto-created public parent')
        self.assertFalse(missing.public_socket.parent.exists())

    def test_symlink_parent_is_rejected(self):
        target = self.base / 'safe-directory'
        target.mkdir(mode=0o700)
        self.ingress_dir.rmdir()
        self.ingress_dir.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, '^unsafe_ingress_directory$'):
            with self.service():
                self.fail('followed symlink parent')
        self.assertFalse((target / 'control.sock').exists())

    def test_legacy_endpoint_blocks_explicit_ingress(self):
        self.private_root.mkdir(mode=0o700)
        legacy_dir = self.private_root / 'socket'
        legacy_dir.mkdir(mode=0o700)
        legacy = legacy_dir / 'control.sock'
        legacy.write_bytes(b'legacy marker')
        with self.assertRaisesRegex(RuntimeError, '^legacy_endpoint_present$'):
            with self.service():
                self.fail('silently started two front doors')
        self.assertEqual(legacy.read_bytes(), b'legacy marker')
        self.assertFalse(self.layout.public_socket.exists())

    def test_incomplete_and_mismatched_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '^incomplete_ingress_configuration$'):
            with serve(self.private_root, self.identities, 'fixture', ingress_layout=self.layout):
                self.fail('started with missing policy')
        with self.assertRaisesRegex(ValueError, '^incomplete_ingress_configuration$'):
            with serve(self.private_root, self.identities, 'fixture', ingress_policy=self.policy):
                self.fail('started with missing layout')
        with self.assertRaisesRegex(ValueError, '^invalid_ingress_configuration$'):
            with self.service(policy=PeerAdmission.local_only(os.getuid() + 1)):
                self.fail('started with mismatched service UID')
        with self.assertRaisesRegex(ValueError, '^invalid_ingress_configuration$'):
            with self.service(layout=IngressLayout(self.layout.public_socket, self.base / 'other')):
                self.fail('started with mismatched private root')
        self.assertFalse(self.private_root.exists())
        self.assertFalse(self.layout.public_socket.exists())

    def test_restart_changes_credentials_without_deleting_persistent_state(self):
        marker = self.private_root / 'persist-me.txt'
        with self.service() as endpoint:
            marker.write_text('durable')
            sock, peer = self.rpc(endpoint)
            try:
                self.assertEqual(peer.call('auth', credential=self.tokens['owner'])
                                 ['principal'], 'owner')
            finally:
                sock.close()
        replacement = Identities()
        replacement_tokens = replacement.provision()
        with self.service(identities=replacement) as endpoint:
            self.assertEqual(marker.read_text(), 'durable')
            old_sock, old_client = self.rpc(endpoint)
            fresh_sock, fresh_client = self.rpc(endpoint)
            try:
                with self.assertRaisesRegex(Fault, '^denied$'):
                    old_client.call('auth', credential=self.tokens['owner'])
                self.assertEqual(fresh_client.call('auth', credential=replacement_tokens['owner'])
                                 ['principal'], 'owner')
            finally:
                old_sock.close()
                fresh_sock.close()
        self.assertEqual(marker.read_text(), 'durable')
        self.assertFalse(self.layout.public_socket.exists())

    def test_shutdown_preserves_replacement_file_at_socket_path(self):
        with self.service() as endpoint:
            endpoint.unlink()
            endpoint.write_text('replacement marker')
        self.assertEqual(self.layout.public_socket.read_text(), 'replacement marker')

    def test_unchanged_legacy_service_still_starts_separately(self):
        with serve(self.private_root, self.identities, 'fixture') as endpoint:
            self.assertEqual(endpoint, self.private_root / 'socket/control.sock')
            self.assertFalse(self.layout.public_socket.exists())
            sock, peer = self.rpc(endpoint)
            try:
                self.assertEqual(peer.call('auth', credential=self.tokens['owner'])
                                 ['principal'], 'owner')
            finally:
                sock.close()
        self.assertFalse(endpoint.exists())


if __name__ == '__main__':
    unittest.main()
