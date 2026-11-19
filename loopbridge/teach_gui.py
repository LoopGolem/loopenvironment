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
    def __init__(self, app, endpoint, credential, demo, demo_review=False):
        self.app, self.endpoint, self.credential = app, endpoint, credential
        self.demo, self.demo_review = demo or demo_review, demo_review
        self.pending_proof = None
        self.focus = None
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='loopteach-rpc')
        self.socket = self.rpc = None
        self.apps = []
        self.windows = []
        self.nodes = []
        self.live = None
        self.note = None
        self.mode = 'elements'
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
        search_row = Gtk.Box(spacing=8)
        self.filter = Gtk.SearchEntry(placeholder_text='Role, name, action or saved meaning',
                                      hexpand=True)
        self.filter.connect('activate', lambda *_: self.page(0))
        controls = Gtk.Button(label='Search controls', tooltip_text='Search the whole scoped tree. Enter searches again.')
        controls.connect('clicked', lambda *_: self.show('elements'))
        notes = Gtk.Button(label='Search saved annotations')
        notes.connect('clicked', lambda *_: self.show('notes'))
        search_row.append(self.filter)
        search_row.append(controls)
        search_row.append(notes)
        content.append(search_row)
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
            help_text = dict(meaning='What the control means, such as document.save.',
                             operationHint='Suggested native action. This does not grant control.',
                             conditions='When the annotation applies.', warnings='Known limits or risks.')
            entry = Gtk.Entry(max_length=128 if key == 'operationHint' else 480,
                              tooltip_text=help_text[key])
            self.inputs[key] = entry
            content.append(self.field(label, entry))
        self.save_button = Gtk.Button(label='Save annotation', sensitive=False)
        self.save_button.connect('clicked', self.save)
        actions = Gtk.Box(spacing=8)
        actions.append(self.save_button)
        self.resolve_button = Gtk.Button(label='Resolve in window', sensitive=False)
        self.resolve_button.connect('clicked', self.resolve_note)
        actions.append(self.resolve_button)
        self.review_buttons = []
        for decision in ('approved', 'rejected'):
            button = Gtk.Button(label='Approve' if decision == 'approved' else 'Reject', sensitive=False)
            button.connect('clicked', lambda _, value=decision: self.review(value))
            actions.append(button)
            self.review_buttons.append(button)
        content.append(actions)
        for name, key, activate in (
                ('find', '<Primary>f', lambda: self.filter.grab_focus()),
                ('save', '<Primary>s', lambda: self.save() if self.save_button.get_sensitive() else None)):
            binding = Gio.SimpleAction.new(name, None)
            binding.connect('activate', lambda *_args, callback=activate: callback())
            self.window.add_action(binding)
            app.set_accels_for_action('win.' + name, [key])
        self.status = Gtk.Label(xalign=0, wrap=True)
        content.append(self.status)
        self.window.present()
        self.request(self.connect, self.display_apps)
        if self.demo:
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
        self.focus = self.window.get_focus()
        self.window.set_sensitive(False)
        future = self.worker.submit(task)
        future.add_done_callback(lambda completed: GLib.idle_add(self.completed, completed, handle))

    def completed(self, future, handler):
        self.busy = False
        self.window.set_sensitive(True)
        if self.focus is not None and self.focus.get_root() == self.window:
            self.focus.grab_focus()
        self.focus = None
        try:
            data = future.result()
        except (Fault, OSError, EOFError, ValueError) as error:
            code = error.message if isinstance(error, Fault) else ''
            if code in ('stale_reference', 'snapshot_required', 'annotation_revision_conflict'):
                self.clear_selection()
                self.status.set_text('The selection or revision changed. Search again and reselect it.')
            elif code == 'grant_denied':
                self.status.set_text('This principal lacks permission for the selected operation.')
            else:
                self.status.set_text('Request unavailable. Reload the window or select again.')
            if self.demo:
                self.failed = True
            return False
        self.status.set_text('')
        handler(data)
        return False

    def display_apps(self, apps):
        self.apps = apps
        for row in self.apps:
            self.app_choice.append_text(row['app'])
        if not self.apps:
            self.status.set_text('Launch an authorized application before teaching.')

    def load_windows(self, *_):
        selected = self.app_choice.get_active()
        if selected < 0:
            return
        self.clear_selection()
        self.nodes = []
        self.render_rows()
        app = self.apps[selected]['app']
        if self.mode == 'notes':
            self.page(0)
            return
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

    def show(self, mode):
        if self.busy:
            return
        self.mode = mode
        self.page(0)

    def fresh_window(self, app, window):
        live = self.call('window.list', app=app)['windows']
        reference = next((item['ref'] for item in live if item['window'] == window['window']
                          and item['pid'] == window['pid']
                          and item['process_start'] == window['process_start']), None)
        if not reference:
            raise ValueError('window_changed')
        return reference

    def page(self, offset):
        chosen = self.app_choice.get_active()
        if chosen < 0 or offset is None:
            return
        app = self.apps[chosen]['app']
        selected = self.window_choice.get_active()
        term = self.filter.get_text().strip()
        if len(term) > 128:
            self.status.set_text('Use up to 128 characters in a search.')
            return
        if self.mode == 'notes':
            self.request(lambda: self.call('teach.search', app=app, query=term,
                                          revision=0, offset=offset), self.display_page)
            return
        if selected < 0:
            self.load_windows()
            return
        target = self.windows[selected]

        def query():
            ref = self.fresh_window(app, target)
            if term:
                return self.call('element.search', ref=ref, query=term, offset=offset)
            return self.call('element.tree', ref=ref, offset=offset, depth=40)

        self.request(query, self.display_page)

    def display_page(self, page):
        self.nodes, self.next = page.get('elements', page.get('annotations')), page['next']
        if page.get('truncated'):
            self.status.set_text('Some controls were omitted by tree limits. Refine the search.')
        elif not self.nodes:
            self.status.set_text('No results for this selection.')
        self.next_button.set_sensitive(self.next is not None)
        self.render_rows()

    def clear_selection(self):
        self.live = self.note = None
        self.save_button.set_sensitive(False)
        self.resolve_button.set_sensitive(False)
        for button in self.review_buttons:
            button.set_sensitive(False)
        self.evidence.set_text('')

    def render_rows(self, *_):
        self.clear_selection()
        while (row := self.list.get_first_child()) is not None:
            self.list.remove(row)
        for node in self.nodes:
            if self.mode == 'notes':
                label = f"{node['meaning']} · revision {node['revision']} · {node['reviewState']}"
            else:
                label = ' '.join([node['role'], node['name'], *node['actions']])
            row = Gtk.ListBoxRow()
            row.node = node
            row.set_child(Gtk.Label(label=label, xalign=0, wrap=True))
            self.list.append(row)

    def inspect(self, _list, row):
        self.clear_selection()
        if row is None:
            return
        if self.mode == 'notes':
            app = self.apps[self.app_choice.get_active()]['app']
            ident = row.node['id']
            self.request(lambda: self.call('teach.inspect', app=app, annotation=ident), self.display_note)
            return
        token = row.node['ref']

        def query():
            element = self.call('element.refresh', ref=token)
            labels = self.call('element.actions', ref=element['ref'])
            return element, labels['actions']

        self.request(query, self.display_evidence)

    def display_note(self, note):
        self.note = note
        self.evidence.set_text(f"{note['provenance']} · revision {note['revision']} · {note['reviewState']}\n"
                               f"Created by {note['createdBy']} · Updated by {note['updatedBy']}")
        for key, entry in self.inputs.items():
            entry.set_text(note['annotation'][key])
        self.save_button.set_label('Save revision')
        self.save_button.set_sensitive(True)
        self.resolve_button.set_sensitive(self.window_choice.get_active() >= 0)
        for button in self.review_buttons:
            button.set_sensitive(True)

    def resolve_note(self, *_):
        selected = self.window_choice.get_active()
        if self.note is None or selected < 0:
            return
        note, window = self.note, self.windows[selected]

        def resolve():
            ref = self.fresh_window(note['app'], window)
            return self.call('teach.resolve', ref=ref, annotation=note['id'])

        def display(result):
            quality = result.get('matchQuality', result['status'])
            origin = result.get('provenance', {}).get('association', 'AT-SPI evidence')
            criteria = ', '.join(result.get('criteria', []))
            self.status.set_text(f"{quality} · {origin}" + (f" · {criteria}" if criteria else ''))
            if self.demo_review:
                if result['status'] != 'matched':
                    self.failed = True
                else:
                    self.complete_demo(self.pending_proof, quality)

        self.request(resolve, display)

    def review(self, value):
        if self.note is None:
            return
        note = self.note
        self.request(lambda: self.call('teach.review', app=note['app'], annotation=note['id'],
                                       revision=note['revision'], decision=value),
                     lambda result: self.saved(result, reviewed=True))

    def display_evidence(self, data):
        element, labels = data
        self.live = element['ref']
        self.evidence.set_text(f"AT-SPI · {element['role']} · {element['name']}\n"
                               f"Actions: {', '.join(labels) or '—'}")
        self.save_button.set_label('Save annotation')
        self.save_button.set_sensitive(True)

    def save(self, *_):
        if not self.live and self.note is None:
            return
        token, note = self.live, self.note
        fields = {key: entry.get_text() for key, entry in self.inputs.items()}

        def submit():
            if note is not None:
                return self.call('teach.update', app=note['app'], annotation=note['id'],
                                 revision=note['revision'], **fields)
            refreshed = self.call('element.refresh', ref=token)
            return self.call('teach.create', ref=refreshed['ref'], **fields)

        self.request(submit, self.saved)

    def saved(self, result, reviewed=False):
        event = 'Review recorded' if reviewed else 'Annotation saved'
        self.status.set_text(f"{event} · revision {result['revision']} · {result['reviewState']}")
        if self.note is not None:
            self.note.update(revision=result['revision'], reviewState=result['reviewState'])
        if self.demo_review:
            self.pending_proof = result
        elif self.demo:
            self.complete_demo(result)

    def complete_demo(self, result, match=None):
        self.result = result
        print(json.dumps(dict(toolkit='GTK4', visible_window=self.window.get_visible(),
                              input='scripted_widget_events', annotation=result, matchQuality=match)),
              flush=True)
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
            self.filter.set_text('document.save' if self.demo_review else 'page.save')
            self.show('notes' if self.demo_review else 'elements')
            self.demo_step += 1
        elif self.demo_step == 3 and self.nodes:
            row = self.list.get_first_child()
            while row is not None:
                if self.demo_review or row.node['role'] == 'frame':
                    self.list.select_row(row)
                    self.demo_step += 1
                    break
                row = row.get_next_sibling()
        elif self.demo_step == 4:
            if self.demo_review and self.note:
                self.inputs['conditions'].set_text('Verified local editor workflow.')
                self.save_button.emit('clicked')
                self.demo_step += 1
            elif not self.demo_review and self.live:
                self.inputs['meaning'].set_text('document.save')
                self.inputs['operationHint'].set_text('page.save')
                self.save_button.emit('clicked')
                self.demo_step += 1
        elif self.demo_review and self.demo_step == 5 and self.pending_proof:
            self.review_buttons[0].emit('clicked')
            self.demo_step += 1
        elif self.demo_review and self.demo_step == 6 and self.note['reviewState'] == 'approved':
            self.resolve_button.emit('clicked')
            self.demo_step += 1
        return self.result is None

    def close(self):
        self.worker.shutdown(wait=True, cancel_futures=True)
        if self.socket is not None:
            self.socket.close()


def run(endpoint, credential, demo=False, demo_review=False):
    app = Gtk.Application(application_id='org.loopenvironment.LoopTeach',
                          flags=Gio.ApplicationFlags.NON_UNIQUE)
    views = []
    app.connect('activate', lambda gtk_app: views.append(Teacher(gtk_app, endpoint, credential, demo, demo_review)))
    try:
        status = app.run([])
        return 1 if (demo or demo_review) and (not views or views[0].result is None) else status
    finally:
        for view in views:
            view.close()
