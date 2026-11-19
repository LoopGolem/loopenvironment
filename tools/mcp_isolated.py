# SPDX-License-Identifier: Apache-2.0
"""Run real host-endpoint denials, then replace this process with MCP stdio."""
import json
import os
from pathlib import Path
import sys

from probe import inspect


def main():
    settings = json.loads(Path('/identity/checks.json').read_text())
    inspect(settings)
    for path in settings['private_paths']:
        if os.path.exists(path) or os.path.exists('/proc/1/root' + path):
            raise RuntimeError('private_path_exposed')
    os.execv(sys.executable, [sys.executable, '-B', '-m', 'loopbridge.mcp',
                             '--socket', '/bridge/control.sock', '--token-file', '/identity/token'])


if __name__ == '__main__':
    main()
