# SPDX-License-Identifier: Apache-2.0
"""Pure tests for the private graphics bounds and lifecycle cleanup policy."""
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from loopbridge.adapter import Refused
from loopbridge.broker import Connection
from loopbridge.desktop_broker import DesktopBroker
from loopbridge.identity import Identities
from loopbridge.private_effects import Effects, IMAGE, png
from loopbridge.private_session import Instance, manager_socket
from loopbridge.protocol import Fault
from loopbridge.service import DESKTOP_SESSION, Journal


class PrivateEffectsTests(unittest.TestCase):
    def test_frame_bounds_and_png_encoding(self):
        self.assertTrue(png(bytes(IMAGE[0] * IMAGE[1] * 3)).startswith(b'\x89PNG\r\n\x1a\n'))
        with self.assertRaisesRegex(Refused, 'capture_invalid_size'):
            png(b'invalid')

    @patch('loopbridge.private_effects.run', return_value=b'')
    @patch('loopbridge.private_effects.available', return_value=True)
    @patch('loopbridge.private_effects.scene')
    def test_pointer_checks_scene_again_at_submission(self, scene, available, run):
        identity = (21, 'start', 1000, '/usr/bin/editor')
        expected = ((4, identity, True, (0, 0, 800, 600)),)
        scene.side_effect = [expected, ()]
        effects = Effects()
        effects.frames = {'id': (float('inf'), b'png', expected)}
        call = effects.prepare('click', 'id', 40, 40, lambda: {identity})
        with self.assertRaisesRegex(Refused, 'private_scene_changed'):
            call.send()
        run.assert_not_called()

    def test_private_probe_is_refused_for_ordinary_desktop(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(Path(tmp))
            broker = DesktopBroker(Identities(), {'desktop': object()}, os.getuid(), journal,
                                   catalog=('editor',), workspace=True)
            peer = Connection(os.getuid(), principal='owner')
            with patch('loopbridge.desktop_broker.available', return_value=False):
                with self.assertRaisesRegex(Fault, 'private_effect_unavailable'):
                    broker.extended(broker.sessions['desktop'], peer, 'session.capture', {})
            peer.principal = 'observer'
            with patch('loopbridge.desktop_broker.available', return_value=True):
                with self.assertRaisesRegex(Fault, 'grant_denied'):
                    broker.extended(broker.sessions['desktop'], peer, 'session.capture', {})


class LifecycleTests(unittest.TestCase):
    def test_cleanup_of_old_session_keeps_journal_and_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp)
            instance = Instance.__new__(Instance)
            instance.root = old
            instance.runtime = old / 'runtime'
            instance.runtime.mkdir()
            for name in ('workspace', 'display', 'home', 'runtime/socket', 'runtime/apps-test'):
                (old / name).mkdir()
            instance.endpoint = old / 'runtime/socket/control.sock'
            (old / 'workspace/report.txt').write_text('possible effect')
            Journal(instance.runtime).mark(DESKTOP_SESSION, 'a' * 32)
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(instance.endpoint))
                instance.cleanup()
            self.assertTrue(Journal(instance.runtime).blocked(DESKTOP_SESSION))
            self.assertEqual((old / 'workspace/report.txt').read_text(), 'possible effect')
            self.assertFalse(instance.endpoint.exists())
            self.assertFalse((old / 'display').exists())

    def test_competing_manager_keeps_existing_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            endpoint = root / 'manager.sock'
            with manager_socket(root, endpoint):
                with self.assertRaises(BlockingIOError):
                    with manager_socket(root, endpoint):
                        pass
                self.assertTrue(endpoint.is_socket())
            self.assertFalse(endpoint.exists())


class LocalModelBoundaryTests(unittest.TestCase):
    def test_unknown_stops_before_remaining_model_calls(self):
        from tools.loopbridge_local_agent import run
        from unittest.mock import Mock

        client = Mock()
        client.request.return_value = {'tools': [
            dict(name='web_activate', description='Local form action', inputSchema={}),
            dict(name='execute_shell', description='Should be filtered', inputSchema={}),
        ]}
        client.invoke.return_value = ({'status': 'unknown'}, True)

        def model(messages, tools):
            self.assertEqual([tool['function']['name'] for tool in tools], ['web_activate'])
            return dict(role='assistant', tool_calls=[
                dict(function=dict(name='web_activate', arguments={'ref': 'fixture'})),
                dict(function=dict(name='web_activate', arguments={'ref': 'fixture'})),
            ])

        result = run(client, 'lab mission', model, max_turns=4)
        self.assertEqual(result['status'], 'unknown')
        client.invoke.assert_called_once_with('web_activate', ref='fixture')
