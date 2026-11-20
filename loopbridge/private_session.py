# SPDX-License-Identifier: Apache-2.0
"""Owner-mediated local lifecycle for disposable Wayland desktops."""
from contextlib import contextmanager, suppress
import fcntl
import json
import os
from pathlib import Path
import secrets
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

from .__main__ import read_private
from .identity import Identities
from .https_egress import Egress, UNIX_PROXY, destinations
from .protocol import DeadlineChannel, Fault, request
from .service import DESKTOP_SESSION, Journal, private_directory, serve

NS = ('user', 'pid', 'mnt', 'net', 'ipc')
PRIVATE = Path('/private')
MAX_SESSIONS = 4
STARTUP = 28


def namespaces():
    return {name: os.readlink('/proc/self/ns/' + name) for name in NS}


def terminate(process, timeout=5):
    if process.poll() is None:
        with suppress(ProcessLookupError):
            process.terminate()
        try:
            process.wait(timeout)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                process.kill()
            process.wait()
    return process.returncode


def wait_ready(process, deadline):
    while time.monotonic() < deadline:
        if select.select([process.stdout], [], [], .1)[0]:
            line = process.stdout.readline(4096)
            if line == b'ready\n':
                return
            if not line:
                break
    raise RuntimeError('private_desktop_startup_failed')


class Instance:
    def __init__(self, root, credentials, hosts=()):
        self.id = secrets.token_hex(8)
        self.root = root / self.id
        self.root.mkdir(mode=0o700)
        self.runtime = self.root / 'runtime'
        self.workspace = self.root / 'workspace'
        for path in (self.runtime, self.workspace, self.root / 'display', self.root / 'home'):
            path.mkdir(mode=0o700)
        self.endpoint = self.runtime / 'socket/control.sock'
        if len(os.fsencode(self.endpoint)) >= 108:
            raise ValueError('private_socket_path_too_long')
        self.process = None
        self.phase = 'starting'
        self.egress = None
        self.egress_thread = None
        self.hosts = hosts
        self.checks = {}
        self.exit = None
        source = Path(__file__).resolve().parent
        system = private_directory(self.root / 'system')
        uid, gid = os.getuid(), os.getgid()
        (system / 'passwd').write_text(f'loopbridge:x:{uid}:{gid}:Private desktop:/private/home:/bin/false\n')
        (system / 'group').write_text(f'loopbridge:x:{gid}:\n')
        (system / 'machine-id').write_text(secrets.token_hex(16) + '\n')
        effects = self.root / 'effects'
        try:
            subprocess.run(['/usr/bin/cc', '-Wall', '-Wextra', '-Werror',
                            str(source.parent / 'tools/private_wayland_effects.c'),
                            '-lwayland-client', '-lxkbcommon', '-o', str(effects)], stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=10, check=True)
        except (OSError, subprocess.SubprocessError):
            effects.unlink(missing_ok=True)
        stream = self.root / 'stream'
        try:
            subprocess.run(['/usr/bin/cc', '-O2', '-Wall', '-Wextra', '-Werror',
                            str(source.parent / 'tools/private_wayland_stream.c'),
                            '-lwayland-client', '-o', str(stream)], stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=10, check=True)
        except (OSError, subprocess.SubprocessError):
            stream.unlink(missing_ok=True)
        (self.root / 'sway.conf').write_text(
            'output HEADLESS-1 mode 800x600\nseat seat0 fallback true\n')
        env = dict(PATH='/usr/bin', HOME='/private/home', XDG_RUNTIME_DIR='/private/run',
                   LANG='C.UTF-8', GDK_BACKEND='wayland', GTK_USE_PORTAL='0',
                   GSETTINGS_BACKEND='memory', WLR_BACKENDS='headless', WLR_RENDERER='pixman',
                   WLR_HEADLESS_OUTPUTS='1', LOOPBRIDGE_PRIVATE_ID=self.id)
        command = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--proc', '/proc',
                   '--dev', '/dev', '--tmpfs', '/tmp', '--ro-bind', '/usr', '/usr',
                   '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/lib', '/lib',
                   '--symlink', 'usr/lib64', '/lib64', '--ro-bind', '/etc/fonts', '/etc/fonts',
                   '--dir', '/etc', '--ro-bind', str(system / 'machine-id'), '/etc/machine-id',
                   '--ro-bind', str(system / 'passwd'), '/etc/passwd',
                   '--ro-bind', str(system / 'group'), '/etc/group',
                   '--ro-bind', str(source), '/app/loopbridge',
                   '--ro-bind', '/usr/share/dbus-1/services/org.a11y.Bus.service',
                   '/private/dbus-services/org.a11y.Bus.service',
                   '--ro-bind', str(self.root / 'sway.conf'), '/private/sway.conf',
                   '--bind', str(self.root / 'home'), '/private/home',
                   '--perms', '0700', '--tmpfs', '/private/run',
                   '--bind', str(self.root / 'display'), '/private/metadata',
                   '--bind', str(self.runtime), '/private/runtime',
                   '--bind', str(self.workspace), '/private/workspace',
                   '--cap-drop', 'ALL', '--clearenv', '--chdir', '/app']
        if effects.is_file():
            command += ['--ro-bind', str(effects), '/private/effects']
        if stream.is_file():
            command += ['--ro-bind', str(stream), '/private/stream']
        if hosts:
            self.egress = Egress(self.root / 'display/https.sock', hosts)
            self.egress_thread = threading.Thread(target=self.egress.serve_forever, daemon=True)
            self.egress_thread.start()
            command += ['--ro-bind', str(self.root / 'display/https.sock'), UNIX_PROXY]
            env['LOOPBRIDGE_HTTPS_HOSTS'] = json.dumps(sorted(hosts))
        for key, value in env.items():
            command.extend(('--setenv', key, value))
        command += ['--', '/usr/bin/dbus-run-session', '--config-file=/app/loopbridge/private_dbus.conf',
                    '--', '/usr/bin/python3', '-B', '-m', 'loopbridge.private_session', '--inside']
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, start_new_session=True)
            self.process.stdin.write(credentials)
            self.process.stdin.flush()
            wait_ready(self.process, time.monotonic() + STARTUP)
            checks = json.loads((self.root / 'display/boundary.json').read_text())
            self.checks = {name: checks[name] != host for name, host in namespaces().items()}
            if not all(self.checks.values()) or not self.endpoint.is_socket():
                raise RuntimeError('private_namespace_check_failed')
            self.phase = 'ready'
        except (OSError, RuntimeError, ValueError, KeyError):
            self.stop('failed')
            raise
        finally:
            if self.process:
                self.process.stdout.close()

    def cleanup(self):
        # Persistent effects and journal records remain together at the old root.
        # Only this instance's transient directories and endpoint are removed.
        for dir_name in ('display', 'home', 'system'):
            path = self.root / dir_name
            if path.is_dir():
                shutil.rmtree(path)
        self.endpoint.unlink(missing_ok=True)
        (self.root / 'effects').unlink(missing_ok=True)
        (self.root / 'stream').unlink(missing_ok=True)
        for path in self.runtime.glob('apps-*'):
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)

    def stop(self, phase='stopped'):
        if self.phase in ('starting', 'ready'):
            if self.process:
                self.process.stdin.close()
                try:
                    self.exit = self.process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    self.exit = terminate(self.process)
            if self.egress:
                self.egress.shutdown()
                self.egress.server_close()
                self.egress_thread.join(timeout=1)
            self.phase = 'failed' if phase == 'stopped' and self.exit != 0 else phase
            self.cleanup()

    def network(self):
        return dict(mode='https_connect' if self.hosts else 'offline', hosts=sorted(self.hosts),
                    events=self.egress.snapshot() if self.egress else [])

    def status(self):
        if self.phase == 'ready' and self.process.poll() is not None:
            self.stop('failed')
        journal = Journal(self.runtime)
        blocked = journal.blocked(DESKTOP_SESSION)
        unknown = None
        if blocked and self.phase != 'ready':
            with suppress(OSError):
                unknown = journal.intent(DESKTOP_SESSION)
        return dict(id=self.id, phase=self.phase, namespaces=self.checks, exitCode=self.exit,
                    blocked=blocked, unknownOperation=unknown, cancellationAssumed=False,
                    **({'socket': str(self.endpoint)} if self.phase == 'ready' else {}))


def inherited_display(compositor):
    runtime = Path(os.environ['XDG_RUNTIME_DIR'])
    expires = time.monotonic() + 14
    while compositor.poll() is None and time.monotonic() < expires:
        display = [p for p in runtime.glob('wayland-*') if p.is_socket()]
        sway = [p for p in runtime.glob('sway-ipc.*.sock') if p.is_socket()]
        if len(display) == len(sway) == 1:
            return dict(WAYLAND_DISPLAY=display[0].name, SWAYSOCK=str(sway[0]))
        time.sleep(.05)
    raise RuntimeError('private_display_unavailable')


def inside():
    credentials = sys.stdin.buffer.readline(4097)
    if not credentials.endswith(b'\n'):
        return 1
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    compositor = subprocess.Popen(['/usr/bin/sway', '-c', '/private/sway.conf'],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    bridge = None
    try:
        env = {**os.environ, **inherited_display(compositor)}
        bridge = subprocess.Popen([sys.executable, '-B', '-m', 'loopbridge.private_session',
                                   '--inside-service'], env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE)
        bridge.stdin.write(credentials)
        bridge.stdin.close()
        del credentials
        wait_ready(bridge, time.monotonic() + STARTUP - 2)
        bridge.stdout.close()
        (PRIVATE / 'metadata/boundary.json').write_text(json.dumps(namespaces()))
        print('ready', flush=True)
        while not stop.wait(.1):
            if compositor.poll() is not None or bridge.poll() is not None:
                return 1
            if select.select([sys.stdin], [], [], 0)[0]:
                return 0
        return 0
    finally:
        if bridge:
            terminate(bridge)
        terminate(compositor)


@contextmanager
def manager_socket(root, endpoint):
    lock = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if endpoint.is_socket():
            endpoint.unlink()
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(endpoint))
            try:
                endpoint.chmod(0o600)
                server.listen(4)
                server.settimeout(.25)
                yield server
            finally:
                endpoint.unlink(missing_ok=True)
    finally:
        os.close(lock)


def manage(root, credentials):
    if not root.is_absolute():
        raise ValueError('absolute_private_root_required')
    root = private_directory(root)
    credentials = (read_private(credentials).rstrip('\n') + '\n').encode()
    identities = Identities()
    identities.load(json.loads(credentials))
    endpoint = root / 'manager.sock'
    stop = threading.Event()
    instances = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    with manager_socket(root, endpoint) as server:
        try:
            print('ready', flush=True)
            while not stop.is_set():
                for instance in instances.values():
                    if instance.phase == 'ready' and instance.process.poll() is not None:
                        instance.stop('failed')
                try:
                    client, _ = server.accept()
                except TimeoutError:
                    continue
                with client:
                    handle(client, root, credentials, identities, instances)
        finally:
            for instance in instances.values():
                instance.stop()


def handle(client, root, credentials, identities, instances):
    channel = DeadlineChannel(client)
    uid = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
    if uid != os.getuid():
        return
    owner = False
    last_id = -1
    for _ in range(12):
        try:
            row = channel.receive(2)
            seq, method, params = request(row)
            if seq <= last_id:
                return
            last_id = seq
        except (Fault, OSError, EOFError):
            return
        try:
            if method == 'auth':
                owner = False
                if set(params) != {'credential'} or identities.authenticate(params['credential']) != 'owner':
                    raise Fault(-32001, 'denied')
                owner = True
                result = {'principal': 'owner'}
            elif not owner:
                raise Fault(-32001, 'denied')
            elif method == 'private.list' and not params:
                result = {'instances': [instance.status() for instance in instances.values()]}
            elif method == 'private.start' and set(params) <= {'httpsHosts'}:
                if len(instances) >= MAX_SESSIONS:
                    raise Fault(-32006, 'private_session_limit')
                try:
                    hosts = destinations(params.get('httpsHosts', []))
                except ValueError:
                    raise Fault(-32602, 'invalid_https_hosts') from None
                instance = Instance(root, credentials, hosts)
                instances[instance.id] = instance
                result = instance.status()
            elif method in ('private.status', 'private.stop', 'private.network') and set(params) == {'id'} and isinstance(params['id'], str):
                instance = instances.get(params['id'])
                if not instance:
                    raise Fault(-32006, 'private_session_unavailable')
                if method == 'private.stop':
                    instance.stop()
                result = instance.network() if method == 'private.network' else instance.status()
            else:
                raise Fault(-32601, 'method_not_found')
            reply = dict(result=result)
        except Fault as error:
            reply = dict(error=dict(code=error.code, message=error.message))
        except (OSError, ValueError, RuntimeError):
            reply = dict(error=dict(code=-32006, message='private_session_failed'))
        try:
            channel.send(dict(jsonrpc='2.0', version=row['version'], id=seq, **reply))
        except OSError:
            return


def inside_service():
    from .presentation import Presentation
    from .private_effects import private_id

    identities = Identities()
    identities.load(json.loads(sys.stdin.buffer.readline(4097)))
    sys.stdin.close()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    presentation = Presentation(private_id())
    with serve(PRIVATE / 'runtime', identities, 'desktop', PRIVATE / 'workspace',
               watch_adapter=True, presentation=presentation) as (endpoint, adapter):
        try:
            print('ready', flush=True)
            while not stop.wait(.1):
                if not adapter.process.is_alive():
                    return 1
        finally:
            presentation.close()
    return 0


if __name__ == '__main__':
    if sys.argv[1:] == ['--inside']:
        raise SystemExit(inside())
    if sys.argv[1:] == ['--inside-service']:
        raise SystemExit(inside_service())
    raise SystemExit(2)
