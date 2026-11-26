# SPDX-License-Identifier: Apache-2.0
"""Reference client for the experimental LoopBridge workspace-effect profile."""
import argparse
from getpass import GetPassWarning, getpass
import json
import os
import socket
import sys
import warnings

from experiments.workspace_document import CAPABILITY, MAX_CONTENT
from experiments.workspace_effect_lab import VERSION
from loopbridge.protocol import Fault, RPC
from loopbridge.service_ingress import peer_identity


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument('--socket', required=True)
    root.add_argument('--service', nargs=3, type=int, metavar=('PID', 'UID', 'GID'),
                      help='expected kernel service identity for explicitly provisioned cross-UID ingress')
    commands = root.add_subparsers(dest='command', required=True)
    authorize = commands.add_parser('authorize', help='read the UTF-8 document from standard input')
    for field in ('attempt_id', 'executor_id', 'objective_id'):
        authorize.add_argument(field)
    authorize.add_argument('accepted_revision', type=int)
    authorize.add_argument('resource_id')
    authorize.add_argument('request_id')
    authorize.add_argument('ttl_seconds', type=int)
    commands.add_parser('status').add_argument('attempt_id')
    audit = commands.add_parser('audit')
    audit.add_argument('attempt_id')
    audit.add_argument('--after-revision', type=int, default=0)
    for name in ('step', 'continue', 'pause', 'cancel'):
        command = commands.add_parser(name)
        command.add_argument('attempt_id')
        command.add_argument('expected_revision', type=int)
        command.add_argument('request_id')
    return root


def main(argv=None):
    arguments = parser()
    params = vars(arguments.parse_args(argv))
    identity = params.pop('service')
    if identity is not None and (identity[0] <= 1 or any(not 0 < n < 0xffffffff for n in identity)):
        arguments.error('supply the expected non-root service PID, UID and GID')
    endpoint, command = params.pop('socket'), params.pop('command')
    try:
        if command == 'authorize':
            data = sys.stdin.buffer.read(MAX_CONTENT + 1)
            if not 0 < len(data) <= MAX_CONTENT:
                print('invalid_content_size', file=sys.stderr)
                return 1
            params.update(capability=CAPABILITY, content=data.decode('utf-8'))
        with socket.socket(socket.AF_UNIX) as peer:
            peer.settimeout(5)
            peer.connect(endpoint)
            observed = peer_identity(peer)
            if (identity is None and observed[1] != os.getuid()) or (identity and observed != tuple(identity)):
                print('unexpected_service_identity', file=sys.stderr)
                return 1
            rpc = RPC(peer, VERSION, timeout=5)
            with warnings.catch_warnings():
                warnings.simplefilter('error', GetPassWarning)
                rpc.call('auth', credential=getpass('Credential: '))
            result = rpc.call(f'effect.{command}', **params)
    except UnicodeError:
        print('invalid_utf8', file=sys.stderr)
        return 1
    except Fault as error:
        print(f'RPC error {error.code} ({error.message})', file=sys.stderr)
        return 1
    except GetPassWarning:
        print('masked_terminal_required', file=sys.stderr)
        return 1
    except (AssertionError, EOFError, OSError):
        print('workspace_effect_transport_failed', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
