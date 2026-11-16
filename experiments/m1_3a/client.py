# SPDX-License-Identifier: Apache-2.0
"""Identical sandbox client for every principal; stdin/stdout are private pipes."""
import json
import socket
import sys
sys.path.insert(0, '/app')  # Read-only M1.2 wire/probe modules from the reused profile.
from protocol import RPC, Fault
from probe import inspect


def main():
    config = json.loads(sys.stdin.readline())
    before = inspect(config)
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(20)
    sock.connect('/bridge/control.sock')
    with sock:
        rpc = RPC(sock)
        try:
            auth = rpc.call('auth', credential=config['credential'])
        except Fault as error:
            auth = dict(denied=error.message)
        print(json.dumps(dict(auth=auth, before=before, after=inspect(config, sock.fileno()))), flush=True)
        for line in sys.stdin:
            command = json.loads(line)
            try:
                value = rpc.call(command['method'], **command['params'])
                print(json.dumps(dict(result=value)), flush=True)
            except Fault as error:
                print(json.dumps(dict(error=error.message)), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print(json.dumps(dict(failure='client_failed')), flush=True)
        raise SystemExit(1)
