# SPDX-License-Identifier: Apache-2.0
"""Independent GTK pane failures, shared invalidation and cancellation."""
import os
import unittest


@unittest.skipUnless(os.environ.get('LOOPSHELL_TEST_GTK') == '1',
                     'opt-in GTK test on a disposable display')
class CombinedWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from gi.repository import Gio
        from loopbridge.visual_view import Gtk

        Gtk.init()
        cls.app = Gtk.Application(application_id='org.loopenvironment.CombinedTest',
                                  flags=Gio.ApplicationFlags.NON_UNIQUE)
        cls.app.register(None)

    def setUp(self):
        from loopshell.bridge import SessionSelection
        from loopshell.combined_view import CombinedWindow

        self.window = CombinedWindow(self.app, '/unused.sock', os.getuid(),
                                     SessionSelection('desktop', 'a' * 32, 'observer'),
                                     'x' * 43)
        self.addCleanup(self.window.destroy)
        self.addCleanup(self.window.stop_views)

    def drain(self, pending):
        from gi.repository import GLib
        context = GLib.MainContext.default()
        for _ in range(32):
            if not pending() or not context.iteration(False):
                break
        self.assertFalse(pending())

    def paint_and_publish(self):
        from gi.repository import Gdk, GLib
        from loopshell.activity import ActivityEvent

        video, activity = self.window.video, self.window.activity
        video.picture.set_paintable(Gdk.MemoryTexture.new(1, 1, Gdk.MemoryFormat.B8G8R8X8,
                                                         GLib.Bytes.new(bytes(4)), 4))
        activity.publish('Autorizado', (ActivityEvent(1, 'state.changed', 'idle', 1),))
        self.drain(lambda: activity.render_source)

    def test_local_video_failure_clears_only_image(self):
        self.paint_and_publish()
        video, activity = self.window.video, self.window.activity
        video.fail('revoked')
        self.drain(lambda: video.draw_source)
        self.assertIn('REVOGADA', video.label.get_text())
        self.assertIsNone(video.picture.get_paintable())
        self.assertFalse(activity.closed)
        self.assertEqual(len(activity.displayed_rows), 1)
        self.assertIsNone(self.window.invalidated)

    def test_local_event_failure_clears_only_events(self):
        self.paint_and_publish()
        video, activity = self.window.video, self.window.activity
        activity.publish('Lacuna no histórico', clear=True)
        self.drain(lambda: activity.render_source)
        self.assertEqual(activity.status.get_text(), 'Lacuna no histórico')
        self.assertEqual(activity.displayed_rows, ())
        self.assertIsNotNone(video.picture.get_paintable())
        self.assertFalse(video.stop.is_set())

    def test_confirmed_end_invalidates_both_panes(self):
        from loopbridge.view_status import ViewerState

        self.paint_and_publish()
        self.window.video.fail('session_ended')
        self.drain(lambda: self.window.video.draw_source)
        self.assertEqual(self.window.invalidated, ViewerState.ENDED)
        self.assert_clean_and_cancelled('SESSÃO ENCERRADA')

    def test_validated_epoch_change_invalidates_both_panes(self):
        from loopbridge.view_status import ViewerState

        self.paint_and_publish()
        activity = self.window.activity
        activity.publish('Epoch diferente', clear=True, replaced=True)
        self.drain(lambda: activity.render_source)
        self.assertEqual(self.window.invalidated, ViewerState.REPLACED)
        self.assert_clean_and_cancelled('SESSÃO SUBSTITUÍDA')

    def test_close_cancels_queued_gtk_sources_and_drops_credential(self):
        from gi.repository import GLib

        video, activity = self.window.video, self.window.activity
        video.fail('connection_lost')
        activity.publish('Autorizado')
        sources = (video.draw_source, activity.render_source)
        self.assertTrue(all(sources))
        self.window.stop_views()
        for source in sources:
            self.assertIsNone(GLib.MainContext.default().find_source_by_id(source))
        self.assertIsNone(video.connection.token)
        self.assertIsNone(activity.credential)
        self.assertIsNone(self.window.invalidated)

    def assert_clean_and_cancelled(self, text):
        video, activity = self.window.video, self.window.activity
        self.assertIsNone(video.picture.get_paintable())
        self.assertEqual(activity.displayed_rows, ())
        self.assertTrue(video.stop.is_set() and activity.closed)
        self.assertIn(text, self.window.heading.get_text())
        self.assertIn(text, video.label.get_text())
        self.assertIn(text, activity.status.get_text())
