# SPDX-License-Identifier: Apache-2.0
"""Paired presentation benchmark with a disposable desktop and a separate GTK process."""
import argparse
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import replace
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

from loopbridge.identity import Identities
from loopbridge.presentation_client import LiveConnection
from loopbridge.private_session import Instance, terminate
from loopbridge.process_boundary import protect_process
from loopshell.bridge import SessionSelection
from loopshell.commands import Action
from loopshell.compositor import load_layer_shell
from loopshell.layout import Layout, save_layout
from tools.loopbridge_desktop_demo import SESSION, element, grant, writable
from tools.loopbridge_presentation_demo import media_children, parent_pid, process_counters
from tools.loopbridge_private_demo import connect_rpc, descendants, namespaced_process
from tools.loopshell_combined_lab import nodes, sway
from tools.presentation_pipeline import PipelineProbe, clock_pair

MODES = ('standalone', 'visual', 'combined', 'dual')
DIRECT = 'combined-direct'


def send(row):
    print(json.dumps(row, separators=(',', ':')), flush=True)


def worker():
    protect_process()
    config = json.load(sys.stdin)
    credentials = config.pop('credentials')
    mode, endpoint = config['mode'], config['endpoint']
    layer = load_layer_shell() if mode != 'standalone' else None
    from gi.repository import GLib
    from loopbridge.visual_view import Watch
    from tools import loopbridge_live_view

    class Measurement:
        def __init__(self):
            self.windows = []
            self.start = None
            self.ready_deadline = time.monotonic() + 14

        def add(self, window):
            video = window.video
            probe = PipelineProbe()
            video.args = replace(video.args, measure_motion=config['motion'])
            video.probe = video.connection.packet_probe = probe
            self.windows.append(window)

        def ready(self):
            expected = 2 if mode == 'dual' else 1
            if len(self.windows) == expected and all(self.view_ready(w) for w in self.windows):
                send({'phase': 'ready'})
                return GLib.SOURCE_REMOVE
            if time.monotonic() < self.ready_deadline:
                return GLib.SOURCE_CONTINUE
            send(dict(phase='not_ready', views=[
                dict(received=w.video.received, unique=w.video.unique, painted=w.video.painted,
                     decoded=w.video.fixture_received, markers_painted=w.video.fixture_frames,
                     failure=w.video.failure) for w in self.windows]))
            return GLib.SOURCE_REMOVE

        def view_ready(self, window):
            video = window.video
            events_ready = not hasattr(window, 'activity') or window.activity.client.cursor is not None
            return (not video.failure and events_ready and video.painted
                    and (not config['motion'] or video.fixture_frames >= 10))

        def counts(self):
            return [w.activity.client._sequence if hasattr(w, 'activity') else 0 for w in self.windows]

        def arm(self):
            self.initial = self.counts()
            self.before = clock_pair()
            self.start = time.monotonic_ns()
            send({'phase': 'start'})
            return GLib.SOURCE_REMOVE

        def finish(self):
            end = time.monotonic_ns()
            clocks = self.before, clock_pair()
            counts = self.counts()

            def report():
                rows = []
                for i, window in enumerate(self.windows):
                    video = window.video
                    row = video.probe.report(self.start, end, clocks)
                    row['video_region'] = [video.picture.get_width(), video.picture.get_height()]
                    row['renderer'] = type(window.get_renderer()).__name__
                    row['activity_queries'] = counts[i] - self.initial[i]
                    row['failure'] = video.failure
                    rows.append(row)
                send({'phase': 'result', 'views': rows})
                app = self.windows[0].get_application()
                for window in self.windows:
                    window.close()
                app.quit()
                return GLib.SOURCE_REMOVE

            # Collect feedback already in flight across the sample boundary.
            GLib.timeout_add(350, report)
            return GLib.SOURCE_REMOVE

    measurement = Measurement()
    GLib.timeout_add(100, measurement.ready)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, measurement.arm)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, measurement.finish)
    pin = config['pin']
    if mode == 'standalone':
        class MeasuredWatch(Watch):
            def __init__(self, *args):
                super().__init__(*args)
                measurement.add(self)

        conn = LiveConnection(endpoint, credentials.pop('observer'), pin['session'], pin['privateId'],
                              pin['epoch'], expected_peer_uid=os.getuid(), expected_principal='observer')
        options = SimpleNamespace(session=pin['session'], private_id=pin['privateId'],
                                  measure_motion=config['motion'], metrics_file=None)
        loopbridge_live_view.Watch = MeasuredWatch
        return loopbridge_live_view.Viewer(options, conn).run([])

    if layer is None:
        raise RuntimeError('gtk4-layer-shell unavailable')
    from loopshell import ui

    class MeasuredWatch(ui.Watch):
        def __init__(self, *args):
            super().__init__(*args)
            measurement.add(self)

    class MeasuredCombined(ui.CombinedWindow):
        def __init__(self, *args):
            super().__init__(*args)
            if mode == DIRECT:
                viewport = self.get_child().get_child()
                content = viewport.get_child()
                viewport.set_child(None)
                self.set_child(content)
            measurement.add(self)

    class BenchShell(ui.Shell):
        def __init__(self, *args):
            super().__init__(*args)
            GLib.idle_add(self.open_trial)

        def open_trial(self):
            if self.anchored_monitor is None:
                raise RuntimeError('anchored layout unavailable')
            action = Action.OBSERVE if mode == 'visual' else Action.COMBINED
            principals = ('observer', 'delegate') if mode == 'dual' else ('observer',)
            for principal in principals:
                selection = SessionSelection(pin['session'], pin['epoch'], principal)
                self.open_view(selection, credentials.pop(principal), action)
            return GLib.SOURCE_REMOVE

    ui.Watch, ui.CombinedWindow, ui.Shell = MeasuredWatch, MeasuredCombined, BenchShell
    return ui.run(Path(config['layout']), layer, endpoint)


def receive(process, expected, timeout=18):
    if not select.select([process.stdout], [], [], timeout)[0]:
        raise RuntimeError(f'GTK worker timeout waiting for {expected}')
    line = process.stdout.readline()
    if not line:
        raise RuntimeError(f'GTK worker exited waiting for {expected}')
    message = json.loads(line)
    if message.get('phase') == 'not_ready':
        raise RuntimeError(f"GTK worker did not verify the scene: {message['views']}")
    if message.get('phase') != expected:
        raise RuntimeError(f'GTK worker wrong phase, expected {expected}')
    return message


@contextmanager
def viewer(config):
    command = [sys.executable, '-B', '-m', 'tools.loopshell_performance_lab', '--worker']
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as process:
        try:
            with process.stdin:
                json.dump(config, process.stdin)
            receive(process, 'ready')
            yield process
        finally:
            if process.poll() is None:
                terminate(process)


def host_counters():
    return [int(value) for value in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]


def host_load(before, after):
    ticks = [b - a for a, b in zip(before, after)]
    total = sum(ticks)
    return dict(busy_pct=round(100 * (total - ticks[3] - ticks[4]) / total, 2),
                steal_pct=round(100 * ticks[7] / total, 2))


def process_measurements(pids, duration, before, after):
    rows = {}
    for key, members in pids.items():
        stable = [pid for pid in members if pid in before and pid in after]
        rows[key] = dict(processes=len(stable), expected=len(members),
                         cpu_pct_one_cpu=round(100 * sum(after[pid][0] - before[pid][0] for pid in stable)
                                               / duration, 2),
                         rss_start_mib=round(sum(before[pid][1] for pid in stable), 2),
                         rss_end_mib=round(sum(after[pid][1] for pid in stable), 2))
    return rows


def counters(pids):
    result = {}
    for pid in {pid for group in pids.values() for pid in group}:
        with suppress(FileNotFoundError, ProcessLookupError, StopIteration):
            result[pid] = process_counters(pid)
    return result


def wait_for(predicate, description, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := predicate():
            return result
        time.sleep(.05)
    raise RuntimeError(description)


class Experiment:
    def __init__(self, instance, owner, credentials, layout, display_pid):
        self.instance, self.owner, self.credentials = instance, owner, credentials
        self.layout, self.display_pid = layout, display_pid
        self.private_pid = instance.process.pid
        self.private_sway = namespaced_process(self.private_pid, instance.root, 'sway')
        self.broker = None

    def capturers(self):
        return media_children(self.private_pid, self.instance.root)

    def authorize(self, mode):
        for principal in ('observer', 'delegate') if mode == 'dual' else ('observer',):
            grant(self.owner, principal, 'desktop.stream')
            grant(self.owner, principal, 'session.discover')

    def open(self, mode, motion=True):
        self.authorize(mode)
        selected = ('observer', 'delegate') if mode == 'dual' else ('observer',)
        pin = self.owner.call('presentation.describe', **SESSION)
        return viewer(dict(mode=mode, endpoint=str(self.instance.endpoint),
                           layout=str(self.layout), pin={k: pin[k] for k in ('session', 'privateId', 'epoch')},
                           motion=motion, credentials={k: self.credentials[k] for k in selected}))

    def calculator(self):
        lease = writable(self.owner)
        try:
            launched = self.owner.call('app.launch', **lease, app='calculator')
            if launched['status'] != 'confirmed':
                raise RuntimeError('Calculator startup was not confirmed')
        finally:
            self.owner.call('release', **lease)

        with self.open('standalone', motion=False) as process:
            process.send_signal(signal.SIGUSR1)
            receive(process, 'start')
            lease = writable(self.owner)
            digit = element(self.owner, 'calculator', lambda row: row['name'] == '7' and 'click' in row['actions'])
            changed = self.owner.call('element.invoke', **lease, ref=digit['ref'], action='click')
            self.owner.call('release', **lease)
            if changed.get('evidence', {}).get('state', {}).get('display') != '7':
                raise RuntimeError('Calculator source value did not change')
            time.sleep(1)
            process.send_signal(signal.SIGUSR2)
            row, = receive(process, 'result')['views']
            process.wait(5)
        if not row['frames']['unique'] or not row['frames']['painted']:
            raise RuntimeError('confirmed Calculator change missing at receiver or paint')
        wait_for(lambda: not self.capturers(), 'pilot capturers still active')
        return {'source_display_verified': True, 'received': row['frames']['received'],
                'unique': row['frames']['unique'], 'painted': row['frames']['painted']}

    def motion(self):
        lease = writable(self.owner)
        assert self.owner.call('app.close', **lease, app='calculator')['status'] == 'confirmed'
        opened = self.owner.call('web.open', **lease, app='browser')
        if opened['status'] != 'confirmed':
            raise RuntimeError(f"offline Firefox startup: {opened['status']} / {opened.get('reason')}")
        ref = self.owner.call('window.list', **SESSION, app='browser')['windows'][0]['ref']
        moved = self.owner.call('web.navigate', **lease, ref=ref, page='motion')
        assert moved['status'] == 'confirmed' and moved['evidence']['state']['page'] == 'motion'
        self.owner.call('release', **lease)

    def groups(self):
        browser = [int(entry.name) for entry in descendants(self.private_pid)
                   if (comm(entry) in ('firefox-esr', 'firefox'))]
        family = set(browser)
        for pid in browser:
            family.update(int(entry.name) for entry in descendants(pid))
        return {'driver': [os.getpid()], 'display_sway': [self.display_pid],
                'private_sway': [self.private_sway], 'broker': [self.broker], 'firefox_tree': sorted(family)}

    def trial(self, mode, seconds):
        with self.open(mode) as process:
            count = 2 if mode == 'dual' else 1
            capturers = wait_for(lambda: (pids if len(pids := self.capturers()) == count else None),
                                 'capture processes')
            self.broker = parent_pid(capturers[0])
            pids = self.groups() | {'gtk': [process.pid]}
            pids.update({f'capture_{i}': [pid] for i, pid in enumerate(sorted(capturers), 1)})
            rectangles = [node['rect'] for node in nodes(sway('-t', 'get_tree')) if node.get('app_id')]
            before, host_before = counters(pids), host_counters()
            start = time.monotonic()
            process.send_signal(signal.SIGUSR1)
            receive(process, 'start')
            end = time.monotonic() + seconds
            # Identical authorized activity in all modes, generated off the GTK process.
            while (remaining := end - time.monotonic()) > 0:
                time.sleep(min(4, remaining))
                if time.monotonic() < end:
                    self.owner.call('release', **writable(self.owner))
            process.send_signal(signal.SIGUSR2)
            after, host_after = counters(pids), host_counters()
            duration = time.monotonic() - start
            result = receive(process, 'result')
            process.wait(5)
        for row in result['views']:
            if row['failure'] or row['frames']['markers_painted'] < 10 or not row['source']:
                raise RuntimeError('cannot qualify a trial without advancing, observed source markers')
            if mode in ('combined', 'dual', DIRECT) and row['activity_queries'] < 2:
                raise RuntimeError('cannot qualify Combined without its activity polling')
        stopped = time.monotonic()
        wait_for(lambda: not self.capturers(), 'capturer survived close')
        assert self.instance.status()['phase'] == 'ready'
        return dict(mode=mode, windows=rectangles, views=result['views'], host=host_load(host_before, host_after),
                    resources=process_measurements(pids, duration, before, after),
                    idle_after_viewer_exit_ms=round((time.monotonic() - stopped) * 1000, 2))

    def residual(self):
        assert not self.capturers()
        pids = self.groups()
        before, host_before = counters(pids), host_counters()
        start = time.monotonic()
        time.sleep(5)
        return dict(seconds=round(time.monotonic() - start, 3), no_capturers=not self.capturers(),
                    private_ready=self.instance.status()['phase'] == 'ready',
                    host=host_load(host_before, host_counters()),
                    resources=process_measurements(pids, time.monotonic() - start, before, counters(pids)))


def comm(entry):
    with suppress(FileNotFoundError, ProcessLookupError):
        return (entry / 'comm').read_text().strip()
    return ''


def main(args):
    root = args.root.resolve(strict=True)
    runtime = Path(os.environ['XDG_RUNTIME_DIR']).resolve(strict=True)
    ipc = Path(os.environ['SWAYSOCK']).resolve(strict=True)
    if runtime.parent != root or ipc.parent != runtime:
        raise ValueError('use a dedicated compositor runtime inside the laboratory root')
    outputs = sway('-t', 'get_outputs')
    if len(outputs) != 1 or outputs[0]['name'] != 'HEADLESS-1' or outputs[0]['scale'] != 1:
        raise ValueError('use one disposable headless output at scale 1')
    protect_process()
    identities = Identities()
    credentials = identities.provision()
    private = Path(tempfile.mkdtemp(prefix='p', dir=root))
    layout = private / 'layout.json'
    save_layout(layout, Layout('left', 'bottom', 260, 180))
    evidence = dict(complete=False, renderer=os.environ.get('GSK_RENDERER'),
                    logical_cpus=len(os.sched_getaffinity(0)), output=outputs[0]['rect'], rounds=[])

    def save():
        args.evidence.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')

    with ExitStack() as stack:
        instance = Instance(private, identities.manifest())
        stack.callback(instance.stop)
        owner = connect_rpc(stack, instance.endpoint, credentials['owner'])
        experiment = Experiment(instance, owner, credentials, layout, int(ipc.name.split('.')[-2]))
        print('Calculator source and standalone paint', flush=True)
        evidence['calculator'] = experiment.calculator()
        save()
        print('Warm offline Firefox source', flush=True)
        experiment.motion()
        for repeat in range(args.repetitions):
            modes = args.modes if repeat % 2 == 0 else reversed(args.modes)
            for mode in modes:
                print(f'round {repeat + 1} {mode}', flush=True)
                evidence['rounds'].append(dict(round=repeat + 1, **experiment.trial(mode, args.seconds)))
                save()
        evidence['without_observers'] = experiment.residual()
        evidence['complete'] = True
        save()


if __name__ == '__main__':
    if sys.argv[1:] == ['--worker']:
        raise SystemExit(worker())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--seconds', type=int, choices=range(8, 31), default=15, metavar='8–30')
    parser.add_argument('--repetitions', type=int, choices=(1, 2), default=2)
    parser.add_argument('--modes', nargs='+', choices=(*MODES, DIRECT), default=MODES,
                        help='combined-direct is a lab-only control without the outer scrolling viewport')
    main(parser.parse_args())
