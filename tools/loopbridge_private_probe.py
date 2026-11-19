# SPDX-License-Identifier: Apache-2.0
"""Bounded, socket-isolated Sway headless experiment. No host display mounts."""
import argparse
import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

TITLE = 'LoopBridge private headless proof'
PRIVATE = Path('/private')


def tree(argv):
    return json.loads(subprocess.check_output([*argv, '-t', 'get_tree', '-r'], timeout=5,
                                             stderr=subprocess.DEVNULL))


def nodes(root):
    yield root
    for key in ('nodes', 'floating_nodes'):
        for child in root.get(key, []):
            yield from nodes(child)


def denied(path):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(.25)
        try:
            sock.connect(path)
        except OSError as error:
            return error.errno in (errno.ENOENT, errno.EACCES, errno.ECONNREFUSED)
    return False


def terminate(proc):
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


def gtk_child():
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import GLib, Gtk

    Gtk.init()
    window = Gtk.Window(title=TITLE, default_width=480, default_height=270)
    button = Gtk.Button(label='Private output')
    button.connect('clicked', lambda _: (PRIVATE / 'clicked').write_text('private_target_received'))
    window.set_child(button)
    window.fullscreen()
    window.present()
    GLib.MainLoop().run()


def inside():
    proof = dict(result='PARTIAL', stage='isolation')
    settings = json.loads((PRIVATE / 'settings.json').read_text())
    current = {key: os.readlink('/proc/self/ns/' + key) for key in settings['namespaces']}
    proof['isolated_namespaces'] = [key for key, value in current.items()
                                     if value != settings['namespaces'][key]]
    proof['host_sockets_denied'] = {key: denied(value) for key, value in settings['sockets'].items()}
    if len(proof['isolated_namespaces']) != len(current) or not all(proof['host_sockets_denied'].values()):
        return proof
    runtime = PRIVATE / 'run'
    compositor = app = None
    try:
        proof['stage'] = 'start'
        with (PRIVATE / 'sway.log').open('wb') as log:
            compositor = subprocess.Popen(['/usr/bin/sway', '-c', '/private/sway.conf'],
                                          stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and compositor.poll() is None:
            sockets = list(runtime.glob('sway-ipc.*.sock'))
            displays = [path for path in runtime.glob('wayland-*') if not path.name.endswith('.lock')]
            if len(sockets) == len(displays) == 1:
                try:
                    command = ['/usr/bin/swaymsg', '-s', str(sockets[0])]
                    tree(command)
                    break
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
            time.sleep(.2)
        else:
            proof['reason'] = 'headless_start_unavailable'
            return proof
        proof['stage'] = 'private_window'
        app = subprocess.Popen([sys.executable, '-B', '/probe.py', '--gtk-child'],
                               env={**os.environ, 'WAYLAND_DISPLAY': displays[0].name,
                                    'GDK_BACKEND': 'wayland'}, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and app.poll() is None:
            current = list(nodes(tree(command)))
            if any(item.get('name') == TITLE and item.get('pid') == app.pid for item in current):
                proof.update(window_observed=True,
                             outputs=[item['name'] for item in current if item.get('type') == 'output'
                                      and item.get('name') != '__i3'])
                break
            time.sleep(.25)
        else:
            proof['reason'] = 'private_window_unavailable'
            return proof
        proof.update(stage='qualified_startup', startup='GO', capture='not_qualified', input='not_qualified')
        (PRIVATE / 'window.visible').write_text('private_window_observed')
        deadline = time.monotonic() + 5
        while not (PRIVATE / 'host.checked').exists() and time.monotonic() < deadline:
            time.sleep(.1)
        if not (PRIVATE / 'host.checked').is_file():
            proof['reason'] = 'live_host_boundary_unconfirmed'
            return proof
        helper = PRIVATE / 'effects'
        if helper.is_file() and proof['outputs'] == ['HEADLESS-1']:
            env = {**os.environ, 'WAYLAND_DISPLAY': displays[0].name}
            captured = subprocess.run([str(helper), 'capture'], env=env, capture_output=True,
                                      timeout=7, check=False)
            if captured.returncode == 0:
                info = json.loads(captured.stdout)
                if info['distinctPixels'] and (info['width'], info['height']) == (800, 600):
                    proof['capture'] = dict(scope='isolated_output', **info)
                    targets = [row for row in nodes(tree(command)) if row.get('pid')]
                    if len(targets) != 1 or targets[0].get('pid') != app.pid:
                        proof['input'] = 'private_target_ambiguous'
                        return proof
                    private_click = subprocess.run([str(helper), 'click'], env=env, capture_output=True,
                                                   timeout=5, check=False)
                    proof['input_exit'] = private_click.returncode
                    deadline = time.monotonic() + 3
                    while not (PRIVATE / 'clicked').exists() and time.monotonic() < deadline:
                        time.sleep(.1)
                    if private_click.returncode == 0 and (PRIVATE / 'clicked').is_file():
                        proof['input'] = 'private_button_confirmed'
                        proof.update(result='GO', stage='qualified_private_capture_and_input')
            proof['capture_exit'] = captured.returncode
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        proof['reason'] = type(error).__name__
    finally:
        terminate(app)
        terminate(compositor)
        proof['clean_shutdown'] = not list(runtime.glob('sway-ipc.*.sock')) and not [
            path for path in runtime.glob('wayland-*') if not path.name.endswith('.lock')]
    return proof


def run():
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='lb5-headless-') as folder:
        root = Path(folder)
        (root / 'run').mkdir(mode=0o700)
        (root / 'sway.conf').write_text('output HEADLESS-1 mode 800x600\nseat seat0 fallback true\n')
        source = Path(__file__).with_name('private_wayland_effects.c')
        try:
            subprocess.run(['/usr/bin/cc', '-Wall', '-Wextra', '-Werror', str(source),
                            '-lwayland-client', '-o', str(root / 'effects')],
                           capture_output=True, timeout=10, check=True)
        except (OSError, subprocess.SubprocessError):
            pass
        host = Path(os.environ['XDG_RUNTIME_DIR'])
        sockets = {'sway': os.environ['SWAYSOCK'], 'wayland': str(host / os.environ['WAYLAND_DISPLAY'])}
        session = os.environ.get('DBUS_SESSION_BUS_ADDRESS', '').removeprefix('unix:path=').split(',')[0]
        if session.startswith('/'):
            sockets['session_bus'] = session
        settings = dict(sockets=sockets, namespaces={key: os.readlink('/proc/self/ns/' + key)
                         for key in ('user', 'pid', 'mnt', 'net', 'ipc')})
        (root / 'settings.json').write_text(json.dumps(settings))
        host_command = ['/usr/bin/swaymsg', '-s', sockets['sway']]
        before = any(row.get('name') == TITLE for row in nodes(tree(host_command)))
        cmd = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent',
               '--ro-bind', '/usr', '/usr', '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
               '--symlink', 'usr/bin', '/bin', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
               '--ro-bind', '/etc/fonts', '/etc/fonts', '--bind', folder, '/private',
               '--ro-bind', str(Path(__file__).resolve()), '/probe.py', '--clearenv',
               '--setenv', 'PATH', '/usr/bin', '--setenv', 'HOME', '/private',
               '--setenv', 'XDG_RUNTIME_DIR', '/private/run', '--setenv', 'WLR_BACKENDS', 'headless',
               '--setenv', 'WLR_RENDERER', 'pixman', '--setenv', 'WLR_HEADLESS_OUTPUTS', '1',
               '--cap-drop', 'ALL', '--', '/usr/bin/python3', '-B', '/probe.py', '--inside']
        child = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        live_isolated = False
        try:
            deadline = time.monotonic() + 28
            while child.poll() is None and time.monotonic() < deadline:
                if (root / 'window.visible').is_file():
                    observed_host = any(row.get('name') == TITLE for row in nodes(tree(host_command)))
                    live_isolated = not before and not observed_host
                    if live_isolated:
                        (root / 'host.checked').write_text('host_tree_excludes_window')
                    break
                time.sleep(.1)
            output, _ = child.communicate(timeout=20)
        finally:
            terminate(child)
        if child.returncode:
            evidence = dict(result='PARTIAL', stage='namespace_process', code=child.returncode)
        else:
            evidence = json.loads(output)
        evidence['live_host_check_before_effects'] = live_isolated
        after = any(row.get('name') == TITLE for row in nodes(tree(host_command)))
        evidence['host_tree_excludes_private_window'] = not before and not after and live_isolated
        if not evidence['host_tree_excludes_private_window'] or not evidence.get('clean_shutdown'):
            evidence.update(result='PARTIAL')
        evidence['elapsed_seconds'] = round(time.monotonic() - start, 3)
        return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--inside', action='store_true')
    parser.add_argument('--gtk-child', action='store_true')
    args = parser.parse_args()
    if args.gtk_child:
        gtk_child()
        return
    if args.inside:
        print(json.dumps(inside()))
        return
    evidence = run()
    if args.evidence:
        with args.evidence.open('x') as stream:
            print(json.dumps(evidence, indent=2), file=stream)
    print(evidence['result'], evidence['stage'])
    return int(evidence['result'] != 'GO')


if __name__ == '__main__':
    raise SystemExit(main())
