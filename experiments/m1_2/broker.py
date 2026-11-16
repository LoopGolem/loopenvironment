# SPDX-License-Identifier: Apache-2.0
"""One-fixture broker. Runs only inside the trusted lab session."""
import hmac
import os
import secrets
import select
import socket
import struct
import subprocess
import time

from experiments.m1_1 import semantic as m1
from experiments.m1_2.protocol import Channel, Fault, History, request


class Fixture:
    def __init__(self):
        import pyatspi
        pyatspi.setTimeout(1000, 2000)
        self.desktop = lambda: pyatspi.Registry.getDesktop(0)
        if any(w['app_id'] == 'org.gnome.Calculator' for w in m1.windows(m1.sway('get_tree'))) or any(
                a.name == 'gnome-calculator' for a in self.desktop()):
            raise m1.Rejected('existing_calculator_close_manually')
        self.process = subprocess.Popen(['/usr/bin/gnome-calculator', '--mode=basic'],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.pidfd = None
        self.display_paths = None
        try:
            self.pidfd = os.pidfd_open(self.process.pid)
            def executed():
                identity = m1.process_identity(self.process.pid)
                if identity[3] != '/usr/bin/gnome-calculator':
                    raise m1.Rejected('executable_not_ready')
                return identity
            self.identity = m1.wait_for(executed)
            self.window, self.app, self.frame = m1.wait_for(
                lambda: m1.discover(self.process, self.desktop))
            def ready():
                m1.button(self.frame)
                current = self.read()
                if not current:
                    raise m1.Rejected('text_not_ready')
                return current
            self.current = m1.wait_for(ready)
            if any(v not in ('', '0') for v in self.current.values()):
                raise m1.Rejected('fixture_not_clean')
        except Exception:
            self.close()
            raise

    def read(self):
        if self.process.poll() is not None or m1.process_identity(self.process.pid) != self.identity:
            raise m1.Rejected('fixture_lifecycle_changed')
        window, app, frame = m1.discover(self.process, self.desktop)
        if (window, app, frame) != (self.window, self.app, self.frame):
            raise m1.Rejected('fixture_source_changed')
        if self.display_paths is None:
            values = m1.texts(frame)
            if values:
                self.display_paths = tuple(values)
            return values
        values = {}
        for path in self.display_paths:
            node = frame
            for index in map(int, path.split('.')):
                node = node[index]
            if node.getRoleName() != 'text' or 'Text' not in node.get_interfaces():
                raise m1.Rejected('display_changed')
            values[path] = node.queryText().getText(0, -1)
        return values

    def reference(self, ttl):
        path, node = m1.button(self.frame)
        return m1.Reference(self.identity, self.window, self.app, self.frame, node,
                            path, time.monotonic() + ttl)

    def invoke(self, reference, grant_valid):
        before = self.read()
        def dispatch_check(ref):
            m1.validate(ref, self.process, self.pidfd, self.desktop)
            if not grant_valid():
                raise m1.Rejected('grant_expired')
            if time.monotonic() >= ref.deadline:
                raise m1.Rejected('expired_reference')
        reference.dispatch(dispatch_check)
        def confirmed():
            after = self.read()
            changed = [p for p in before if after.get(p) != before[p]]
            if len(changed) != 1 or after[changed[0]] != before[changed[0]] + '7':
                raise m1.Rejected('result_not_confirmed')
            return after
        self.current = m1.wait_for(confirmed, timeout=3)
        return self.current

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=5)
        if self.pidfd is not None:
            os.close(self.pidfd)
            self.pidfd = None


class Broker:
    def __init__(self, fixture, secret, uid, ttl=10):
        self.fixture, self.secret, self.uid, self.ttl = fixture, secret, uid, ttl
        self.epoch = secrets.token_hex(16)
        self.history = History(self.epoch)
        self.last = fixture.read()
        self.deadline = time.monotonic() + 180
        self.audit = []

    def poll(self):
        state = self.fixture.read()
        if state != self.last:
            self.last = state
            self.history.append(state)

    def handle(self, state, method, params):
        # Every call is checked against the live, fixture-scoped grant.
        if method == 'auth':
            state['authorized'] = False
            self.invalidate(state)
            if set(params) != {'credential'} or not isinstance(params['credential'], str):
                raise Fault(-32001, 'denied')
            if state['uid'] != self.uid or time.monotonic() >= self.deadline or not hmac.compare_digest(
                    params['credential'].encode(), self.secret.encode()):
                raise Fault(-32001, 'denied')
            state['authorized'] = True
            return {'authorized': True, 'scope': 'fixture.read+digit7+events'}
        if not state['authorized'] or state['uid'] != self.uid or time.monotonic() >= self.deadline:
            raise Fault(-32001, 'denied')
        if method == 'snapshot':
            if params:
                raise Fault(-32602, 'invalid_params')
            self.poll()
            self.invalidate(state)
            state['handle'] = secrets.token_hex(16)
            state['reference'] = self.fixture.reference(self.ttl)
            state['subscribed'] = True
            return dict(epoch=self.epoch, cursor=self.history.seq, state=self.last,
                        reference=state['handle'], reference_ttl=self.ttl)
        if method == 'invoke7':
            if set(params) != {'reference'} or not isinstance(params['reference'], str):
                raise Fault(-32602, 'invalid_params')
            if not state.get('reference') or params['reference'] != state.get('handle'):
                raise Fault(-32002, 'expired_reference')
            try:
                self.fixture.invoke(state['reference'],
                                    lambda: state['authorized'] and time.monotonic() < self.deadline)
                self.poll()
            except m1.Rejected as error:
                if str(error) == 'grant_expired':
                    raise Fault(-32001, 'denied') from None
                if str(error) == 'expired_reference':
                    raise Fault(-32002, 'expired_reference') from None
                raise Fault(-32006, 'fixture_unavailable_or_outcome_unknown') from None
            return {'confirmed': True, 'cursor': self.history.seq}
        if method == 'events':
            if set(params) != {'epoch', 'cursor'}:
                raise Fault(-32602, 'invalid_params')
            if not state.get('subscribed'):
                raise Fault(-32004, 'snapshot_required')
            self.poll()
            return dict(epoch=self.epoch, events=self.history.since(params['epoch'], params['cursor']),
                        cursor=self.history.seq)
        raise Fault(-32601, 'method_not_found')

    @staticmethod
    def invalidate(state):
        if state.get('reference'):
            state['reference'].invalidate()
        state.pop('reference', None)
        state.pop('handle', None)

    def serve_connection(self, connection):
        pid, uid, gid = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        state = dict(authorized=False, uid=uid)
        channel = Channel(connection)
        connection.settimeout(.15)
        deadline = time.monotonic() + 90
        request_count = 0
        try:
            while time.monotonic() < deadline and request_count < 32:
                try:
                    value = channel.receive()
                except socket.timeout:
                    continue
                request_id, method, params = request(value)
                request_count += 1
                started = time.monotonic()
                try:
                    result = self.handle(state, method, params)
                    reply = dict(jsonrpc='2.0', id=request_id, result=result)
                    outcome = 'ok'
                except Fault as error:
                    reply = dict(jsonrpc='2.0', id=request_id,
                                 error=dict(code=error.code, message=error.message))
                    outcome = error.message
                self.audit.append(dict(method=method if method in ('auth', 'snapshot', 'invoke7', 'events') else 'unknown_method', outcome=outcome, peer_uid=uid,
                                       authorized=state['authorized'], duration_ms=round((time.monotonic()-started)*1000)))
                channel.send(reply)
        except (EOFError, OSError, Fault):
            pass  # No outstanding mutation queue or automatic retries.
        finally:
            self.invalidate(state)
            connection.close()

    def serve_until(self, listener, child):
        deadline = time.monotonic() + 120
        while child.poll() is None and time.monotonic() < deadline:
            if select.select([listener], [], [], .1)[0]:
                connection, _ = listener.accept()
                self.serve_connection(connection)
        if child.poll() is None:
            child.terminate()
            raise RuntimeError('client_timeout')
