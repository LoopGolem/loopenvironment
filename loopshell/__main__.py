# SPDX-License-Identifier: Apache-2.0
"""Launch the standalone LoopShell V0.8-A experiment."""
import argparse
from pathlib import Path

from .compositor import load_layer_shell
from .layout import config_path


def main():
    parser = argparse.ArgumentParser(description='LoopShell V0.8-A layout experiment')
    parser.add_argument('--config', type=Path, default=config_path(), help='layout preferences file')
    parser.add_argument('--preview', action='store_true', help='use an ordinary GTK4 window')
    args = parser.parse_args()
    shell = None if args.preview else load_layer_shell()
    try:
        from .ui import run
    except (ImportError, ValueError):
        parser.exit(1, 'LoopShell requires GTK4 and PyGObject.\n')
    return run(args.config, shell)


if __name__ == '__main__':
    raise SystemExit(main())
