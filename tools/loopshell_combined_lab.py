# SPDX-License-Identifier: Apache-2.0
"""Qualify Combined on a disposable headless Sway and a real private desktop."""
import argparse
from contextlib import ExitStack, suppress
from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from loopbridge.identity import Identities
from loopbridge.presentation_client import LiveConnection
from loopbridge.private_session import Instance, terminate
from loopbridge.process_boundary import protect_process
from loopbridge.view_status import ViewerState
from loopshell.bridge import SessionSelection
from loopshell.commands import Action
from loopshell.compositor import load_layer_shell
from loopshell.layout import Layout, save_layout
from tools.loopbridge_desktop_demo import SESSION, element, grant, writable
from tools.loopbridge_presentation_demo import media_children, parent_pid, process_counters
from tools.loopbridge_private_demo import connect_rpc, denied, namespaced_process


def sway(*arguments):
    return json.loads(subprocess.check_output(
        ['/usr/bin/swaymsg', '-s', os.environ['SWAYSOCK'], '-r', *arguments], text=True))


def nodes(node):
    yield node
    for child in node['nodes'] + node['floating_nodes']:
        yield from nodes(child)


def text(widget):
    buffer = widget.get_buffer()
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)


class Lab:
    def __init__(self, ui, layer, instance, owner, credentials, evidence):
        self.ui, self.layer, self.instance, self.owner = ui, layer, instance, owner
        self.credentials = credentials
        self.context = ui.GLib.MainContext.default()
        self.shell = None
        self.final_views = []
        self.result = {'complete': False}
        self.evidence = evidence
        self.pid = instance.process.pid
        self.compositor = namespaced_process(self.pid, instance.root, 'sway')
        self.bridge = None

    def save_evidence(self):
        self.evidence.write_text(json.dumps(self.result, ensure_ascii=False, indent=2) + '\n')

    def wait(self, predicate, description, seconds=8):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            while self.context.pending():
                self.context.iteration(False)
            if result := predicate():
                return result
            time.sleep(.02)
        raise AssertionError(description)

    def submit(self, widget, value):
        widget.set_text(value)
        widget.emit('activate')

    def authenticate(self, principal='observer'):
        console = self.shell.console
        if console.client.principal:
            console.connection_button.emit('clicked')
        console.connection_button.emit('clicked')
        self.submit(console.password, self.credentials[principal])
        self.wait(lambda: console.client.principal == principal and not console.busy, 'console auth')

    def open(self, action=Action.COMBINED):
        console = self.shell.console
        before = set(self.shell.app.get_windows())
        self.submit(console.entry, action.value + ' desktop')
        self.wait(lambda: console.view_request, action.value + ' selection')
        self.submit(console.password, self.credentials[console.client.principal])
        assert console.password.get_text() == ''
        return self.wait(lambda: next((view for view in self.shell.app.get_windows()
                                      if view not in before and view.get_mapped()), None),
                         action.value + ' map')

    def media(self, view):
        return view.video.picture.get_paintable() is not None

    def events(self, view):
        return view.activity.status.get_text().startswith('Autorizado')

    def ready(self, view):
        self.wait(lambda: self.media(view) and (not hasattr(view, 'activity') or self.events(view)),
                  'authorized video or activity missing')
        return view

    def fault(self, view, video=None, activity=None):
        if video:
            self.wait(lambda: view.video.failure == video and not self.media(view), 'video ' + video)
        if activity:
            self.wait(lambda: view.activity.status.get_text().startswith(activity)
                      and not view.activity.displayed_rows, 'activity ' + activity)

    def closed(self, view):
        panes = (view.video, view.activity) if hasattr(view, 'activity') else (view.video,)
        for pane in panes:
            worker = getattr(pane, 'worker', None)
            if worker:
                self.wait(lambda: not worker.is_alive(), 'worker survived close')
        video = view.video
        assert not any((video.status_source, video.draw_source, video.draw_tick, video.frame_handler))
        assert video.connection.peer.fileno() == -1 and video.connection.token is None
        assert video.connection.channel is None and not self.media(view)
        assert video.latest is None and video.pending_paint is None
        if hasattr(view, 'activity'):
            activity = view.activity
            assert not any((activity.render_source, activity.adjustment_handler, activity.rows, activity.displayed_rows))
            assert activity.credential is None and activity.client.principal is None
            assert not text(activity.event_view)

    def close(self, view):
        view.close()
        self.closed(view)

    def grant(self, capability, principal='observer'):
        return grant(self.owner, principal, capability)

    def revoke(self, key):
        self.owner.call('revoke', **SESSION, grant=key)

    def cycle(self):
        self.owner.call('release', **writable(self.owner))

    def capturers(self):
        return media_children(self.pid, self.instance.root)

    def private_ready(self):
        assert self.instance.status()['phase'] == 'ready' and self.instance.process.pid == self.pid

    def geometry(self, combined, width, height):
        usable = dict(x=260, y=0, width=width - 260, height=height - 180)
        self.wait(lambda: any(row['rect'] == usable for row in sway('-t', 'get_workspaces')),
                  'exclusive zones')
        windows = {row['name']: row['rect'] for row in nodes(sway('-t', 'get_tree'))
                   if row.get('app_id') == 'loopshell-c3-foot'
                   or row.get('name') in ('LoopShell · Combined · desktop', 'LoopBridge · sessão privada ao vivo')}
        assert len(windows) == 3
        x = 260
        for rect in sorted(windows.values(), key=lambda row: row['x']):
            assert rect['height'] == usable['height'] and rect['y'] == 0 and rect['x'] == x
            x += rect['width']
        assert x == width
        zones = [self.layer.get_exclusive_zone(window) for window in self.shell.windows]
        assert zones == [260, 180]
        rect = windows['LoopShell · Combined · desktop']
        self.wait(lambda: (combined.get_width(), combined.get_height()) == (rect['width'], rect['height']),
                  'GTK geometry')
        picture, feed = combined.video.picture, combined.activity.scroll
        assert picture.get_content_fit() == self.ui.Gtk.ContentFit.CONTAIN
        assert picture.get_height() > feed.get_height() > 0
        return dict(output=[width, height], usable=usable, zones=zones, windows=windows,
                    picture=[picture.get_width(), picture.get_height()],
                    feed=[feed.get_width(), feed.get_height()])

    def integration(self):
        print('independent grants and genuine activity', flush=True)
        self.authenticate()
        media = self.grant('desktop.stream')
        view = self.open()
        self.wait(lambda: self.media(view), 'stream-only image')
        self.fault(view, activity='Permissão insuficiente')
        self.close(view)
        self.revoke(media)
        activity = self.grant('session.discover')
        view = self.open()
        self.wait(lambda: self.events(view), 'activity-only authorization')
        self.fault(view, video='grant_denied')
        self.close(view)
        media = self.grant('desktop.stream')

        view = self.ready(self.open())
        painted = view.video.painted
        lease = writable(self.owner)
        assert self.owner.call('app.launch', **lease, app='calculator')['status'] == 'confirmed'
        self.owner.call('release', **lease)
        self.wait(lambda: view.video.painted > painted, 'calculator did not change private image')
        self.wait(lambda: 'control.released' in text(view.activity.event_view), 'real event missing')
        rows = view.activity.displayed_rows
        assert all(b.sequence == a.sequence + 1 for a, b in zip(rows, rows[1:]))
        with ExitStack() as peers:
            observer = connect_rpc(peers, self.instance.endpoint, self.credentials['observer'])
            denied('grant_denied', observer.call, 'acquire', **SESSION, ttl=8)
            denied('grant_denied', observer.call, 'workspace.read', **SESSION, path='example')

        print('concurrency, geometry and console disconnect', flush=True)
        self.grant('desktop.stream', 'delegate')
        self.grant('session.discover', 'delegate')
        self.authenticate('delegate')
        second = self.ready(self.open())
        assert second.selection.principal == 'delegate'
        self.close(second)
        assert self.media(view)
        self.authenticate()
        visual = self.ready(self.open(Action.OBSERVE))
        before_paint = view.video.painted, visual.video.painted
        lease = writable(self.owner)
        digit = element(self.owner, 'calculator', lambda row: row['name'] == '7' and 'click' in row['actions'])
        answer = self.owner.call('element.invoke', **lease, ref=digit['ref'], action='click')
        assert answer['status'] == 'confirmed' and answer['evidence']['state']['display'] == '7'
        self.owner.call('release', **lease)
        self.wait(lambda: (view.video.painted > before_paint[0] and visual.video.painted > before_paint[1]),
                  'new Calculator frame missing in Combined or Visual')
        third = self.open()
        self.fault(third, video='presentation_limit')
        self.wait(lambda: self.events(third), 'third view activity')
        self.close(third)
        self.result['geometry'] = [self.geometry(view, 1280, 800)]
        assert sway('output', 'HEADLESS-1', 'mode', '1024x768')[0]['success']
        self.result['geometry'].append(self.geometry(view, 1024, 768))
        console = self.shell.console
        console.connection_button.emit('clicked')
        polls = view.activity.client._sequence
        self.wait(lambda: view.activity.client._sequence > polls, 'console disconnect stopped activity')
        assert console.client.principal is None and self.media(view)
        self.authenticate()

        print('revocations and isolated transport failures', flush=True)
        self.revoke(media)
        self.fault(view, video='revoked')
        self.fault(visual, video='revoked')
        self.wait(lambda: 'grant.revoked' in text(view.activity.event_view), 'events stopped with media revoke')
        self.close(view)
        self.close(visual)
        media = self.grant('desktop.stream')
        view = self.ready(self.open())
        self.revoke(activity)
        self.fault(view, activity='Acesso perdido')
        assert self.media(view)
        self.close(view)
        activity = self.grant('session.discover')
        view = self.ready(self.open())
        self.revoke(media)
        self.revoke(activity)
        self.fault(view, video='revoked', activity='Acesso perdido')
        self.close(view)
        self.grant('desktop.stream')
        self.grant('session.discover')

        view = self.ready(self.open())
        view.video.connection.interrupt()
        self.wait(lambda: 'encerramento da sessão não confirmado' in view.video.label.get_text()
                  and not self.media(view), 'unconfirmed media EOF')
        assert view.invalidated is None and self.events(view)
        self.close(view)
        view = self.ready(self.open())
        view.activity.client.interrupt()
        self.fault(view, activity='Conexão interrompida')
        assert view.invalidated is None and self.media(view)
        self.close(view)

        print('freeze, retention gap, stale selection and reopen', flush=True)
        view = self.ready(self.open())
        helper, = self.wait(lambda: self.capturers(), 'capture helper')
        os.kill(helper, signal.SIGSTOP)
        try:
            self.fault(view, video='heartbeat_timeout')
        finally:
            with suppress(ProcessLookupError):
                os.kill(helper, signal.SIGCONT)
        assert self.events(view)
        self.close(view)
        view = self.ready(self.open())
        self.cycle()
        self.wait(lambda: 'control.released' in text(view.activity.event_view), 'pre-gap event')
        for _ in range(5):
            self.cycle()
        self.fault(view, activity='Lacuna no histórico')
        assert self.media(view)
        self.close(view)

        before = set(self.shell.app.get_windows())
        self.shell.open_view(SessionSelection('desktop', '0' * 32, 'observer'),
                             self.credentials['observer'], Action.COMBINED)
        stale, = set(self.shell.app.get_windows()) - before
        self.wait(lambda: stale.invalidated is ViewerState.REPLACED, 'stale epoch accepted')
        self.closed(stale)
        self.close(stale)
        view = self.ready(self.open())
        assert 'sem novos eventos' in view.activity.status.get_text()
        self.cycle()
        self.wait(lambda: 'control.released' in text(view.activity.event_view), 'post-resync real event')
        visual = self.ready(self.open(Action.OBSERVE))
        shown = (text(console.view), text(view.activity.event_view), view.video.label.get_text(),
                 view.activity.status.get_text())
        assert all(token not in field for token in self.credentials.values() for field in shown)
        self.final_views.extend((view, visual))
        self.private_ready()
        self.result['integration'] = dict(
            passed=['video_only', 'activity_only', 'both_authorized', 'media_revoke', 'activity_revoke',
                    'both_revoked', 'media_disconnect_unconfirmed', 'activity_disconnect', 'no_heartbeat',
                    'retention_gap', 'stale_epoch', 'explicit_resync', 'two_distinct_combined', 'combined_and_visual',
                    'third_media_denied', 'console_disconnect', 'observer_control_and_workspace_denied',
                    'credentials_absent_from_ui', 'authentic_calculator_change', 'dual_visual_update'],
            consecutive_events=[vars(row) for row in rows],
        )

    def sample(self, name, seconds, views=(), *, generate_events=False):
        from loopbridge.visual_view import percentiles

        probes = ('received', 'unique', 'overwritten', 'painted', 'presented')
        latency = ('capture_to_receive', 'paint_latencies', 'latencies')
        stream_pids = self.wait(lambda: (pids if len(pids := self.capturers()) == len(views) else None),
                                'capture processes') if views else []
        if stream_pids:
            self.bridge = parent_pid(stream_pids[0])
        pids = dict(shell_and_driver=os.getpid(), private_sway=self.compositor, bridge=self.bridge)
        pids.update({f'capture_{index}': pid for index, pid in enumerate(stream_pids, 1)})
        resources_before = {role: process_counters(pid) for role, pid in pids.items()}
        initial = [{field: getattr(view.video, field) for field in probes} for view in views]
        latency_offset = [{field: len(getattr(view.video, field)) for field in latency} for view in views]
        initial_events = [(view.activity.client._sequence, view.activity.client.cursor) for view in views]
        started = time.monotonic()
        keepalive, generate = started + 10, started + 4

        def sample_done():
            nonlocal keepalive, generate
            now = time.monotonic()
            if now >= keepalive:
                self.owner.call('snapshot', **SESSION)
                keepalive = now + 10
            if generate_events and now >= generate:
                self.cycle()
                generate = now + 4
            return now - started >= seconds

        self.wait(sample_done, 'measurement timeout', seconds + 5)
        elapsed = time.monotonic() - started
        resources = {}
        for role, pid in pids.items():
            cpu_before, rss_before = resources_before[role]
            cpu_after, rss_after = process_counters(pid)
            resources[role] = dict(cpu_percent_one_logical_cpu=round((cpu_after - cpu_before) / elapsed * 100, 2),
                                   rss_start_mib=round(rss_before, 2), rss_end_mib=round(rss_after, 2),
                                   rss_growth_mib=round(rss_after - rss_before, 2))
        panes = []
        for index, view in enumerate(views):
            assert self.media(view) and self.events(view)
            frames = {field: getattr(view.video, field) - initial[index][field] for field in probes}
            delays = {field: percentiles(list(getattr(view.video, field))[latency_offset[index][field]:])
                      for field in latency}
            request, cursor = initial_events[index]
            polls, events = view.activity.client._sequence - request, view.activity.client.cursor - cursor
            assert .42 <= polls / elapsed <= .55
            assert (events > 0) == generate_events
            panes.append(dict(frames=frames, duplicates=frames['received'] - frames['unique'],
                              painted_fps=round(frames['painted'] / elapsed, 2),
                              event_queries=polls, event_queries_per_second=round(polls / elapsed, 3),
                              events=events, latency_ms=delays))
        self.private_ready()
        self.result.setdefault('performance', {})[name] = dict(seconds=round(elapsed, 2),
                                                               resources=resources, panes=panes)
        self.save_evidence()

    def performance(self):
        print('static Combined, 60 seconds', flush=True)
        self.authenticate()
        lease = writable(self.owner)
        assert self.owner.call('app.launch', **lease, app='calculator')['status'] == 'confirmed'
        self.owner.call('release', **lease)
        self.grant('desktop.stream')
        self.grant('session.discover')
        view = self.ready(self.open())
        self.wait(lambda: 'IMAGEM ESTÁTICA' in view.video.label.get_text(), 'static heartbeat')
        self.sample('static_one', 60, (view,))
        assert 'IMAGEM ESTÁTICA' in view.video.label.get_text()
        self.close(view)

        print('offline Firefox motion, one Combined, 30 seconds', flush=True)
        self.authenticate()
        lease = writable(self.owner)
        assert self.owner.call('app.close', **lease, app='calculator')['status'] == 'confirmed'
        opening = self.owner.call('web.open', **lease, app='browser')
        if opening['status'] != 'confirmed':
            raise RuntimeError('private Firefox was not confirmed: '
                               f"{opening['status']} / {opening.get('reason')}")
        ref = self.owner.call('window.list', **SESSION, app='browser')['windows'][0]['ref']
        response = self.owner.call('web.navigate', **lease, ref=ref, page='motion')
        assert response['status'] == 'confirmed' and response['evidence']['state']['page'] == 'motion'
        self.owner.call('release', **lease)
        self.grant('desktop.stream')
        self.grant('session.discover')
        view = self.ready(self.open())
        self.wait(lambda: view.video.fixture_frames >= 10, 'motion marker')
        self.sample('motion_one', 30, (view,), generate_events=True)
        self.close(view)

        print('offline Firefox motion, two Combined, 30 seconds', flush=True)
        self.grant('desktop.stream')
        self.grant('session.discover')
        self.grant('desktop.stream', 'delegate')
        self.grant('session.discover', 'delegate')
        first = self.ready(self.open())
        self.authenticate('delegate')
        second = self.ready(self.open())
        self.wait(lambda: min(first.video.fixture_frames, second.video.fixture_frames) >= 10,
                  'motion markers in both streams')
        self.sample('motion_two', 30, (first, second), generate_events=True)
        closing = time.monotonic()
        self.close(first)
        self.close(second)
        self.wait(lambda: not self.capturers(), 'capture process remained active')
        self.result['capture_idle_ms'] = round((time.monotonic() - closing) * 1000, 2)
        self.sample('motion_unobserved', 8)

        print('slow viewer and backpressure', flush=True)
        self.grant('desktop.stream')
        pin = self.owner.call('presentation.describe', **SESSION)
        slow = LiveConnection(self.instance.endpoint, self.credentials['observer'], pin['session'],
                              pin['privateId'], pin['epoch'], expected_peer_uid=os.getuid(),
                              expected_principal='observer')
        try:
            slow.connect()
            self.wait(lambda: self.capturers(), 'slow viewer helper')
            self.wait(lambda: not self.capturers(), 'slow helper did not stop', 12)
            assert slow.reason() == 'slow_viewer'
            self.result['slow_viewer_retired'] = True
        finally:
            slow.release()


def run(args):
    root = args.root.resolve(strict=True)
    runtime = Path(os.environ['XDG_RUNTIME_DIR']).resolve(strict=True)
    ipc = Path(os.environ['SWAYSOCK']).resolve(strict=True)
    if runtime.parent != root or ipc.parent != runtime:
        raise ValueError('run a dedicated compositor under the laboratory root')
    if [output['name'] for output in sway('-t', 'get_outputs')] != ['HEADLESS-1']:
        raise ValueError('use a dedicated headless Sway output')
    layer = load_layer_shell()
    if layer is None:
        raise RuntimeError('gtk4-layer-shell unavailable')
    from loopshell import ui

    protect_process()
    identities = Identities()
    credentials = identities.provision()
    private = Path(tempfile.mkdtemp(prefix='p', dir=root))
    layout = private / 'layout.json'
    save_layout(layout, Layout('left', 'bottom', 260, 180))
    with ExitStack() as stack:
        instance = Instance(private, identities.manifest())
        stack.callback(instance.stop)
        owner = connect_rpc(stack, instance.endpoint, credentials['owner'])
        foot = subprocess.Popen(['/usr/bin/foot', '--app-id=loopshell-c3-foot', '/usr/bin/sleep', '180'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        stack.callback(terminate, foot)
        lab = Lab(ui, layer, instance, owner, credentials, args.evidence)
        failures = []

        class DrivenShell(ui.Shell):
            def __init__(self, *values):
                super().__init__(*values)
                lab.shell = self
                ui.GLib.idle_add(self.drive)

            def drive(self):
                try:
                    lab.wait(lambda: len(self.windows) == 2 and all(window.get_mapped() for window in self.windows),
                             'anchored surfaces')
                    if args.performance:
                        lab.performance()
                    else:
                        lab.integration()
                except Exception as error:
                    failures.append(error)
                finally:
                    self.app.quit()
                return ui.GLib.SOURCE_REMOVE

        ui.Shell = DrivenShell
        if args.performance:
            class MeasuredCombined(ui.CombinedWindow):
                def __init__(self, *values):
                    super().__init__(*values)
                    self.video.args = replace(self.video.args, measure_motion=True)

            ui.CombinedWindow = MeasuredCombined
        assert ui.run(layout, layer, instance.endpoint) == 0
        if failures:
            raise failures[0]
        for view in lab.final_views:
            lab.closed(view)
        lab.private_ready()
        assert owner.call('snapshot', **SESSION)['phase'] == 'idle'
        if not args.performance:
            assert owner.call('window.list', **SESSION, app='calculator')['windows']
        lab.result['private_healthy_after_shell'] = True
        lab.result['no_capture_helpers_after_shell'] = lab.wait(
            lambda: not lab.capturers(), 'capture helper survived Shell')
        lab.result['complete'] = True
        lab.save_evidence()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--performance', action='store_true')
    run(parser.parse_args())
