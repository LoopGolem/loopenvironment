# SPDX-License-Identifier: Apache-2.0
"""Reference command-line client for the local D.2B experimental profile."""
import argparse
from getpass import GetPassWarning, getpass
import json
import os
import socket
import sys
import warnings

from experiments.supervision_lab import PLAN, VERSION
from loopbridge.protocol import Fault, RPC
from loopbridge.service_ingress import peer_identity


def parser():
    root = argparse.ArgumentParser(
        description=__doc__,
        epilog='Control commands return receipts at the recorded revision. status reads the current progress snapshot.',
    )
    root.add_argument('--socket', required=True)
    for key in ('uid', 'gid', 'pid'):
        root.add_argument(f'--service-{key}', type=int,
                          help=f'Expected kernel service {key.upper()} from the approved harness')
    commands = root.add_subparsers(dest='command', required=True)
    authorize = commands.add_parser('authorize')
    authorize.add_argument('executor_id')
    authorize.add_argument('objective_id')
    authorize.add_argument('accepted_revision', type=int)
    authorize.add_argument('request_id')
    authorize.add_argument('ttl_seconds', type=int)
    authorize.set_defaults(operation=PLAN)
    for command in ('status', 'audit', 'start', 'pause', 'step', 'continue', 'cancel'):
        action = commands.add_parser(command)
        action.add_argument('attempt_id')
        if command not in ('status', 'audit'):
            action.add_argument('expected_revision', type=int)
            action.add_argument('request_id')
    return root


def main(argv=None):
    arguments = parser()
    params = vars(arguments.parse_args(argv))
    identity = tuple(params.pop(f'service_{key}') for key in ('pid', 'uid', 'gid'))
    if identity == (None, None, None):
        identity = None
    elif any(value is None or not 0 < value < 0xffffffff for value in identity) or identity[0] == 1:
        arguments.error('supply a complete non-root service PID, UID and GID')
    endpoint = params.pop('socket')
    command = params.pop('command')
    try:
        with socket.socket(socket.AF_UNIX) as peer:
            peer.settimeout(5)
            peer.connect(endpoint)
            observed = peer_identity(peer)
            if (identity is None and observed[1] != os.getuid()) or (identity is not None and observed != identity):
                print('unexpected_service_uid' if identity is None else 'unexpected_service_identity',
                      file=sys.stderr)
                return 1
            rpc = RPC(peer, VERSION, timeout=5)
            with warnings.catch_warnings():
                warnings.simplefilter('error', GetPassWarning)
                rpc.call('auth', credential=getpass('Credential: '))
            result = rpc.call(f'execution.{command}', **params)
    except Fault as error:
        print(f'RPC error {error.code}: {error.message}', file=sys.stderr)
        return 1
    except GetPassWarning:
        print('masked_terminal_required', file=sys.stderr)
        return 1
    except (AssertionError, EOFError, OSError):
        print('execution_transport_failed', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
