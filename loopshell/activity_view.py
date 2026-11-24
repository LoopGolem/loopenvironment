# SPDX-License-Identifier: Apache-2.0
"""GTK4 presentation of the bounded structured activity feed."""
from collections import deque
from threading import Lock, Thread

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk

from .activity import ActivityClient
from .console import ERROR_TEXT
from .errors import Error, ShellError

DISPLAY_LIMIT = 64


class ActivityWindow(Gtk.ApplicationWindow):
    def __init__(self, app, endpoint, expected_uid, selection, credential):
        super().__init__(application=app, title=f'LoopShell · atividade · {selection.session}')
        self.set_default_size(560, 460)
        self.client = ActivityClient(endpoint, expected_uid, selection)
        self.credential = credential
        self.worker = None
        self.lock = Lock()
        self.rows = deque(maxlen=DISPLAY_LIMIT)
        self.closed = False
        self.render_source = 0
        self.displayed_rows = ()
        self.message = 'CONECTANDO'
        self.status = Gtk.Label(label=self.message, xalign=0, wrap=True, max_width_chars=42)
        self.event_view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                       wrap_mode=Gtk.WrapMode.WORD_CHAR)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, 'set_margin_' + side)(8)
        box.append(Gtk.Label(label=f'Sessão {selection.session}', xalign=0))
        box.append(self.status)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(self.event_view)
        box.append(scroll)
        self.set_child(box)
        self.connect('map', self.start)
        self.connect('close-request', self.close_requested)

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
            self.publish(f'{message} Nova sincronização com session activity {self.client.selection.session}.',
                         clear=True)
        finally:
            self.client.close()

    def publish(self, message, events=(), *, clear=False):
        with self.lock:
            if self.closed:
                return
            self.message = message
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
            message, rows = self.message, tuple(self.rows)
        self.status.set_text(message)
        if rows == self.displayed_rows:
            return GLib.SOURCE_REMOVE
        self.displayed_rows = rows
        text = '\n'.join(f'{event.sequence:>7}  {event.kind} · {event.phase} · revisão {event.revision}'
                         for event in rows)
        buffer = self.event_view.get_buffer()
        buffer.set_text(text)
        buffer.place_cursor(buffer.get_end_iter())
        self.event_view.scroll_mark_onscreen(buffer.get_insert())
        return GLib.SOURCE_REMOVE

    def stop_polling(self):
        with self.lock:
            self.closed = True
            self.credential = None
            self.rows.clear()
            source, self.render_source = self.render_source, 0
        if source:
            GLib.source_remove(source)
        self.client.cancel()
        self.displayed_rows = ()
        self.event_view.get_buffer().set_text('')

    def close_requested(self, _window):
        self.stop_polling()
        return False
