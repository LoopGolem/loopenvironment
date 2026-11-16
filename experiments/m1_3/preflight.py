# SPDX-License-Identifier: Apache-2.0
"""Bounded M1.3 inventory. Never captures pixels, injects input or grants control."""
import argparse
from collections import Counter
import ctypes as C
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

from experiments.m1_1 import semantic as m1
from experiments.m1_2.broker import Fixture
from experiments.m1_2.isolation import command, namespaces
from experiments.m1_2.run import endpoints
from experiments.m1_2.probe import connect


class Interface(C.Structure):
    _fields_ = [('name', C.c_char_p), ('version', C.c_int),
                ('method_count', C.c_int), ('methods', C.c_void_p),
                ('event_count', C.c_int), ('events', C.c_void_p)]


def registry():
    # wl_display.get_registry (opcode 1), followed by a roundtrip. No global bind.
    w = C.CDLL('libwayland-client.so.0')
    w.wl_display_connect.argtypes = [C.c_char_p]
    w.wl_display_connect.restype = C.c_void_p
    w.wl_proxy_marshal_flags.argtypes = [C.c_void_p, C.c_uint, C.POINTER(Interface), C.c_uint, C.c_uint]
    w.wl_proxy_marshal_flags.restype = C.c_void_p
    w.wl_proxy_add_listener.argtypes = [C.c_void_p, C.POINTER(C.c_void_p), C.c_void_p]
    w.wl_proxy_add_listener.restype = C.c_int
    w.wl_display_roundtrip.argtypes = [C.c_void_p]
    w.wl_display_roundtrip.restype = C.c_int
    w.wl_proxy_destroy.argtypes = [C.c_void_p]
    w.wl_display_disconnect.argtypes = [C.c_void_p]
    display = w.wl_display_connect(None)
    if not display:
        raise RuntimeError('display_unavailable')
    proxy = None
    items = {}

    @C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_uint, C.c_char_p, C.c_uint)
    def add(data, proxy, name, interface, version):
        items[name] = (interface.decode('ascii'), version)

    @C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_uint)
    def remove(data, proxy, name):
        items.pop(name, None)

    listener = (C.c_void_p * 2)(C.cast(add, C.c_void_p), C.cast(remove, C.c_void_p))
    try:
        interface = Interface.in_dll(w, 'wl_registry_interface')
        proxy = w.wl_proxy_marshal_flags(display, 1, C.byref(interface), 1, 0, C.c_void_p())
        if not proxy or w.wl_proxy_add_listener(proxy, listener, None) != 0:
            raise RuntimeError('registry_listener_failed')
        if w.wl_display_roundtrip(display) < 0:
            raise RuntimeError('registry_roundtrip_failed')
        result = {}
        for name, version in items.values():
            result[name] = max(result.get(name, 0), version)
        return dict(sorted(result.items()))
    finally:
        if proxy:
            w.wl_proxy_destroy(proxy)
        w.wl_display_disconnect(display)


def portal_alternative():
    """The sole bounded alternative: existing-session portal/Mutter availability."""
    from gi.repository import Gio
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    def call(destination, path, interface, method):
        return bus.call_sync(destination, path, interface, method, None, None,
                             Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
    xml = call('org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop',
               'org.freedesktop.DBus.Introspectable', 'Introspect')
    interfaces = sorted(n.attrib['name'] for n in ET.fromstring(xml).findall('interface'))
    names = call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                 'org.freedesktop.DBus', 'ListNames')
    return dict(interfaces=interfaces, remote_desktop='org.freedesktop.portal.RemoteDesktop' in interfaces,
                screen_cast='org.freedesktop.portal.ScreenCast' in interfaces,
                mutter_remote_desktop_owned='org.gnome.Mutter.RemoteDesktop' in names,
                mutter_screen_cast_owned='org.gnome.Mutter.ScreenCast' in names,
                connect_to_eis_attempted=False)


def semantic_gap():
    """Real, unmodified Foot, with a live GTK accessibility positive control."""
    control = Fixture()  # Refuses to touch an existing Calculator; invokes no action.
    child = None
    try:
        child = subprocess.Popen(['/usr/bin/foot', '--app-id=org.loopenvironment.M13Gap',
                                  '--title=M1.3 semantic gap fixture', '/usr/bin/python3', '-I', '-c',
                                  'import time; print("M1.3 controlled terminal text", flush=True); time.sleep(12)'],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 close_fds=True)
        def mapped():
            if child.poll() is not None:
                raise m1.Rejected('foot_exited')
            return m1.unique([w for w in m1.windows(m1.sway('get_tree'))
                              if w['pid'] == child.pid and w['app_id'] == 'org.loopenvironment.M13Gap'],
                             'foot_window_not_unique')
        window = m1.wait_for(mapped, timeout=5)
        identity = m1.process_identity(child.pid)
        started = time.monotonic()
        samples = []
        for _ in range(8):
            mapped()
            if m1.process_identity(child.pid) != identity:
                raise m1.Rejected('foot_identity_changed')
            applications = list(control.desktop())
            samples.append(dict(elapsed_ms=round((time.monotonic()-started)*1000),
                                foot_matches=sum(a.get_process_id() == child.pid for a in applications),
                                calculator_matches=sum(a.get_process_id() == control.process.pid for a in applications)))
            control.read()  # Positive control: query real GTK text each sample.
            time.sleep(.4)
        return dict(window=window, executable=identity[3], samples=samples,
                    duration_ms=round((time.monotonic()-started)*1000),
                    positive_control_pid=control.process.pid,
                    gap_observed=all(s['foot_matches'] == 0 and s['calculator_matches'] == 1 for s in samples),
                    scope='no_foot_atspi_application_for_window_pid_during_sampling')
    finally:
        if child:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=3)
        control.close()


def clipboard_isolation():
    """Test endpoint reachability, never clipboard contents or transfers."""
    paths = endpoints()
    baseline = {name: connect(path) for name, path in paths.items()}
    with tempfile.TemporaryDirectory(prefix='m13-probe-') as folder:
        os.chmod(folder, 0o700)
        listener = socket.socket(socket.AF_UNIX)
        sentinel = socket.socket(socket.AF_UNIX)
        try:
            listener.bind(str(Path(folder) / 'control.sock'))
            os.chmod(Path(folder) / 'control.sock', 0o600)
            sentinel.connect(paths['sway'])
            sentinel.set_inheritable(True)
            config = dict(endpoints=paths, host_ns=namespaces(), broker_pid=os.getpid(), devices=['/dev/uinput'])
            # Exactly the M1.2 mount/namespace profile, with only the probe as payload.
            args = command(folder)[:-1] + ['-c',
                    'import json,sys; from probe import inspect; print(json.dumps(inspect(json.load(sys.stdin))))']
            result = subprocess.run(args, input=json.dumps(config).encode(), stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=8, close_fds=True, env={'PATH': '/usr/bin'})
            if result.returncode:
                raise RuntimeError('isolated_probe_failed')
            return dict(baseline=baseline, isolated=json.loads(result.stdout),
                        clipboard_content_read=False, clipboard_content_written=False,
                        grant_authenticated=False, payload='independent_probe_only')
        finally:
            sentinel.close()
            listener.close()


def versions():
    packages = ['sway', 'libwlroots-0.18', 'foot', 'libwayland-client0', 'bubblewrap',
                'python3-pyatspi', 'python3-gi', 'xdg-desktop-portal', 'xdg-desktop-portal-gtk',
                'xdg-desktop-portal-gnome', 'xdg-desktop-portal-wlr']
    result = subprocess.run(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Status}\n',
                             *packages], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=3)
    installed = {}
    for line in result.stdout.splitlines():
        name, version, status = line.split('\t')
        if status == 'installed':
            installed[name] = version
    return dict(packages=installed, python=sys.version.split()[0], kernel=os.uname().release)


def clipboard_configuration():
    configured = any(line.strip() == 'exec VBoxClient --clipboard --session-type wayland --foreground'
                     for line in (Path.home() / '.config/sway/config').read_text().splitlines())
    processes = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / 'comm').read_text().strip() != 'VBoxClient':
                continue
            args = (entry / 'cmdline').read_bytes().split(b'\0')
            processes.append(dict(clipboard=b'--clipboard' in args,
                                  wayland=b'wayland' in args, foreground=b'--foreground' in args))
        except (OSError, ProcessLookupError):
            continue
    return dict(sway_autostart_matches_known_command=configured, vboxclient_process_flags=processes,
                vboxclient_version=subprocess.check_output(['VBoxClient', '--version'], text=True, timeout=3).strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry-worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    if args.registry_worker:
        print(json.dumps(registry()))
        return 0
    if not args.evidence:
        parser.error('--evidence required')
    report = dict(result='PARTIAL', started=datetime.now(timezone.utc).isoformat(), phase='preflight')
    with args.evidence.open('x') as output:
        try:
            report['versions'] = versions()
            raw = subprocess.check_output([sys.executable, '-m', 'experiments.m1_3.preflight', '--registry-worker'], timeout=8)
            report['wayland_globals'] = json.loads(raw)
            report['tools_available'] = {tool: shutil.which(tool) is not None for tool in
                                         ('wayland-info', 'grim', 'wayvnc', 'wtype', 'wl-copy', 'wl-paste')}
            report['portal_alternative'] = portal_alternative()
            report['clipboard_configuration'] = clipboard_configuration()
            report['clipboard_isolation'] = clipboard_isolation()
            report['semantic_gap'] = semantic_gap()
            report['input_device_types'] = dict(Counter(i['type'] for i in m1.sway('get_inputs')))
            # Inventory is not a control-policy proof. Assessment is in the lab report.
            report['completed'] = True
        except Exception as error:
            report['failure'] = type(error).__name__  # No args, paths, bus data or pixel data.
        json.dump(report, output, indent=2)
        output.write('\n')
    print('Preflight recorded; full M1.3 control proof not executed.')
    return 0 if report.get('completed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
