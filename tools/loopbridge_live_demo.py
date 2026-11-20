# SPDX-License-Identifier: Apache-2.0
"""Helpers and an offline editor exercise for the local GTK observation window."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time

from loopbridge.__main__ import provision, read_private
from loopbridge.observation import observe
from loopbridge.protocol import Fault

from .loopbridge_demo import Process
from .loopbridge_desktop_demo import grant
from .loopbridge_private_demo import connect_rpc
from .mcp_mission import Client, SESSION, require, window


class LiveView:
    def __init__(self, stack, private, credentials):
        self.instance = private['id']
        self.mark = credentials.parent / 'viewer.json'
        command = [sys.executable, '-B', '-m', 'tools.loopbridge_watch',
                   '--socket', private['socket'], '--token-file', str(credentials / 'observer.token'),
                   '--expected-private-id', self.instance, '--ready-file', str(self.mark)]
        self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, close_fds=True)
        stack.callback(self.close)
        print('Janela LoopBridge na VM · instância ' + self.instance, flush=True)
        try:
            self.sample()
        except RuntimeError:
            print('Para abrir a janela na sessão gráfica: ' + shlex.join(command), flush=True)
            raise

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

    def sample(self, after=0, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self.process.poll() is None:
            try:
                frame = json.loads(self.mark.read_text())
                if (frame['privateId'] == self.instance and frame['monotonic'] >= after
                        and time.monotonic() - frame['monotonic'] < 2.5):
                    return {key: frame[key] for key in ('privateId', 'capturedAt', 'revision',
                                                       'frames', 'changes', 'width', 'height')}
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(.1)
        raise RuntimeError('live_viewer_frame_unavailable')


def client_command(private, credentials, principal):
    return [sys.executable, '-B', '-m', 'tools.loopbridge_mcp_sandbox',
            '--socket', private['socket'], '--token-file', credentials / (principal + '.token')]


def editor_target(client):
    offset = 0
    ref = window(client, 'editor')
    while offset is not None:
        page = client.call('element_tree', **SESSION, ref=ref, offset=offset, depth=40)
        entries = [row for row in page['elements'] if row['editable'] and 'multi_line' in row['state']]
        if entries:
            require(len(entries) == 1, 'editor_target_ambiguous')
            return entries[0]['ref']
        offset = page['next']
    raise RuntimeError('editor_target_unavailable')


def fixture(root, evidence):
    with ExitStack() as stack:
        creds = root / 'credentials'
        provision(creds)
        token = lambda principal: read_private(creds / (principal + '.token')).strip()
        manager = Process(stack, [sys.executable, '-B', '-m', 'loopbridge', 'private',
                                  '--root', root / 'private', '--credentials', creds / 'service.json'])
        require(manager.line() == b'ready\n', 'private_manager_not_ready')
        def admin(method, **params):
            with ExitStack() as connection:
                bridge = connect_rpc(connection, root / 'private/manager.sock', token('owner'))
                return bridge.call(method, **params)

        private = admin('private.start')
        owner = connect_rpc(stack, private['socket'], token('owner'))
        for cap, target in (('desktop.capture', '*'), ('session.discover', '*'),
                            ('desktop.observe', 'app:editor')):
            grant(owner, 'observer', cap, target)
        for cap, target in (('workspace.read', 'workspace'), ('workspace.write', 'workspace'),
                            ('session.discover', '*'), ('desktop.observe', 'app:editor'),
                            ('desktop.control', 'app:editor'), ('app.launch', 'app:editor')):
            grant(owner, 'delegate', cap, target)
        viewer = LiveView(stack, private, creds)
        evidence['firstFrame'] = viewer.sample()
        stop = threading.Event()
        failures = []
        scheduled = ((10, 'submitting'), (30, 'received'), (60, 'processing'), (120, 'completed'))
        evidence['fixtureDelaySeconds'] = [delay for delay, _ in scheduled]
        evidence['mcpMutations'] = []
        with Client(client_command(private, creds, 'delegate'), modern=True) as agent:
            permit = agent.call('lease_acquire', **SESSION, ttl=170)
            lease = dict(**SESSION, lease=permit['id'], epoch=permit['epoch'], generation=permit['generation'])
            agent.call('workspace_write', **lease, path='async.txt', text='verifying\n')
            agent.call('app_open_document', **lease, app='editor', document='async.txt')
            started = time.monotonic()

            def advance():
                try:
                    for delay, state in scheduled:
                        while (remaining := started + delay - time.monotonic()) > 0:
                            if stop.wait(min(20, remaining)):
                                return
                            if remaining > 20:
                                agent.call('sessions_list')
                        agent.call('element_set_text', **lease, ref=editor_target(agent), text=state)
                        evidence['mcpMutations'].append(dict(state=state, tool='element_set_text',
                            seconds=round(time.monotonic() - started, 3)))
                except (OSError, RuntimeError, ValueError) as error:
                    failures.append(str(error))

            driver = threading.Thread(target=advance)
            with Client(client_command(private, creds, 'observer'), modern=True) as observer:
                evidence['observerControlDenied'] = (
                    'lease_acquire' not in observer.tools and
                    observer.refused('lease_acquire', **SESSION, ttl=10) == 'grant_denied')
                require(evidence['observerControlDenied'], 'observer_can_control')
                driver.start()
                try:
                    def read():
                        try:
                            return dict(status=observer.call('element_get_text', **SESSION,
                                ref=editor_target(observer))['text'].strip())
                        except (RuntimeError, OSError, Fault):
                            return dict(status='pending')

                    evidence['observation'] = observe(read, timeout=132, interval=5,
                        on_change=lambda event: event.update(frame=viewer.sample(after=time.monotonic())))
                    require(evidence['observation']['state'] == 'success', 'fixture_not_observed')
                finally:
                    stop.set()
                    driver.join()
        require(not failures, 'fixture_mcp_driver_failed')
        last = viewer.sample()
        evidence['lastFrame'] = last
        require(last['changes'] >= 5, 'visible_fixture_changes_missing')
        viewer.close()
        require(admin('private.status', id=private['id'])['phase'] == 'ready',
                'viewer_closed_private_session')
        evidence.update(sessionReadyAfterViewerClose=True, result='GO')
        admin('private.stop', id=private['id'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    evidence = dict(result='PARTIAL')
    try:
        with tempfile.TemporaryDirectory(prefix='lb6-live-') as folder:
            fixture(Path(folder), evidence)
    except (OSError, RuntimeError, EOFError, ValueError, KeyError, Fault) as error:
        evidence['reason'] = str(error) if type(error) is RuntimeError else type(error).__name__
    with args.evidence.open('x') as output:
        json.dump(evidence, output, indent=2)
    print(evidence['result'], evidence.get('reason', ''), flush=True)
    return int(evidence['result'] != 'GO')


if __name__ == '__main__':
    raise SystemExit(main())
