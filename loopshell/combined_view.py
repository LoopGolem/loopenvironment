# SPDX-License-Identifier: Apache-2.0
"""One session selection with independent visual and activity panes."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Pango

from loopbridge.presentation_client import LiveConnection
from loopbridge.view_status import STATE_TEXT, ViewerState
from loopbridge.visual_view import ViewOptions, VisualPane

from .activity_view import ActivityPane


class CombinedWindow(Gtk.ApplicationWindow):
    def __init__(self, app, endpoint, expected_uid, selection, credential):
        super().__init__(application=app, title=f'LoopShell · Combined · {selection.session}')
        self.set_default_size(824, 660)
        self.invalidated = None
        self.selection = selection
        command = 'session combined'
        connection = LiveConnection(endpoint, credential, selection.session, selection.private_id,
                                    selection.epoch, expected_peer_uid=expected_uid,
                                    expected_principal=selection.principal)
        self.video = VisualPane(ViewOptions(selection.session, show_reconnect=True, reopen_command=command),
                                connection, on_invalidated=self.invalidate)
        self.activity = ActivityPane(endpoint, expected_uid, selection, credential,
                                     reopen_command=command, on_replaced=self.activity_replaced)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.heading = Gtk.Label(label=f'Sessão {selection.session} · {selection.principal}',
                                 wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)
        content.append(self.heading)
        self.video.prepend(Gtk.Label(label='Vídeo', xalign=0))
        self.activity.prepend(Gtk.Label(label='Atividade', xalign=0))
        self.activity.scroll.set_min_content_height(72)
        split = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL, wide_handle=True, vexpand=True,
                          start_child=self.video, end_child=self.activity,
                          resize_start_child=True, resize_end_child=False,
                          shrink_start_child=False, shrink_end_child=False)
        content.append(split)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(content)
        self.set_child(scroll)
        self.connect('close-request', self.close_requested)

    def activity_replaced(self):
        self.invalidate(ViewerState.REPLACED)

    def invalidate(self, state):
        # Only validated identity or lifecycle results reach this callback.
        if self.invalidated is not None:
            return
        self.invalidated = state
        self.stop_views()
        text = STATE_TEXT[state]
        self.heading.set_text(f'Sessão {self.selection.session} · {text}')
        self.video.label.set_text(text)
        self.activity.status.set_text(f'{text} · Nova autorização com session combined {self.selection.session}')

    def stop_views(self):
        self.video.stop_stream()
        self.activity.stop_polling()

    def close_requested(self, _window):
        self.stop_views()
        return False
