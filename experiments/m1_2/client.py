# SPDX-License-Identifier: Apache-2.0
"""Adversarial lab client, executed ONLY inside the explicit Bubblewrap profile."""
import json
import socket
import sys
import time
from protocol import Fault, RPC
from probe import inspect


def expect_fault(code, operation):
    try:
        operation()
    except Fault as error:
        assert error.code == code, 'unexpected_denial'
        return error.message
    raise AssertionError('operation_not_rejected')


def connect():
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(20)
    sock.connect('/bridge/control.sock')
    return sock, RPC(sock)


def run(config, result):
    result.update( {'isolation_before_auth': inspect(config)})
    sock, rpc = connect()
    with sock:
        if config['mode'] == 'denied':
            result['bad_credential'] = expect_fault(-32001, lambda: rpc.call('auth', credential='not-enrolled'))
            result['read_denied'] = expect_fault(-32001, lambda: rpc.call('snapshot'))
            result['write_denied'] = expect_fault(-32001, lambda: rpc.call('invoke7', reference='guessed'))
            result['events_denied'] = expect_fault(-32001, lambda: rpc.call('events', epoch='guessed', cursor=0))
            return result
        assert rpc.call('auth', credential=config['credential'])['authorized']
        result['isolation_with_valid_grant'] = inspect(config, sock.fileno())
        snapshot = rpc.call('snapshot')
        initial = snapshot['state']
        assert all(v in ('', '0') for v in initial.values())
        result['cross_scope'] = expect_fault(-32002, lambda: rpc.call('invoke7', reference='another-session-or-target'))
        result['unsupported_method'] = expect_fault(-32601, lambda: rpc.call('raw.session', path='ignored'))
        time.sleep(snapshot['reference_ttl'] + .1)
        result['expired_reference'] = expect_fault(-32002, lambda: rpc.call('invoke7', reference=snapshot['reference']))
        fresh = rpc.call('snapshot')
        assert fresh['state'] == initial, 'denied_action_changed_state'
        assert rpc.call('invoke7', reference=fresh['reference'])['confirmed']
        first = rpc.call('events', epoch=fresh['epoch'], cursor=fresh['cursor'])
        assert len(first['events']) == 1 and first['events'][0]['seq'] == fresh['cursor']+1
        assert '7' in first['events'][0]['state'].values()
        result['first_event'] = first['events'][0]
        # Overflow a real two-event history with three confirmed UI changes.
        for _ in range(2):
            assert rpc.call('invoke7', reference=fresh['reference'])['confirmed']
        result['gap'] = expect_fault(-32003, lambda: rpc.call('events', epoch=fresh['epoch'], cursor=fresh['cursor']))
        result['epoch_mismatch'] = expect_fault(-32004, lambda: rpc.call('events', epoch='previous-broker-epoch', cursor=0))
        recovered = rpc.call('snapshot')
        assert '777' in recovered['state'].values()
        assert rpc.call('events', epoch=recovered['epoch'], cursor=recovered['cursor'])['events'] == []
        result['snapshot_recovery'] = dict(state=recovered['state'], cursor=recovered['cursor'])
        disconnected_reference = recovered['reference']
        cursor, epoch = recovered['cursor'], recovered['epoch']
    sock, rpc = connect()
    with sock:
        assert rpc.call('auth', credential=config['credential'])['authorized']
        result['disconnected_reference'] = expect_fault(-32002, lambda: rpc.call('invoke7', reference=disconnected_reference))
        result['resubscribe_required'] = expect_fault(-32004, lambda: rpc.call('events', epoch=epoch, cursor=cursor))
        final = rpc.call('snapshot')
        assert final['state'] == recovered['state']
        assert rpc.call('invoke7', reference=final['reference'])['confirmed']
        resumed = rpc.call('events', epoch=final['epoch'], cursor=final['cursor'])
        assert resumed['events'][0]['seq'] == final['cursor'] + 1
        assert '7777' in resumed['events'][0]['state'].values()
        result['reconnected_event'] = resumed['events'][0]
    return result


if __name__ == '__main__':
    try:
        result = {}
        run(json.load(sys.stdin), result)
        print(json.dumps(dict(ok=True, checks=result)))
    except Exception as error:
        # Never echo provisioning input, token, arbitrary error strings or paths.
        print(json.dumps(dict(ok=False, failure=type(error).__name__, checks=result,
                             fault=error.message if isinstance(error, Fault) else None)))
        raise SystemExit(1)
