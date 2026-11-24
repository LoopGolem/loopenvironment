# SPDX-License-Identifier: Apache-2.0
"""GTK4 demonstration surfaces. Commands are handled locally as text."""
from collections import deque

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, Gtk

from .compositor import apply_layout, setup_surfaces
from .layout import CONSOLE_EDGES, HEIGHT_LIMITS, RAIL_SIDES, WIDTH_LIMITS
from .layout import Layout, load_layout, save_layout

PROMPT = 'bridge-demo> '
HELP = (
    'Demonstração local. Operações planejadas e indisponíveis:\n'
    '  agents list\n  sessions list\n  session observe <id>\n'
    '  mission create\n  mission status <id>\n  system status'
)

STYLE = b"""
.rail { background: #192332; color: #e0e9f5; padding: 10px; }
.console { background: #101822; color: #e0e9f5; padding: 6px 10px; }
.console textview, .console textview text {
  background: #101822; color: #c4d7e9; font-family: monospace;
}
.console .prompt { color: #79e2ba; font-family: monospace; }
.shell-title { font-size: 19px; font-weight: bold; }
.shell-muted { color: #a9bfd5; }
.preview-workspace { background: #303b48; color: #f0f4fa; }
"""


def command_reply(command):
    if command == 'help':
        return HELP
    return 'Comando demonstrativo desconhecido. Digite help.'


def label(text, style=None):
    widget = Gtk.Label(label=text, xalign=0, wrap=True)
    if style:
        widget.add_css_class(style)
    return widget


class DemoConsole(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class('console')
        self.append(label('Console demonstrativo', 'shell-muted'))
        self.history = deque(['Digite help para consultar os comandos planejados.'], maxlen=64)
        self.view = Gtk.TextView(editable=False, cursor_visible=False,
                                 wrap_mode=Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(self.view)
        self.append(scroll)
        row = Gtk.Box(spacing=8)
        row.append(label(PROMPT, 'prompt'))
        entry = Gtk.Entry(placeholder_text='Digite help', max_length=256, hexpand=True)
        entry.connect('activate', self.submit)
        row.append(entry)
        self.append(row)
        self.paint_history()

    def submit(self, entry):
        command = entry.get_text().strip()
        if command:
            self.history.append(PROMPT + command + '\n' + command_reply(command))
            self.paint_history()
        entry.set_text('')

    def paint_history(self):
        buffer = self.view.get_buffer()
        buffer.set_text('\n'.join(self.history))
        buffer.place_cursor(buffer.get_end_iter())
        self.view.scroll_mark_onscreen(buffer.get_insert())


class Shell:
    def __init__(self, app, path, layer_shell):
        self.app = app
        self.path = path
        self.layer_shell = layer_shell
        self.preferences = load_layout(path)
        self.windows = []
        self.monitor = None
        self.geometry_watch = None
        self.anchored_monitor = None
        self.console = DemoConsole()
        self.rail = self.build_rail()
        self.display = Gdk.Display.get_default()
        css = Gtk.CssProvider()
        css.load_from_data(STYLE)
        Gtk.StyleContext.add_provider_for_display(
            self.display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.monitors = self.display.get_monitors()
        self.monitors.connect('items-changed', self.update_monitor)
        self.update_monitor()

    def build_rail(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.append(label('LoopShell', 'shell-title'))
        content.append(label('Sessões simuladas', 'shell-muted'))
        content.append(label('Exemplo local'))
        self.mode_label = label('', 'shell-muted')
        content.append(self.mode_label)
        content.append(Gtk.Separator())

        self.side = Gtk.DropDown.new_from_strings(['Esquerda', 'Direita'])
        self.side.set_selected(RAIL_SIDES.index(self.preferences.side))
        self.edge = Gtk.DropDown.new_from_strings(['Topo', 'Rodapé'])
        self.edge.set_selected(CONSOLE_EDGES.index(self.preferences.edge))
        self.width = Gtk.SpinButton.new_with_range(*WIDTH_LIMITS, 1)
        self.width.set_value(self.preferences.width)
        self.height = Gtk.SpinButton.new_with_range(*HEIGHT_LIMITS, 1)
        self.height.set_value(self.preferences.height)
        for name, widget in (
            ('Lado do painel', self.side), ('Largura (px)', self.width),
            ('Borda do console', self.edge), ('Altura (px)', self.height),
        ):
            text = label(name)
            widget.update_relation([Gtk.AccessibleRelation.LABELLED_BY], [[text]])
            content.append(text)
            content.append(widget)

        apply_button = Gtk.Button(label='Aplicar layout')
        apply_button.connect('clicked', self.save)
        content.append(apply_button)
        self.save_label = label('')
        content.append(self.save_label)
        close_button = Gtk.Button(label='Fechar LoopShell')
        close_button.connect('clicked', lambda _button: self.app.quit())
        content.append(close_button)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(content)
        scroll.add_css_class('rail')
        return scroll

    def save(self, _button):
        self.width.update()
        self.height.update()
        self.preferences = Layout(
            RAIL_SIDES[self.side.get_selected()], CONSOLE_EDGES[self.edge.get_selected()],
            self.width.get_value_as_int(), self.height.get_value_as_int(),
        )
        try:
            save_layout(self.path, self.preferences)
        except OSError:
            self.save_label.set_text('Falha ao salvar as preferências.')
        else:
            self.save_label.set_text('')
        self.render()

    def update_monitor(self, *_args):
        if self.monitor is not None:
            self.monitor.disconnect(self.geometry_watch)
        self.monitor = self.monitors.get_item(0)
        if self.monitor is not None:
            self.geometry_watch = self.monitor.connect('notify::geometry', self.render)
        self.render()

    def render(self, *_args):
        geometry = self.monitor.get_geometry() if self.monitor is not None else None
        fitted = self.preferences.fit(geometry.width, geometry.height) if geometry else None
        anchored = self.monitor if self.layer_shell is not None and fitted else None
        if not self.windows or anchored != self.anchored_monitor:
            self.rebuild_windows(anchored)
        if anchored is not None:
            self.mode_label.set_text(f'Painel {fitted.width} px · Console {fitted.height} px')
            apply_layout(self.layer_shell, *self.windows, fitted)
        else:
            reason = 'tela compacta' if self.layer_shell is not None else 'janela comum'
            self.mode_label.set_text(f'Prévia ({reason})\nSem reserva no Sway')
            self.rail.set_size_request(min(self.preferences.width, geometry.width // 2)
                                       if geometry else self.preferences.width, -1)
            self.console.set_size_request(-1, min(self.preferences.height, geometry.height // 2)
                                          if geometry else self.preferences.height)
            self.preview_row.reorder_child_after(
                self.rail, None if self.preferences.side == 'left' else self.preview_column)
            self.preview_column.reorder_child_after(
                self.console, None if self.preferences.edge == 'top' else self.workspace)
        for window in self.windows:
            if not window.get_visible():
                window.present()

    def rebuild_windows(self, monitor):
        for widget in (self.rail, self.console):
            parent = widget.get_parent()
            if isinstance(parent, Gtk.Window):
                parent.set_child(None)
            elif isinstance(parent, Gtk.Box):
                parent.remove(widget)
            widget.set_size_request(-1, -1)
        for window in self.windows:
            window.destroy()
        self.anchored_monitor = monitor
        if monitor is not None:
            rail = self.window('LoopShell · Painel')
            console = self.window('LoopShell · Console')
            setup_surfaces(self.layer_shell, monitor, rail, console)
            rail.set_child(self.rail)
            console.set_child(self.console)
            self.windows = [rail, console]
        else:
            preview = self.window('LoopShell · Prévia')
            preview.set_default_size(800, 500)
            self.preview_row = Gtk.Box()
            self.preview_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            self.workspace = Gtk.Label(label='Área de trabalho', vexpand=True)
            self.workspace.add_css_class('preview-workspace')
            self.preview_column.append(self.workspace)
            self.preview_column.append(self.console)
            self.preview_row.append(self.rail)
            self.preview_row.append(self.preview_column)
            preview.set_child(self.preview_row)
            self.windows = [preview]

    def window(self, title):
        window = Gtk.ApplicationWindow(application=self.app, title=title)
        window.connect('close-request', self.close)
        return window

    def close(self, _window):
        self.app.quit()
        return False


def run(path, layer_shell):
    app = Gtk.Application(application_id='org.loopenvironment.LoopShell',
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(application):
        supported = (layer_shell is not None and layer_shell.is_supported()
                     and layer_shell.get_protocol_version() >= 4)
        Shell(application, path, layer_shell if supported else None)

    app.connect('activate', activate)
    return app.run([])
