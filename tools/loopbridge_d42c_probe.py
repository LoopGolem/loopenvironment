# SPDX-License-Identifier: Apache-2.0
"""Ordinary UID 1000 probes for the D4.2C Debian VM profile."""
import argparse
from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket

from loopbridge.__main__ import read_private, write_private
from loopbridge.identity import VERIFIER
from loopbridge.presentation import CAPABILITY
from loopbridge.private_session import INSTANCE_ID
from loopbridge.process_boundary import protect_process
from loopbridge.protocol import Fault, RPC
from loopbridge.service import DESKTOP_SESSION
from loopbridge.service_admin import owner_input
from loopbridge.service_ingress import peer_uid
from loopbridge.service_smoke import EPOCH, INGRESS

CLIENT_UID = 1000
SERVICE_UID = 980


def verify(condition, failure):
    if not condition:
        raise ValueError(failure)


@contextmanager
def ingress_rpc(endpoint, uid):
    with socket.socket(socket.AF_UNIX) as peer:
        peer.settimeout(3)
        peer.connect(str(endpoint))
        verify(peer_uid(peer) == uid, 'unexpected_ingress_peer')
        yield RPC(peer)


def expect_fault(rpc, message, method, **params):
    try:
        rpc.call(method, **params)
    except Fault as error:
        verify(error.message == message, method + '_unexpected_error')
    else:
        raise ValueError(method + '_unexpected_success')


def check_ingress(endpoint, uid, token, instance_id, epoch, prior_token=None):
    scope = dict(session=DESKTOP_SESSION)
    pin = dict(**scope, privateId=instance_id, epoch=epoch)
    with ingress_rpc(endpoint, uid) as rpc:
        expect_fault(rpc, 'denied', 'presentation.open', **pin)
        expect_fault(rpc, 'denied', 'auth', credential='invalid', uid=uid, principal='owner')
        expect_fault(rpc, 'denied', 'auth', credential='invalid')
        if prior_token is not None:
            expect_fault(rpc, 'denied', 'auth', credential=prior_token)
        verify(rpc.call('auth', credential=token)['principal'] == 'observer', 'unexpected_principal')
        expect_fault(rpc, 'method_not_found', 'private.list')
        expect_fault(rpc, 'method_not_found', 'private.stop', id=instance_id)
        expect_fault(rpc, 'grant_denied', 'audit', **scope)
        expect_fault(rpc, 'grant_denied', 'delegate', **scope, principal='delegate',
                     capability=CAPABILITY, target='*', ttl=1)
        expect_fault(rpc, 'grant_denied', 'acquire', **scope, ttl=1)
        expect_fault(rpc, 'grant_denied', 'session.capture', **scope)
        expect_fault(rpc, 'grant_denied', 'workspace.list', **scope, offset=0)
        wrong_epoch = ('0' if epoch[0] != '0' else '1') + epoch[1:]
        expect_fault(rpc, 'presentation_identity_mismatch', 'presentation.open',
                     **{**pin, 'epoch': wrong_epoch})
        snapshot = rpc.call('snapshot', **scope)
        verify(snapshot['session'] == DESKTOP_SESSION and snapshot['epoch'] == epoch
               and snapshot['phase'] == 'idle'
               and set(snapshot['capabilities']) == {'session.discover', CAPABILITY}
               and type(snapshot['cursor']) is int and snapshot['cursor'] > 0,
               'unexpected_snapshot')
        event_page = rpc.call('events', **scope, epoch=epoch, cursor=snapshot['cursor'] - 1)
        events = event_page['events']
        verify(event_page['epoch'] == epoch and event_page['cursor'] == snapshot['cursor']
               and len(events) == 1 and events[0]['kind'] == 'control.released'
               and events[0]['epoch'] == epoch and events[0]['seq'] == snapshot['cursor']
               and events[0]['state']['phase'] == 'idle', 'expected_authority_event_missing')
    return dict(peerUid=uid, principal='observer', event='control.released',
                cursor=event_page['cursor'], administrativeRpcDenied=True,
                captureInputAndWorkspaceDenied=True, wrongPinDenied=True,
                priorBearerDenied=prior_token is not None)


def connect(path):
    with socket.socket(socket.AF_UNIX) as peer:
        peer.settimeout(3)
        peer.connect(str(path))


def read_open(path):
    os.close(os.open(path, os.O_RDONLY | os.O_NONBLOCK))


def inaccessible(operation, path, allowed_errors):
    try:
        operation(path)
    except OSError as error:
        if error.errno in allowed_errors:
            return errno.errorcode[error.errno]
        raise ValueError('unexpected_resource_error:' + str(error.errno)) from None
    raise ValueError('unexpected_direct_access')


def check_private(instance_id, sway_pid, namespace_pid):
    run = Path('/run/loopbridge-private')
    session = run / instance_id / 'runtime/socket'
    proc = Path('/proc') / str(sway_pid)
    private_run = proc / 'root/private/run'
    sockets = {
        'manager': run / 'manager.sock', 'control': session / 'control.sock',
        'relay': session / 'relay.sock', 'wayland': private_run / 'wayland-1',
        'swayIpc': private_run / f'sway-ipc.{SERVICE_UID}.{namespace_pid}.sock',
        'dbus': private_run / 'session-bus',
    }
    files = {
        'workspace': Path('/var/lib/loopbridge/sessions') / instance_id / 'workspace',
        'verifierRegistry': Path('/var/lib/loopbridge/verifiers.json'),
        'ownerCredential': Path('/var/lib/loopbridge-admin/owner.token'),
        'credentialSource': Path('/etc/loopbridge/credentials/manager-verifiers.json'),
        'deliveredCredential': Path('/run/credentials/loopbridge.service/manager-verifiers.json'),
        'privateProcessFd': proc / 'fd',
        'privateProcessEnvironment': proc / 'environ',
    }
    denied = (errno.EACCES, errno.EPERM)
    return {**{name: inaccessible(connect, path, denied) for name, path in sockets.items()},
            **{name: inaccessible(read_open, path, denied) for name, path in files.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    generate = commands.add_parser('generate')
    generate.add_argument('--token-file', required=True, type=Path)
    live = commands.add_parser('live')
    live.add_argument('--token-file', required=True, type=Path)
    live.add_argument('--previous-token-file', type=Path)
    live.add_argument('--epoch', required=True)
    live.add_argument('--sway-pid', required=True, type=int)
    live.add_argument('--sway-namespace-pid', required=True, type=int)
    stopped = commands.add_parser('stopped')
    for command in (live, stopped):
        command.add_argument('--private-id', required=True)
    args = parser.parse_args()
    try:
        verify(os.getuid() == os.geteuid() == CLIENT_UID, 'ordinary_client_uid_required')
        protect_process()
        if args.action == 'generate':
            token = secrets.token_urlsafe(32)
            write_private(args.token_file, token)
            print(hashlib.sha256(token.encode()).hexdigest())
            return 0
        verify(INSTANCE_ID.fullmatch(args.private_id), 'invalid_private_id')
        endpoint = INGRESS / (args.private_id + '.sock')
        if args.action == 'stopped':
            report = {'publicRouteAbsent': inaccessible(connect, endpoint, (errno.ENOENT,))}
        else:
            verify(EPOCH.fullmatch(args.epoch) and args.sway_pid > 1 and args.sway_namespace_pid > 1,
                   'invalid_epoch_or_pid')
            previous = (owner_input(read_private(args.previous_token_file).encode())
                        if args.previous_token_file else None)
            token = owner_input(read_private(args.token_file).encode())
            report = check_ingress(endpoint, SERVICE_UID, token, args.private_id, args.epoch, previous)
            report['directAccessDenied'] = check_private(args.private_id, args.sway_pid, args.sway_namespace_pid)
        print(json.dumps(report, sort_keys=True))
    except (AssertionError, EOFError, Fault, KeyError, OSError, ValueError) as error:
        parser.exit(1, f'D4.2C probe failed ({type(error).__name__}): {error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
