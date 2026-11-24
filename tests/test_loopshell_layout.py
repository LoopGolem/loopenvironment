# SPDX-License-Identifier: Apache-2.0
"""Deterministic checks for the V0.8-A layout and Wayland requests."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from loopshell.compositor import apply_layout, load_layer_shell, setup_surfaces, show_surfaces
from loopshell.layout import Layout, config_path, load_layout, save_layout


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(TemporaryDirectory())) / 'shell' / 'layout.json'

    def test_static_limits_and_type_validation(self):
        self.assertEqual(Layout.from_config({'width': -23, 'height': 9999}),
                         Layout(width=200, height=400))
        self.assertEqual(Layout.from_config({'width': 9999, 'height': -23}),
                         Layout(width=480, height=120))
        self.assertEqual(Layout.from_config({'width': True, 'height': '300',
                                             'side': ['left'], 'edge': 'middle'}),
                         Layout())
        self.assertEqual(Layout.from_config({'width': 240.0, 'edge': 'top'}),
                         Layout(edge='top'))

    def test_fit_preserves_workspace_at_logical_size(self):
        preferred = Layout('right', 'top', 480, 400)
        self.assertEqual(preferred.fit(1000, 700), preferred)
        self.assertEqual(preferred.fit(700, 500), Layout('right', 'top', 380, 300))
        self.assertEqual(preferred.fit(520, 320), Layout('right', 'top', 200, 120))
        self.assertEqual(preferred.fit(1000, 700), preferred)

    def test_compact_output_uses_preview(self):
        self.assertIsNone(Layout().fit(519, 320))
        self.assertIsNone(Layout().fit(520, 319))

    def test_preferences_are_restored_and_replaced(self):
        first = Layout('right', 'top', 444, 250)
        second = Layout('left', 'bottom', 240, 130)
        for layout in (first, second):
            save_layout(self.path, layout)
            self.assertEqual(load_layout(self.path), layout)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_a_failed_replace_preserves_existing_preferences(self):
        save_layout(self.path, Layout())
        with patch.object(Path, 'replace', side_effect=OSError):
            with self.assertRaises(OSError):
                save_layout(self.path, Layout(side='right'))
        self.assertEqual(load_layout(self.path), Layout())
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_missing_or_malformed_file_falls_back(self):
        self.assertEqual(load_layout(self.path), Layout())
        self.path.parent.mkdir()
        for content in (b'{', b'null', b'[]', b'\xff', b' ' * 5000):
            with self.subTest(content=content[:10]):
                self.path.write_bytes(content)
                self.assertEqual(load_layout(self.path), Layout())
        self.path.write_bytes(b'{"side":"right","width":"huge","height":1,"other":true}')
        self.assertEqual(load_layout(self.path), Layout(side='right', height=120))

    def test_xdg_configuration_path(self):
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.path.parent)}):
            self.assertEqual(config_path().parent, self.path.parent / 'loopenvironment')
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': 'relative'}):
            self.assertEqual(config_path().parent, Path.home() / '.config' / 'loopenvironment')


class LayerShellTests(unittest.TestCase):
    def test_missing_library_falls_back(self):
        with patch('loopshell.compositor.CDLL', side_effect=OSError):
            self.assertIsNone(load_layer_shell())

    def test_rail_reserves_space_first_and_both_surfaces_use_on_demand_focus(self):
        shell = Mock(Layer=SimpleNamespace(OVERLAY='overlay', TOP='top'),
                     KeyboardMode=SimpleNamespace(ON_DEMAND='on-demand'))
        monitor, rail, console = Mock(), Mock(), Mock()
        setup_surfaces(shell, monitor, rail, console)
        self.assertEqual([args for args, _kw in shell.set_layer.call_args_list],
                         [(rail, 'overlay'), (console, 'top')])
        self.assertEqual([args for args, _kw in shell.set_monitor.call_args_list],
                         [(rail, monitor), (console, monitor)])
        self.assertEqual([args for args, _kw in shell.set_keyboard_mode.call_args_list],
                         [(rail, 'on-demand'), (console, 'on-demand')])

    def test_console_waits_for_the_first_rail_frame(self):
        rail, console = Mock(), Mock()
        rail.get_visible.return_value = False
        clock = rail.get_frame_clock.return_value
        clock.connect_after.return_value = 17

        show_surfaces(rail, console)

        rail.set_visible.assert_called_once_with(True)
        console.set_visible.assert_not_called()
        signal, callback = clock.connect_after.call_args.args
        self.assertEqual(signal, 'after-paint')
        callback(clock)
        console.set_visible.assert_called_once_with(True)
        clock.disconnect.assert_called_once_with(17)

        rail.get_visible.return_value = True
        show_surfaces(rail, console)
        clock.connect_after.assert_called_once()

    def test_unmapped_rail_does_not_show_a_delayed_console(self):
        rail, console = Mock(), Mock()
        rail.get_visible.return_value = False
        rail.get_mapped.return_value = False
        clock = rail.get_frame_clock.return_value

        show_surfaces(rail, console)
        clock.connect_after.call_args.args[1](clock)
        console.set_visible.assert_not_called()

    def test_switching_orientation_updates_both_surfaces(self):
        edge = SimpleNamespace(LEFT='left', RIGHT='right', TOP='top', BOTTOM='bottom')
        shell = Mock(Edge=edge)
        rail, console = Mock(), Mock()

        for layout in (Layout(), Layout('right', 'top', 300, 150)):
            with self.subTest(layout=layout):
                shell.reset_mock()
                apply_layout(shell, rail, console, layout)
                active_anchors = [(window, side) for (window, side, enabled), _kw
                                  in shell.set_anchor.call_args_list if enabled]
                self.assertCountEqual(active_anchors, [
                    (rail, layout.side), (rail, 'top'), (rail, 'bottom'),
                    (console, layout.edge), (console, 'left'), (console, 'right'),
                ])
                self.assertEqual(shell.set_anchor.call_count, 8)
                rail.set_default_size.assert_called_with(layout.width, 0)
                console.set_default_size.assert_called_with(0, layout.height)
                self.assertEqual([args for args, _kw in shell.set_exclusive_zone.call_args_list],
                                 [(rail, layout.width), (console, layout.height)])
