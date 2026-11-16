# SPDX-License-Identifier: Apache-2.0
"""Trusted local M1.1 diagnostic; no public Bridge API."""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
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

    def dispatch(self, check):
        # Reject before touching any old AT-SPI proxy, let alone dispatching.
        if not self.valid or time.monotonic() >= self.deadline:
            self.valid = False
            raise Rejected('expired_reference')
        try:
            check(self)
            index, names = click_index(self.node)
        except Exception:
            self.valid = False
            raise
        if not self.node.queryAction().doAction(index):
            raise Rejected('action_not_accepted')
        return names


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


def run(report):
    import pyatspi
    pyatspi.setTimeout(1000, 2000)
    desktop = lambda: pyatspi.Registry.getDesktop(0)
    # Check both sources before launching; never adopt/close an existing calculator.
    existing = windows(sway('get_tree'))
    if any(w['app_id'] == 'org.gnome.Calculator' for w in existing) or any(
            a.name == 'gnome-calculator' for a in desktop()):
        raise Rejected('existing_calculator_close_manually')
    report['outputs'] = [{k: o.get(k) for k in ('name', 'make', 'model', 'active')}
                         for o in sway('get_outputs')]
    old = None
    for iteration in range(1, 4):
        p = subprocess.Popen(['/usr/bin/gnome-calculator', '--mode=basic'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pidfd = os.pidfd_open(p.pid)
        ref = None
        try:
            identity = process_identity(p.pid)
            if identity[3] != '/usr/bin/gnome-calculator':
                raise Rejected('unexpected_executable')
            window, app, frame = wait_for(lambda: discover(p, desktop))
            path, node = wait_for(lambda: button(frame))
            ref = Reference(identity, window, app, frame, node, path, time.monotonic()+20)
            before = texts(frame)
            if not before or any(v not in ('', '0') for v in before.values()):
                raise Rejected('fixture_not_clean')
            stale = None
            if old:
                try:
                    old.dispatch(lambda _: (_ for _ in ()).throw(AssertionError('stale check reached adapter')))
                    raise Rejected('stale_reference_accepted')
                except Rejected as error:
                    if str(error) != 'expired_reference':
                        raise
                    stale = str(error)
                if texts(frame) != before:
                    raise Rejected('replacement_changed')
            names = ref.dispatch(lambda r: validate(r, p, pidfd, desktop))
            def confirmed():
                _, _, fresh_frame = discover(p, desktop)
                after = texts(fresh_frame)
                changed = [k for k, value in after.items()
                           if value == '7' and before.get(k) in ('', '0')]
                if set(after) != set(before) or len(changed) != 1:
                    raise Rejected('result_not_confirmed')
                return after, changed[0]
            after, display_path = wait_for(confirmed, timeout=5)
            report['runs'].append(dict(iteration=iteration, timestamp=datetime.now(timezone.utc).isoformat(),
                process=dict(pid=p.pid, start_ticks=identity[1], executable=identity[3]),
                window=window, atspi_pid=app.get_process_id(), frame_count=1,
                button=dict(name='7', role=node.getRoleName(), path=path, actions=names),
                before=before, after=after, display_path=display_path,
                observation='query_after_action', stale_rejection=stale))
        finally:
            if ref:
                ref.invalidate()  # BEFORE termination, retained for replacement check.
                old = ref
            if p.poll() is None:
                p.terminate()  # Only our supervised child; no killall or PID guessing.
            p.wait(timeout=5)
            os.close(pidfd)
        wait_for(lambda: absent(p.pid, desktop))
    report['result'] = 'GO'


def absent(pid, desktop):
    if any(w['pid'] == pid for w in windows(sway('get_tree'))) or any(
            a.get_process_id() == pid for a in desktop()):
        raise Rejected('old_sources_present')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    # Exclusive creation prevents overwriting an earlier evidence record.
    with args.evidence.open('x') as output:
        report = dict(result='PARTIAL', runs=[], started=datetime.now(timezone.utc).isoformat())
        try:
            run(report)
        except Exception as error:
            report['failure'] = type(error).__name__ + ':' + (str(error) if isinstance(error, Rejected) else 'adapter_or_runtime_error')
        json.dump(report, output, indent=2)
        output.write('\n')
    print(report['result'])
    return 0 if report['result'] == 'GO' else 1


if __name__ == '__main__':
    raise SystemExit(main())
