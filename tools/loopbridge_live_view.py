# SPDX-License-Identifier: Apache-2.0
"""Read-only GTK4 viewer for one authorized private LoopBridge stream."""
import argparse
from pathlib import Path
import re
import signal
import sys

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk

from loopbridge.__main__ import read_private
from loopbridge.presentation_client import LiveConnection
from loopbridge.process_boundary import close_bootstrap_stdin, protect_process
from loopbridge.visual_view import ViewOptions, Watch


class Viewer(Gtk.Application):
    def __init__(self, args, connection):
        super().__init__(application_id='org.loopenvironment.LoopBridgeLiveView',
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.args, self.connection = args, connection

    def do_activate(self):
        options = ViewOptions(self.args.session, self.args.private_id,
                              self.args.measure_motion, self.args.metrics_file)
        window = Watch(self, options, self.connection)

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
