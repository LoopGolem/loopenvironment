# SPDX-License-Identifier: Apache-2.0
"""Launch the standalone LoopShell client."""
import argparse
from pathlib import Path

from loopbridge.process_boundary import protect_process

from .compositor import load_layer_shell
from .layout import config_path


def main():
    parser = argparse.ArgumentParser(description='LoopShell V0.8-B.1 read-only console')
    parser.add_argument('--config', type=Path, default=config_path(), help='layout preferences file')
    parser.add_argument('--preview', action='store_true', help='use an ordinary GTK4 window')
    parser.add_argument('--socket', type=Path, help='absolute path to the LoopBridge client socket')
    parser.add_argument('--peer-uid', type=int, help='expected Linux UID of the socket peer')
    args = parser.parse_args()
    if args.socket is not None and not args.socket.is_absolute():
        parser.error('--socket requires an absolute path')
    if args.peer_uid is not None and (args.socket is None or not 0 <= args.peer_uid < 2**32 - 1):
        parser.error('--peer-uid requires --socket and a valid Linux UID')
    if args.socket is not None:
        try:
            protect_process()
        except OSError:
            parser.exit(1, "LoopShell could not protect its credential process.\n")
    shell = None if args.preview else load_layer_shell()
    try:
        from .ui import run
    except (ImportError, ValueError):
        parser.exit(1, 'LoopShell requires GTK4 and PyGObject.\n')
    return run(args.config, shell, args.socket, args.peer_uid)


if __name__ == '__main__':
    raise SystemExit(main())
