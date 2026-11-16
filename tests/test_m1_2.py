# SPDX-License-Identifier: Apache-2.0
import socket
import time
import unittest
from unittest.mock import Mock, patch

from experiments.m1_1.semantic import Reference, Rejected
from experiments.m1_2.broker import Broker, Fixture
from experiments.m1_2.protocol import Channel, Fault, History, MAX_FRAME, encode, request


class WireTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = socket.socketpair()
        self.addCleanup(self.a.close)
        self.addCleanup(self.b.close)

    def test_fragment_timeout_preserves_partial_frame(self):
        channel = Channel(self.b)
        self.b.settimeout(.01)
        self.a.sendall(b'{"jsonrpc":"2.0",')
        with self.assertRaises(socket.timeout):
            channel.receive()
        self.a.sendall(b'"id":1,"method":"snapshot","params":{}}\n')
        self.assertEqual(request(channel.receive()), (1, 'snapshot', {}))

    def test_multiple_frames_and_eof(self):
        self.a.sendall(encode({'x': 1}) + encode({'x': 2}))
        self.a.shutdown(socket.SHUT_WR)
        channel = Channel(self.b)
        self.assertEqual(channel.receive(), {'x': 1})
        self.assertEqual(channel.receive(), {'x': 2})
        with self.assertRaises(EOFError):
            channel.receive()

    def test_malformed_utf8_and_nonfinite(self):
        for raw in (b'bad\n', b'\xff\n', b'NaN\n'):
            self.a.sendall(raw)
            with self.assertRaises(Fault):
                Channel(self.b).receive()

    def test_oversized_message(self):
        self.a.sendall(b'x' * (MAX_FRAME + 1))
        with self.assertRaisesRegex(Fault, 'frame_limit'):
            Channel(self.b).receive()

    def test_invalid_envelopes(self):
        for value in ([], {}, dict(jsonrpc='2.0', id=True, method='snapshot', params={}),
                      dict(jsonrpc='2.0', id=1, method='invoke7', params=[])):
            with self.subTest(value=value), self.assertRaises(Fault):
                request(value)


class HistoryTests(unittest.TestCase):
    def test_order_gap_and_snapshot_watermark(self):
        h = History('epoch', capacity=2)
        for value in ('7', '77', '777'):
            h.append({'display': value})
        self.assertEqual([e['seq'] for e in h.since('epoch', 1)], [2, 3])
        with self.assertRaisesRegex(Fault, 'gap_snapshot_required'):
            h.since('epoch', 0)
        self.assertEqual(h.since('epoch', h.seq), [])
        self.assertEqual(len(h.items), 2)

    def test_epoch_and_invalid_cursors(self):
        h = History('new')
        with self.assertRaisesRegex(Fault, 'epoch_changed'):
            h.since('old', 0)
        for cursor in (-1, True, '0', 1):
            with self.subTest(cursor=cursor), self.assertRaises(Fault):
                h.since('new', cursor)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Mock()
        self.fixture.read.return_value = {'display': ''}
        self.broker = Broker(self.fixture, 'provisioned-test-only', uid=1000)
        self.state = dict(uid=1000, authorized=False)

    def authenticate(self):
        self.broker.handle(self.state, 'auth', {'credential': 'provisioned-test-only'})

    def test_unenrolled_same_uid_cannot_read_write_or_subscribe(self):
        for method in ('snapshot', 'invoke7', 'events', 'raw.session'):
            with self.subTest(method=method), self.assertRaisesRegex(Fault, 'denied'):
                self.broker.handle(self.state, method, {})
        self.fixture.invoke.assert_not_called()
        self.fixture.reference.assert_not_called()

    def test_uid_and_secret_both_required(self):
        self.state['uid'] = 1001
        with self.assertRaisesRegex(Fault, 'denied'):
            self.authenticate()
        self.state['uid'] = 1000
        for token in ('wrong', '', '\u2603'):
            with self.subTest(token=token), self.assertRaises(Fault):
                self.broker.handle(self.state, 'auth', {'credential': token})
        self.assertFalse(self.state['authorized'])

    def test_reauthentication_failure_revokes_connection(self):
        self.authenticate()
        self.broker.handle(self.state, 'snapshot', {})
        reference = self.state['reference']
        with self.assertRaises(Fault):
            self.broker.handle(self.state, 'auth', {'credential': 'wrong'})
        reference.invalidate.assert_called_once()
        with self.assertRaisesRegex(Fault, 'denied'):
            self.broker.handle(self.state, 'snapshot', {})

    def test_grant_expiry_checked_each_request(self):
        self.authenticate()
        self.broker.deadline = 0
        with self.assertRaisesRegex(Fault, 'denied'):
            self.broker.handle(self.state, 'snapshot', {})
        self.fixture.reference.assert_not_called()

    def test_wrong_or_disconnected_reference_does_not_invoke(self):
        self.authenticate()
        snap = self.broker.handle(self.state, 'snapshot', {})
        with self.assertRaisesRegex(Fault, 'expired_reference'):
            self.broker.handle(self.state, 'invoke7', {'reference': 'other-session'})
        self.broker.invalidate(self.state)
        with self.assertRaisesRegex(Fault, 'expired_reference'):
            self.broker.handle(self.state, 'invoke7', {'reference': snap['reference']})
        self.fixture.invoke.assert_not_called()

    def test_new_connection_requires_snapshot_and_own_reference(self):
        self.authenticate()
        snap = self.broker.handle(self.state, 'snapshot', {})
        other = dict(uid=1000, authorized=True)
        with self.assertRaisesRegex(Fault, 'snapshot_required'):
            self.broker.handle(other, 'events', {'epoch': self.broker.epoch, 'cursor': 0})
        with self.assertRaisesRegex(Fault, 'expired_reference'):
            self.broker.handle(other, 'invoke7', {'reference': snap['reference']})
        self.fixture.invoke.assert_not_called()

    def test_no_raw_adapter_parameters(self):
        self.authenticate()
        for method, params in [('raw.session', {'path': '/run/example'}),
                               ('snapshot', {'pid': 1}), ('invoke7', {'reference': 'x', 'action': 'arbitrary'})]:
            with self.subTest(method=method), self.assertRaises(Fault):
                self.broker.handle(self.state, method, params)
        self.fixture.invoke.assert_not_called()


class DispatchBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture.__new__(Fixture)
        self.fixture.process, self.fixture.pidfd, self.fixture.desktop = Mock(), 12, Mock()
        self.fixture.read = Mock(return_value={'display': ''})
        self.node = Mock()
        self.reference = Reference((), {}, None, None, self.node, (), time.monotonic()+10)

    def test_grant_expired_during_validation_never_calls_action(self):
        with patch('experiments.m1_2.broker.m1.validate'):
            with self.assertRaisesRegex(Rejected, 'grant_expired'):
                self.fixture.invoke(self.reference, lambda: False)
        self.node.queryAction.assert_not_called()
        self.assertFalse(self.reference.valid)

    def test_reference_expires_during_validation_never_calls_action(self):
        def expire(*args):
            self.reference.deadline = 0
        with patch('experiments.m1_2.broker.m1.validate', side_effect=expire):
            with self.assertRaisesRegex(Rejected, 'expired_reference'):
                self.fixture.invoke(self.reference, lambda: True)
        self.node.queryAction.assert_not_called()
        self.assertFalse(self.reference.valid)


if __name__ == '__main__':
    unittest.main()
