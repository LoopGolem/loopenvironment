# SPDX-License-Identifier: Apache-2.0
"""External demo client entry point mounted in the M1.2 sandbox."""
import json
import sys

from loopbridge.__main__ import rpc_stream
from probe import inspect


def main():
    config = json.loads(sys.stdin.readline(16384))
    probes = inspect(config)
    print(json.dumps(probes), flush=True)
    return rpc_stream('/bridge/control.sock', config['credential'], sys.stdin, sys.stdout)


if __name__ == '__main__':
    raise SystemExit(main())
