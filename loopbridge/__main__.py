# SPDX-License-Identifier: Apache-2.0
"""Trusted lab provisioning, local service and interactive RPC client."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import stat
import sys
import threading

from .identity import Identities, PRINCIPALS
from .protocol import Fault, RPC, VERSION


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(data + '\n')


def provision(folder):
    folder.mkdir(mode=0o700)
    credentials = Identities().provision()
    write_private(folder / 'service.json', json.dumps(credentials))
    for principal in PRINCIPALS:
        write_private(folder / (principal + '.token'), credentials[principal])


def read_private(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'r') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError('unsafe_credential_file')
        return stream.read(4097)


def service(args):
    from .service import serve
    identities = Identities()
    identities.load(json.loads(read_private(args.credentials)))
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    with serve(args.runtime, identities, args.mode, args.workspace):
        print('ready', flush=True)
        stop.wait()


def rpc_stream(endpoint, credential, input_stream, output_stream, version=VERSION):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(30)
        sock.connect(endpoint)
        rpc = RPC(sock, version)
        try:
            result = rpc.call('auth', credential=credential)
        except Fault as error:
            print(json.dumps({'error': error.message}), file=output_stream, flush=True)
            return 1
        print(json.dumps({'result': result}), file=output_stream, flush=True)
        for line in iter(lambda: input_stream.readline(8193), ''):
            if len(line) > 8192:
                raise ValueError('frame_limit')
            request = json.loads(line)
            try:
                response = {'result': rpc.call(request['method'], **request.get('params', {}))}
            except Fault as error:
                response = {'error': error.message}
            print(json.dumps(response), file=output_stream, flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    setup = subparsers.add_parser('provision')
    setup.add_argument('directory', type=Path)
    daemon = subparsers.add_parser('serve')
    daemon.add_argument('--runtime', type=Path, required=True)
    daemon.add_argument('--credentials', type=Path, required=True)
    daemon.add_argument('--mode', choices=('desktop', 'calculator', 'fixture'), default='desktop')
    daemon.add_argument('--workspace', type=Path)
    client = subparsers.add_parser('client')
    client.add_argument('--socket', required=True)
    client.add_argument('--token-file', type=Path)
    teacher = subparsers.add_parser('teach')
    teacher.add_argument('--socket', required=True)
    teacher.add_argument('--token-file', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'provision':
            provision(args.directory)
        elif args.command == 'serve':
            service(args)
        elif args.command == 'teach':
            from .teach_cli import teach
            with socket.socket(socket.AF_UNIX) as sock:
                sock.settimeout(30)
                sock.connect(args.socket)
                rpc = RPC(sock)
                rpc.call('auth', credential=read_private(args.token_file).rstrip('\n'))
                return teach(rpc, input, sys.stdout)
        else:
            credential = (read_private(args.token_file) if args.token_file
                          else sys.stdin.readline(129)).rstrip('\n')
            return rpc_stream(args.socket, credential, sys.stdin, sys.stdout)
    except Fault as error:
        print('loopbridge: ' + error.message, file=sys.stderr)
        return 1
    except (OSError, RuntimeError, EOFError, ValueError, KeyError, TypeError, RecursionError):
        print('loopbridge: startup, transport or input failed', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
