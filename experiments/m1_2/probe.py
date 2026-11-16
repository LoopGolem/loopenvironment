# SPDX-License-Identifier: Apache-2.0
"""Independent raw OS probes: no broker code or claim of policy enforcement."""
import errno
import glob
import os
import socket
import stat
import subprocess


def connect(address):
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(.4)
    try:
        sock.connect(address)
        return {'connected': True}
    except OSError as error:
        return {'connected': False, 'errno': error.errno}
    finally:
        sock.close()


def inspect(config, allowed_socket=None):
    denied = {}
    for name, address in config['endpoints'].items():
        denied[name] = connect(address)
    # Try reaching host resources through proc roots, not only original paths.
    for name, address in config['endpoints'].items():
        if address.startswith('/'):
            denied['proc_root_' + name] = connect('/proc/1/root' + address)
    devices = glob.glob('/dev/input/*') + glob.glob('/dev/dri/*') + glob.glob('/dev/video*')
    denied_devices = {}
    for path in config['devices']:
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except OSError as error:
            denied_devices[path.rsplit('/', 1)[-1]] = error.errno
        else:
            os.close(fd)
            raise AssertionError('protected_device_opened')
    # Look for any inherited socket descriptor BEFORE creating the Bridge socket.
    inherited = []
    unexpected = []
    for entry in os.listdir('/proc/self/fd'):
        try:
            mode = os.fstat(int(entry)).st_mode
            if int(entry) > 2 and int(entry) != allowed_socket:
                unexpected.append(int(entry))
            if stat.S_ISSOCK(mode) and int(entry) != allowed_socket:
                inherited.append(int(entry))
        except OSError:
            pass
    status = open('/proc/self/status').read().splitlines()
    security = {line.split(':')[0]: line.split(':', 1)[1].strip()
                for line in status if line.startswith(('CapEff:', 'NoNewPrivs:'))}
    ns = {k: os.readlink('/proc/self/ns/' + k) for k in config['host_ns']}
    assert all(ns[k] != config['host_ns'][k] for k in ns), 'shared_namespace'
    assert security == {'CapEff': '0000000000000000', 'NoNewPrivs': '1'}, 'unsafe_privileges'
    assert not devices and not inherited and not unexpected, 'inherited_descriptor_or_device'
    assert all(not r['connected'] and r.get('errno') in (errno.ENOENT, errno.EACCES, errno.ECONNREFUSED)
               for r in denied.values()), 'direct_session_access'
    nested = subprocess.run(['/usr/bin/unshare', '--user', '--map-root-user', '/usr/bin/true'],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=2, close_fds=True)
    assert nested.returncode != 0, 'nested_userns_available'
    assert not os.path.exists('/home') and not os.path.exists('/sys'), 'host_tree_visible'
    assert not os.path.exists('/proc/' + str(config['broker_pid'])), 'broker_visible_in_proc'
    return dict(endpoints=denied, devices=denied_devices, exposed_device_count=len(devices),
                inherited_socket_count=len(inherited), unexpected_descriptor_count=len(unexpected),
                private_namespaces=list(ns), security=security,
                nested_userns_denied=True)
