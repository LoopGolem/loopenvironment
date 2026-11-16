# SPDX-License-Identifier: Apache-2.0
"""M1.3B diagnostics only. No input injector, compositor patch or takeover endpoint."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

from experiments.m1_1 import semantic as m1
from experiments.m1_2.protocol import Fault, RPC
from experiments.m1_3.preflight import registry, portal_alternative, clipboard_isolation
from experiments.m1_3a.adapter import Calculator
from experiments.m1_3a.authority import TARGET
from experiments.m1_3a.broker import Broker
from experiments.m1_3a.identity import Identities

BASE = '4d180f09415d554e6cf885658d654e143dbd6d50'


def input_summary(inputs, seats):
    # No hardware names/identifiers, keymaps, serials or focused-window IDs.
    return dict(devices=[dict(type=d.get('type'), libinput=bool(d.get('libinput')))
                         for d in inputs],
                seats=[dict(capabilities=s.get('capabilities'),
                            device_count=len(s.get('devices', []))) for s in seats])


def inventory():
    packages = ['sway', 'libwlroots-0.18', 'libwayland-client0', 'libwayland-dev',
                'libwlroots-0.18-dev', 'libgtk-4-1', 'libgtk-4-dev', 'at-spi2-core',
                'libei1', 'libeis1', 'weston', 'cage', 'bubblewrap', 'gnome-calculator']
    p = subprocess.run(['dpkg-query', '-W', '-f=${Package}\t${Version}\t${db:Status-Status}\n',
                        *packages], capture_output=True, text=True, timeout=3)
    installed = {}
    for line in p.stdout.splitlines():
        name, version, status = line.split('\t')
        if status == 'installed':
            installed[name] = version
    return dict(packages=installed, queried_not_installed=sorted(set(packages)-set(installed)),
                tools={name: shutil.which(name) is not None for name in
                       ('cc', 'pkg-config', 'meson', 'ninja', 'wayland-scanner', 'weston', 'cage', 'wtype')},
                python=sys.version.split()[0], kernel=os.uname().release,
                input=input_summary(m1.sway('get_inputs'), m1.sway('get_seats')))


def fault(operation, expected):
    try:
        operation()
    except Fault as error:
        if error.message == expected:
            return error.message
        raise AssertionError('unexpected_fault') from None
    raise AssertionError('operation_not_denied')


def stop_child(process, pidfd):
    signal.pidfd_send_signal(pidfd, signal.SIGSTOP)
    def observed():
        pid, status = os.waitpid(process.pid, os.WUNTRACED | os.WNOHANG)
        if pid != process.pid or not os.WIFSTOPPED(status):
            raise RuntimeError('fixture_not_stopped')
        return True
    m1.wait_for(observed, timeout=.6)


class PausedCalculator(Calculator):
    """Fault injection in our supervised child only, after genuine target preparation."""
    def __init__(self):
        super().__init__()
        self.stopped = threading.Event()
        self.watchdog = None
        self.watchdog_fired = False

    def resume(self):
        try:
            signal.pidfd_send_signal(self.fixture.pidfd, signal.SIGCONT)
        except ProcessLookupError:
            pass  # Our supervised child already exited; pidfd prevents PID reuse.

    def emergency_resume(self):
        self.watchdog_fired = True
        self.resume()

    def send(self, prepared):
        # Independent finite recovery even if AT-SPI doesn't honor its timeout.
        self.watchdog = threading.Timer(6, self.emergency_resume)
        self.watchdog.start()
        stop_child(self.fixture.process, self.fixture.pidfd)
        self.stop_at = time.monotonic()
        self.stopped.set()
        super().send(prepared)  # Real AT-SPI/D-Bus call, NOT a simulated dispatch.

    def close(self):
        if self.watchdog:
            self.watchdog.cancel()
            self.watchdog.join(1)
        try:
            self.resume()
        finally:
            super().close()


def pending_semantic(report, secret_guard):
    """Two trusted harness peers authenticate through real socket transport.

    This is a negative diagnostic of the existing broker, NOT a takeover POC or
    an isolated-client claim. Separate Bubblewrap probes test direct bypass.
    """
    adapter = PausedCalculator()
    sockets, workers = [], []
    try:
        identities = Identities()
        credentials = identities.provision()
        secret_guard.extend(credentials.values())
        broker = Broker(identities, {'S': adapter}, os.getuid())
        def peer(principal):
            a, b = socket.socketpair()
            a.settimeout(12)
            sockets.append(a)
            worker = threading.Thread(target=broker.serve_connection, args=(b,))
            workers.append(worker)
            worker.start()
            rpc = RPC(a)
            if rpc.call('auth', credential=credentials[principal])['principal'] != principal:
                raise AssertionError('wrong_identity')
            return rpc
        owner, delegate = peer('owner'), peer('delegate')
        grant = None
        for capability in ('desktop.observe', 'desktop.control'):
            g = owner.call('delegate', session='S', principal='delegate', capability=capability,
                           target=TARGET, ttl=120)
            if capability == 'desktop.control':
                grant = g['grant']
        lease = delegate.call('acquire', session='S', ttl=30)
        snap = delegate.call('snapshot', session='S')
        params = dict(session='S', lease=lease['id'], epoch=lease['epoch'],
                      generation=lease['generation'], reference=snap['reference'])
        report.update(initial=snap['state'], principal_transport='authenticated_socketpairs_trusted_harness',
                      fixture_pid=adapter.fixture.process.pid)
        with ThreadPoolExecutor(2) as executor:
            invocation = executor.submit(lambda: fault(lambda: delegate.call('invoke7', **params), 'outcome_unknown'))
            if not adapter.stopped.wait(5):
                raise RuntimeError('stop_not_observed')
            # Admin request competes with an actual in-flight D-Bus invocation.
            revocation = executor.submit(lambda: owner.call('revoke', session='S', grant=grant))
            report['invoke_result'] = invocation.result(timeout=10)
            report['timeout_after_stop_ms'] = round((time.monotonic()-adapter.stop_at)*1000)
            revocation.result(timeout=10)
        session = broker.sessions['S']
        report.update(phase_after_timeout=session.phase, generation_before=lease['generation'],
                      generation_after=session.generation, watchdog_fired=adapter.watchdog_fired)
        report['new_control'] = fault(lambda: owner.call('acquire', session='S', ttl=10), 'control_busy')
        report['logical_restart'] = fault(lambda: owner.call('restart', session='S'), 'handoff_not_confirmed')
        report['old_request'] = fault(lambda: delegate.call('invoke7', **params), 'grant_denied')
        report['takeover_endpoint'] = fault(lambda: owner.call('takeover', session='S'), 'method_not_found')
        # Disconnect the old client AFTER its timed-out request. This still cannot
        # recall a message already sent on the broker's separate accessibility bus.
        sockets[1].shutdown(socket.SHUT_RDWR)
        adapter.resume()
        def delivered():
            _, _, frame = m1.discover(adapter.fixture.process, adapter.fixture.desktop)
            state = m1.texts(frame)
            if '7' not in state.values():
                raise m1.Rejected('late_effect_not_yet_observed')
            return state
        try:
            after = m1.wait_for(delivered, timeout=4)
            report.update(after_resume=after, late_effect_observed=True)
        except m1.Rejected:
            report.update(late_effect_observed=False, observation='not_observed_within_bounded_query')
        report['audit'] = list(broker.audit)
        report['takeover_confirmed'] = False
        if session.phase != 'blocked' or session.generation != lease['generation'] or adapter.watchdog_fired:
            raise AssertionError('diagnostic_invariant_failed')
    finally:
        # Resume before joining workers; never leave our Calculator stopped.
        adapter.resume()
        for sock in sockets:
            sock.close()
        for worker in workers:
            worker.join(12)
        try:
            if any(t.is_alive() for t in workers):
                raise RuntimeError('worker_timeout')
        finally:
            adapter.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--worker', choices=('registry', 'portal'))
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(registry() if args.worker == 'registry' else portal_alternative()))
        return 0
    report = dict(result='PARTIAL', diagnostic_completed=False, base_commit=BASE,
                  started=datetime.now(timezone.utc).isoformat(), real_takeover_implemented=False,
                  semantic={})
    secrets = []
    with args.evidence.open('x') as output:
        try:
            report['environment'] = inventory()
            for mode in ('registry', 'portal'):
                child = subprocess.run([sys.executable, '-m', 'experiments.m1_3b.diagnose',
                    '--evidence', str(args.evidence), '--worker', mode],
                    capture_output=True, timeout=8, check=True)
                report[mode] = json.loads(child.stdout)
            report['isolation'] = clipboard_isolation()  # Probe only, no clipboard access.
            pending_semantic(report['semantic'], secrets)
            report.update(diagnostic_completed=True, result='NO-GO',
                decision_scope='stock_existing_Sway_plus_M1.3A_is_not_a_takeover_enforcement_boundary')
        except Exception as error:
            report['failure'] = type(error).__name__  # No raw error, argv, socket path or secret.
        if any(s in json.dumps(report) for s in secrets):
            report = dict(result='NO-GO', failure='sensitive_output_removed')
        json.dump(report, output, indent=2)
        output.write('\n')
    print(report['result'], 'diagnostic_completed=' + str(report.get('diagnostic_completed', False)))
    # Success means the negative diagnostic completed, NEVER a GO for takeover.
    return 0 if report.get('diagnostic_completed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
