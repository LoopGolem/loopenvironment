# SPDX-License-Identifier: Apache-2.0
"""Open a real private desktop on the main Wayland desktop and measure local presentation."""
import argparse
from contextlib import ExitStack, closing
import json
import os
from pathlib import Path
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

from loopbridge.__main__ import provision, read_private
from loopbridge.browser import process_tree
from loopbridge.presentation import CAPABILITY
from loopbridge.presentation_client import LiveConnection
from loopbridge.private_session import terminate
from loopbridge.protocol import Fault, RPC
from loopbridge.service import DESKTOP_SESSION, Journal
from experiments.m1_2.probe import connect

from .loopbridge_demo import Process, check, endpoints, launch
from .loopbridge_desktop_demo import SESSION, grant, writable
from .loopbridge_private_demo import connect_rpc, denied, namespaced_process, sockets


def eventually(callback, description, timeout=8):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            result = callback()
        except (FileNotFoundError, ProcessLookupError, json.JSONDecodeError):
            result = None
        if result:
            return result
        time.sleep(.05)
    raise RuntimeError(description)


def read_metrics(path, predicate):
    row = json.loads(path.read_text())
    return row if predicate(row) else None


def operator_confirmed(prompt, owner):
    print(prompt, flush=True)
    until = time.monotonic() + 45
    while time.monotonic() < until:
        if select.select([sys.stdin], [], [], 5)[0]:
            return sys.stdin.readline().strip().lower() == 'yes'
        owner.call('presentation.describe', **SESSION)
    return False


def start_window(stack, command):
    process = subprocess.Popen([sys.executable, '-B', '-m', *map(str, command)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               env={**os.environ, 'GDK_BACKEND': 'wayland'})
    stack.callback(terminate, process)
    return process


def media_children(manager, folder):
    namespace = json.loads((folder / 'display/boundary.json').read_text())['pid']
    rows = []
    for pid, row in process_tree(manager).items():
        if Path(row[3]).name == 'stream':
            try:
                if os.readlink(f'/proc/{pid}/ns/pid') == namespace:
                    rows.append(pid)
            except FileNotFoundError:
                pass
    return rows


def process_counters(pid):
    path = Path(f'/proc/{pid}')
    fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
    status = (path / 'status').read_text().splitlines()
    rss = next(int(line.split()[1]) for line in status if line.startswith('VmRSS:'))
    return (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK'), rss / 1024


def resource_sample(pids, seconds):
    start = time.monotonic()
    before = {key: process_counters(pid)[0] for key, pid in pids.items()}
    time.sleep(seconds)
    elapsed = time.monotonic() - start
    return {key: dict(cpuOneCorePct=round((cpu - before[key]) / elapsed * 100, 2),
                      rssMiB=round(rss, 2)) for key, (cpu, rss) in
            ((key, process_counters(pid)) for key, pid in pids.items())}


def borrow_media(stack, instance, pin, token):
    live = LiveConnection(instance['socket'], token, DESKTOP_SESSION, pin['privateId'], pin['epoch'])
    stack.enter_context(closing(live.peer))
    live.connect()
    packets = live.packets()
    check(next(packets)[2] is not None)
    return live, packets


def connection_closed(packets):
    try:
        for _ in range(8):
            next(packets)
    except (EOFError, ConnectionResetError):
        return True
    return False


def negative_checks(stack, admin, a, b, owner, token, pin, controller, manager, folder,
                    compositor, viewer_command, initial_grant, evidence):
    identity = {key: pin[key] for key in ('session', 'privateId', 'epoch')}
    checks = evidence['negative'] = {}
    evidence['stage'] = 'same_uid_authorization'
    # Both peers use the lab UID and the same reachable control socket.
    with closing(socket.socket(socket.AF_UNIX)) as peer:
        peer.connect(a['socket'])
        denied('denied', RPC(peer).call, 'presentation.open', **identity)
    checks['sameUidUnauthenticatedDenied'] = True
    read_only = connect_rpc(stack, a['socket'], token('delegate'))
    for cap in ('session.discover', 'desktop.observe', 'desktop.capture'):
        grant(owner, 'delegate', cap)
    denied('grant_denied', read_only.call, 'presentation.open', **identity)
    checks['discoverObserveAndCaptureDoNotGrantStream'] = True
    other = connect_rpc(stack, b['socket'], token('owner'))
    other_pin = other.call('presentation.describe', **SESSION)
    sibling_observer = connect_rpc(stack, b['socket'], token('observer'))
    denied('grant_denied', sibling_observer.call, 'presentation.open',
           **{key: other_pin[key] for key in identity})
    checks['grantDoesNotCrossSession'] = True
    denied('presentation_identity_mismatch', other.call, 'presentation.open', **identity)
    denied('presentation_identity_mismatch', owner.call, 'presentation.open',
           **{**identity, 'epoch': other_pin['epoch']})
    checks['stalePrivateIdAndEpochDenied'] = True

    evidence['stage'] = 'isolated_observer'
    observer = connect_rpc(stack, a['socket'], token('observer'))
    denied('grant_denied', observer.call, 'session.capture', **SESSION)
    denied('grant_denied', observer.call, 'acquire', ttl=2, **SESSION)
    denied('grant_denied', observer.call, 'window.list', app='browser', **SESSION)
    denied('grant_denied', observer.call, 'delegate', **SESSION, principal='delegate',
           capability=CAPABILITY, target='*', ttl=2)
    checks['streamDoesNotGrantCaptureInspectOrLease'] = True
    host_endpoints = endpoints()
    proc = Path(f'/proc/{compositor}')
    inner_pid = next(line.split()[-1] for line in (proc / 'status').read_text().splitlines()
                     if line.startswith('NSpid:'))
    private_paths = {'private_wayland': '/private/run/wayland-1',
                     'private_sway': f'/private/run/sway-ipc.{os.getuid()}.{inner_pid}.sock',
                     'private_dbus': '/private/run/session-bus'}
    proc_paths = {name: str(proc / 'root') + path for name, path in private_paths.items()}
    checks['sameUidHostProcAccess'] = {name: connect(path)['connected'] for name, path in proc_paths.items()}
    checks['sameUidCanReadLabCredentialFile'] = os.access(folder.parents[1] / 'cred/observer.token', os.R_OK)
    agent, probes, auth = launch(stack, Path(a['socket']).parent,
                                 {**host_endpoints, **private_paths,
                                  **{'host_proc_' + key: path for key, path in proc_paths.items()}},
                                 token('observer'), manager, (str(folder),))
    check(auth['result']['principal'] == 'observer')
    agent.denied('grant_denied', 'session.capture', **SESSION)
    checks['isolatedObserver'] = dict(endpointsDenied=len(probes['endpoints']),
                                    privatePathsDenied=probes['private_paths_denied'],
                                    inheritedSockets=probes['inherited_socket_count'],
                                    visibleDevices=probes['exposed_device_count'],
                                    namespaces=probes['private_namespaces'])
    check(not sockets(folder / 'display'))
    check(set(sockets(folder / 'runtime/socket')) == {'control.sock'})
    checks['noMediaOrDisplayListenerInExposedRuntime'] = True

    evidence['stage'] = 'media_revocation'
    live_grant = grant(owner, 'observer', CAPABILITY)
    live, packets = borrow_media(stack, a, pin, token('observer'))
    stream = live.metadata['stream']
    denied('presentation_unavailable', read_only.call, 'presentation.status', **identity, stream=stream)
    start = time.monotonic()
    owner.call('revoke', **SESSION, grant=live_grant)
    check(connection_closed(packets))
    checks['revokeToReaderEofMs'] = round((time.monotonic() - start) * 1000, 2)
    check(live.reason() == 'revoked')
    # The earlier grant may still authorize a fresh stream; revoke it before testing reconnect.
    owner.call('revoke', **SESSION, grant=initial_grant)
    denied('grant_denied', observer.call, 'presentation.open', **identity)
    checks['revocationStopsDeliveryReconnectDenied'] = True

    short = owner.call('delegate', **SESSION, principal='observer', capability=CAPABILITY,
                       target='*', ttl=1)['grant']
    with ExitStack() as connection:
        live, packets = borrow_media(connection, a, pin, token('observer'))
        # Leave the Unix buffer bounded until the broker observes expiry.
        time.sleep(1.15)
        check(connection_closed(packets) and live.reason() == 'grant_expired')
    owner.call('revoke', **SESSION, grant=short)
    checks['grantExpiryStopsDelivery'] = True
    grant(owner, 'observer', CAPABILITY)
    with ExitStack() as connection:
        live, packets = borrow_media(connection, a, pin, token('observer'))
        live.peer.sendall(b'input')
        check(connection_closed(packets) and live.reason() == 'unexpected_media_input')
    checks['mediaRejectsInboundBytes'] = True

    evidence['stage'] = 'viewer_crash'
    view = start_window(stack, viewer_command)
    eventually(lambda: media_children(manager, folder), 'crash_viewer_not_attached')
    view.kill()
    view.wait(timeout=5)
    eventually(lambda: not media_children(manager, folder), 'capture_active_after_viewer_crash')
    check(admin('private.status', id=a['id'])['phase'] == 'ready')
    checks['viewerCrashKeepsDesktopReady'] = True

    evidence['stage'] = 'capture_process_failure'
    with ExitStack() as connection:
        live, packets = borrow_media(connection, a, pin, token('observer'))
        capture = eventually(lambda: media_children(manager, folder), 'capture_pid_missing')
        check(len(capture) == 1)
        os.kill(capture[0], signal.SIGKILL)
        check(connection_closed(packets) and live.reason() == 'capture_failed')
        check(admin('private.status', id=a['id'])['phase'] == 'ready')
    checks['capturerDeathKeepsDesktopReady'] = True

    with ExitStack() as connection:
        latest, packets = borrow_media(connection, a, pin, token('observer'))
        check(owner.call('release', **controller)['phase'] == 'idle')
        check(admin('private.stop', id=a['id'])['phase'] == 'stopped')
        check(connection_closed(packets) and latest.reason() == 'session_ended_or_unreachable')
    checks['sessionStopClosesStream'] = True
    denied('presentation_identity_mismatch', other.call, 'presentation.open', **identity)
    checks['reconnectToReplacementWithOldIdentityDenied'] = True


def run(root, args, evidence):
    with ExitStack() as stack:
        provision(root / 'cred')

        def token(principal):
            return read_private(root / 'cred' / (principal + '.token')).strip()

        manager = Process(stack, [sys.executable, '-B', '-m', 'loopbridge', 'private',
                                  '--root', root / 'run', '--credentials', root / 'cred/service.json'])
        check(manager.line() == b'ready\n')

        def admin(method, **params):
            with ExitStack() as request:
                return connect_rpc(request, root / 'run/manager.sock', token('owner')).call(method, **params)

        a = admin('private.start')
        owner = connect_rpc(stack, a['socket'], token('owner'))
        folder = root / 'run' / a['id']
        compositor = namespaced_process(manager.child.pid, folder, 'sway')
        initial_grant = grant(owner, 'observer', CAPABILITY)
        pin = owner.call('presentation.describe', **SESSION)
        check(not media_children(manager.child.pid, folder))
        controller = writable(owner)
        metrics = root / 'view.json'
        evidence['stage'] = 'open_graphical_window'
        viewer_command = ['tools.loopbridge_live_view', '--socket', a['socket'],
                            '--token-file', root / 'cred/observer.token', '--private-id', a['id'],
                            '--epoch', pin['epoch'], '--measure-motion', '--metrics-file', metrics]
        view = start_window(stack, viewer_command)
        first = eventually(lambda: read_metrics(metrics, lambda item: item['painted'] >= 1),
                           'viewer_did_not_paint_private_output')
        evidence['readyWindow'] = dict(width=first['width'], height=first['height'],
                                       firstPaintMs=first['firstPaintMs'], handshakeMs=first['handshakeMs'])
        print('Live GTK4 window mapped and painting on the main desktop.', flush=True)
        if args.wait_for_operator:
            evidence['operatorConfirmedWindow'] = operator_confirmed(
                'Type yes when the private desktop is visible.', owner)
            check(evidence['operatorConfirmedWindow'])
        evidence['stage'] = 'launch_calculator_and_firefox'
        check(owner.call('app.launch', **controller, app='calculator')['status'] == 'confirmed')
        eventually(lambda: read_metrics(metrics, lambda row: row['painted'] > first['painted']),
                   'calculator_open_did_not_change_view')
        time.sleep(1.5)
        check(owner.call('app.close', **controller, app='calculator')['status'] == 'confirmed')
        check(owner.call('web.open', **controller, app='browser')['status'] == 'confirmed')
        ref = owner.call('window.list', **SESSION, app='browser')['windows'][0]['ref']
        result = owner.call('web.navigate', **controller, ref=ref, page='motion')
        check(result['status'] == 'confirmed' and result['evidence']['state']['page'] == 'motion')
        evidence['stage'] = 'measure_motion'
        first_motion = eventually(lambda: read_metrics(metrics, lambda row: row.get('motion', {}).get('painted', 0) >= 10),
                                  'viewer_did_not_decode_motion_marker')
        print('Offline Firefox animation is live in the GTK4 window.', flush=True)
        capture = eventually(lambda: media_children(manager.child.pid, folder), 'capture_process_unavailable')
        check(len(capture) == 1)
        sway_parent = int(Path(f'/proc/{capture[0]}/stat').read_text().rsplit(')', 1)[1].split()[1])
        evidence['withObserver'] = resource_sample(dict(compositor=compositor, capturer=capture[0],
                                                         bridge=sway_parent, viewer=view.pid), args.seconds)
        report = eventually(lambda: read_metrics(metrics,
                            lambda row: row.get('motion', {}).get('painted', 0) > first_motion['motion']['painted']),
                            'viewer_stopped_updating')
        evidence['view'] = report
        print(json.dumps(report['motion'], sort_keys=True), flush=True)
        if args.wait_for_operator:
            evidence['operatorConfirmedMotion'] = operator_confirmed(
                'Type yes after watching the Firefox animation.', owner)
            check(evidence['operatorConfirmedMotion'])
        if args.hold:
            until = time.monotonic() + args.hold
            while (remaining := until - time.monotonic()) > 0:
                time.sleep(min(5, remaining))
                owner.call('presentation.describe', **SESSION)

        evidence['stage'] = 'disconnect_viewer'
        start = time.monotonic()
        check(terminate(view) == 0)
        eventually(lambda: not media_children(manager.child.pid, folder), 'capture_active_after_disconnect')
        evidence['viewerExitToCaptureIdleMs'] = round((time.monotonic() - start) * 1000, 2)
        check(admin('private.status', id=a['id'])['phase'] == 'ready')
        ref = owner.call('window.list', **SESSION, app='browser')['windows'][0]['ref']
        check(owner.call('web.discover', **SESSION, ref=ref)['page'] == 'motion')
        evidence['privateFirefoxAfterViewerExit'] = 'confirmed'
        evidence['withoutObserver'] = resource_sample(dict(compositor=compositor, bridge=sway_parent), args.seconds)
        check(not media_children(manager.child.pid, folder))
        evidence['withoutObserver'].update(capturer=None, viewer=None)

        if not args.view_only:
            evidence['stage'] = 'legacy_png_baseline'
            png_grant = grant(owner, 'delegate', 'desktop.capture')
            legacy_metrics = root / 'legacy.json'
            legacy = start_window(stack, ['tools.loopbridge_watch', '--socket', a['socket'],
                                  '--token-file', root / 'cred/delegate.token',
                                  '--expected-private-id', a['id'], '--ready-file', legacy_metrics])
            first = eventually(lambda: read_metrics(legacy_metrics, lambda row: row['frames'] >= 1),
                               'legacy_viewer_unavailable')
            time.sleep(args.seconds)
            last = eventually(lambda: read_metrics(legacy_metrics, lambda row: row['frames'] > first['frames']),
                              'legacy_viewer_stalled')
            evidence['pngBaseline'] = dict(frames=last['frames'] - first['frames'],
                                           unique=last['changes'] - first['changes'],
                                           seconds=round(last['monotonic'] - first['monotonic'], 2),
                                           uniqueFps=round((last['changes'] - first['changes']) /
                                                           (last['monotonic'] - first['monotonic']), 2))
            terminate(legacy)
            owner.call('revoke', **SESSION, grant=png_grant)
            negative_checks(stack, admin, a, admin('private.start'), owner, token, pin, controller,
                            manager.child.pid, folder, compositor, viewer_command, initial_grant, evidence)
        evidence['stage'] = 'complete'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=8)
    parser.add_argument('--hold', type=int, default=0, help='leave the animation visible before teardown')
    parser.add_argument('--wait-for-operator', action='store_true')
    parser.add_argument('--view-only', action='store_true', help='skip the baseline and failure matrix')
    args = parser.parse_args()
    if not 4 <= args.seconds <= 30 or not 0 <= args.hold <= 60:
        parser.error('measurement must be 4–30 seconds and hold must be 0–60 seconds')
    root = Path(tempfile.mkdtemp(prefix='lb7-'))
    evidence = dict(stage='startup', result='PARTIAL', operatorConfirmedWindow=False,
                    operatorConfirmedMotion=False)
    try:
        run(root, args, evidence)
        view = evidence['view']
        latency = view['appToPresentationMs']
        perf = ('GO' if view['motion']['fps'] >= 28 and latency
                and latency['samples'] >= 60 and latency['p95'] <= 100 else 'PARTIAL')
        evidence['gates'] = dict(streaming='GO', performance=perf,
                                 sandboxAuthorization='GO' if not args.view_only else 'PARTIAL',
                                 unrestrictedSameUid='PARTIAL',
                                 humanObservation='GO' if evidence['operatorConfirmedMotion'] else 'PARTIAL')
    except (OSError, Fault, RuntimeError, AssertionError, ValueError, KeyError, EOFError) as error:
        evidence['failure'] = str(error) if isinstance(error, (Fault, RuntimeError)) else type(error).__name__
    finally:
        if any(Journal(path).blocked(DESKTOP_SESSION) for path in root.glob('run/*/runtime')):
            shutil.rmtree(root / 'cred')
            evidence['blockedRuntimePreserved'] = True
        else:
            shutil.rmtree(root)
        with args.evidence.open('x') as file:
            json.dump(evidence, file, indent=2)
            file.write('\n')
    print(evidence['result'], evidence['stage'], evidence.get('failure', ''), flush=True)
    return int(evidence['stage'] != 'complete')


if __name__ == '__main__':
    raise SystemExit(main())
