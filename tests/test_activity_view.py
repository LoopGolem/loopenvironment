# SPDX-License-Identifier: Apache-2.0
"""Activity projection, connection lifetime and the Core broker contract."""
from contextlib import contextmanager
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import patch

from loopbridge.identity import Identities
from loopbridge.protocol import DeadlineChannel, Fault, RPC
from loopbridge.service import SESSION, serve
from loopshell.activity import (ActivityClient, ActivityEvent, MAX_CONNECTION_AGE,
                                MAX_EVENTS, MAX_POLLS, POLL_INTERVAL, project_batch)
from loopshell.bridge import SessionSelection
from loopshell.errors import Error, ShellError

TOKEN = 'x' * 43
EPOCH = 'a' * 32
REPLACEMENT = 'b' * 32
PIN = SessionSelection('desktop', EPOCH, 'observer')
AUTH = {'result': {'principal': 'observer'}}
SNAPSHOT = dict(session='desktop', epoch=EPOCH, phase='idle', revision=2, cursor=5)


def row(seq=6, **fields):
    return dict(epoch=EPOCH, seq=seq, source='authority', kind='control.changed',
                state=dict(phase='controlled', revision=4)) | fields


def batch(*events, cursor=None, epoch=EPOCH):
    return dict(epoch=epoch, cursor=5 + len(events) if cursor is None else cursor,
                events=list(events))


def error_reply(code, message):
    return {'error': dict(code=code, message=message, data={'echo': TOKEN})}


class ActivityTests(unittest.TestCase):
    def assert_fault(self, reason, call, *args):
        with self.assertRaises(ShellError) as caught:
            call(*args)
        self.assertIs(caught.exception.error, reason)
        self.assertEqual(str(caught.exception), reason.name)

    @contextmanager
    def wire(self, *replies):
        with TemporaryDirectory() as folder, socket.socket(socket.AF_UNIX) as listener:
            endpoint = Path(folder) / 'bridge.sock'
            listener.bind(str(endpoint))
            listener.listen()
            listener.settimeout(2)
            calls, errors = [], []

            def serve_wire():
                try:
                    with listener.accept()[0] as peer:
                        channel = DeadlineChannel(peer)
                        for body in replies:
                            try:
                                request = channel.receive(2)
                            except EOFError:
                                return
                            method = request['method']
                            calls.append((method, {} if method == 'auth' else request['params']))
                            if callable(body):
                                body(channel)
                            elif body is not None:
                                channel.send(dict(jsonrpc='2.0', version=request['version'],
                                                  id=request['id'], **body))
                except Exception as exc:
                    errors.append(type(exc).__name__)

            worker = Thread(target=serve_wire, daemon=True)
            worker.start()
            client = ActivityClient(endpoint, os.getuid(), PIN)
            try:
                yield client, calls
            finally:
                client.close()
                worker.join(3)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])

    def test_projects_only_approved_fields_in_sequence(self):
        projected = project_batch(batch(row(state=dict(phase='controlled', revision=4, value=TOKEN),
                                            administrative=TOKEN),
                                        row(7, kind='control.released')), EPOCH, 5)
        self.assertEqual(projected, (7, (ActivityEvent(6, 'control.changed', 'controlled', 4),
                                        ActivityEvent(7, 'control.released', 'controlled', 4))))
        self.assertEqual(project_batch(batch(), EPOCH, 5), (5, ()))
        self.assertNotIn(TOKEN, repr(projected))

    def test_rejects_malformed_batch_instead_of_advancing(self):
        for payload in (
            [], batch() | {'session': 'other'}, batch(cursor=True), batch(cursor=9), batch(cursor=1 << 63),
            batch(row(7), row(6)), batch(row(), row()), batch(row(True)),
            batch(row(epoch='bad')), batch(row(source=TOKEN)), batch(row(kind=TOKEN)),
            batch(row(state={'phase': {}, 'revision': 3})),
            batch(row(state={'phase': 'idle', 'revision': False})),
            batch(row(state={'phase': 'idle', 'revision': -1})),
            batch(*(row(seq) for seq in range(6, 7 + MAX_EVENTS))),
        ):
            with self.subTest(payload_type=type(payload)):
                self.assert_fault(Error.INVALID_RESPONSE, project_batch, payload, EPOCH, 5)
        for payload in (batch(epoch=REPLACEMENT), batch(row(epoch=REPLACEMENT))):
            self.assert_fault(Error.EPOCH_CHANGED, project_batch, payload, EPOCH, 5)

    def test_auth_snapshot_and_polls_share_a_dedicated_socket(self):
        with self.wire(AUTH, {'result': SNAPSHOT | {'state': {'text': TOKEN}}},
                       {'result': batch(row())}, {'result': batch(cursor=6)}) as (client, calls):
            self.assert_fault(Error.SNAPSHOT_REQUIRED, client.poll)
            client.begin(TOKEN)
            self.assertNotIn(TOKEN, vars(client).values())
            self.assertEqual(client.poll(), (ActivityEvent(6, 'control.changed', 'controlled', 4),))
            self.assertEqual(client.poll(), ())
            self.assertEqual(client.cursor, 6)
            self.assertEqual(calls, [
                ('auth', {}), ('snapshot', {'session': PIN.session}),
                ('events', dict(session=PIN.session, epoch=EPOCH, cursor=5)),
                ('events', dict(session=PIN.session, epoch=EPOCH, cursor=6)),
            ])

    def test_explicit_identity_and_current_snapshot_required(self):
        for reason, replies, methods in (
            (Error.AUTHENTICATION, [error_reply(-32001, 'denied')], ['auth']),
            (Error.OWNER_CREDENTIAL, [{'result': {'principal': 'owner'}}], ['auth']),
            (Error.AUTHENTICATION, [{'result': {'principal': 'delegate'}}], ['auth']),
            (Error.PERMISSION, [AUTH, error_reply(-32001, 'grant_denied')], ['auth', 'snapshot']),
            (Error.EPOCH_CHANGED, [AUTH, {'result': SNAPSHOT | {'epoch': REPLACEMENT}}],
             ['auth', 'snapshot']),
            (Error.INVALID_RESPONSE, [AUTH, {'result': SNAPSHOT | {'session': 'other'}}],
             ['auth', 'snapshot']),
            (Error.INVALID_RESPONSE, [AUTH, {'result': SNAPSHOT | {'cursor': False}}],
             ['auth', 'snapshot']),
        ):
            with self.subTest(reason=reason), self.wire(*replies) as (client, calls):
                self.assert_fault(reason, client.begin, TOKEN)
                self.assertIsNone(client.principal)
                self.assertIsNone(client.cursor)
                self.assertEqual([method for method, _ in calls], methods)

    def test_any_event_failure_retires_the_socket_and_cursor(self):
        for reason, reply in (
            (Error.INVALID_CURSOR, error_reply(-32602, 'invalid_cursor')),
            (Error.HISTORY_GAP, error_reply(-32003, 'gap_snapshot_required')),
            (Error.EPOCH_CHANGED, error_reply(-32004, 'epoch_changed_snapshot_required')),
            (Error.SNAPSHOT_REQUIRED, error_reply(-32004, 'snapshot_required')),
            (Error.SESSION_UNAVAILABLE, error_reply(-32006, 'target_unavailable')),
            (Error.PERMISSION, error_reply(-32001, 'grant_denied')),
            (Error.INVALID_RESPONSE, {'result': batch(row(7))}),
            (Error.DISCONNECTED, None),
        ):
            with self.subTest(reason=reason), self.wire(
                    AUTH, {'result': SNAPSHOT}, {'result': batch()}, reply) as (client, _):
                client.begin(TOKEN)
                self.assertEqual(client.poll(), ())
                self.assert_fault(reason, client.poll)
                self.assert_fault(Error.SNAPSHOT_REQUIRED, client.poll)
                self.assertIsNone(client.principal)

    def test_timeout_clears_authorization(self):
        with self.wire(AUTH, {'result': SNAPSHOT}, None) as (client, _):
            client.begin(TOKEN)
            with patch.object(DeadlineChannel, 'receive', side_effect=TimeoutError):
                self.assert_fault(Error.TIMEOUT, client.poll)
            self.assertIsNone(client.principal)

    def test_cancel_releases_a_blocked_receive(self):
        in_rpc = Event()

        def hold_until_socket_shutdown(channel):
            in_rpc.set()
            self.assertEqual(channel.sock.recv(1), b'')

        with self.wire(AUTH, {'result': SNAPSHOT}, hold_until_socket_shutdown) as (client, _):
            client.begin(TOKEN)
            results = []

            def poll():
                try:
                    client.poll()
                except ShellError as exc:
                    results.append(exc.error)

            thread = Thread(target=poll, daemon=True)
            thread.start()
            self.assertTrue(in_rpc.wait(1))
            client.cancel()
            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(results, [Error.DISCONNECTED])
            self.assertIsNone(client.principal)

    def test_poll_budget_and_age_require_explicit_resync(self):
        client = ActivityClient(None, None, PIN, clock=lambda: 0)
        self.assert_fault(Error.SNAPSHOT_REQUIRED, next, client.updates())
        client.started, client.cursor = 0, 5
        with patch.object(client, 'poll', return_value=()) as poll, \
                patch.object(client.cancelled, 'wait', return_value=False) as delay:
            updates = client.updates()
            for _ in range(MAX_POLLS):
                self.assertEqual(next(updates), ())
            self.assert_fault(Error.REAUTH_REQUIRED, next, updates)
            self.assertEqual(poll.call_count, MAX_POLLS)
            delay.assert_called_with(POLL_INTERVAL)
            client.clock = lambda: MAX_CONNECTION_AGE
            self.assert_fault(Error.REAUTH_REQUIRED, next, client.updates())
            self.assertEqual(poll.call_count, MAX_POLLS)
            client.cancel()
            self.assertEqual(list(client.updates()), [])

    def test_core_broker_retention_resync_and_revocation(self):
        identities = Identities()
        credentials = identities.provision()
        with TemporaryDirectory() as directory, serve(Path(directory) / 'runtime', identities, 'fixture') as endpoint:
            with socket.socket(socket.AF_UNIX) as owner_socket, socket.socket(socket.AF_UNIX) as observer_socket:
                owner_socket.connect(str(endpoint))
                observer_socket.connect(str(endpoint))
                owner, observer = RPC(owner_socket), RPC(observer_socket)
                owner.call('auth', credential=credentials['owner'])
                observer.call('auth', credential=credentials['observer'])

                def grant(capability):
                    return owner.call('delegate', session=SESSION, principal='observer',
                                      capability=capability, target='*', ttl=120)['grant']

                def activity_cycle():
                    lease = owner.call('acquire', session=SESSION, ttl=10)
                    owner.call('release', session=SESSION, lease=lease['id'],
                               generation=lease['generation'], epoch=lease['epoch'])

                grant('session.discover')
                selection = SessionSelection(SESSION, owner.call('snapshot', session=SESSION)['epoch'], 'observer')
                client = ActivityClient(endpoint, None, selection)
                self.addCleanup(client.close)
                self.assertEqual(observer.call('discover')['sessions'], [SESSION])
                self.assert_fault(Error.PERMISSION, client.begin, credentials['observer'])
                observe_grant = grant('desktop.observe')
                with self.assertRaisesRegex(Fault, '^snapshot_required$'):
                    observer.call('events', session=SESSION, epoch=selection.epoch, cursor=0)

                client.begin(credentials['observer'])
                baseline = client.cursor
                self.assertEqual(client.poll(), ())
                with self.assertRaisesRegex(Fault, '^grant_denied$'):
                    observer.call('acquire', session=SESSION, ttl=10)
                activity_cycle()
                rows = client.poll()
                self.assertEqual([(event.sequence, event.kind) for event in rows],
                                 [(baseline + 1, 'control.changed'), (baseline + 2, 'control.released')])
                for _ in range(5):
                    activity_cycle()
                self.assert_fault(Error.HISTORY_GAP, client.poll)

                reopened = ActivityClient(endpoint, None, selection)
                self.addCleanup(reopened.close)
                reopened.begin(credentials['observer'])
                self.assertGreater(reopened.cursor, baseline + MAX_EVENTS)
                self.assertEqual(reopened.poll(), ())
                owner.call('revoke', session=SESSION, grant=observe_grant)
                self.assert_fault(Error.PERMISSION, reopened.poll)
                self.assertEqual(owner.call('snapshot', session=SESSION)['phase'], 'idle')


@unittest.skipUnless(os.environ.get('LOOPSHELL_TEST_GTK') == '1',
                     'opt-in GTK test on a disposable display')
class ActivityWindowTests(unittest.TestCase):
    def test_bounded_rows_and_cancelled_render_on_close(self):
        from loopshell.activity_view import ActivityWindow, DISPLAY_LIMIT, GLib, Gtk

        Gtk.init()
        application = Gtk.Application()
        self.assertTrue(application.register(None))
        window = ActivityWindow(application, None, None, PIN, TOKEN)
        self.addCleanup(window.destroy)
        events = tuple(ActivityEvent(seq, 'state.changed', 'idle', seq)
                       for seq in range(1, DISPLAY_LIMIT + 3))
        window.publish('Autorizado', events)
        context = GLib.MainContext.default()
        for _ in range(32):
            if not context.iteration(False) or not window.render_source:
                break
        self.assertEqual(window.render_source, 0)
        self.assertEqual(len(window.displayed_rows), DISPLAY_LIMIT)
        self.assertEqual(window.displayed_rows[0].sequence, 3)
        self.assertEqual(window.event_view.get_buffer().get_line_count(), DISPLAY_LIMIT)

        window.publish('Autorizado', events)
        pending = window.render_source
        self.assertNotEqual(pending, 0)
        window.stop_polling()
        self.assertIsNone(context.find_source_by_id(pending))
        self.assertIsNone(window.credential)
        self.assertEqual(len(window.rows), 0)
        self.assertEqual(window.event_view.get_buffer().get_char_count(), 0)
        window.publish('Autorizado', events)
        self.assertEqual(window.render_source, 0)
