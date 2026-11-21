# SPDX-License-Identifier: Apache-2.0
"""Read-only GTK4 viewer for one authorized private LoopBridge stream."""
import argparse
from collections import deque
from contextlib import suppress
import json
from pathlib import Path
import re
import signal
import socket
from statistics import median
import sys
import threading
import time

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk

from loopbridge.__main__ import read_private
from loopbridge.presentation import STRIDE
from loopbridge.presentation_client import LiveConnection
from loopbridge.private_effects import OUTPUT
from loopbridge.process_boundary import close_bootstrap_stdin, protect_process
from loopbridge.protocol import Fault


def motion_marker(pixels):
    # Sample the calibrated 1:1 offline fixture. Reject clipped or altered cells.
    offset = pixels.find(b'\xc5\x00\xf9')
    while offset >= 0:
        start = offset + 4 * 3 + STRIDE * 3
        if (offset % 4 == 0 and offset % STRIDE + 4 * 384 <= STRIDE
                and pixels[start + 24:start + 27] == b'\x9b\xef\x11'):
            word = 0
            for bit in range(62):
                pos = start + (bit + 2) * 24
                cell = pixels[pos:pos + 3]
                if cell == b'\xf0\xf0\xf0':
                    word |= 1 << bit
                elif cell != b'\x08\x08\x08':
                    break
            else:
                return word & 0xfffff, word >> 20
        offset = pixels.find(b'\xc5\x00\xf9', offset + 1)
    return None


def percentiles(samples):
    if not samples:
        return None
    ordered = sorted(samples)
    return dict(samples=len(ordered), median=round(median(ordered), 2),
                p95=round(ordered[(95 * len(ordered) + 99) // 100 - 1], 2))


class Watch(Gtk.ApplicationWindow):
    def __init__(self, app, args, connection):
        super().__init__(application=app, title='LoopBridge · sessão privada ao vivo')
        self.args, self.connection = args, connection
        self.set_default_size(824, 660)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, 'set_margin_' + side)(10)
        self.label = Gtk.Label(xalign=0)
        self.picture = Gtk.Picture(can_target=False, can_shrink=True, vexpand=True)
        box.append(self.label)
        box.append(self.picture)
        self.set_child(box)
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.failure = None
        self.latest = None
        self.last_packet = self.last_change = None
        self.first_paint = self.pending_paint = None
        self.draw_scheduled = False
        self.received = self.unique = self.overwritten = self.painted = self.presented = 0
        self.started = time.monotonic_ns()
        self.recent = deque()
        self.timings = deque()
        self.fixture_first = self.fixture_last = None
        self.fixture_last_capture = self.fixture_last_feedback = 0
        self.fixture_received = self.fixture_frames = 0
        self.latencies = deque(maxlen=3600)
        self.paint_latencies = deque(maxlen=3600)
        self.capture_to_receive = deque(maxlen=3600)
        self.connected = None
        self.connect('map', self.start)
        self.connect('close-request', self.close_requested)
        self.status()

    def start(self, _window):
        if hasattr(self, 'worker'):
            return
        self.worker = threading.Thread(target=self.receive, daemon=True)
        self.worker.start()
        self.get_frame_clock().connect('after-paint', self.after_paint)
        GLib.timeout_add(250, self.status)

    def close_requested(self, _window):
        self.stop.set()
        with suppress(OSError):
            self.connection.peer.shutdown(socket.SHUT_RDWR)
        return False

    def receive(self):
        last = None
        try:
            self.connection.connect()
            with self.lock:
                self.connected = time.monotonic_ns()
            for _, captured, data in self.connection.packets():
                now = time.monotonic_ns()
                marker = motion_marker(data) if data and self.args.measure_motion else None
                with self.lock:
                    self.last_packet = now
                    if data is None:
                        continue
                    self.received += 1
                    self.capture_to_receive.append((now - captured) / 1e6)
                    if marker and marker[0] > self.fixture_last_capture:
                        self.fixture_last_capture = marker[0]
                        self.fixture_received += 1
                    if data == last:
                        continue
                    last = data
                    self.unique += 1
                    self.last_change = now
                    if self.latest:
                        self.overwritten += 1
                    else:
                        GLib.idle_add(self.schedule_draw)
                    self.latest = (data, marker)
        except Fault as error:
            self.failure = error.message
        except (OSError, EOFError, ValueError, KeyError, AssertionError):
            if not self.stop.is_set():
                self.failure = self.connection.reason()
        finally:
            self.connection.peer.close()

    def schedule_draw(self):
        if not self.draw_scheduled and not self.stop.is_set():
            self.draw_scheduled = True
            self.add_tick_callback(self.draw)
        return GLib.SOURCE_REMOVE

    def draw(self, _widget, clock):
        self.draw_scheduled = False
        with self.lock:
            latest, self.latest = self.latest, None
        if latest is not None and not self.failure:
            data, marker = latest
            texture = Gdk.MemoryTexture.new(*OUTPUT, Gdk.MemoryFormat.B8G8R8X8,
                                            GLib.Bytes.new(data), STRIDE)
            self.picture.set_paintable(texture)
            self.pending_paint = (clock.get_frame_counter(), marker)
        return GLib.SOURCE_REMOVE

    def after_paint(self, _clock):
        if self.pending_paint is None:
            return
        counter, marker = self.pending_paint
        self.pending_paint = None
        now = time.monotonic_ns()
        if self.first_paint is None:
            self.first_paint = now
        self.painted += 1
        self.recent.append(now)
        wall_minus_monotonic_ms = (time.time_ns() - now) / 1e6
        self.timings.append((counter, marker, wall_minus_monotonic_ms))
        if marker and (not self.fixture_last or marker[0] > self.fixture_last[0]):
            self.fixture_first = self.fixture_first or marker
            self.fixture_last = marker
            self.fixture_frames += 1
            latency = wall_minus_monotonic_ms + now / 1e6 - marker[1]
            if 0 <= latency <= 2000:
                self.paint_latencies.append(latency)

    def feedback(self):
        clock = self.get_frame_clock()
        if clock is None:
            return
        while self.timings:
            counter, marker, offset = self.timings[0]
            timing = clock.get_timings(counter)
            if timing is not None and not timing.get_complete():
                if clock.get_frame_counter() - counter < 12:
                    break
            self.timings.popleft()
            presented = timing.get_presentation_time() if timing is not None else 0
            if presented > 0 and timing.get_complete():
                self.presented += 1
                if marker and marker[0] > self.fixture_last_feedback:
                    self.fixture_last_feedback = marker[0]
                    latency = presented / 1000 + offset - marker[1]
                    if 0 <= latency <= 2000:
                        self.latencies.append(latency)

    def report(self, state, fps):
        with self.lock:
            fixture_received = self.fixture_received
            result = dict(state=state, reason=self.failure, width=OUTPUT[0], height=OUTPUT[1],
                          received=self.received, unique=self.unique, mailboxDropped=self.overwritten,
                          duplicate=self.received - self.unique, painted=self.painted,
                          presentationFeedback=self.presented, fps=round(fps, 2),
                          captureToReceiveMs=percentiles(self.capture_to_receive),
                          appToPaintMs=percentiles(self.paint_latencies),
                          appToPresentationMs=percentiles(self.latencies),
                          handshakeMs=round((self.connected - self.started) / 1e6, 2) if self.connected else None,
                          firstPaintMs=round((self.first_paint - self.started) / 1e6, 2) if self.first_paint else None)
        if self.fixture_first and self.fixture_last[1] > self.fixture_first[1]:
            first, last = self.fixture_first, self.fixture_last
            duration = (last[1] - first[1]) / 1000
            result['motion'] = dict(sourceFrames=last[0] - first[0] + 1, painted=self.fixture_frames,
                                    missed=last[0] - first[0] + 1 - self.fixture_frames,
                                    seconds=duration, fps=round((self.fixture_frames - 1) / duration, 2),
                                    receivedSourceFrames=fixture_received)
        return result

    def status(self):
        if self.stop.is_set():
            return GLib.SOURCE_REMOVE
        self.feedback()
        now = time.monotonic_ns()
        with self.lock:
            change, packet = self.last_change, self.last_packet
        while self.recent and now - self.recent[0] > 2_000_000_000:
            self.recent.popleft()
        fps = len(self.recent) / 2
        if self.failure:
            self.picture.set_paintable(None)
            state = 'DESCONECTADO · ' + self.failure.replace('_', ' ')
        elif not self.first_paint:
            state = 'CONECTANDO'
        elif not packet or now - packet > 2_500_000_000:
            state = 'CONGELADO'
        elif now - change > 2_000_000_000:
            state = 'AO VIVO · sem mudanças'
        else:
            state = 'AO VIVO'
        latency = percentiles(self.latencies)
        delay = f" · {latency['median']:.0f} ms" if latency else ''
        self.label.set_text(f'{state} · {self.args.session}/{self.args.private_id[:8]} · '
                            f'{OUTPUT[0]}×{OUTPUT[1]} · {fps:.1f} FPS{delay}')
        if self.args.metrics_file and self.get_mapped():
            mark = self.args.metrics_file
            tmp = mark.with_suffix('.tmp')
            try:
                tmp.write_text(json.dumps(self.report(state, fps)))
                tmp.replace(mark)
            except OSError:
                pass
        return GLib.SOURCE_CONTINUE


class Viewer(Gtk.Application):
    def __init__(self, args, connection):
        super().__init__(application_id='org.loopenvironment.LoopBridgeLiveView',
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.args, self.connection = args, connection

    def do_activate(self):
        window = Watch(self, self.args, self.connection)

        def close():
            window.close()
            return GLib.SOURCE_REMOVE

        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, close)
        window.present()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True, type=Path)
    parser.add_argument('--peer-uid', type=int, help='expected Unix peer UID before authentication')
    credential = parser.add_mutually_exclusive_group(required=True)
    credential.add_argument('--token-file', type=Path)
    credential.add_argument('--token-stdin', action='store_true')
    parser.add_argument('--session', default='desktop')
    parser.add_argument('--private-id', required=True)
    parser.add_argument('--epoch', required=True)
    parser.add_argument('--measure-motion', action='store_true')
    parser.add_argument('--metrics-file', type=Path)
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{16}', args.private_id) or not re.fullmatch('[a-f0-9]{32}', args.epoch):
        parser.error('invalid private instance or epoch')
    if args.peer_uid is not None and not 0 < args.peer_uid < 0xffffffff:
        parser.error('invalid peer UID')
    protect_process()
    if args.token_stdin:
        token = sys.stdin.readline(129).strip()
        close_bootstrap_stdin()
    else:
        token = read_private(args.token_file).strip()
    connection = LiveConnection(args.socket, token, args.session, args.private_id, args.epoch,
                                expected_peer_uid=args.peer_uid)
    return Viewer(args, connection).run([])


if __name__ == '__main__':
    raise SystemExit(main())
