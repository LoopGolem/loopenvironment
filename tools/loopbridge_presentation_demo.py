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

from loopbridge.__main__ import write_private
from loopbridge.identity import Identities
from loopbridge.presentation import CAPABILITY
from loopbridge.presentation_client import LiveConnection
from loopbridge.private_session import terminate
from loopbridge.process_boundary import protect_process
from loopbridge.protocol import Fault, RPC
from loopbridge.service import DESKTOP_SESSION, Journal
from experiments.m1_2.probe import connect

from .loopbridge_demo import ROOT, Process, check, endpoints, launch
from .loopbridge_desktop_demo import SESSION, grant, writable
from .loopbridge_private_demo import connect_rpc, denied, descendants, namespaced_process, sockets


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


def start_window(stack, command, credential):
    process = subprocess.Popen([sys.executable, '-B', '-m', *map(str, command)],
                               stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, close_fds=True,
                               env={**os.environ, 'GDK_BACKEND': 'wayland'})
    stack.callback(terminate, process)
    with process.stdin:
        process.stdin.write((credential + '\n').encode())
    return process


def parent_pid(pid):
    stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return int(stat[1])


def media_children(manager, folder):
    # The protected helper's /proc exe and ns links can be inaccessible.
    # Sway and the Bridge have the same trusted supervisor.
    supervisor = parent_pid(namespaced_process(manager, folder, 'sway'))
    rows = []
    for process in descendants(supervisor):
        try:
            if (process / 'comm').read_text().strip() == 'stream':
                rows.append(int(process.name))
        except FileNotFoundError:
            continue
    return rows


def raw_proc_probe(processes, **options):
    report = subprocess.run([sys.executable, '-B', '-m', 'tools.loopbridge_security_probe'],
                            input=json.dumps(dict(processes=processes, **options)), text=True,
                            capture_output=True, check=True, timeout=20,
                            env={'PATH': '/usr/bin', 'LANG': 'C.UTF-8'})
    return json.loads(report.stdout)


def authenticate(endpoint, token, expect_denied):
    with socket.socket(socket.AF_UNIX) as peer:
        peer.connect(str(endpoint))
        rpc = RPC(peer)
        if expect_denied:
            denied('denied', rpc.call, 'auth', credential=token)
        else:
            return rpc.call('auth', credential=token)['principal']


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


def negative_checks(stack, admin, a, b, owner, tokens, sibling_tokens, pin, controller, manager, folder,
                    compositor, viewer_command, initial_grant, evidence):
    identity = {key: pin[key] for key in ('session', 'privateId', 'epoch')}
    checks = evidence['negative'] = {}
    evidence['stage'] = 'same_uid_authorization'
    # Both peers use the lab UID and the same reachable control socket.
    with closing(socket.socket(socket.AF_UNIX)) as peer:
        peer.connect(a['socket'])
        denied('denied', RPC(peer).call, 'presentation.open', **identity)
    checks['sameUidUnauthenticatedDenied'] = True
    read_only = connect_rpc(stack, a['socket'], tokens['delegate'])
    other = connect_rpc(stack, b['socket'], sibling_tokens['owner'])
    other_pin = other.call('presentation.describe', **SESSION)
    sibling_observer = connect_rpc(stack, b['socket'], sibling_tokens['observer'])
    denied('grant_denied', sibling_observer.call, 'presentation.open',
           **{key: other_pin[key] for key in identity})
    checks['grantDoesNotCrossSession'] = True
    denied('presentation_identity_mismatch', other.call, 'presentation.open', **identity)
    denied('presentation_identity_mismatch', owner.call, 'presentation.open',
           **{**identity, 'epoch': other_pin['epoch']})
    checks['stalePrivateIdAndEpochDenied'] = True

    evidence['stage'] = 'isolated_observer'
    observer = connect_rpc(stack, a['socket'], tokens['observer'])
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
    exposed = {**host_endpoints, **private_paths, 'sibling_control': b['socket'],
               **{'host_proc_' + key: path for key, path in proc_paths.items()}}
    credential_folder = folder.parents[1] / 'cred'
    private_files = (str(folder), str(credential_folder / 'service.json'))
    # Each launcher deliberately marks a socket and memfd inheritable before exec.
    with ExitStack() as probes_stack:
        _, _, auth = launch(probes_stack, Path(a['socket']).parent, exposed, None, manager, private_files)
        check(auth == {'error': 'denied'})
        restricted, _, auth = launch(probes_stack, Path(a['socket']).parent, exposed,
                                     tokens['delegate'], manager, private_files)
        check(auth['result']['principal'] == 'delegate')
        restricted.denied('grant_denied', 'presentation.open', **identity)
        grant(owner, 'delegate', 'desktop.observe')
        restricted.denied('grant_denied', 'presentation.open', **identity)
        for cap in ('session.discover', 'desktop.capture'):
            grant(owner, 'delegate', cap)
        restricted.denied('grant_denied', 'presentation.open', **identity)
        agent, probes, auth = launch(probes_stack, Path(a['socket']).parent, exposed,
                                     tokens['observer'], manager, private_files)
        check(auth['result']['principal'] == 'observer')
        agent.denied('grant_denied', 'session.capture', **SESSION)
        agent.denied('grant_denied', 'acquire', ttl=2, **SESSION)
        # Give the sibling socket to an independent client carrying only A's token.
        _, _, auth = launch(probes_stack, Path(b['socket']).parent,
                            {**exposed, 'sibling_control': a['socket']},
                            tokens['observer'], manager, private_files)
        check(auth == {'error': 'denied'})
    checks['isolatedObserver'] = dict(endpointsDenied=len(probes['endpoints']),
                                    privatePathsDenied=probes['private_paths_denied'],
                                    inheritedSockets=probes['inherited_socket_count'],
                                    inheritedDescriptors=probes['unexpected_descriptor_count'],
                                    visibleDevices=probes['exposed_device_count'],
                                    namespaces=probes['private_namespaces'])
    checks['isolatedUnauthenticatedDenied'] = True
    checks['isolatedNoGrantAndObserveOnlyDenied'] = True
    checks['discoverObserveAndCaptureDoNotGrantStream'] = True
    checks['isolatedCredentialRejectedBySibling'] = True
    check(not sockets(folder / 'display'))
    check(set(sockets(folder / 'runtime/socket')) == {'control.sock'})
    checks['noMediaOrDisplayListenerInExposedRuntime'] = True

    evidence['stage'] = 'media_revocation'
    live_grant = grant(owner, 'observer', CAPABILITY)
    live, packets = borrow_media(stack, a, pin, tokens['observer'])
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
        live, packets = borrow_media(connection, a, pin, tokens['observer'])
        # Leave the Unix buffer bounded until the broker observes expiry.
        time.sleep(1.15)
        check(connection_closed(packets) and live.reason() == 'grant_expired')
    owner.call('revoke', **SESSION, grant=short)
    checks['grantExpiryStopsDelivery'] = True
    grant(owner, 'observer', CAPABILITY)
    with ExitStack() as connection:
        live, packets = borrow_media(connection, a, pin, tokens['observer'])
        live.peer.sendall(b'input')
        check(connection_closed(packets) and live.reason() == 'unexpected_media_input')
    checks['mediaRejectsInboundBytes'] = True

    evidence['stage'] = 'viewer_crash'
    view = start_window(stack, viewer_command, tokens['observer'])
    eventually(lambda: media_children(manager, folder), 'crash_viewer_not_attached')
    view.kill()
    view.wait(timeout=5)
    eventually(lambda: not media_children(manager, folder), 'capture_active_after_viewer_crash')
    check(admin('private.status', id=a['id'])['phase'] == 'ready')
    checks['viewerCrashKeepsDesktopReady'] = True

    evidence['stage'] = 'capture_process_failure'
    with ExitStack() as connection:
        live, packets = borrow_media(connection, a, pin, tokens['observer'])
        capture = eventually(lambda: media_children(manager, folder), 'capture_pid_missing')
        check(len(capture) == 1)
        os.kill(capture[0], signal.SIGKILL)
        check(connection_closed(packets) and live.reason() == 'capture_failed')
        check(admin('private.status', id=a['id'])['phase'] == 'ready')
    checks['capturerDeathKeepsDesktopReady'] = True

    with ExitStack() as connection:
        latest, packets = borrow_media(connection, a, pin, tokens['observer'])
        check(owner.call('release', **controller)['phase'] == 'idle')
        check(admin('private.stop', id=a['id'])['phase'] == 'stopped')
        check(connection_closed(packets) and latest.reason() == 'session_ended_or_unreachable')
    checks['sessionStopClosesStream'] = True
    denied('presentation_identity_mismatch', other.call, 'presentation.open', **identity)
    checks['reconnectToReplacementWithOldIdentityDenied'] = True


def run(root, args, evidence):
    with ExitStack() as stack:
        protect_process()
        bootstrap = Identities()
        manager_token = bootstrap.provision()['owner']
        credential_folder = root / 'cred'
        credential_folder.mkdir(mode=0o700)
        verifier_file = credential_folder / 'service.json'
        write_private(verifier_file, json.dumps(bootstrap.manifest()))
        manager = Process(stack, [sys.executable, '-B', '-m', 'loopbridge', 'private',
                                  '--root', root / 'run', '--credentials', verifier_file,
                                  '--scoped-credentials'])
        check(manager.line() == b'ready\n')
        manager_socket = root / 'run/manager.sock'

        def admin(method, **params):
            with ExitStack() as request:
                return connect_rpc(request, manager_socket, manager_token).call(method, **params)

        def start_instance():
            authority = Identities()
            tokens = authority.provision()
            verifiers = authority.manifest()['verifiers']
            return admin('private.start', credentialVerifiers=verifiers), tokens, verifiers

        evidence['stage'] = 'scoped_credentials'
        denied('invalid_session_verifiers', admin, 'private.start')
        bootstrap_verifiers = bootstrap.manifest()['verifiers']
        denied('reused_session_verifier', admin, 'private.start', credentialVerifiers=bootstrap_verifiers)
        authenticate(manager_socket, bootstrap_verifiers['owner'], expect_denied=True)
        a, tokens, verifiers = start_instance()
        authenticate(a['socket'], manager_token, expect_denied=True)
        authenticate(manager_socket, tokens['owner'], expect_denied=True)
        authenticate(a['socket'], verifiers['owner'], expect_denied=True)
        denied('reused_session_verifier', admin, 'private.start', credentialVerifiers=verifiers)
        evidence['credentialChecks'] = dict(missingSessionVerifiersDenied=True, verifierReplayDenied=True,
                                            bootstrapAndSessionSecretsSeparated=True,
                                            managerVerifierReuseDenied=True,
                                            activeSessionVerifierReuseDenied=True)
        owner = connect_rpc(stack, a['socket'], tokens['owner'])
        folder = root / 'run' / a['id']
        compositor = namespaced_process(manager.child.pid, folder, 'sway')
        initial_grant = grant(owner, 'observer', CAPABILITY)
        pin = owner.call('presentation.describe', **SESSION)
        check(not media_children(manager.child.pid, folder))
        controller = writable(owner)
        metrics = root / 'view.json'
        evidence['stage'] = 'open_graphical_window'
        viewer_command = ['tools.loopbridge_live_view', '--socket', a['socket'],
                            '--token-stdin', '--private-id', a['id'],
                            '--epoch', pin['epoch'], '--measure-motion', '--metrics-file', metrics]
        view = start_window(stack, viewer_command, tokens['observer'])
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
        bridge = parent_pid(capture[0])
        evidence['withObserver'] = resource_sample(dict(compositor=compositor, capturer=capture[0],
                                                         bridge=bridge, viewer=view.pid), args.seconds)
        report = eventually(lambda: read_metrics(metrics,
                            lambda row: row.get('motion', {}).get('painted', 0) > first_motion['motion']['painted']),
                            'viewer_stopped_updating')
        evidence['view'] = report
        print(json.dumps(report['motion'], sort_keys=True), flush=True)
        if not args.view_only:
            evidence['stage'] = 'same_uid_process_protection'
            registry_probe = root / 'wayland-registry'
            subprocess.run(['/usr/bin/cc', str(ROOT / 'tools/wayland_scope_probe.c'), '-lwayland-client',
                            '-o', str(registry_probe)], check=True, timeout=10)
            proc = raw_proc_probe(dict(manager=manager.child.pid, bridge=bridge, viewer=view.pid,
                                       capturer=capture[0], compositor=compositor), display=compositor,
                                 waylandProbe=str(registry_probe), manifest=str(verifier_file))
            evidence['sameUidProbe'] = proc
            for role in ('manager', 'bridge', 'viewer', 'capturer'):
                check(proc[role]['pidMetadata'])
                check(not any(proc[role][key] for key in ('outputFd', 'environment', 'memory')))
            check(proc['manifestReadable'] and not proc['clientBearerFilesPresent'])
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
        evidence['withoutObserver'] = resource_sample(dict(compositor=compositor, bridge=bridge), args.seconds)
        check(not media_children(manager.child.pid, folder))
        evidence['withoutObserver'].update(capturer=None, viewer=None)

        if not args.view_only:
            evidence['stage'] = 'legacy_png_baseline'
            png_grant = grant(owner, 'delegate', 'desktop.capture')
            legacy_metrics = root / 'legacy.json'
            legacy = start_window(stack, ['tools.loopbridge_watch', '--socket', a['socket'],
                                  '--token-stdin', '--expected-private-id', a['id'],
                                  '--ready-file', legacy_metrics], tokens['delegate'])
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
            b, sibling_tokens, _ = start_instance()
            negative_checks(stack, admin, a, b, owner, tokens, sibling_tokens, pin, controller,
                            manager.child.pid, folder, compositor, viewer_command, initial_grant, evidence)
            denied('reused_session_verifier', admin, 'private.start', credentialVerifiers=verifiers)
            c, replacement_tokens, _ = start_instance()
            authenticate(c['socket'], tokens['owner'], expect_denied=True)
            authenticate(c['socket'], tokens['observer'], expect_denied=True)
            replacement = connect_rpc(stack, c['socket'], replacement_tokens['owner'])
            denied('presentation_identity_mismatch', replacement.call, 'presentation.open',
                   **{key: pin[key] for key in ('session', 'privateId', 'epoch')})
            evidence['credentialChecks'].update(stoppedSessionVerifierReuseDenied=True,
                                                formerCredentialsRejectedByReplacement=True)
            for instance in (b, c):
                check(admin('private.stop', id=instance['id'])['phase'] == 'stopped')
            check(not any(sockets(folder / 'runtime/socket') for folder in (root / 'run').glob('*/')))
            evidence['negative']['allInstanceSocketsReleased'] = True
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
    except (OSError, Fault, RuntimeError, AssertionError, ValueError, KeyError, EOFError,
            subprocess.SubprocessError) as error:
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
