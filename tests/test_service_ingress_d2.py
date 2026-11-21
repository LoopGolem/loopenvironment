# SPDX-License-Identifier: Apache-2.0
"""Unprivileged D2 tests for OS-peer admission vs logical Bridge authority."""
import os
from pathlib import Path
import socket
import threading
import tempfile
import unittest

from loopbridge.adapter import Fixture
from loopbridge.broker import Broker, Connection
from loopbridge.identity import Identities
from loopbridge.protocol import Fault, RPC
from loopbridge.service import Journal
from loopbridge.service_ingress import IngressLayout, PeerAdmission


class IngressContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='lb-ingress-')
        self.addCleanup(self.tmp.cleanup)
        self.service_uid = os.getuid()
        self.operator_uid = self.service_uid + 1000
        self.unlisted_uid = self.service_uid + 2000
        self.identities = Identities()
        self.tokens = self.identities.provision()

    def make_broker(self, policy=None):
        return Broker(self.identities, {'calculator': Fixture()}, self.service_uid,
                      Journal(Path(self.tmp.name)), ingress_policy=policy)

    def test_default_still_admits_only_service_uid(self):
        broker = self.make_broker()
        local = Connection(self.service_uid)
        self.assertEqual(broker.handle(local, 'auth', {'credential': self.tokens['owner']})
                         ['principal'], 'owner')
        for uid in (self.operator_uid, self.unlisted_uid):
            with self.subTest(uid=uid):
                with self.assertRaisesRegex(Fault, '^denied$'):
                    broker.handle(Connection(uid), 'auth', {'credential': self.tokens['owner']})

    def test_explicit_peer_uid_needs_bearer_authentication(self):
        policy = PeerAdmission(self.service_uid, frozenset({self.operator_uid}))
        broker = self.make_broker(policy)
        peer = Connection(self.operator_uid)
        with self.assertRaisesRegex(Fault, '^denied$'):
            broker.handle(peer, 'discover', {})
        with self.assertRaisesRegex(Fault, '^denied$'):
            broker.handle(peer, 'auth', {'credential': 'incorrect'})
        self.assertIsNone(peer.principal)
        self.assertEqual(broker.handle(peer, 'auth', {'credential': self.tokens['observer']})
                         ['principal'], 'observer')
        # A valid OS peer and authenticated observer still need grants.
        with self.assertRaisesRegex(Fault, '^grant_denied$'):
            broker.handle(peer, 'discover', {})

    def test_unlisted_uid_with_valid_owner_token_is_denied(self):
        policy = PeerAdmission(self.service_uid, frozenset({self.operator_uid}))
        broker = self.make_broker(policy)
        peer = Connection(self.unlisted_uid)
        with self.assertRaisesRegex(Fault, '^denied$'):
            broker.handle(peer, 'auth', {'credential': self.tokens['owner']})
        # Even a forged in-memory principal label cannot skip OS admission.
        peer.principal = 'owner'
        with self.assertRaisesRegex(Fault, '^denied$'):
            broker.handle(peer, 'discover', {})

    def test_explicit_policy_does_not_implicitly_admit_service_uid(self):
        policy = PeerAdmission(self.service_uid, frozenset({self.operator_uid}))
        broker = self.make_broker(policy)
        with self.assertRaisesRegex(Fault, '^denied$'):
            broker.handle(Connection(self.service_uid), 'auth',
                          {'credential': self.tokens['owner']})
        self.assertTrue(policy.permits(self.operator_uid))
        self.assertFalse(policy.permits(self.service_uid))

    def test_failed_reauthentication_removes_previous_authority(self):
        policy = PeerAdmission(self.service_uid, frozenset({self.operator_uid}))
        broker = self.make_broker(policy)
        peer = Connection(self.operator_uid)
        broker.handle(peer, 'auth', {'credential': self.tokens['owner']})
        self.assertEqual(peer.principal, 'owner')
        with self.assertRaisesRegex(Fault, '^denied$'):
            broker.handle(peer, 'auth', {'credential': 'bad'})
        self.assertIsNone(peer.principal)
        with self.assertRaisesRegex(Fault, '^denied$'):
            broker.handle(peer, 'discover', {})

    def test_reject_unsafe_peer_uid_rosters(self):
        invalid = (
            (True, frozenset({0})),
            (-1, frozenset({0})),
            (1, frozenset()),
            (1, {1}),
            (1, frozenset({False})),
            (1, frozenset({-3})),
            (1, frozenset({'1000'})),
        )
        for service_uid, uids in invalid:
            with self.subTest(service_uid=service_uid, uids=uids):
                with self.assertRaisesRegex(ValueError, '^invalid_ingress_peer_policy$'):
                    PeerAdmission(service_uid, uids)

    def test_broker_rejects_policy_for_a_different_service_uid(self):
        wrong = PeerAdmission(self.service_uid + 1, frozenset({self.operator_uid}))
        with self.assertRaisesRegex(ValueError, '^invalid_ingress_peer_policy$'):
            self.make_broker(wrong)
        with self.assertRaisesRegex(ValueError, '^invalid_ingress_peer_policy$'):
            self.make_broker(object())

    def test_peer_uid_validation_has_no_boolean_or_string_shortcuts(self):
        policy = PeerAdmission(self.service_uid, frozenset({self.operator_uid}))
        self.assertFalse(policy.permits(str(self.operator_uid)))
        self.assertFalse(policy.permits(True))
        self.assertFalse(policy.permits(None))

    def test_disjoint_absolute_ingress_paths_are_accepted(self):
        layout = IngressLayout(
            Path('/run/loopbridge-ingress/control.sock'),
            Path('/var/lib/loopbridge/private'))
        self.assertEqual(layout.public_socket.name, 'control.sock')

    def test_ingress_socket_must_not_reside_under_private_root(self):
        for public in (
            Path('/var/lib/loopbridge/private/control.sock'),
            Path('/var/lib/loopbridge/private/socket/control.sock'),
            Path('/var/lib/loopbridge/private'),
        ):
            with self.subTest(public=public):
                with self.assertRaisesRegex(ValueError, '^invalid_ingress_layout$'):
                    IngressLayout(public, Path('/var/lib/loopbridge/private'))

    def test_real_unix_socket_peer_uid_follows_kernel_admission(self):
        # Same-user socketpair verifies SO_PEERCRED reaches the broker; the
        # policy deliberately admits a different synthetic UID only.
        policy = PeerAdmission(self.service_uid, frozenset({self.operator_uid}))
        broker = self.make_broker(policy)
        client, server = socket.socketpair()
        with client, server:
            worker = threading.Thread(target=broker.serve_connection, args=(server,))
            worker.start()
            with self.assertRaisesRegex(Fault, '^denied$'):
                RPC(client).call('auth', credential=self.tokens['owner'])
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())

    def test_ingress_paths_reject_relative_and_traversal_forms(self):
        candidates = (
            (Path('relative/control.sock'), Path('/var/lib/loopbridge/private')),
            (Path('/run/service/../control.sock'), Path('/var/lib/loopbridge/private')),
            (Path('/run/ingress/control.sock'), Path('../private')),
            (Path('/run/ingress/control.sock'), Path('/')),
        )
        for public, private in candidates:
            with self.subTest(public=public, private=private):
                with self.assertRaisesRegex(ValueError, '^invalid_ingress_layout$'):
                    IngressLayout(public, private)


if __name__ == '__main__':
    unittest.main()
