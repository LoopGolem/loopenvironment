# SPDX-License-Identifier: Apache-2.0
"""Optional GTK4 layer-shell integration on the current display."""
from ctypes import CDLL, RTLD_GLOBAL


def load_layer_shell():
    try:
        # Load before importing GTK so the library can wrap Wayland requests.
        CDLL('libgtk4-layer-shell.so.0', mode=RTLD_GLOBAL)
        import gi
        gi.require_version('Gtk4LayerShell', '1.0')
        from gi.repository import Gtk4LayerShell
    except (OSError, ValueError, ImportError):
        return None
    return Gtk4LayerShell


def setup_surfaces(shell, monitor, rail, console):
    # Sway subtracts overlay zones before top zones. The console then stretches
    # across the usable width the rail leaves behind.
    for window, layer, name in (
        (rail, shell.Layer.OVERLAY, 'loopshell-rail'),
        (console, shell.Layer.TOP, 'loopshell-console'),
    ):
        shell.init_for_window(window)
        shell.set_monitor(window, monitor)
        shell.set_namespace(window, name)
        shell.set_layer(window, layer)
        shell.set_keyboard_mode(window, shell.KeyboardMode.ON_DEMAND)
        window.set_decorated(False)


def apply_layout(shell, rail, console, layout):
    edges = {name: getattr(shell.Edge, name.upper())
             for name in ('left', 'right', 'top', 'bottom')}
    for window, anchors, width, height, zone in (
        (rail, (layout.side, 'top', 'bottom'), layout.width, 0, layout.width),
        (console, (layout.edge, 'left', 'right'), 0, layout.height, layout.height),
    ):
        for name, edge in edges.items():
            shell.set_anchor(window, edge, name in anchors)
        window.set_default_size(width, height)
        shell.set_exclusive_zone(window, zone)
