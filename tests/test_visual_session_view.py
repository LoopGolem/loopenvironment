# SPDX-License-Identifier: Apache-2.0
"""Client-side pinning, segregated media and deterministic viewer states."""
from contextlib import contextmanager
from pathlib import Path
import os
import socket
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from loopbridge.presentation import FORMAT, FRAME, FRAME_BYTES, HEADER, HEARTBEAT, STRIDE
from loopbridge.presentation_client import LiveConnection
from loopbridge.private_effects import OUTPUT
from loopbridge.protocol import DeadlineChannel, Fault
from loopbridge.view_status import HEARTBEAT_NS, ViewerState, terminal_reason, viewer_state

PIN = dict(session='desktop', privateId='a' * 16, epoch='b' * 32)
META = dict(**PIN, principal='observer', authorization='authorized', capability='desktop.stream',
            input=False, state='available', transport='unix_stream_upgrade_v1', format=FORMAT,
            width=OUTPUT[0], height=OUTPUT[1], stride=STRIDE)
TOKEN = 'x' * 43


class PresentationClientTests(unittest.TestCase):
    @contextmanager
    def server(self, replies):
        with TemporaryDirectory() as root, socket.socket(socket.AF_UNIX) as listener:
            endpoint = Path(root) / 'stream.sock'
            listener.bind(str(endpoint))
            listener.listen()
            listener.settimeout(3)
            methods, errors = [], []

            def serve():
                try:
                    with listener.accept()[0] as peer:
                        channel = DeadlineChannel(peer)
                        for body in replies:
                            if isinstance(body, bytes):
                                peer.sendall(body)
                                continue
                            req = channel.receive(3)
                            methods.append((req['method'], req['params'] if req['method'] != 'auth' else {}))
                            channel.send(dict(jsonrpc='2.0', id=req['id'], version=req['version'], **body))
                except Exception as error:
                    errors.append(type(error).__name__)

            worker = Thread(target=serve, daemon=True)
            worker.start()
            live = LiveConnection(endpoint, TOKEN, PIN['session'], None, PIN['epoch'],
                                  expected_principal='observer', expected_peer_uid=os.getuid())
            try:
                yield live, methods
            finally:
                live.cancel()
                live.peer.close()
                worker.join(4)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])

    def test_describe_then_open_with_validated_pin_and_binary_on_its_own_socket(self):
        frames = bytes(FRAME_BYTES)
        open_row = dict(META, state='opening', stream='c' * 32)
        with self.server([{'result': {'principal': 'observer'}}, {'result': META},
                          {'result': open_row}, HEADER.pack(HEARTBEAT, 0, 100),
                          HEADER.pack(FRAME, 1, 101) + frames]) as (live, methods):
            self.assertEqual(live.connect(), open_row)
            packets = live.packets()
            self.assertEqual(next(packets), (0, 100, None))
            self.assertEqual(next(packets), (1, 101, frames))
            self.assertEqual(methods, [('auth', {}), ('presentation.describe', {'session': 'desktop'}),
                                       ('presentation.open', PIN)])
            self.assertFalse(live.metadata['input'])
            with self.assertRaises(EOFError):
                next(packets)
            live.cancel()
            self.assertIsNone(live.token)

    def test_discover_does_not_authorize_describe(self):
        with self.server([{'result': {'principal': 'observer'}},
                          {'error': {'code': -32001, 'message': 'grant_denied'}}]) as (live, methods):
            with self.assertRaisesRegex(Fault, 'grant_denied'):
                live.connect()
            self.assertEqual([m for m, _ in methods], ['auth', 'presentation.describe'])
            self.assertIsNone(live.channel)

    def test_separate_credential_must_authenticate_the_console_principal(self):
        for principal in ('owner', 'delegate'):
            with self.subTest(principal=principal), self.server(
                    [{'result': {'principal': principal}}]) as (live, methods):
                with self.assertRaisesRegex(Fault, 'presentation_principal_mismatch'):
                    live.connect()
                self.assertEqual(methods, [('auth', {})])

    def test_replacement_does_not_auto_open(self):
        for state in ('available', 'unavailable'):
            with self.subTest(state=state), self.server(
                    [{'result': {'principal': 'observer'}},
                     {'result': dict(META, epoch='d' * 32, state=state)}]) as (live, methods):
                with self.assertRaisesRegex(Fault, 'presentation_identity_mismatch'):
                    live.connect()
                self.assertEqual([m for m, _ in methods], ['auth', 'presentation.describe'])

    def test_open_rechecks_identity_and_no_input(self):
        for extra in (dict(privateId='d' * 16), dict(epoch='e' * 32), dict(input=0), dict(epoch='malformed')):
            with self.subTest(extra=extra), self.server(
                    [{'result': {'principal': 'observer'}}, {'result': META},
                     {'result': dict(META, state='opening', stream='c' * 32) | extra}]) as (live, _):
                if extra.get('input') == 0 or extra.get('epoch') == 'malformed':
                    with self.assertRaisesRegex(ValueError, 'invalid_presentation_response'):
                        live.connect()
                else:
                    with self.assertRaisesRegex(Fault, 'presentation_identity_mismatch'):
                        live.connect()
                self.assertIsNone(live.channel)

    def test_status_requires_the_exact_stream_and_closed_state(self):
        stream = 'c' * 32
        for extra, expected in (
            ({'state': 'closed'}, 'session_ended'),
            ({'state': 'live'}, 'session_ended_or_unreachable'),
            ({'stream': 'd' * 32, 'state': 'closed'}, 'session_ended_or_unreachable'),
            ({'state': 'closed', 'reason': TOKEN}, 'connection_lost'),
        ):
            result = dict(**PIN, stream=stream, principal='observer', reason='session_ended') | extra
            with self.subTest(extra=tuple(extra)), self.server(
                    [{'result': {'principal': 'observer'}}, {'result': result}]) as (live, methods):
                live.metadata = {'stream': stream, 'principal': 'observer'}
                live.identity.update(PIN)
                self.assertEqual(live.reason(), expected)
                self.assertEqual(methods[-1], ('presentation.status', dict(**PIN, stream=stream)))

    def test_cancel_interrupts_an_in_flight_status_request_and_clears_token(self):
        with TemporaryDirectory() as root, socket.socket(socket.AF_UNIX) as listener:
            endpoint = Path(root) / 'status.sock'
            listener.bind(str(endpoint))
            listener.listen()
            live = LiveConnection(endpoint, TOKEN, PIN['session'], PIN['privateId'], PIN['epoch'])
            live.metadata = {'principal': 'observer', 'stream': 'c' * 32}
            self.addCleanup(live.release)
            results = []

            def diagnostic():
                results.append(live.reason())

            worker = Thread(target=diagnostic, daemon=True)
            listener.settimeout(2)
            worker.start()
            with listener.accept()[0] as peer:
                channel = DeadlineChannel(peer)
                auth = channel.receive(1)
                channel.send(dict(jsonrpc='2.0', version=auth['version'], id=auth['id'],
                                  result={'principal': 'observer'}))
                self.assertEqual(channel.receive(1)['method'], 'presentation.status')
                live.cancel()
                peer.settimeout(.5)
                self.assertEqual(peer.recv(1), b'')
                worker.join(.5)
            self.assertFalse(worker.is_alive())
            self.assertIsNone(live.token)
            self.assertIsNone(live.diagnostic_peer)
            self.assertEqual(results, ['session_ended_or_unreachable'])


class ViewerStateTests(unittest.TestCase):
    def state(self, now, **overrides):
        values = dict(connected=10, painted=20, packet=20, change=20, failure=None)
        return viewer_state(now, **(values | overrides))

    def test_connection_first_paint_and_static_output_are_distinct(self):
        self.assertIs(self.state(0, connected=None, painted=None), ViewerState.CONNECTING)
        self.assertIs(self.state(15, painted=None, packet=None), ViewerState.FIRST_FRAME)
        self.assertIs(self.state(20), ViewerState.LIVE)
        self.assertIs(self.state(3_000_000_020, packet=3_000_000_000), ViewerState.STATIC)

    def test_missing_heartbeat_never_counts_as_live_or_healthy(self):
        self.assertIs(self.state(20 + HEARTBEAT_NS), ViewerState.STALLED)
        self.assertIs(self.state(10 + HEARTBEAT_NS, painted=None, packet=None), ViewerState.STALLED)

    def test_terminal_authority_identity_and_disconnect_states(self):
        for reason, expected in (
            ('grant_denied', ViewerState.DENIED), ('revoked', ViewerState.REVOKED),
            ('grant_expired', ViewerState.REVOKED), ('session_ended', ViewerState.ENDED),
            ('presentation_identity_mismatch', ViewerState.REPLACED),
            ('session_ended_or_unreachable', ViewerState.DISCONNECTED),
            ('heartbeat_timeout', ViewerState.STALLED),
        ):
            with self.subTest(reason=reason):
                self.assertIs(self.state(20, failure=reason), expected)
        self.assertEqual(terminal_reason(TOKEN), 'connection_lost')
