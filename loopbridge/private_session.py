# SPDX-License-Identifier: Apache-2.0
"""Owner-mediated local lifecycle for disposable Wayland desktops."""
from contextlib import ExitStack, contextmanager, suppress
import json
import os
from pathlib import Path
import re
import secrets
import select
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

from .__main__ import read_private
from .identity import Identities
from .https_egress import Egress, UNIX_PROXY, destinations
from .process_boundary import close_bootstrap_stdin, protect_process
from .protocol import DeadlineChannel, Fault, request, unique_object
from .service import (DESKTOP_SESSION, Journal, directory_lock, legacy_listener,
                      private_directory, serve)
from .service_bootstrap import (HELPERS, HardenedService, VerifierRegistry, executable_helper,
                                load_systemd_manifest)
from .service_diagnostics import (Cleanup, Diagnostic, Phase, Reason, READINESS_ERRORS,
                                  READINESS_PROGRESS, readiness_error)
from .service_ingress import UNIX_PATH_LIMIT, bound_listener, path_inode, peer_uid
from .service_relay import SessionRelay

NS = ('user', 'pid', 'mnt', 'net', 'ipc')
PRIVATE = Path('/private')
MAX_SESSIONS = 4
STARTUP = 28
READINESS_RECORD_LIMIT = 4096
INSTANCE_ID = re.compile('[0-9a-f]{16}')


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


def wait_ready(process, deadline, *, phase=None, progress=None):
    def failure(reason):
        if phase is not None:
            return Diagnostic(phase, reason=reason)
        return RuntimeError('private_desktop_startup_failed')

    # Read directly from the pipe so buffered lines or a partial frame cannot
    # hide progress or keep readline() blocked past the readiness deadline.
    fd = process.stdout.fileno()
    pending = b''
    while (remaining := deadline - time.monotonic()) > 0:
        if not select.select([fd], [], [], remaining)[0]:
            break
        chunk = os.read(fd, READINESS_RECORD_LIMIT)
        if not chunk:
            raise failure(Reason.EOF)
        pending += chunk
        while b'\n' in pending:
            line, _, pending = pending.partition(b'\n')
            if len(line) >= READINESS_RECORD_LIMIT:
                raise failure(Reason.FRAME)
            if line == b'ready':
                return
            if phase is not None and line in READINESS_PROGRESS:
                phase = READINESS_PROGRESS[line]
                if progress is not None:
                    progress(phase)
            elif phase is not None and line in READINESS_ERRORS:
                failed_phase, reason = READINESS_ERRORS[line]
                raise Diagnostic(failed_phase, reason=reason)
        if len(pending) >= READINESS_RECORD_LIMIT:
            raise failure(Reason.FRAME)
    raise failure(Reason.TIMEOUT)


def announce_startup(phase):
    print(f'stage:{phase}', flush=True)


def lab_helpers(root, tools):
    effects = root / 'effects'
    stream = root / 'stream'
    for output, name, flags, libraries in (
            (effects, 'effects', [], ['-lwayland-client', '-lxkbcommon']),
            (stream, 'stream', ['-O2'], ['-lwayland-client'])):
        try:
            subprocess.run(['/usr/bin/cc', *flags, '-Wall', '-Wextra', '-Werror',
                            str(tools / f'private_wayland_{name}.c'), *libraries, '-o', str(output)],
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=True)
        except (OSError, subprocess.SubprocessError):
            output.unlink(missing_ok=True)
    return effects, stream


def isolated_python(entry):
    # -I omits /app from sys.path. Only the verified, read-only mount is added.
    code = ("import sys; sys.path.insert(0, '/app'); "
            f"from loopbridge.private_session import {entry}; raise SystemExit({entry}(hardened=True))")
    return ['/usr/bin/python3', '-I', '-B', '-c', code]


class Instance:
    def __init__(self, root, manifest, hosts=(), *, hardened=None):
        self.id = secrets.token_hex(8)
        self.root = root / self.id
        try:
            self.root.mkdir(mode=0o700)
            self.root_inode = path_inode(self.root.lstat())
        except OSError:
            if hardened is not None:
                raise Diagnostic(Phase.STATE_PREPARE, Cleanup.UNCONFIRMED) from None
            raise
        self.runtime = self.root / 'runtime'
        self.endpoint = self.runtime / 'socket/control.sock'
        self.hardened = hardened
        self.state = self.runtime
        self.relay = None
        self.ingress = ExitStack()
        self.process = None
        self.phase = 'starting'
        self.egress = None
        self.egress_thread = None
        self.hosts = hosts
        self.checks = {}
        self.exit = None
        startup_phase = Phase.STATE_PREPARE
        try:
            if hardened is not None:
                self.state = hardened.state / 'sessions' / self.id
                self.state.mkdir(mode=0o700)
                Journal(self.state.parent).sync()
            self.workspace = (self.root if hardened is None else self.state) / 'workspace'
            for path in (self.runtime, self.workspace, self.root / 'display', self.root / 'home'):
                path.mkdir(mode=0o700)
            if len(os.fsencode(self.endpoint)) >= UNIX_PATH_LIMIT:
                raise ValueError('private_socket_path_too_long')
            startup_phase = Phase.DESKTOP_STARTUP
            self.start_desktop(manifest)
            if hardened is not None:
                startup_phase = Phase.RELAY_PUBLICATION
                self.relay = SessionRelay(hardened.ingress, hardened.ingress.directory / (self.id + '.sock'),
                                          self.runtime / 'socket/relay.sock')
                self.ingress.enter_context(self.relay.serve())
            self.phase = 'ready'
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            if hardened is None:
                self.stop('failed')
                raise
            cleanup = Cleanup.UNCONFIRMED
            try:
                self.stop('failed')
                if not os.path.lexists(self.root):
                    cleanup = Cleanup.CONFIRMED
            except (OSError, RuntimeError, ValueError, KeyError):
                pass
            if isinstance(error, Diagnostic):
                raise Diagnostic(error.phase, cleanup, reason=error.reason) from None
            raise Diagnostic(startup_phase, cleanup) from None
        finally:
            if self.process:
                self.process.stdout.close()

    def start_desktop(self, manifest):
        source = Path(__file__).resolve().parent
        system = private_directory(self.root / 'system')
        uid, gid = os.getuid(), os.getgid()
        (system / 'passwd').write_text(f'loopbridge:x:{uid}:{gid}:Private desktop:/private/home:/bin/false\n')
        (system / 'group').write_text(f'loopbridge:x:{gid}:\n')
        (system / 'machine-id').write_text(secrets.token_hex(16) + '\n')
        if self.hardened is None:
            effects, stream = lab_helpers(self.root, source.parent / 'tools')
        else:
            self.hardened.require_helpers()
            effects, stream = self.hardened.helpers / 'effects', self.hardened.helpers / 'stream'
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
        if self.hardened is not None:
            command += ['--bind', str(self.state), '/private/state']
        if self.hosts:
            self.egress = Egress(self.root / 'display/https.sock', self.hosts)
            self.egress_thread = threading.Thread(target=self.egress.serve_forever, daemon=True)
            self.egress_thread.start()
            command += ['--ro-bind', str(self.root / 'display/https.sock'), UNIX_PROXY]
            env['LOOPBRIDGE_HTTPS_HOSTS'] = json.dumps(sorted(self.hosts))
        for key, value in env.items():
            command.extend(('--setenv', key, value))
        command += ['--', '/usr/bin/dbus-run-session', '--config-file=/app/loopbridge/private_dbus.conf', '--']
        command += (['/usr/bin/python3', '-B', '-m', 'loopbridge.private_session', '--inside']
                    if self.hardened is None else isolated_python('inside'))
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, start_new_session=True,
                                        close_fds=True)
        self.process.stdin.write((json.dumps(manifest) + '\n').encode())
        self.process.stdin.flush()
        phase = Phase.DESKTOP_STARTUP if self.hardened is not None else None
        wait_ready(self.process, time.monotonic() + STARTUP, phase=phase)
        try:
            checks = json.loads((self.root / 'display/boundary.json').read_text())
            self.checks = {name: checks[name] != host for name, host in namespaces().items()}
            if not all(self.checks.values()) or not self.endpoint.is_socket():
                raise RuntimeError('private_namespace_check_failed')
        except (OSError, RuntimeError, ValueError, KeyError, TypeError):
            if self.hardened is not None:
                raise Diagnostic(Phase.DESKTOP_BOUNDARY) from None
            raise

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
            self.ingress.close()
            if self.process:
                with suppress(OSError):
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
            if self.hardened is None:
                self.cleanup()
            else:
                with suppress(FileNotFoundError):
                    if path_inode(self.root.lstat()) == self.root_inode:
                        shutil.rmtree(self.root)

    def network(self):
        return dict(mode='https_connect' if self.hosts else 'offline', hosts=sorted(self.hosts),
                    events=self.egress.snapshot() if self.egress else [])

    def check_running(self):
        if self.phase == 'ready' and (self.process.poll() is not None
                                     or self.relay is not None and self.relay.stop.is_set()):
            self.stop('failed')
        return self.phase == 'ready'

    def status(self):
        self.check_running()
        endpoints = {}
        if self.phase == 'ready':
            endpoints['socket'] = str(self.endpoint)
            if self.relay is not None:
                endpoints['ingressSocket'] = str(self.relay.endpoint)
        return dict(id=self.id, phase=self.phase, namespaces=self.checks, exitCode=self.exit,
                    **journal_status(self.state, inspect_pending=self.phase != 'ready'), **endpoints)


def journal_status(state, *, inspect_pending):
    journal = Journal(state)
    blocked = journal.blocked(DESKTOP_SESSION)
    unknown = None
    if blocked and inspect_pending:
        with suppress(OSError):
            unknown = journal.intent(DESKTOP_SESSION)
    return dict(blocked=blocked, unknownOperation=unknown, cancellationAssumed=False)


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


def inside(*, hardened=False):
    protect_process()
    if hardened and not all(executable_helper(PRIVATE / name) for name in HELPERS):
        return 1
    manifest = sys.stdin.buffer.readline(4097)
    if not manifest.endswith(b'\n'):
        return 1
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    compositor = subprocess.Popen(['/usr/bin/sway', '-c', '/private/sway.conf'],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, close_fds=True)
    bridge = None
    startup_phase = Phase.DESKTOP_DISPLAY
    try:
        if hardened:
            announce_startup(startup_phase)
        env = {**os.environ, **inherited_display(compositor)}
        startup_phase = Phase.DESKTOP_BROKER
        if hardened:
            announce_startup(startup_phase)
        command = (isolated_python('inside_service') if hardened else
                   [sys.executable, '-B', '-m', 'loopbridge.private_session', '--inside-service'])
        bridge = subprocess.Popen(command, env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, close_fds=True)
        bridge.stdin.write(manifest)
        bridge.stdin.close()
        del manifest
        wait_ready(bridge, time.monotonic() + STARTUP - 2,
                   phase=startup_phase if hardened else None,
                   progress=announce_startup if hardened else None)
        bridge.stdout.close()
        startup_phase = Phase.DESKTOP_BOUNDARY
        if hardened:
            announce_startup(startup_phase)
        (PRIVATE / 'metadata/boundary.json').write_text(json.dumps(namespaces()))
        print('ready', flush=True)
        startup_phase = None
        while not stop.wait(.1):
            if compositor.poll() is not None or bridge.poll() is not None:
                return 1
            if select.select([sys.stdin], [], [], 0)[0]:
                return 0
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        if not hardened or startup_phase is None:
            raise
        if isinstance(error, Diagnostic):
            print(readiness_error(error.phase, error.reason), flush=True)
        else:
            print(readiness_error(startup_phase, None), flush=True)
        return 1
    finally:
        if bridge:
            terminate(bridge)
        terminate(compositor)


@contextmanager
def manager_socket(root, endpoint, *, hardened=False):
    with directory_lock(root):
        if not hardened and endpoint.is_socket():
            endpoint.unlink()
        listener = bound_listener if hardened else legacy_listener
        with listener(endpoint, backlog=4) as server:
            server.settimeout(.25)
            yield server


def manage(root, credentials=None, *, scoped=False, hardened=None):
    protect_process()
    if not root.is_absolute():
        raise ValueError('absolute_private_root_required')
    identities = Identities()
    endpoint = root / 'manager.sock'
    stop = threading.Event()
    instances = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    with ExitStack() as stack:
        registry = None
        if hardened is None:
            private_directory(root)
            identities.load_manifest(json.loads(read_private(credentials), object_pairs_hook=unique_object),
                                     allow_legacy=not scoped)
        else:
            if not isinstance(hardened, HardenedService) or credentials is not None:
                raise ValueError('invalid_hardened_bootstrap')
            hardened.validate(root)
            stack.enter_context(directory_lock(hardened.state))
            identities.load_manifest(load_systemd_manifest())
            registry = VerifierRegistry(hardened.state)
            registry.enroll_manager(identities.manifest())
            private_directory(hardened.state / 'sessions')
            Journal(hardened.state).sync()
            scoped = True
        manifest = identities.manifest()
        used_verifiers = set(manifest['verifiers'].values())
        server = stack.enter_context(manager_socket(root, endpoint, hardened=hardened is not None))
        try:
            print('ready', flush=True)
            while not stop.is_set():
                for instance in list(instances.values()):
                    if not instance.check_running() and hardened is not None:
                        del instances[instance.id]
                try:
                    client, _ = server.accept()
                except TimeoutError:
                    continue
                with client:
                    handle(client, root, identities, instances, manifest, scoped, used_verifiers,
                           hardened=hardened, registry=registry)
        finally:
            for instance in instances.values():
                instance.stop()


def retired_status(state, instance_id):
    if not INSTANCE_ID.fullmatch(instance_id):
        raise Fault(-32006, 'private_session_unavailable')
    try:
        folder = private_directory(state / 'sessions' / instance_id, create=False)
    except FileNotFoundError:
        raise Fault(-32006, 'private_session_unavailable') from None
    return dict(id=instance_id, phase='retired', namespaces={}, exitCode=None,
                **journal_status(folder, inspect_pending=True))


def handle(client, root, identities, instances, manifest, scoped, used_verifiers, *,
           hardened=None, registry=None):
    if (hardened is None) != (registry is None) or hardened is not None and not scoped:
        raise ValueError('incomplete_hardened_enrollment')
    channel = DeadlineChannel(client)
    if peer_uid(client) != os.getuid():
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
            elif method == 'private.start' and set(params) <= {'httpsHosts', 'credentialVerifiers'}:
                if len(instances) >= MAX_SESSIONS:
                    raise Fault(-32006, 'private_session_limit')
                try:
                    hosts = destinations(params.get('httpsHosts', []))
                except ValueError:
                    raise Fault(-32602, 'invalid_https_hosts') from None
                session_manifest = manifest
                if scoped:
                    session_identities = Identities()
                    try:
                        session_identities.load_verifiers(params.get('credentialVerifiers'))
                    except ValueError:
                        raise Fault(-32602, 'invalid_session_verifiers') from None
                    session_manifest = session_identities.manifest()
                    verifiers = set(session_manifest['verifiers'].values())
                    try:
                        reserved = (registry.reserve_session(verifiers) if registry is not None
                                    else not used_verifiers & verifiers)
                    except OSError:
                        raise Diagnostic(Phase.STATE_PREPARE) from None
                    if not reserved:
                        raise Fault(-32602, 'reused_session_verifier')
                elif 'credentialVerifiers' in params:
                    raise Fault(-32602, 'scoped_credentials_disabled')
                instance = Instance(root, session_manifest, hosts, hardened=hardened)
                if scoped and registry is None:
                    used_verifiers.update(verifiers)
                instances[instance.id] = instance
                result = instance.status()
                if hardened is not None and result['phase'] != 'ready':
                    del instances[instance.id]
                    cleanup = Cleanup.UNCONFIRMED if os.path.lexists(instance.root) else Cleanup.CONFIRMED
                    raise Diagnostic(Phase.DESKTOP_READY_EXITED, cleanup)
            elif method in ('private.status', 'private.stop', 'private.network') and set(params) == {'id'} and isinstance(params['id'], str):
                instance = instances.get(params['id'])
                if instance is None and hardened is not None and method == 'private.status':
                    result = retired_status(hardened.state, params['id'])
                elif instance is None:
                    raise Fault(-32006, 'private_session_unavailable')
                else:
                    if method == 'private.stop':
                        instance.stop()
                    result = instance.network() if method == 'private.network' else instance.status()
                    if hardened is not None and instance.phase != 'ready':
                        del instances[instance.id]
            else:
                raise Fault(-32601, 'method_not_found')
            reply = dict(result=result)
        except Fault as error:
            reply = dict(error=dict(code=error.code, message=error.message))
        except Diagnostic as error:
            data = {'cleanup': error.cleanup}
            if error.reason is not None:
                data['reason'] = error.reason
            reply = dict(error=dict(code=-32006, message=error.phase, data=data))
            with suppress(OSError):
                print(error, file=sys.stderr, flush=True)
        except (OSError, ValueError, RuntimeError):
            reply = dict(error=dict(code=-32006, message='private_session_failed'))
        try:
            channel.send(dict(jsonrpc='2.0', version=row['version'], id=seq, **reply))
        except OSError:
            return


def inside_service(*, hardened=False):
    from .presentation import Presentation
    from .private_effects import private_id

    progress = announce_startup if hardened else None
    if progress is not None:
        progress(Phase.BROKER_BOOTSTRAP)
    protect_process()
    identities = Identities()
    identities.load_manifest(json.loads(sys.stdin.buffer.readline(4097), object_pairs_hook=unique_object))
    close_bootstrap_stdin()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    presentation = Presentation(private_id())
    with serve(PRIVATE / 'runtime', identities, 'desktop', PRIVATE / 'workspace',
               watch_adapter=True, presentation=presentation,
               session_state=PRIVATE / 'state' if hardened else None,
               startup_progress=progress) as (endpoint, adapter):
        try:
            if progress is not None:
                progress(Phase.BROKER_READY)
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
