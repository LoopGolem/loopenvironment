# SPDX-License-Identifier: Apache-2.0
"""External demo client entry point mounted in the M1.2 sandbox."""
import errno
import json
import os
import sys

from loopbridge.__main__ import rpc_stream
from probe import inspect


def main():
    config = json.loads(sys.stdin.readline(16384))
    probes = inspect(config)
    private_denials = 0
    for path in config.get('private_paths', []):
        for candidate in (path, '/proc/1/root' + path):
            try:
                descriptor = os.open(candidate, os.O_RDONLY | os.O_NONBLOCK)
            except OSError as error:
                if error.errno not in (errno.ENOENT, errno.EACCES):
                    raise
                private_denials += 1
            else:
                os.close(descriptor)
                raise AssertionError('private_path_visible')
    probes['private_paths_denied'] = private_denials
    print(json.dumps(probes), flush=True)
    return rpc_stream('/bridge/control.sock', config['credential'], sys.stdin, sys.stdout)


if __name__ == '__main__':
    raise SystemExit(main())
