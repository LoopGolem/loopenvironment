# SPDX-License-Identifier: Apache-2.0
"""GTK4 presentation of the bounded structured activity feed."""
from collections import deque
from threading import Lock, Thread

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk, Pango

from .activity import ActivityClient
from .console import ERROR_TEXT
from .errors import Error, ShellError

DISPLAY_LIMIT = 64


class ActivityPane(Gtk.Box):
    def __init__(self, endpoint, expected_uid, selection, credential, *, on_replaced=None,
                 reopen_command='session activity'):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.client = ActivityClient(endpoint, expected_uid, selection)
        self.on_replaced = on_replaced
        self.reopen_command = reopen_command
        self.credential = credential
        self.worker = None
        self.lock = Lock()
        self.rows = deque(maxlen=DISPLAY_LIMIT)
        self.closed = False
        self.render_source = 0
        self.displayed_rows = ()
        self.replaced = False
        self.follow_tail = False
        self.message = 'CONECTANDO'
        self.status = Gtk.Label(label=self.message, xalign=0, wrap=True,
                                wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=42)
        self.event_view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                       wrap_mode=Gtk.WrapMode.WORD_CHAR)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(self, 'set_margin_' + side)(8)
        self.append(self.status)
        self.scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                         overlay_scrolling=False)
        self.scroll.set_child(self.event_view)
        self.adjustment_handler = self.scroll.get_vadjustment().connect('changed', self.scroll_to_tail)
        self.append(self.scroll)
        self.connect('map', self.start)

    def start(self, _window):
        if self.worker is None and not self.closed:
            self.worker = Thread(target=self.receive, daemon=True)
            self.worker.start()

    def receive(self):
        authorized = False
        try:
            with self.lock:
                credential, self.credential = self.credential, None
            try:
                if self.client.cancelled.is_set():
                    return
                self.client.begin(credential)
            finally:
                del credential
            for events in self.client.updates():
                principal = self.client.selection.principal
                authorized = True
                change = 'atualizado' if events else 'sem novos eventos'
                self.publish(f'Autorizado · {principal} · {change} · sequência {self.client.cursor}', events)
        except ShellError as exc:
            if exc.error is Error.PERMISSION and authorized:
                message = 'Acesso perdido · grant revogado, expirado ou sessão indisponível.'
            elif exc.error is Error.DISCONNECTED:
                message = 'Conexão interrompida · estado da sessão desconhecido.'
            else:
                message = ERROR_TEXT[exc.error]
            self.publish(f'{message} Nova sincronização com {self.reopen_command} {self.client.selection.session}.',
                         clear=True, replaced=exc.error is Error.EPOCH_CHANGED)
        finally:
            self.client.close()

    def publish(self, message, events=(), *, clear=False, replaced=False):
        with self.lock:
            if self.closed:
                return
            self.message = message
            self.replaced = replaced
            if clear:
                self.rows.clear()
            self.rows.extend(events)
            if not self.render_source:
                self.render_source = GLib.idle_add(self.render)

    def render(self):
        with self.lock:
            self.render_source = 0
            if self.closed:
                return GLib.SOURCE_REMOVE
            message, rows, replaced = self.message, tuple(self.rows), self.replaced
        if replaced and self.on_replaced is not None:
            self.on_replaced()
            return GLib.SOURCE_REMOVE
        self.status.set_text(message)
        if rows == self.displayed_rows:
            return GLib.SOURCE_REMOVE
        self.displayed_rows = rows
        text = '\n'.join(f'{event.sequence}  {event.kind} · {event.phase} · revisão {event.revision}'
                         for event in rows)
        bounds = self.scroll.get_vadjustment()
        self.follow_tail = bool(rows and bounds.get_value() >= bounds.get_upper() - bounds.get_page_size() - 1)
        self.event_view.get_buffer().set_text(text)
        return GLib.SOURCE_REMOVE

    def scroll_to_tail(self, bounds):
        end = bounds.get_upper() - bounds.get_page_size()
        if self.follow_tail and end > bounds.get_lower():
            self.follow_tail = False
            # GTK may unmap the pane as new rows arrive. Use an immediate adjustment.
            bounds.set_value(end)

    def stop_polling(self):
        with self.lock:
            self.closed = True
            self.credential = None
            self.rows.clear()
            source, self.render_source = self.render_source, 0
        if source:
            GLib.source_remove(source)
        self.client.cancel()
        if self.adjustment_handler:
            self.scroll.get_vadjustment().disconnect(self.adjustment_handler)
            self.adjustment_handler = 0
        self.on_replaced = None
        self.follow_tail = False
        self.displayed_rows = ()
        self.event_view.get_buffer().set_text('')


class ActivityWindow(Gtk.ApplicationWindow):
    def __init__(self, app, endpoint, expected_uid, selection, credential):
        super().__init__(application=app, title=f'LoopShell · atividade · {selection.session}')
        self.set_default_size(560, 460)
        self.activity = ActivityPane(endpoint, expected_uid, selection, credential)
        self.activity.prepend(Gtk.Label(label=f'Sessão {selection.session}', xalign=0))
        self.set_child(self.activity)
        self.connect('close-request', self.close_requested)

    def stop_polling(self):
        self.activity.stop_polling()

    def close_requested(self, _window):
        self.stop_polling()
        return False
