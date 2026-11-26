# SPDX-License-Identifier: Apache-2.0
"""Synthetic qualification fixtures for the Sway baseline collector."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import sway_baseline as baseline


class SwayBaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / 'config'
        self.config.write_text('set $mod Mod4\n')
        self.socket = Path(self.tmp.name) / 'sway.sock'
        self.identity = ('synthetic-boot', (100, '1000', 1000, '/usr/bin/sway'))
        self.socket_identity = (str(self.socket), (1, 10, 1000, 1000, 0o140600))
        rect = {'x': 0, 'y': 0, 'width': 1280, 'height': 800}
        leaves = [
            {'id': number, 'type': 'con', 'name': f'private window {number}',
             'focus': [], 'focused': number == 2, 'nodes': [], 'floating_nodes': []}
            for number in (2, 3)
        ]
        self.replies = {
            'version': {'human_readable': '1.10.1', 'major': 1, 'minor': 10, 'patch': 1,
                        'loaded_config_file_name': str(self.config)},
            'config': {'config': 'set $mod Mod4\n'},
            'outputs': [{'name': 'Virtual-1', 'make': 'Virtual', 'model': 'Virtual',
                         'serial': 'synthetic', 'active': True, 'power': True,
                         'modes': [], 'current_mode': {'width': 1280, 'height': 800},
                         'rect': rect}],
            'workspaces': [{'name': '1', 'focused': True, 'rect': rect, 'output': 'Virtual-1'}],
            'tree': {'id': 1, 'type': 'root', 'focused': False, 'focus': [2, 3],
                     'nodes': leaves, 'floating_nodes': []},
        }

    def query(self, socket_path, pid, name):
        reply = self.replies[name]
        if isinstance(reply, Exception):
            raise reply
        return deepcopy(reply)

    def capture(self):
        with patch.object(baseline, 'session_identity',
                          return_value=(self.identity, self.socket_identity)), \
                patch.object(baseline, 'query', side_effect=self.query):
            result = baseline.capture(100, self.socket)
        return result

    def complete_capture(self):
        result = self.capture()
        self.assertNotIn(None, result['components'].values())
        return result

    def test_focus_change_requires_expected_dynamic_component(self):
        before = self.complete_capture()
        tree = self.replies['tree']
        tree['focus'].reverse()
        tree['nodes'][0]['focused'] = False
        tree['nodes'][1]['focused'] = True
        after = self.complete_capture()

        review = baseline.compare(before, after)
        self.assertEqual(review['result'], 'unexpected_change')
        self.assertEqual(review['structural_changed'], [])
        self.assertEqual(review['dynamic_changed'], ['focus'])
        allowed = baseline.compare(before, after, expected_dynamic=['focus'])
        self.assertEqual(allowed['result'], 'expected_dynamic_change')

    def test_configuration_file_edit_and_reload_are_distinct(self):
        before = self.complete_capture()
        self.config.write_text('set $mod Mod1\n')
        after_edit = self.complete_capture()
        review = baseline.compare(before, after_edit)
        self.assertEqual(review['result'], 'unexpected_change')
        self.assertEqual(review['structural_changed'], ['config_file_content'])

        self.replies['config']['config'] = self.config.read_text()
        after_reload = self.complete_capture()
        review = baseline.compare(after_edit, after_reload)
        self.assertEqual(review['result'], 'unexpected_change')
        self.assertEqual(review['structural_changed'], ['loaded_config'])

    def test_compositor_start_time_change_is_structural(self):
        before = self.complete_capture()
        self.identity = ('synthetic-boot', (100, '1001', 1000, '/usr/bin/sway'))
        review = baseline.compare(before, self.complete_capture())
        self.assertEqual(review['result'], 'unexpected_change')
        self.assertEqual(review['structural_changed'], ['compositor'])

    def test_output_identity_and_mode_changes_are_reported_separately(self):
        before = self.complete_capture()
        output = self.replies['outputs'][0]
        output['current_mode']['width'] = 1640
        review = baseline.compare(before, self.complete_capture())
        self.assertEqual(review['dynamic_changed'], ['output_modes_and_geometry'])
        self.assertEqual(review['structural_changed'], [])

        output['serial'] = 'another-output'
        review = baseline.compare(before, self.complete_capture(),
                                  expected_dynamic=['output_modes_and_geometry'])
        self.assertEqual(review['result'], 'unexpected_change')
        self.assertEqual(review['structural_changed'], ['output_identity'])

    def test_missing_data_and_capture_failure_are_insufficient(self):
        before = self.complete_capture()
        self.replies['outputs'][0].pop('serial')
        self.replies['workspaces'] = TimeoutError('private diagnostic')
        after = self.capture()
        review = baseline.compare(before, after)
        self.assertEqual(review['result'], 'insufficient_evidence')
        self.assertEqual(review['missing_components'], [
            'output_identity', 'workspaces', 'focus', 'output_modes_and_geometry', 'output_state',
        ])
        self.assertNotIn('private diagnostic', json.dumps(after))

    def test_malformed_ipc_version_reply_is_insufficient(self):
        before = self.complete_capture()
        self.replies['version'] = None
        review = baseline.compare(before, self.capture())
        self.assertEqual(review['result'], 'insufficient_evidence')
        self.assertEqual(review['missing_components'], [
            'version', 'config_file_identity', 'config_file_content',
        ])

    def test_identity_race_invalidates_capture(self):
        with patch.object(baseline, 'session_identity',
                          side_effect=[(self.identity, self.socket_identity),
                                       (self.identity, ('replacement socket',))]), \
                patch.object(baseline, 'query', side_effect=self.query):
            result = baseline.capture(100, self.socket)
        self.assertTrue(all(value is None for value in result['components'].values()))

    def test_canonicalized_objects_preserve_ordered_focus_and_hide_raw_values(self):
        before = self.complete_capture()
        self.replies['tree'] = dict(reversed(list(self.replies['tree'].items())))
        after = self.complete_capture()
        self.assertEqual(baseline.compare(before, after)['result'], 'unchanged')
        for private_value in ('synthetic-boot', 'private window 2', str(self.config), 'Virtual-1'):
            self.assertNotIn(private_value, json.dumps(after))
