# SPDX-License-Identifier: Apache-2.0
"""Typed commands, bounded local transport, and a real broker fixture."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import Mock, patch

from loopbridge.identity import Identities
from loopbridge.presentation import FORMAT, STRIDE
from loopbridge.private_effects import OUTPUT
from loopbridge.protocol import DeadlineChannel, Fault, RPC
from loopbridge.service import SESSION, serve
from loopshell.bridge import BridgeClient, SessionSelection
from loopshell.commands import Action, Command, MAX_INPUT, parse
from loopshell.console import ERROR_TEXT, dispatch, history_entry
from loopshell.errors import Error, ShellError

TOKEN = 'x' * 43


class ShellTests(unittest.TestCase):
    def assert_error(self, code, call, *args):
        with self.assertRaises(ShellError) as caught:
            call(*args)
        self.assertIs(caught.exception.error, code)
        self.assertEqual(str(caught.exception), code.name)


class CommandTests(ShellTests):
    def test_typed_grammar(self):
        for line, expected in (
            ('help', Command(Action.HELP)), ('clear', Command(Action.CLEAR)),
            ('exit', Command(Action.EXIT)), (' sessions\tlist ', Command(Action.LIST)),
            ('session status desktop', Command(Action.STATUS, 'desktop')),
            ('session observe desktop', Command(Action.OBSERVE, 'desktop')),
            ('session activity desktop', Command(Action.ACTIVITY, 'desktop')),
            ('session combined desktop', Command(Action.COMBINED, 'desktop')), ('\t ', None),
        ):
            with self.subTest(line=line):
                self.assertEqual(parse(line), expected)

    def test_invalid_unknown_and_unavailable_commands(self):
        for line, reason in (
            ('help extra', Error.INVALID_COMMAND), ('session status', Error.INVALID_COMMAND),
            ('session status a b', Error.INVALID_COMMAND), ('session status ../a', Error.INVALID_COMMAND),
            ('session status "a"', Error.INVALID_COMMAND), ('session status é', Error.INVALID_COMMAND),
            ('sessions list\nexit', Error.INVALID_COMMAND), ('help\x00', Error.INVALID_COMMAND),
            ('unexpected', Error.UNKNOWN_COMMAND), ('system status', Error.UNAVAILABLE),
            ('agent list', Error.UNAVAILABLE), ('mission create foo', Error.UNAVAILABLE),
            ('session observe', Error.INVALID_COMMAND), ('session activity desktop extra', Error.INVALID_COMMAND),
            ('session activity ../desktop', Error.INVALID_COMMAND), ('acquire desktop', Error.UNAVAILABLE),
            ('session combined', Error.INVALID_COMMAND), ('session combined desktop | id', Error.INVALID_COMMAND),
        ):
            with self.subTest(line=line):
                self.assert_error(reason, parse, line)

    def test_limits_before_parsing(self):
        self.assertEqual(parse('help'.ljust(MAX_INPUT)), Command(Action.HELP))
        self.assert_error(Error.INPUT_LIMIT, parse, 'help'.ljust(MAX_INPUT + 1))
        self.assert_error(Error.INVALID_COMMAND, parse, 'session status ' + TOKEN)

    def test_shell_text_never_reaches_a_process_or_arbitrary_rpc(self):
        client = Mock(spec=BridgeClient)
        with patch('os.system') as system, patch('subprocess.Popen') as spawn:
            for line in ('/bin/sh', 'ls $(id)', 'help; id', 'sessions list | id',
                         'session status desktop;whoami', 'session combined desktop;whoami', 'eval __import__("os")',
                         'rpc acquire', 'control acquire desktop'):
                with self.subTest(line=line), self.assertRaises(ShellError):
                    dispatch(parse(line), client)
            system.assert_not_called()
            spawn.assert_not_called()
        self.assertEqual(client.mock_calls, [])

    def test_history_uses_static_command_name_and_errors(self):
        command = parse('session status sample-id')
        self.assertNotIn('sample-id', history_entry(command, ERROR_TEXT[Error.PERMISSION]))
        self.assertNotIn(TOKEN, history_entry(None, ERROR_TEXT[Error.AUTHENTICATION]))


class TransportTests(ShellTests):
    @contextmanager
    def wire(self, *replies, expected_uid=None):
        with TemporaryDirectory() as folder, socket.socket(socket.AF_UNIX) as listener:
            endpoint = Path(folder) / 'bridge.sock'
            listener.bind(str(endpoint))
            listener.listen()
            listener.settimeout(2)
            received, errors = [], []

            def peer_loop():
                try:
                    peer, _ = listener.accept()
                    with peer:
                        channel = DeadlineChannel(peer)
                        for body in replies:
                            try:
                                request = channel.receive(2)
                            except EOFError:
                                break
                            received.append(request)
                            if body is None:
                                break
                            if isinstance(body, bytes):
                                peer.sendall(body)
                            else:
                                channel.send(dict(jsonrpc='2.0', id=request['id'],
                                                  version=request['version'], **body))
                except Exception as error:
                    errors.append(error)

            worker = Thread(target=peer_loop, daemon=True)
            worker.start()
            client = BridgeClient(endpoint, expected_uid)
            try:
                yield client, received
            finally:
                client.close()
                worker.join(3)
                self.assertFalse(worker.is_alive())
                self.assertFalse(errors)

    def test_explicit_auth_and_two_typed_rpcs(self):
        with self.wire({'result': {'principal': 'observer'}},
                       {'result': {'sessions': ['desktop']}},
                       {'result': {'session': 'desktop', 'phase': 'idle', 'revision': 7,
                                   'state': {'untrusted': TOKEN}}}) as (client, calls):
            self.assertIsNone(client.principal)
            client.connect(TOKEN)
            self.assertEqual(client.principal, 'observer')
            self.assertNotIn(TOKEN, vars(client).values())
            self.assertEqual(json.loads(dispatch(parse('sessions list'), client)),
                             {'sessions': ['desktop']})
            command = parse('session status desktop')
            response = dispatch(command, client)
            self.assertEqual(json.loads(response), {'session': 'desktop', 'phase': 'idle', 'revision': 7})
            self.assertNotIn(TOKEN, history_entry(command, response))
            self.assertEqual([(req['method'], req['params']) for req in calls],
                             [('auth', {'credential': TOKEN}), ('discover', {}),
                              ('snapshot', {'session': 'desktop'})])

    def test_visual_selection_pins_console_identity_without_returning_media(self):
        with self.wire({'result': {'principal': 'observer'}},
                       {'result': {'session': 'desktop', 'phase': 'idle', 'revision': 1,
                                   'epoch': 'a' * 32}}) as (client, calls):
            client.connect(TOKEN)
            selection = client.select_session('desktop')
            self.assertEqual((selection.session, selection.epoch, selection.principal),
                             ('desktop', 'a' * 32, 'observer'))
            self.assertEqual([r['method'] for r in calls], ['auth', 'snapshot'])

    def test_visual_selection_requires_a_valid_epoch(self):
        with self.wire({'result': {'principal': 'observer'}},
                       {'result': {'session': 'desktop', 'phase': 'idle', 'revision': 1,
                                   'epoch': 'stale'}}) as (client, _):
            client.connect(TOKEN)
            self.assert_error(Error.INVALID_RESPONSE, client.select_session, 'desktop')
            self.assertIsNone(client.principal)

    def test_combined_selection_uses_snapshot_when_authorized(self):
        with self.wire({'result': {'principal': 'observer'}},
                       {'result': {'session': 'desktop', 'phase': 'idle', 'revision': 2,
                                   'epoch': 'a' * 32}}) as (client, calls):
            client.connect(TOKEN)
            self.assertEqual(client.select_combined('desktop'),
                             SessionSelection('desktop', 'a' * 32, 'observer'))
            self.assertEqual([call['method'] for call in calls], ['auth', 'snapshot'])

    def test_combined_stream_only_selection_validates_presentation_metadata(self):
        media = dict(session='desktop', principal='observer', privateId='b' * 16, epoch='a' * 32,
                     capability='desktop.stream', authorization='authorized', state='available',
                     transport='unix_stream_upgrade_v1', format=FORMAT, width=OUTPUT[0], height=OUTPUT[1],
                     stride=STRIDE, input=False)
        for replacement in ({}, {'session': 'other'}, {'principal': 'delegate'}, {'input': True},
                            {'epoch': TOKEN}, {'privateId': TOKEN}):
            with self.subTest(replacement=tuple(replacement)), self.wire(
                    {'result': {'principal': 'observer'}},
                    {'error': {'code': -32001, 'message': 'grant_denied'}},
                    {'result': media | replacement}) as (client, calls):
                client.connect(TOKEN)
                if replacement:
                    self.assert_error(Error.INVALID_RESPONSE, client.select_combined, 'desktop')
                else:
                    self.assertEqual(client.select_combined('desktop'),
                                     SessionSelection('desktop', 'a' * 32, 'observer', 'b' * 16))
                self.assertEqual([call['method'] for call in calls],
                                 ['auth', 'snapshot', 'presentation.describe'])
                self.assertEqual(calls[-1]['params'], {'session': 'desktop'})

    def test_combined_selection_does_not_bypass_an_invalid_snapshot(self):
        with self.wire({'result': {'principal': 'observer'}},
                       {'result': {'session': 'other', 'phase': 'idle', 'revision': 1}}) as (client, calls):
            client.connect(TOKEN)
            self.assert_error(Error.INVALID_RESPONSE, client.select_combined, 'desktop')
            self.assertEqual([call['method'] for call in calls], ['auth', 'snapshot'])

    def test_disconnected_and_bad_endpoint(self):
        client = BridgeClient()
        self.assert_error(Error.DISCONNECTED, client.list_sessions)
        self.assert_error(Error.DISCONNECTED, client.session_status, 'desktop')
        self.assert_error(Error.DISCONNECTED, client.connect, TOKEN)
        with TemporaryDirectory() as folder:
            missing = BridgeClient(Path(folder) / 'missing.sock')
            self.assert_error(Error.DISCONNECTED, missing.connect, TOKEN)
            self.assertIsNone(missing.principal)

    def test_pin_mismatch_prevents_sending_credential(self):
        with self.wire(None, expected_uid=os.getuid() + 1) as (client, calls):
            self.assert_error(Error.PEER_MISMATCH, client.connect, TOKEN)
        self.assertEqual(calls, [])

    def test_authentication_denial_and_input_limits(self):
        with self.wire({'error': {'code': -32001, 'message': 'denied',
                                  'data': {'echo': TOKEN}}}) as (client, calls):
            self.assert_error(Error.AUTHENTICATION, client.connect, TOKEN + 'y')
            self.assertEqual(calls, [])
            self.assert_error(Error.AUTHENTICATION, client.connect, TOKEN)
            self.assertIsNone(client.principal)

    def test_owner_credential_does_not_open_a_shell_session(self):
        with self.wire({'result': {'principal': 'owner'}}) as (client, calls):
            self.assert_error(Error.OWNER_CREDENTIAL, client.connect, TOKEN)
            self.assert_error(Error.DISCONNECTED, client.list_sessions)
            self.assertEqual([call['method'] for call in calls], ['auth'])

    def test_remote_negative_results_are_distinct(self):
        with self.wire({'result': {'principal': 'delegate'}},
                       {'error': {'code': -32001, 'message': 'grant_denied'}},
                       {'error': {'code': -32006, 'message': 'target_unavailable'}},
                       {'error': {'code': -32601, 'message': 'method_not_found'}},
                       {'error': {'code': -32000, 'message': TOKEN}}) as (client, _):
            client.connect(TOKEN)
            self.assert_error(Error.PERMISSION, client.list_sessions)
            self.assert_error(Error.SESSION_UNAVAILABLE, client.session_status, 'desktop')
            self.assert_error(Error.UNAVAILABLE, client.session_status, 'desktop')
            self.assert_error(Error.REMOTE_FAILURE, client.session_status, 'desktop')
            self.assertEqual(client.principal, 'delegate')

    def test_timeout_retires_connection(self):
        with self.wire({'result': {'principal': 'observer'}}, None) as (client, _):
            client.connect(TOKEN)
            with patch.object(DeadlineChannel, 'receive', side_effect=TimeoutError):
                self.assert_error(Error.TIMEOUT, client.list_sessions)
            self.assert_error(Error.DISCONNECTED, client.list_sessions)

    def test_eof_retires_connection(self):
        with self.wire({'result': {'principal': 'observer'}}, None) as (client, _):
            client.connect(TOKEN)
            self.assert_error(Error.DISCONNECTED, client.list_sessions)
            self.assertIsNone(client.principal)

    def test_malformed_wire_frames_fail_closed(self):
        for frame in (b'not JSON\n', b'[]\n', b'{' * 8192 + b'\n',
                      b'{"jsonrpc":"2.0","version":"0.6","id":true,"result":{}}\n',
                      b'{"jsonrpc":"2.0","version":"0.6","id":2,"result":{},"error":{}}\n',
                      b'{"jsonrpc":"2.0","version":"0.6","id":1,"id":1,"result":{}}\n'):
            with self.subTest(frame=frame[:24]), self.wire(frame) as (client, _):
                self.assert_error(Error.INVALID_RESPONSE, client.connect, TOKEN)
                self.assertIsNone(client.principal)

    def test_invalid_results_and_credential_echo_fail_closed(self):
        for body in ({'sessions': [TOKEN]}, {'sessions': ['same', 'same']}, {'sessions': 3}):
            with self.subTest(body_type=type(body['sessions'])), self.wire(
                    {'result': {'principal': 'observer'}}, {'result': body}) as (client, _):
                client.connect(TOKEN)
                self.assert_error(Error.INVALID_RESPONSE, client.list_sessions)
                self.assertIsNone(client.principal)
        with self.wire({'result': {'principal': 'observer'}},
                       {'result': {'session': 'other', 'phase': 'idle', 'revision': 7}}) as (client, _):
            client.connect(TOKEN)
            self.assert_error(Error.INVALID_RESPONSE, client.session_status, 'desktop')


@unittest.skipUnless(os.environ.get('LOOPSHELL_TEST_GTK') == '1',
                     'opt-in GTK test on a disposable display')
class ConsoleGeometryTests(unittest.TestCase):
    def test_authenticated_console_fits_minimum_reserved_height(self):
        from loopshell.bridge import SessionSelection
        from loopshell.layout import HEIGHT_LIMITS, MIN_WORKSPACE
        from loopshell.ui import CommandConsole, Gdk, Gtk, STYLE

        Gtk.init()
        display = Gdk.Display.get_default()
        self.assertIsNotNone(display)
        provider = Gtk.CssProvider()
        provider.load_from_data(STYLE)
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.addCleanup(Gtk.StyleContext.remove_provider_for_display, display, provider)

        client = BridgeClient(Path('/unused.sock'))
        client.principal = 'observer'
        console = CommandConsole(client, lambda: None)
        window = Gtk.Window(child=console)
        self.addCleanup(window.destroy)
        console.view.get_buffer().set_text('Session status\n' * 64)
        command_minimum, *_ = console.measure(Gtk.Orientation.VERTICAL, MIN_WORKSPACE[0])
        self.assertLessEqual(command_minimum, HEIGHT_LIMITS[0])
        console.prompt_view(SessionSelection('desktop', 'a' * 32, 'observer'))
        credential_minimum, *_ = console.measure(Gtk.Orientation.VERTICAL, MIN_WORKSPACE[0])
        self.assertLessEqual(credential_minimum, HEIGHT_LIMITS[0])


class BrokerIntegration(ShellTests):
    def test_observer_shell_against_disposable_loopbridge(self):
        identities = Identities()
        creds = identities.provision()
        with TemporaryDirectory() as directory, serve(Path(directory) / 'runtime', identities, 'fixture') as endpoint:
            with socket.socket(socket.AF_UNIX) as owner_peer, socket.socket(socket.AF_UNIX) as probe_peer:
                owner_peer.connect(str(endpoint))
                owner = RPC(owner_peer)
                owner.call('auth', credential=creds['owner'])

                shell = BridgeClient(endpoint)
                try:
                    shell.connect(creds['observer'])
                    self.assertEqual(shell.principal, 'observer')
                    self.assert_error(Error.PERMISSION, shell.list_sessions)
                    grant = owner.call('delegate', session=SESSION, principal='observer',
                                       capability='session.discover', target='*', ttl=120)
                    self.assertEqual(shell.list_sessions(), {'sessions': [SESSION]})
                    self.assert_error(Error.PERMISSION, shell.session_status, SESSION)
                    owner.call('delegate', session=SESSION, principal='observer',
                               capability='desktop.observe', target='*', ttl=120)
                    self.assertEqual(shell.session_status(SESSION)['phase'], 'idle')
                    self.assert_error(Error.PERMISSION, shell.session_status, 'unknown')
                    for command in ('acquire calculator', 'mission create test', 'system status'):
                        self.assert_error(Error.UNAVAILABLE, parse, command)

                    audit = owner.call('audit', session=SESSION)['entries']
                    self.assertEqual([row['method'] for row in audit if row['principal'] == 'observer'],
                                     ['auth', 'discover', 'discover', 'snapshot', 'snapshot', 'snapshot'])
                    self.assertNotIn(creds['observer'], json.dumps(audit))
                    probe_peer.connect(str(endpoint))
                    probe = RPC(probe_peer)
                    probe.call('auth', credential=creds['observer'])
                    with self.assertRaisesRegex(Fault, '^grant_denied$'):
                        probe.call('acquire', session=SESSION, ttl=10)
                    owner.call('revoke', session=SESSION, grant=grant['grant'])
                    self.assert_error(Error.PERMISSION, shell.list_sessions)
                finally:
                    shell.close()

                self.assertEqual(owner.call('snapshot', session=SESSION)['phase'], 'idle')
