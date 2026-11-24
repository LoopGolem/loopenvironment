# SPDX-License-Identifier: Apache-2.0
"""Reusable GTK4 window for one authorized private LoopBridge stream."""
from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path
from statistics import median
import threading
import time

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk

from .presentation import STRIDE
from .private_effects import OUTPUT
from .protocol import Fault
from .view_status import STATE_TEXT, ViewerState, terminal_reason, viewer_state


@dataclass(frozen=True)
class ViewOptions:
    session: str
    private_id: str | None = None
    measure_motion: bool = False
    metrics_file: Path | None = None
    show_reconnect: bool = False


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
        self.label = Gtk.Label(xalign=0, wrap=True, max_width_chars=48)
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
        self.stop_stream()
        return False

    def stop_stream(self):
        self.stop.set()
        self.connection.cancel()
        with self.lock:
            self.latest = None
        if self.connected is None and not hasattr(self, 'worker'):
            self.connection.peer.close()
        self.clear_image()

    def clear_image(self):
        self.pending_paint = None
        self.picture.set_paintable(None)
        return GLib.SOURCE_REMOVE

    def fail(self, reason, *, replace=False):
        with self.lock:
            if self.stop.is_set():
                return
            if replace or not self.failure:
                self.failure = terminal_reason(reason)
            self.latest = None
        GLib.idle_add(self.clear_image)

    def receive(self):
        last = data = None
        try:
            self.connection.connect()
            with self.lock:
                if self.stop.is_set():
                    return
                self.connected = time.monotonic_ns()
            for _, captured, data in self.connection.packets():
                now = time.monotonic_ns()
                marker = motion_marker(data) if data and self.args.measure_motion else None
                with self.lock:
                    if self.stop.is_set() or self.failure:
                        return
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
            self.fail(error.message)
        except (EOFError, OSError):
            self.fail('connection_lost')
            # Drop media and clear the window before bounded status diagnostics.
            last = data = None
            self.connection.peer.close()
            if self.connected is not None and not self.stop.is_set():
                reason = self.connection.reason()
                if self.failure != 'heartbeat_timeout' or reason in (
                    'revoked', 'grant_expired', 'session_ended', 'presentation_identity_mismatch',
                ):
                    self.fail(reason, replace=True)
        except (ValueError, KeyError, TypeError, AssertionError, AttributeError):
            self.fail('invalid_presentation_response')
        finally:
            self.connection.token = None
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
            can_draw = not self.failure and not self.stop.is_set()
        if latest is not None and can_draw:
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
            state = viewer_state(now, connected=self.connected, painted=self.first_paint,
                                 packet=self.last_packet, change=self.last_change, failure=self.failure)
            failed = self.failure is not None
        if state is ViewerState.STALLED and not failed:
            self.fail('heartbeat_timeout')
            self.clear_image()
            self.connection.interrupt()
            failed = True
        while self.recent and now - self.recent[0] > 2_000_000_000:
            self.recent.popleft()
        fps = 0 if failed else len(self.recent) / 2
        text = STATE_TEXT[state]
        if failed and self.args.show_reconnect:
            text += ' · Nova autorização: session observe ' + self.args.session
        private_id = self.connection.identity['privateId'] or self.args.private_id
        identity = f'{self.args.session}/{private_id[:8]}' if private_id else self.args.session
        latency = percentiles(self.latencies)
        delay = f" · {latency['median']:.0f} ms" if latency else ''
        self.label.set_text(f'{text} · {identity} · {OUTPUT[0]}×{OUTPUT[1]} · {fps:.1f} FPS{delay}')
        if self.args.metrics_file and self.get_mapped():
            mark = self.args.metrics_file
            tmp = mark.with_suffix('.tmp')
            try:
                tmp.write_text(json.dumps(self.report(STATE_TEXT[state], fps)))
                tmp.replace(mark)
            except OSError:
                pass
        return GLib.SOURCE_CONTINUE
