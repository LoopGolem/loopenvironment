# SPDX-License-Identifier: Apache-2.0
"""D4.2A ACL and transport tests with unprivileged Unix sockets."""
from array import array
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import os
from pathlib import Path
import socket
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from loopbridge.service_ingress import (ACCESS_ACL, DEFAULT_ACL, CrossUIDIngress, PeerAdmission,
                                       bound_listener, named_user_acl, peer_uid, read_acl)
from loopbridge.service_relay import BUFFER_BYTES, MAX_CONNECTIONS, SessionRelay


class RelayFixture(unittest.TestCase):
    def setUp(self):
        self.base = Path(self.enterContext(TemporaryDirectory(prefix='d4-')))
        self.private = self.base / 'private'
        self.public = self.base / 'ingress'
        for directory in (self.private, self.public):
            directory.mkdir(mode=0o700)
        self.front = self.public / 'session.sock'
        self.back = self.private / 'relay.sock'
        self.uid = os.geteuid()
        self.client_uid = 65432 if self.uid != 65432 else 65431
        self.policy = PeerAdmission(self.uid, frozenset((self.client_uid,)))
        self.ingress = CrossUIDIngress(self.public, self.private, self.policy)
        os.setxattr(self.public, ACCESS_ACL, named_user_acl(self.client_uid, 7, 1))

    def client(self):
        peer = self.enterContext(closing(socket.socket(socket.AF_UNIX)))
        peer.settimeout(3)
        peer.connect(str(self.front))
        return peer

    def simulated_peer_uid(self, peer):
        # Keep SO_PEERCRED real on the service side of the outbound connection.
        return self.client_uid if peer.getsockname() == str(self.front) else peer_uid(peer)

    def relay(self, *, admitted=True):
        backend = self.enterContext(bound_listener(self.back))
        backend.settimeout(2)
        if admitted:
            self.enterContext(patch('loopbridge.service_relay.peer_uid', side_effect=self.simulated_peer_uid))
        relay = SessionRelay(self.ingress, self.front, self.back)
        return backend, relay

    @staticmethod
    def receive_all(sock):
        output = bytearray()
        while data := sock.recv(64 * 1024):
            output.extend(data)
        return bytes(output)

    @staticmethod
    def closed(sock):
        try:
            return sock.recv(1) == b''
        except ConnectionResetError:
            return True


class CrossUIDACLTests(RelayFixture):
    def test_explicit_and_distinct_nonroot_uids(self):
        for service_uid, allowed in ((self.uid, (self.uid,)), (self.uid, (0,)),
                                     (self.uid + 1, (self.client_uid,)),
                                     (self.uid, (self.client_uid, self.client_uid + 1))):
            with self.subTest(service_uid=service_uid, allowed=allowed):
                with self.assertRaisesRegex(ValueError, 'invalid_cross_uid_ingress'):
                    CrossUIDIngress(self.public, self.private,
                                    PeerAdmission(service_uid, frozenset(allowed)))
        with self.assertRaises(ValueError):
            CrossUIDIngress(self.private, self.private, self.policy)

    def test_acl_and_mode_are_verified_before_listen(self):
        original = socket.socket.listen

        def inspect(listener, backlog):
            self.assertEqual(read_acl(self.front), named_user_acl(self.client_uid, 6, 2))
            self.assertEqual(stat.S_IMODE(self.front.lstat().st_mode), 0o620)
            self.assertEqual(self.front.lstat().st_uid, self.uid)
            original(listener, backlog)

        with patch.object(socket.socket, 'listen', inspect):
            with self.ingress.listen(self.front):
                self.assertTrue(self.front.is_socket())
        self.assertFalse(self.front.exists())

    def test_ordinary_mode_is_not_a_named_acl(self):
        os.removexattr(self.public, ACCESS_ACL)
        self.public.chmod(0o710)
        with self.assertRaisesRegex(ValueError, 'unsafe_cross_uid_ingress_directory'):
            with self.ingress.listen(self.front):
                self.fail('published with ordinary group mode')
        self.assertFalse(self.front.exists())

    def test_wrong_named_uid_default_acl_and_owner_are_refused(self):
        expected = named_user_acl(self.client_uid, 7, 1)
        os.setxattr(self.public, ACCESS_ACL, named_user_acl(self.client_uid + 2, 7, 1))
        with self.assertRaises(ValueError):
            self.ingress.validate()
        os.setxattr(self.public, ACCESS_ACL, expected)
        os.setxattr(self.public, DEFAULT_ACL, expected)
        with self.assertRaises(ValueError):
            self.ingress.validate()
        os.removexattr(self.public, DEFAULT_ACL)
        with patch('loopbridge.service_ingress.os.getegid', return_value=os.getegid() + 1):
            with self.assertRaises(ValueError):
                self.ingress.validate()

    def test_failed_acl_write_does_not_listen_or_leave_endpoint(self):
        with (patch('loopbridge.service_ingress.os.setxattr', side_effect=PermissionError),
              patch.object(socket.socket, 'listen') as listen):
            with self.assertRaises(PermissionError):
                with self.ingress.listen(self.front):
                    self.fail('published without socket ACL')
            listen.assert_not_called()
        self.assertFalse(self.front.exists())

    def test_preserves_preexisting_and_replaced_paths(self):
        with closing(socket.socket(socket.AF_UNIX)) as other:
            other.bind(str(self.front))
            inode = self.front.stat().st_ino
            with self.assertRaises(OSError):
                with self.ingress.listen(self.front):
                    self.fail('displaced existing socket')
            self.assertEqual(self.front.stat().st_ino, inode)
        self.front.unlink()
        with self.ingress.listen(self.front):
            self.front.unlink()
            self.front.write_text('replacement')
        self.assertEqual(self.front.read_text(), 'replacement')


class SessionRelayTests(RelayFixture):
    def test_real_unlisted_peer_is_refused_before_private_connect(self):
        backend, relay = self.relay(admitted=False)
        backend.settimeout(.2)
        with relay.serve():
            self.assertTrue(self.closed(self.client()))
            with self.assertRaises(TimeoutError):
                backend.accept()

    def test_bidirectional_half_close_and_binary_transport(self):
        backend, relay = self.relay()
        with relay.serve():
            client = self.client()
            private, _ = backend.accept()
            with private:
                private.settimeout(3)
                # A pathname in the client payload remains opaque to the relay.
                request = os.fsencode(self.private / 'other.sock') + b'\x00\xff'
                client.sendall(request)
                client.shutdown(socket.SHUT_WR)
                self.assertEqual(self.receive_all(private), request)
                block = bytes(range(256)) * 16384
                # Write in parallel so the fixture exercises bounded buffering.
                with ThreadPoolExecutor(1) as executor:
                    def respond():
                        private.sendall(block)
                        private.shutdown(socket.SHUT_WR)

                    sender = executor.submit(respond)
                    self.assertEqual(self.receive_all(client), block)
                    sender.result()

    def test_ancillary_descriptors_are_discarded_in_both_directions(self):
        backend, relay = self.relay()
        with relay.serve(), TemporaryDirectory(dir=self.base) as folder:
            client = self.client()
            private, _ = backend.accept()
            with private, (Path(folder) / 'synthetic').open('wb') as fixture:
                private.settimeout(2)
                rights = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array('i', [fixture.fileno()]))]
                for sender, receiver in ((client, private), (private, client)):
                    sender.sendmsg([b'x'], rights)
                    data, ancillary, flags, _ = receiver.recvmsg(1, socket.CMSG_SPACE(4))
                    self.assertEqual((data, ancillary, flags), (b'x', [], 0))

    def test_backpressure_caps_read_ahead_and_stop_closes_both_sides(self):
        backend, relay = self.relay()
        with relay.serve():
            client = self.client()
            private, _ = backend.accept()
            self.addCleanup(private.close)
            private.setblocking(False)
            total = 0
            for _ in range(32):
                try:
                    total += private.send(b'x' * BUFFER_BYTES)
                except BlockingIOError:
                    break
            self.assertLess(total, 16 * BUFFER_BYTES)
            self.assertGreater(total, 0)
        private.settimeout(1)
        self.assertTrue(self.closed(private))
        client.settimeout(1)
        self.assertLessEqual(len(self.receive_all(client)), 2 * BUFFER_BYTES)

    def test_connection_slot_limit(self):
        backend, relay = self.relay()
        with relay.serve():
            for _ in range(MAX_CONNECTIONS):
                self.client()
                private, _ = backend.accept()
                self.addCleanup(private.close)
            self.assertTrue(self.closed(self.client()))

    def test_idle_transport_times_out(self):
        backend, relay = self.relay()
        with patch('loopbridge.service_relay.IDLE_TIMEOUT', .2), relay.serve():
            client = self.client()
            private, _ = backend.accept()
            with private:
                private.settimeout(1)
                self.assertTrue(self.closed(client))
                self.assertTrue(self.closed(private))

    def test_replaced_private_socket_is_never_dialed(self):
        backend, relay = self.relay()
        with relay.serve():
            self.back.unlink()
            with bound_listener(self.back) as replacement:
                replacement.settimeout(.2)
                self.assertTrue(self.closed(self.client()))
                with self.assertRaises(TimeoutError):
                    replacement.accept()

    def test_invalid_targets_refused_at_registration(self):
        with bound_listener(self.front):
            with self.assertRaises(ValueError):
                SessionRelay(self.ingress, self.front, self.front)
        self.back.symlink_to(self.private / 'missing.sock')
        with self.assertRaises(FileNotFoundError):
            SessionRelay(self.ingress, self.front, self.back)
