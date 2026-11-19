# SPDX-License-Identifier: Apache-2.0
"""GTK structured teacher. Desktop data and privileges come through the socket."""
from concurrent.futures import ThreadPoolExecutor
import json
import socket
import time

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk

from .protocol import Fault, RPC


class Teacher:
    def __init__(self, app, endpoint, credential, demo):
        self.app, self.endpoint, self.credential, self.demo = app, endpoint, credential, demo
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='loopteach-rpc')
        self.socket = self.rpc = None
        self.apps = []
        self.windows = []
        self.nodes = []
        self.live = None
        self.offset = 0
        self.next = None
        self.busy = False
        self.failed = False
        self.demo_step = 0
        self.result = None
        self.window = Gtk.ApplicationWindow(application=app, title='LoopTeach', default_width=680,
                                            default_height=640)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for edge in ('top', 'bottom', 'start', 'end'):
            getattr(content, 'set_margin_' + edge)(16)
        self.window.set_child(content)
        self.app_choice = Gtk.ComboBoxText()
        self.window_choice = Gtk.ComboBoxText()
        self.window_choice.connect('changed', self.load_tree)
        self.app_choice.connect('changed', self.load_windows)
        content.append(self.field('Application', self.app_choice))
        content.append(self.field('Window', self.window_choice))
        self.filter = Gtk.SearchEntry(placeholder_text='Filter this page by role, name, or action')
        self.filter.connect('search-changed', self.render_rows)
        content.append(self.filter)
        viewer = Gtk.ScrolledWindow(min_content_height=130, vexpand=True)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.connect('row-selected', self.inspect)
        viewer.set_child(self.list)
        content.append(viewer)
        nav = Gtk.Box(spacing=8)
        self.prev_button = Gtk.Button(label='First page')
        self.prev_button.connect('clicked', lambda *_: self.page(0))
        self.next_button = Gtk.Button(label='Next page')
        self.next_button.connect('clicked', lambda *_: self.page(self.next))
        nav.append(self.prev_button)
        nav.append(self.next_button)
        content.append(nav)
        self.evidence = Gtk.Label(xalign=0, wrap=True, selectable=True)
        content.append(self.evidence)
        self.inputs = {}
        for key, label in (('meaning', 'Meaning'), ('operationHint', 'Suggested action'),
                           ('conditions', 'Conditions'), ('warnings', 'Warnings')):
            entry = Gtk.Entry(max_length=128 if key == 'operationHint' else 480)
            self.inputs[key] = entry
            content.append(self.field(label, entry))
        self.save_button = Gtk.Button(label='Save annotation', sensitive=False)
        self.save_button.connect('clicked', self.save)
        content.append(self.save_button)
        self.status = Gtk.Label(xalign=0, wrap=True)
        content.append(self.status)
        self.window.present()
        self.request(self.connect, self.display_apps)
        if demo:
            self.deadline = time.monotonic() + 55
            GLib.timeout_add(100, self.run_demo)

    @staticmethod
    def field(label, widget):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        name = Gtk.Label(label=label, xalign=0, width_chars=18)
        name.set_mnemonic_widget(widget)
        widget.set_hexpand(True)
        box.append(name)
        box.append(widget)
        return box

    def connect(self):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(30)
        self.socket.connect(self.endpoint)
        self.rpc = RPC(self.socket)
        self.rpc.call('auth', credential=self.credential)
        self.credential = None
        return self.call('app.list')['applications']

    def call(self, method, **params):
        return self.rpc.call(method, session='desktop', **params)

    def request(self, task, handle):
        if self.busy:
            return
        self.busy = True
        self.status.set_text('Loading…')
        self.window.set_sensitive(False)
        future = self.worker.submit(task)
        future.add_done_callback(lambda completed: GLib.idle_add(self.completed, completed, handle))

    def completed(self, future, handler):
        self.busy = False
        self.window.set_sensitive(True)
        try:
            data = future.result()
        except (Fault, OSError, EOFError, ValueError):
            self.status.set_text('Request refused or unavailable. Reload the window or select again.')
            if self.demo:
                self.failed = True
            return False
        self.status.set_text('')
        handler(data)
        return False

    def display_apps(self, apps):
        self.apps = [row for row in apps if row['state'] == 'running']
        for row in self.apps:
            self.app_choice.append_text(row['app'])
        if not self.apps:
            self.status.set_text('Launch an authorized application before teaching.')

    def load_windows(self, *_):
        selected = self.app_choice.get_active()
        if selected < 0:
            return
        app = self.apps[selected]['app']
        self.request(lambda: self.call('window.list', app=app)['windows'], self.display_windows)

    def display_windows(self, windows):
        self.windows = [row for row in windows if row['ref']]
        self.window_choice.remove_all()
        for row in self.windows:
            self.window_choice.append_text(f"{row['application_id']} · {row['window']}")
        if not self.windows:
            self.status.set_text('No verified accessible window is available.')

    def load_tree(self, *_):
        self.page(0)

    def page(self, offset):
        selected = self.window_choice.get_active()
        if selected < 0 or offset is None:
            return
        window = self.windows[selected]
        app = self.apps[self.app_choice.get_active()]['app']

        def query():
            live = self.call('window.list', app=app)['windows']
            reference = next((item['ref'] for item in live if item['window'] == window['window']
                              and item['pid'] == window['pid']
                              and item['process_start'] == window['process_start']), None)
            if not reference:
                raise ValueError('window_changed')
            return self.call('element.tree', ref=reference, offset=offset, depth=40)

        self.request(query, self.display_page)

    def display_page(self, page):
        self.nodes, self.next = page['elements'], page['next']
        self.next_button.set_sensitive(self.next is not None)
        self.render_rows()

    def render_rows(self, *_):
        self.live = None
        self.save_button.set_sensitive(False)
        self.evidence.set_text('')
        while (row := self.list.get_first_child()) is not None:
            self.list.remove(row)
        query = self.filter.get_text().strip().casefold()
        for node in self.nodes:
            searchable = ' '.join([node['role'], node['name'], *node['actions']])
            if query not in searchable.casefold():
                continue
            row = Gtk.ListBoxRow()
            row.node = node
            row.set_child(Gtk.Label(label=searchable, xalign=0, wrap=True))
            self.list.append(row)

    def inspect(self, _list, row):
        self.live = None
        self.save_button.set_sensitive(False)
        if row is None:
            return
        token = row.node['ref']

        def query():
            element = self.call('element.refresh', ref=token)
            labels = self.call('element.actions', ref=element['ref'])
            return element, labels['actions']

        self.request(query, self.display_evidence)

    def display_evidence(self, data):
        element, labels = data
        self.live = element['ref']
        self.evidence.set_text(f"AT-SPI · {element['role']} · {element['name']}\n"
                               f"Actions: {', '.join(labels) or '—'}")
        self.save_button.set_sensitive(True)

    def save(self, *_):
        if not self.live:
            return
        token = self.live
        fields = {key: entry.get_text() for key, entry in self.inputs.items()}

        def submit():
            refreshed = self.call('element.refresh', ref=token)
            return self.call('teach.create', ref=refreshed['ref'], **fields)

        self.request(submit, self.saved)

    def saved(self, result):
        self.result = result
        self.status.set_text(f"Annotation saved · revision {result['revision']}")
        if self.demo:
            print(json.dumps(dict(toolkit='GTK4', visible_window=self.window.get_visible(),
                                  input='scripted_widget_events', annotation=result)), flush=True)
            self.app.quit()

    def run_demo(self):
        if self.failed or time.monotonic() >= self.deadline:
            self.failed = True
            self.app.quit()
            return False
        if self.busy:
            return True
        if self.demo_step == 0 and self.apps:
            for index, app in enumerate(self.apps):
                if app['app'] == 'editor':
                    self.app_choice.set_active(index)
                    self.demo_step += 1
                    break
        elif self.demo_step == 1 and self.windows:
            self.window_choice.set_active(0)
            self.demo_step += 1
        elif self.demo_step == 2 and self.nodes:
            row = self.list.get_first_child()
            while row is not None:
                if row.node['role'] == 'frame':
                    self.list.select_row(row)
                    self.demo_step += 1
                    break
                row = row.get_next_sibling()
        elif self.demo_step == 3 and self.live:
            self.inputs['meaning'].set_text('document.save')
            self.inputs['operationHint'].set_text('page.save')
            self.save_button.emit('clicked')
            self.demo_step += 1
        return self.result is None

    def close(self):
        self.worker.shutdown(wait=True, cancel_futures=True)
        if self.socket is not None:
            self.socket.close()


def run(endpoint, credential, demo=False):
    app = Gtk.Application(application_id='org.loopenvironment.LoopTeach',
                          flags=Gio.ApplicationFlags.NON_UNIQUE)
    views = []
    app.connect('activate', lambda gtk_app: views.append(Teacher(gtk_app, endpoint, credential, demo)))
    try:
        status = app.run([])
        return 1 if demo and (not views or views[0].result is None) else status
    finally:
        for view in views:
            view.close()
