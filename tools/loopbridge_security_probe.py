# SPDX-License-Identifier: Apache-2.0
"""Non-mutating same-UID checks against disposable sessions. Emit only outcomes."""
import json
import os
from pathlib import Path
import subprocess
import sys


def can_open(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return False
    os.close(fd)
    return True


def can_readlink(path):
    try:
        os.readlink(path)
    except OSError:
        return False
    return True


def proc_access(pid):
    root = Path(f'/proc/{pid}')
    return dict(pidMetadata=can_open(root / 'stat'), procRoot=can_readlink(root / 'root'),
                outputFd=can_open(root / 'fd/1'), environment=can_open(root / 'environ'),
                memory=can_open(root / 'mem'))


def direct_display(pid, wayland_probe):
    display = Path(f'/proc/{pid}/root/private/run')
    wayland = next((path for path in display.glob('wayland-*') if path.is_socket()), None)
    sway = next(iter(display.glob('sway-ipc.*.sock')), None)
    result = dict(waylandRegistry=False, screencopyAdvertised=False, virtualInputAdvertised=False,
                  swayOutputQuery=False, dbusGetId=False)
    if wayland:
        run = subprocess.run([wayland_probe], env={'WAYLAND_DISPLAY': str(wayland)},
                             capture_output=True, timeout=4)
        result.update(waylandRegistry=run.returncode == 0,
                      screencopyAdvertised=b'zwlr_screencopy_manager_v1' in run.stdout,
                      virtualInputAdvertised=b'zwlr_virtual_pointer_manager_v1' in run.stdout
                      and b'zwp_virtual_keyboard_manager_v1' in run.stdout)
    if sway:
        result['swayOutputQuery'] = subprocess.run(
            ['/usr/bin/swaymsg', '-s', str(sway), '-t', 'get_outputs'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4).returncode == 0
    result['dbusGetId'] = subprocess.run(
        ['/usr/bin/gdbus', 'call', '--address', 'unix:path=' + str(display / 'session-bus'),
         '--dest', 'org.freedesktop.DBus', '--object-path', '/org/freedesktop/DBus',
         '--method', 'org.freedesktop.DBus.GetId'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4).returncode == 0
    return result


def main():
    query = json.load(sys.stdin)
    result = {role: proc_access(pid) for role, pid in query['processes'].items()}
    if 'display' in query:
        result['directDisplay'] = direct_display(query['display'], query['waylandProbe'])
        manifest = Path(query['manifest'])
        result['manifestReadable'] = can_open(manifest)
        result['clientBearerFilesPresent'] = bool(list(manifest.parent.glob('*.token')))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
