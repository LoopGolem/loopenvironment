# SPDX-License-Identifier: Apache-2.0
"""Trusted Sway and AT-SPI Calculator primitives promoted from M1.1."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import select
import subprocess
import time


class Rejected(RuntimeError):
    pass


def unique(items, reason):
    if len(items) != 1:
        raise Rejected(reason)
    return items[0]


def sway(kind):
    return json.loads(subprocess.check_output(
        ['swaymsg', '-r', '-t', kind], timeout=3))


def windows(tree):
    result = []
    if tree.get('pid') and (tree.get('app_id') or tree.get('window')):
        result.append({k: tree.get(k) for k in ('id', 'pid', 'app_id', 'shell')})
    for child in tree.get('nodes', []) + tree.get('floating_nodes', []):
        result.extend(windows(child))
    return result


def correlate(records, apps, pid):
    window = unique([w for w in records if w['pid'] == pid], 'window_missing_or_ambiguous')
    if window['app_id'] != 'org.gnome.Calculator' or window['shell'] != 'xdg_shell':
        raise Rejected('unexpected_window_identity')
    app = unique([a for a in apps if a.get_process_id() == pid], 'tree_missing_or_ambiguous')
    frame = unique([a for a in app if a.getRoleName() == 'frame'], 'frame_missing_or_ambiguous')
    return window, app, frame


def process_identity(pid):
    # comm may contain spaces and parentheses; field 22 follows the last ')'.
    stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return (pid, stat[19], os.stat(f'/proc/{pid}').st_uid,
            os.readlink(f'/proc/{pid}/exe'))


def walk(root):
    pending = [((), root)]
    count = 0
    while pending:
        path, node = pending.pop()
        count += 1
        if count > 1500 or len(path) > 40:
            raise Rejected('tree_limit')
        yield path, node
        pending.extend((path + (i,), node[i]) for i in reversed(range(node.childCount)))


def button(frame):
    return unique([(p, n) for p, n in walk(frame)
                   if n.getRoleName() in ('push button', 'button') and n.name == '7'],
                  'digit_missing_or_ambiguous')


def texts(frame):
    # Exclude labels: a button label containing '7' cannot verify the display.
    return {'.'.join(map(str, p)): n.queryText().getText(0, -1)
            for p, n in walk(frame)
            if n.getRoleName() == 'text' and 'Text' in n.get_interfaces()}


def click_index(node):
    if 'Action' not in node.get_interfaces():
        raise Rejected('action_interface_absent')
    action = node.queryAction()
    names = [action.getName(i) for i in range(action.nActions)]
    return unique([i for i, name in enumerate(names) if name == 'click'],
                  'click_missing_or_ambiguous'), names


@dataclass
class Reference:
    identity: tuple
    window: dict
    app: object
    frame: object
    node: object
    path: tuple
    deadline: float
    valid: bool = True

    def invalidate(self):
        self.valid = False


def wait_for(read, timeout=10):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            return read()
        except Exception as error:
            last = error
            time.sleep(.15)
    raise Rejected('readiness_timeout:' + type(last).__name__) from last


def discover(p, desktop):
    if p.poll() is not None:
        raise Rejected('owned_process_exited')
    return correlate(windows(sway('get_tree')), list(desktop()), p.pid)


def validate(ref, p, pidfd, desktop):
    if select.select([pidfd], [], [], 0)[0] or p.poll() is not None:
        raise Rejected('process_exited')
    if process_identity(p.pid) != ref.identity:
        raise Rejected('process_identity_changed')
    window, app, frame = discover(p, desktop)
    if window != ref.window or app != ref.app or frame != ref.frame:
        raise Rejected('source_identity_changed')
    path, node = button(frame)
    if path != ref.path or node != ref.node:
        raise Rejected('element_changed')
    import pyatspi
    state = node.getState()
    if state.contains(pyatspi.STATE_DEFUNCT) or not state.contains(pyatspi.STATE_SENSITIVE) or not state.contains(pyatspi.STATE_SHOWING):
        raise Rejected('element_unavailable')


class Fixture:
    def __init__(self):
        import pyatspi
        pyatspi.setTimeout(1000, 2000)
        self.desktop = lambda: pyatspi.Registry.getDesktop(0)
        if any(w['app_id'] == 'org.gnome.Calculator' for w in windows(sway('get_tree'))) or any(
                a.name == 'gnome-calculator' for a in self.desktop()):
            raise Rejected('existing_calculator_close_manually')
        self.process = subprocess.Popen(['/usr/bin/gnome-calculator', '--mode=basic'],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.pidfd = None
        self.display_paths = None
        try:
            self.pidfd = os.pidfd_open(self.process.pid)
            def executed():
                identity = process_identity(self.process.pid)
                if identity[3] != '/usr/bin/gnome-calculator':
                    raise Rejected('executable_not_ready')
                return identity
            self.identity = wait_for(executed)
            self.window, self.app, self.frame = wait_for(
                lambda: discover(self.process, self.desktop))
            def ready():
                button(self.frame)
                current = self.read()
                if not current:
                    raise Rejected('text_not_ready')
                return current
            self.current = wait_for(ready)
            if any(v not in ('', '0') for v in self.current.values()):
                raise Rejected('fixture_not_clean')
        except Exception:
            self.close()
            raise

    def read(self):
        if self.process.poll() is not None or process_identity(self.process.pid) != self.identity:
            raise Rejected('fixture_lifecycle_changed')
        window, app, frame = discover(self.process, self.desktop)
        if (window, app, frame) != (self.window, self.app, self.frame):
            raise Rejected('fixture_source_changed')
        if self.display_paths is None:
            values = texts(frame)
            if values:
                self.display_paths = tuple(values)
            return values
        values = {}
        for path in self.display_paths:
            node = frame
            for index in map(int, path.split('.')):
                node = node[index]
            if node.getRoleName() != 'text' or 'Text' not in node.get_interfaces():
                raise Rejected('display_changed')
            values[path] = node.queryText().getText(0, -1)
        return values

    def reference(self, ttl):
        path, node = button(self.frame)
        return Reference(self.identity, self.window, self.app, self.frame, node,
                            path, time.monotonic() + ttl)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        if self.pidfd is not None:
            os.close(self.pidfd)
            self.pidfd = None


class Calculator(Fixture):
    source = 'atspi_query'

    def snapshot(self):
        state = self.read()
        reference = self.reference(10)
        click_index(reference.node)
        return state, reference

    def prepare(self, ref, expected):
        if not ref.valid or time.monotonic() >= ref.deadline:
            raise Rejected('expired_reference')
        before = self.read()
        if before != expected:
            raise Rejected('state_changed')
        validate(ref, self.process, self.pidfd, self.desktop)
        index, _ = click_index(ref.node)
        return before, ref, ref.node.queryAction(), index

    def send(self, prepared):
        _, ref, action, index = prepared
        if not ref.valid or time.monotonic() >= ref.deadline:
            raise Rejected('expired_reference')
        ref.invalidate()
        if not action.doAction(index):
            raise Rejected('action_not_accepted')

    def confirm(self, prepared):
        before = prepared[0]

        def confirmed():
            # Fresh discovery and text query, independent of doAction's reply.
            after = self.read()
            changed = [path for path in before if after.get(path) != before[path]]
            if set(before) != set(after) or len(changed) != 1:
                raise Rejected('result_not_confirmed')
            path = changed[0]
            expected = '7' if before[path] in ('', '0') else before[path] + '7'
            if after[path] != expected:
                raise Rejected('result_not_confirmed')
            return after

        return wait_for(confirmed, timeout=3)
