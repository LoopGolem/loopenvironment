# SPDX-License-Identifier: Apache-2.0
"""GTK4 surfaces for the typed LoopBridge console."""
from collections import deque
from threading import Thread

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk

from loopbridge.presentation_client import LiveConnection
from loopbridge.visual_view import ViewOptions, Watch

from .bridge import BridgeClient, TOKEN, TOKEN_LENGTH
from .commands import Action, MAX_INPUT, parse
from .compositor import apply_layout, setup_surfaces, show_surfaces
from .console import ERROR_TEXT, PROMPT, dispatch, history_entry
from .errors import Error, ShellError
from .layout import CONSOLE_EDGES, HEIGHT_LIMITS, RAIL_SIDES, WIDTH_LIMITS
from .layout import Layout, load_layout, save_layout

STYLE = b"""
.rail { background: #192332; color: #e0e9f5; padding: 10px; }
.console { background: #101822; color: #e0e9f5; padding: 6px 10px; }
.console textview, .console textview text {
  background: #101822; color: #c4d7e9; font-family: monospace;
}
/* Keep the history scrollable within the minimum exclusive zone. */
.console scrollbar.vertical slider { min-height: 20px; }
.console .prompt { color: #79e2ba; font-family: monospace; }
.shell-title { font-size: 19px; font-weight: bold; }
.shell-muted { color: #a9bfd5; }
.preview-workspace { background: #303b48; color: #f0f4fa; }
"""


def label(text, style=None):
    widget = Gtk.Label(label=text, xalign=0, wrap=True)
    if style:
        widget.add_css_class(style)
    return widget


class CommandConsole(Gtk.Box):
    def __init__(self, client, quit_shell, open_view=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.client = client
        self.quit_shell = quit_shell
        self.open_view = open_view
        self.view_selection = None
        self.busy = False
        self.add_css_class('console')
        self.status = label('', 'shell-muted')
        self.status.set_hexpand(True)
        self.connection_button = Gtk.Button()
        self.connection_button.connect('clicked', self.connection_action)
        header = Gtk.Box(spacing=8)
        header.append(self.status)
        header.append(self.connection_button)
        self.append(header)
        self.history = deque(maxlen=64)
        self.view = Gtk.TextView(editable=False, cursor_visible=False,
                                 wrap_mode=Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(self.view)
        self.append(scroll)

        row = Gtk.Box(spacing=8)
        row.append(label(PROMPT, 'prompt'))
        self.entry = Gtk.Entry(placeholder_text='Digite help', max_length=MAX_INPUT + 1,
                               hexpand=True)
        self.entry.connect('activate', self.submit)
        row.append(self.entry)
        self.password = Gtk.Entry(visibility=False, input_purpose=Gtk.InputPurpose.PASSWORD,
                                  input_hints=Gtk.InputHints.PRIVATE,
                                  placeholder_text='Credencial · pressione Enter',
                                  max_length=TOKEN_LENGTH + 1)
        self.password.connect('activate', self.authenticate)
        self.input_stack = Gtk.Stack()
        self.input_stack.add_named(row, 'command')
        self.input_stack.add_named(self.password, 'credential')
        self.append(self.input_stack)
        self.refresh()

    def refresh(self):
        credential_entry = self.input_stack.get_visible_child() == self.password
        if self.busy:
            status = 'Consultando…' if self.client.principal else 'Autenticando…'
        elif self.view_selection is not None:
            status = 'Credencial de observação'
        elif self.client.principal:
            status = f'Conectado · {self.client.principal}'
        elif self.client.endpoint:
            status = 'Desconectado'
        else:
            status = 'Desconectado · use --socket'
        self.status.set_text(status)
        button = ('Cancelar' if credential_entry else
                  'Desconectar' if self.client.principal else 'Conectar')
        self.connection_button.set_label(button)
        self.connection_button.set_sensitive(not self.busy and self.client.endpoint is not None)
        self.entry.set_editable(not self.busy)

    def connection_action(self, _button):
        if self.input_stack.get_visible_child() == self.password:
            self.view_selection = None
            self.password.set_text('')
            self.input_stack.set_visible_child_name('command')
        elif self.client.principal:
            self.client.close()
        else:
            self.input_stack.set_visible_child_name('credential')
            self.password.grab_focus()
        self.refresh()

    def authenticate(self, entry):
        if self.busy:
            return
        credential = entry.get_text()
        entry.set_text('')
        self.connection_button.grab_focus()
        self.input_stack.set_visible_child_name('command')
        selection, self.view_selection = self.view_selection, None
        if selection is not None:
            self.refresh()
            if not TOKEN.fullmatch(credential):
                self.record(None, ERROR_TEXT[Error.AUTHENTICATION])
                self.entry.grab_focus()
            else:
                self.open_view(selection, credential)
            return

        def connect():
            self.client.connect(credential)
            return 'Autenticado. As consultas continuam sujeitas aos grants do LoopBridge.'

        self.start_io(connect)

    def submit(self, entry):
        if self.busy:
            return
        line = entry.get_text()
        entry.set_text('')
        try:
            command = parse(line)
        except ShellError as error:
            self.record(None, ERROR_TEXT[error.error])
            return
        if command is None:
            return
        if command.action is Action.CLEAR:
            self.history.clear()
            self.paint_history()
        elif command.action is Action.EXIT:
            self.quit_shell()
        elif command.action is Action.OBSERVE:
            if self.open_view is None:
                self.record(command, ERROR_TEXT[Error.UNAVAILABLE])
            else:
                self.start_io(lambda: self.client.select_session(command.session),
                              command, on_success=self.prompt_view)
        elif command.action.remote:
            self.start_io(lambda: dispatch(command, self.client), command)
        else:
            self.record(command, dispatch(command, self.client))

    def prompt_view(self, selection):
        self.view_selection = selection
        self.input_stack.set_visible_child_name('credential')
        self.refresh()
        self.password.grab_focus()

    def start_io(self, task, command=None, *, on_success=None):
        self.busy = True
        self.refresh()

        def work():
            try:
                text = task()
            except ShellError as error:
                GLib.idle_add(self.finished, command, ERROR_TEXT[error.error], None)
            else:
                GLib.idle_add(self.finished, command, text, on_success)

        Thread(target=work, daemon=True).start()

    def finished(self, command, result, on_success):
        self.busy = False
        self.refresh()
        if on_success is None:
            self.record(command, result)
            self.entry.grab_focus()
        else:
            on_success(result)

    def record(self, command, text):
        self.history.append(history_entry(command, text))
        self.paint_history()

    def paint_history(self):
        buffer = self.view.get_buffer()
        buffer.set_text('\n'.join(self.history))
        buffer.place_cursor(buffer.get_end_iter())
        self.view.scroll_mark_onscreen(buffer.get_insert())


class Shell:
    def __init__(self, app, path, layer_shell, client):
        self.app = app
        self.path = path
        self.layer_shell = layer_shell
        self.preferences = load_layout(path)
        self.windows = []
        self.monitor = None
        self.geometry_watch = None
        self.anchored_monitor = None
        self.console = CommandConsole(client, app.quit, self.open_view)
        self.rail = self.build_rail()
        self.display = Gdk.Display.get_default()
        css = Gtk.CssProvider()
        css.load_from_data(STYLE)
        Gtk.StyleContext.add_provider_for_display(
            self.display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.monitors = self.display.get_monitors()
        self.monitors.connect('items-changed', self.update_monitor)
        self.update_monitor()

    def open_view(self, selection, credential):
        client = self.console.client
        try:
            stream = LiveConnection(client.endpoint, credential, selection.session, None, selection.epoch,
                                    expected_peer_uid=client.expected_uid, expected_principal=selection.principal)
        except OSError:
            self.console.record(None, ERROR_TEXT[Error.DISCONNECTED])
            return
        options = ViewOptions(selection.session, show_reconnect=True)
        Watch(self.app, options, stream).present()

    def build_rail(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.append(label('LoopShell', 'shell-title'))
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
            show_surfaces(*self.windows)
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
            if not self.windows[0].get_visible():
                self.windows[0].present()

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


def run(path, layer_shell, endpoint=None, expected_uid=None):
    client = BridgeClient(endpoint, expected_uid)
    app = Gtk.Application(application_id='org.loopenvironment.LoopShell',
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(application):
        supported = (layer_shell is not None and layer_shell.is_supported()
                     and layer_shell.get_protocol_version() >= 4)
        Shell(application, path, layer_shell if supported else None, client)

    def shutdown(application):
        for window in application.get_windows():
            if isinstance(window, Watch):
                window.stop_stream()

    app.connect('activate', activate)
    app.connect('shutdown', shutdown)
    try:
        return app.run([])
    finally:
        client.close()
