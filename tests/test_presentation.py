# SPDX-License-Identifier: Apache-2.0
"""Authority and lifecycle regressions for a pinned presentation."""
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest

from loopbridge.broker import Connection
from loopbridge.desktop_broker import DesktopBroker
from loopbridge.identity import Identities
from loopbridge.presentation import CAPABILITY, Presentation
from loopbridge.protocol import Fault
from loopbridge.service import Journal


class PresentationAuthorityTests(unittest.TestCase):
    def setUp(self):
        root = self.enterContext(TemporaryDirectory())
        self.now = 10
        self.backend = Presentation('a' * 16, Path('/usr/bin/true'))
        self.broker = DesktopBroker(Identities(), {'desktop': object()}, os.getuid(),
                                    Journal(Path(root)), clock=lambda: self.now,
                                    catalog=('editor',), presentation=self.backend)
        self.session = self.broker.sessions['desktop']
        self.owner = Connection(os.getuid(), principal='owner')
        self.observer = Connection(os.getuid(), principal='observer')
        self.identity = dict(session='desktop', privateId=self.backend.private_id, epoch=self.session.epoch)

    def call(self, peer, method, **params):
        return self.broker.handle(peer, method, dict(session='desktop', **params))

    def grant(self, capability, target='*', ttl=10):
        return self.call(self.owner, 'delegate', principal='observer', capability=capability,
                         target=target, ttl=ttl)['grant']

    def open_stream(self, peer=None, **pin):
        return self.broker.handle(peer or self.observer, 'presentation.open', {**self.identity, **pin})

    def test_stream_permission_is_independent_and_session_wide(self):
        for capability in ('session.discover', 'desktop.observe', 'desktop.capture'):
            self.grant(capability)
        with self.assertRaisesRegex(Fault, 'grant_denied'):
            self.open_stream()
        with self.assertRaisesRegex(Fault, 'invalid_scope'):
            self.grant(CAPABILITY, 'app:editor')
        self.grant(CAPABILITY)
        self.assertEqual(self.open_stream()['state'], 'opening')
        with self.assertRaisesRegex(Fault, 'grant_denied'):
            self.call(self.observer, 'acquire', ttl=2)

    def test_identity_and_status_are_bound_to_origin_and_principal(self):
        self.grant(CAPABILITY)
        with self.assertRaisesRegex(Fault, 'presentation_identity_mismatch'):
            self.open_stream(epoch='old')
        with self.assertRaisesRegex(Fault, 'presentation_identity_mismatch'):
            self.open_stream(privateId='b' * 16)
        row = self.open_stream()
        for principal in ('owner', 'delegate'):
            with self.assertRaisesRegex(Fault, 'presentation_unavailable'):
                self.broker.handle(Connection(os.getuid(), principal=principal), 'presentation.status',
                                   dict(**self.identity, stream=row['stream']))

    def test_revoke_closes_matching_peer_without_touching_controller(self):
        grant = self.grant(CAPABILITY)
        lease = self.call(self.owner, 'acquire', ttl=10)
        row = self.open_stream()
        stream = self.backend.streams[row['stream']]
        source, sink = socket.socketpair()
        with source, sink:
            stream.peer = source
            self.call(self.owner, 'revoke', grant=grant)
            sink.settimeout(.5)
            self.assertEqual(sink.recv(1), b'')
        self.assertEqual(self.session.lease.id, lease['id'])
        self.assertEqual(self.session.generation, lease['generation'])
        with self.assertRaisesRegex(Fault, 'grant_denied'):
            self.open_stream()
        status = self.broker.handle(self.observer, 'presentation.status',
                                    dict(**self.identity, stream=row['stream']))
        self.assertEqual((status['state'], status['authorization'], status['reason']),
                         ('closed', 'revoked', 'revoked'))

    def test_disconnect_and_expiry_free_bounded_slots(self):
        self.grant(CAPABILITY)
        first = self.backend.streams[self.open_stream()['stream']]
        other = Connection(os.getuid(), principal='observer')
        second = self.backend.streams[self.open_stream(other)['stream']]
        with self.assertRaisesRegex(Fault, 'presentation_limit'):
            self.open_stream()
        self.broker.disconnect(other)
        self.assertEqual(second.reason, 'viewer_disconnected')
        self.open_stream()
        self.now += 11
        with self.session.lock:
            self.assertFalse(self.backend.active(first))
        self.assertEqual(first.reason, 'grant_expired')
