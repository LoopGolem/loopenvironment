# SPDX-License-Identifier: Apache-2.0
"""Bounded M1.2 runner: trusted launcher, broker and independent sandbox clients."""
import argparse
from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import tempfile

from experiments.m1_2.broker import Broker, Fixture
from experiments.m1_2.isolation import launch, namespaces
from experiments.m1_2.probe import connect


def endpoints():
    from gi.repository import Gio
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    address = bus.call_sync('org.a11y.Bus', '/org/a11y/bus', 'org.a11y.Bus',
                            'GetAddress', None, None, Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
    def unix_address(value):
        match = re.search(r'(?:^|,)path=([^,;]+)', value.removeprefix('unix:'))
        if match:
            return match[1]
        match = re.search(r'(?:^|,)abstract=([^,;]+)', value.removeprefix('unix:'))
        if match:
            return '\0' + match[1]
        raise RuntimeError('unsupported_bus_address')
    runtime = Path(os.environ['XDG_RUNTIME_DIR'])
    result = dict(sway=os.environ['SWAYSOCK'],
                  wayland=str(runtime / os.environ['WAYLAND_DISPLAY']),
                  session_bus=unix_address(os.environ['DBUS_SESSION_BUS_ADDRESS']),
                  atspi_bus=unix_address(address))
    display = re.fullmatch(r':(\d+)(?:\.\d+)?', os.environ.get('DISPLAY', ''))
    if display:
        result['x11'] = '/tmp/.X11-unix/X' + display[1]
    for name, path in [('pipewire', runtime / 'pipewire-0'),
                        ('system_bus', Path('/run/dbus/system_bus_socket'))]:
        if path.exists():
            result[name] = str(path)
    return result


def execute(report):
    report['stage'] = 'session_baseline'
    paths = endpoints()
    report['baseline'] = {name: connect(path) for name, path in paths.items()}
    required = {'sway', 'wayland', 'session_bus', 'atspi_bus'}
    if not all(report['baseline'][name]['connected'] for name in required):
        raise RuntimeError('trusted_session_baseline_unavailable')
    # Independent network-namespace control for abstract AF_UNIX endpoints.
    canary = socket.socket(socket.AF_UNIX)
    canary.bind('\0m12-' + secrets.token_hex(12))
    canary.listen(4)
    paths['abstract_canary'] = canary.getsockname().decode()
    report['baseline']['abstract_canary'] = connect(paths['abstract_canary'])
    fixture = None
    try:
        report['stage'] = 'fixture_readiness'
        fixture = Fixture()
        report['correlation'] = dict(window=fixture.window, atspi_pid=fixture.app.get_process_id(),
                                     start_ticks=fixture.identity[1], executable=fixture.identity[3])
        credential = secrets.token_urlsafe(32)
        broker = Broker(fixture, credential, os.getuid())
        report['audit'] = broker.audit
        initial = fixture.read()
        # Only this fresh private directory is shared, read-only, with clients.
        with tempfile.TemporaryDirectory(prefix='m12-') as folder:
            os.chmod(folder, 0o700)
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(str(Path(folder) / 'control.sock'))
            os.chmod(Path(folder) / 'control.sock', 0o600)
            listener.listen(4)
            try:
                for mode in ('denied', 'authorized'):
                    report['stage'] = 'client_' + mode
                    # A real session socket is deliberately inheritable in the parent.
                    # close_fds must prevent it reaching either untrusted client.
                    sentinel = socket.socket(socket.AF_UNIX)
                    sentinel.connect(paths['sway'])
                    sentinel.set_inheritable(True)
                    config = dict(mode=mode, endpoints=paths, host_ns=namespaces(),
                                  broker_pid=os.getpid(), credential=credential if mode == 'authorized' else '',
                                  devices=sorted(set(glob.glob('/dev/input/event*') + glob.glob('/dev/dri/*')
                                                     + glob.glob('/dev/video*') + ['/dev/uinput'])))
                    child = launch(folder)
                    sentinel.close()
                    try:
                        child.stdin.write(json.dumps(config).encode())
                        child.stdin.close()
                        broker.serve_until(listener, child)
                        child.wait(timeout=3)
                        raw = child.stdout.read(32768)
                        errors = child.stderr.read(4096)
                        outcome = json.loads(raw)
                        report['clients'][mode] = outcome
                        if errors:
                            report.setdefault('warnings', []).append(mode + ':client_stderr_present_not_recorded')
                        if child.returncode or not outcome['ok']:
                            raise RuntimeError('isolated_client_failed')
                    finally:
                        if child.poll() is None:
                            child.terminate()
                            child.wait(timeout=3)
                        child.stdout.close()
                        child.stderr.close()
                    if mode == 'denied' and fixture.read() != initial:
                        raise RuntimeError('denied_client_changed_fixture')
                report['denied_client_state_unchanged'] = True
                report['final_state'] = fixture.read()
                report['audit'] = broker.audit
                report['event_history_capacity'] = 2
                report['stage'] = 'completed'
                report['result'] = 'GO'
            finally:
                listener.close()
    finally:
        canary.close()
        if fixture:
            fixture.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    report = dict(result='PARTIAL', started=datetime.now(timezone.utc).isoformat(), clients={})
    with args.evidence.open('x') as output:
        try:
            execute(report)
        except Exception as error:
            report['result'] = 'PARTIAL'
            report['failure'] = type(error).__name__
            from experiments.m1_1.semantic import Rejected
            if isinstance(error, Rejected) and str(error) in {
                    'existing_calculator_close_manually', 'fixture_not_clean',
                    'fixture_lifecycle_changed', 'fixture_source_changed', 'display_changed'}:
                report['reason'] = str(error)  # Fixed diagnostic vocabulary, no arguments.
        json.dump(report, output, indent=2)
        output.write('\n')
    print(report['result'])
    return 0 if report['result'] == 'GO' else 1


if __name__ == '__main__':
    raise SystemExit(main())
