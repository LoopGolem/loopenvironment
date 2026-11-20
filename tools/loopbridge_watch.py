# SPDX-License-Identifier: Apache-2.0
"""Show one authorized private LoopBridge desktop in a local GTK4 window."""
import argparse
import json
from pathlib import Path
import re
import threading
import time

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk

from loopbridge.__main__ import read_private
from loopbridge.protocol import Fault
from .loopbridge_view import capture_frame


class WatchWindow(Gtk.ApplicationWindow):
    def __init__(self, app, args, token):
        super().__init__(application=app, title='LoopBridge · observação do desktop privado')
        self.args, self.token = args, token
        self.stop = threading.Event()
        self.last_frame = None
        self.failure = None
        self.frames = self.changes = 0
        self.digest = None
        self.set_default_size(824, 680)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, 'set_margin_' + side)(10)
        self.status = Gtk.Label(xalign=0)
        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(True)
        self.picture.set_vexpand(True)
        box.append(self.status)
        box.append(self.picture)
        self.set_child(box)
        self.connect('close-request', self.close_requested)
        self.connect('map', self.start_polling)
        self.update_status()

    def start_polling(self, _window):
        if not hasattr(self, 'worker'):
            GLib.timeout_add(250, self.update_status)
            self.worker = threading.Thread(target=self.poll, name='loopbridge-watch', daemon=True)
            self.worker.start()

    def close_requested(self, _window):
        self.stop.set()
        return False

    def poll(self):
        epoch = None
        while not self.stop.is_set():
            started = time.monotonic()
            frame, failure = None, None
            try:
                frame = capture_frame(str(self.args.socket), self.token, self.args.session,
                                      self.args.expected_private_id, epoch)
                epoch = frame['epoch']
            except Fault as error:
                if error.message in ('stale_reference', 'snapshot_required', 'capture_expired',
                                     'private_scene_changed', 'capture_response_limit'):
                    failure = 'transient'
                else:
                    failure = 'disconnected'
            except (OSError, EOFError, ValueError, KeyError, AssertionError):
                failure = 'disconnected'
            rendered = threading.Event()
            GLib.idle_add(self.present_sample, frame, failure, rendered)
            # Keep one sample in flight even if the graphical session is stalled.
            while not rendered.wait(.25):
                if self.stop.is_set():
                    return
            self.stop.wait(max(.05, self.args.interval - (time.monotonic() - started)))

    def present_sample(self, frame, failure, rendered):
        try:
            if self.stop.is_set():
                return GLib.SOURCE_REMOVE
            self.failure = failure
            if frame:
                try:
                    texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(frame['data']))
                except GLib.Error:
                    self.failure = 'transient'
                else:
                    self.picture.set_paintable(texture)
                    self.last_frame = time.monotonic()
                    self.frames += 1
                    self.changes += self.digest != frame['sha256']
                    self.digest = frame['sha256']
                    if self.args.ready_file and self.get_mapped():
                        mark = self.args.ready_file
                        tmp = mark.with_suffix('.tmp')
                        try:
                            tmp.write_text(json.dumps(dict(privateId=frame['privateId'],
                                capturedAt=frame['capturedAt'], revision=frame['revision'],
                                monotonic=self.last_frame, frames=self.frames,
                                changes=self.changes, width=texture.get_width(),
                                height=texture.get_height())))
                            tmp.replace(mark)
                        except OSError:
                            pass
            if self.failure == 'disconnected':
                self.picture.set_paintable(None)
            self.update_status()
            return GLib.SOURCE_REMOVE
        finally:
            rendered.set()

    def update_status(self):
        if self.stop.is_set():
            return GLib.SOURCE_REMOVE
        age = None if self.last_frame is None else time.monotonic() - self.last_frame
        if self.failure == 'disconnected':
            state = 'DESCONECTADO'
        elif age is None:
            state = 'CONECTANDO'
        elif age > max(2.5, self.args.interval * 2.5):
            state = 'CONGELADO'
        else:
            state = 'AO VIVO · 800×600'
        suffix = '' if age is None else f' · último quadro há {age:.1f} s'
        self.status.set_text(f'{state} · instância {self.args.expected_private_id}{suffix}')
        return GLib.SOURCE_CONTINUE


class WatchApp(Gtk.Application):
    def __init__(self, args, token):
        super().__init__(application_id='org.loopenvironment.LoopBridgeWatch',
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.args, self.token = args, token

    def do_activate(self):
        WatchWindow(self, self.args, self.token).present()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True, type=Path)
    parser.add_argument('--token-file', required=True, type=Path,
                        help='observer credential with desktop.capture')
    parser.add_argument('--session', default='desktop')
    parser.add_argument('--expected-private-id', required=True)
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--ready-file', type=Path, help='temporary metadata for a supervising demo')
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{16}', args.expected_private_id):
        parser.error('invalid private instance ID')
    if not 0.5 <= args.interval <= 5:
        parser.error('--interval must be 0.5–5 seconds')
    token = read_private(args.token_file).rstrip('\n')
    return WatchApp(args, token).run([])


if __name__ == '__main__':
    raise SystemExit(main())
