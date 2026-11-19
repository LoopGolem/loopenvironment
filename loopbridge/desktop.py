# SPDX-License-Identifier: Apache-2.0
"""Sway window correlation and bounded AT-SPI operations on supervised apps."""
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import os
import secrets
import subprocess
import tempfile
import time

from .adapter import Refused
from .linux_desktop import process_identity, sway, texts, wait_for, walk, windows
from .workspace import Workspace
from .teaching_picker import Picker
from .semantic_operations import (POLICIES, Prepared, SemanticOperations, actions,
                                  semantic_signature, short, state_flags)

CATALOG = {
    'calculator': ('/usr/bin/gnome-calculator', 'org.gnome.Calculator', '--mode=basic'),
    'editor': ('/usr/bin/gnome-text-editor', 'org.gnome.TextEditor', '--standalone'),
    'files': ('/usr/bin/nautilus', 'org.gnome.Nautilus', '--new-window'),
    'clocks': ('/usr/bin/gnome-clocks', 'org.gnome.clocks'),
    'browser': ('/usr/bin/firefox-esr', 'firefox-esr'),
}
EDITED_DOCUMENT = 'report.txt'
PAGE = 8


@dataclass
class Application:
    process: object
    identity: tuple | None = None
    document: str | None = None


@dataclass
class Target:
    app: str
    window: dict
    frame: object
    path: tuple | None
    node: object = None
    signature: tuple | None = None


class Desktop:
    source = 'sway_atspi_workspace'

    def __init__(self, runtime, workspace):
        import pyatspi

        pyatspi.setTimeout(1000, 2000)
        self.desktop = lambda: pyatspi.Registry.getDesktop(0)
        sway('get_tree')
        self.workspace = Workspace(workspace) if workspace else None
        self.profile = tempfile.TemporaryDirectory(prefix='apps-', dir=runtime)
        self.apps = {}
        self.references = OrderedDict()
        self.operations = SemanticOperations(self)
        self.picker = Picker(self)

    def close(self):
        for app in self.apps.values():
            process = app.process
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if self.workspace:
            self.workspace.close()
        self.profile.cleanup()

    def supported(self, app):
        return (app != 'browser' and os.access(CATALOG[app][0], os.X_OK)
                and (app not in ('editor', 'files') or self.workspace is not None))

    def app_info(self, app):
        executable, app_id, *_ = CATALOG[app]
        running = self.apps.get(app)
        return dict(app=app, application_id=app_id, installed=os.access(executable, os.X_OK),
                    launch_supported=self.supported(app),
                    state='running' if running and running.process.poll() is None else 'stopped',
                    mutations=POLICIES[app].mutations())

    def process(self, app):
        running = self.apps.get(app)
        if running is None or running.process.poll() is not None:
            raise Refused('application_not_running')
        identity = process_identity(running.process.pid)
        if identity != running.identity:
            raise Refused('process_identity_changed')
        return running

    def match(self, app):
        running = self.process(app)
        pid, ticks, _, _ = running.identity
        records = [record for record in windows(sway('get_tree')) if record['pid'] == pid]
        allowed = [record for record in records
                   if record['app_id'] == CATALOG[app][1] and record['shell'] == 'xdg_shell']
        applications = [item for item in self.desktop() if item.get_process_id() == pid]
        if len(allowed) == 1 and len(records) == 1 and len(applications) == 1:
            frames = [node for node in applications[0] if node.getRoleName() == 'frame']
        else:
            frames = []
        frame = frames[0] if len(frames) == 1 else None
        return allowed[:16], frame, pid, ticks

    def reference(self, target):
        token = secrets.token_hex(16)
        self.references[token] = target
        if len(self.references) > 1024:
            self.references.popitem(last=False)
        return token

    def resolve(self, app, token, element=False):
        saved = self.references.get(token)
        if saved is None or saved.app != app or (saved.path is not None) != element:
            raise Refused('stale_reference')
        records, frame, _, _ = self.match(app)
        if saved.window not in records or frame != saved.frame or frame is None:
            raise Refused('window_unavailable_or_ambiguous')
        if self.apps[app].document:
            self.verify_document(app, frame)
        if not element:
            return saved, frame
        node = frame
        for index in saved.path:
            if index >= node.childCount:
                raise Refused('stale_reference')
            node = node[index]
        if node != saved.node or semantic_signature(node) != saved.signature or 'defunct' in state_flags(node):
            raise Refused('stale_reference')
        return saved, node

    def window_list(self, app):
        records, frame, pid, ticks = self.match(app)
        return dict(app=app, windows=[
            dict(window=str(row['id']), pid=pid, process_start=ticks,
                 application_id=row['app_id'], source='sway',
                 semantic='correlated' if frame is not None else 'unsupported_or_ambiguous',
                 ref=self.reference(Target(app, row, frame, None)) if frame is not None else None)
            for row in records])

    def label(self, app, text):
        if app == 'files':
            # The window can surface mount names and host paths in sidebars.
            return ''
        if self.workspace:
            text = (text or '').replace(str(self.workspace.path), 'workspace')
        return short(text)

    def describe(self, target, path, node):
        signature = semantic_signature(node)
        role, name, interfaces = signature
        flags = state_flags(node)
        labels, truncated = actions(node, interfaces)
        concealed = 'protected' in flags or role == 'password text'
        return dict(path=list(path), role=short(role),
                    name='' if concealed else self.label(target.app, name),
                    description='' if concealed else self.label(target.app, node.description),
                    state=sorted(flags)[:16],
                    interfaces=list(interfaces)[:12], actions=[short(label, 48) for label in labels],
                    actions_truncated=truncated,
                    editable='EditableText' in interfaces and 'editable' in flags,
                    children=node.childCount, source='atspi', confidence='reported',
                    ref=self.reference(Target(target.app, target.window, target.frame,
                                              path, node, signature)))

    def tree(self, app, token, offset, depth):
        target, frame = self.resolve(app, token)
        pending = [((), frame)]
        page, index, truncated = [], 0, False
        while pending and len(page) < PAGE:
            path, node = pending.pop()
            if node is None:
                continue
            if index >= offset:
                page.append(self.describe(target, path, node))
            index += 1
            count = node.childCount
            if len(path) < depth:
                pending.extend((path + (i,), node[i]) for i in reversed(range(min(count, 128))))
            if count and (len(path) == depth or count > 128):
                truncated = True
        return dict(elements=page, next=index if pending and index < 512 else None,
                    truncated=truncated or bool(pending and index >= 512))

    def query(self, method, app, params):
        if method == 'teach.capture':
            return self.picker.capture(app, params['ref'])
        if method == 'teach.find':
            return self.picker.find(app, params['ref'], params['evidence'])
        if method == 'app.info':
            return self.app_info(app)
        if method == 'window.list':
            return self.window_list(app)
        if method.startswith('workspace.'):
            if method == 'workspace.list':
                return self.workspace.listing(params['offset'])
            return dict(text=self.workspace.read(params['path']), source='workspace')
        if method == 'window.inspect':
            target, node = self.resolve(app, params['ref'])
            return dict(window=str(target.window['id']), role=node.getRoleName(),
                        name=self.label(app, node.name), semantic='correlated', source='atspi')
        if method == 'element.tree':
            return self.tree(app, params['ref'], params['offset'], params['depth'])
        if method in ('element.inspect', 'element.refresh'):
            selected, node = self.resolve(app, params['ref'], element=True)
            result = self.describe(selected, selected.path, node)
            if method == 'element.inspect':
                result.pop('ref')
            return result
        return self.operations.read(method, app, params)

    def prepare_launch(self, app, document=None):
        if not self.supported(app):
            raise Refused('launch_unsupported')
        existing = self.apps.get(app)
        if existing and existing.process.poll() is None:
            raise Refused('application_already_running')
        executable, app_id, *args = CATALOG[app]
        if any(row['app_id'] == app_id for row in windows(sway('get_tree'))):
            raise Refused('external_application_already_running')
        # Single-instance GTK programs may forward argv to a background peer.
        if app != 'editor':
            for entry in Path('/proc').iterdir():
                if not entry.name.isdecimal():
                    continue
                try:
                    if os.readlink(entry / 'exe') == os.path.realpath(executable):
                        raise Refused('external_application_already_running')
                except OSError:
                    continue
        if app == 'editor':
            document = document or EDITED_DOCUMENT
            try:
                args.append(self.workspace.file_path(document))
            except (OSError, ValueError):
                raise Refused('invalid_workspace_document') from None
        elif document is not None:
            raise Refused('unsupported_document_launch')
        elif app == 'files':
            self.workspace.verify_root()
            args.append(str(self.workspace.path))
        home = Path(self.profile.name) / app
        home.mkdir(exist_ok=True, mode=0o700)
        env = {key: os.environ[key] for key in ('WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR',
                                               'DBUS_SESSION_BUS_ADDRESS') if key in os.environ}
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'),
                   XDG_DATA_HOME=str(home / 'data'), XDG_CACHE_HOME=str(home / 'cache'),
                   GSETTINGS_BACKEND='memory', GDK_BACKEND='wayland', GTK_USE_PORTAL='0', LANG='C.UTF-8',
                   GIO_USE_VFS='local', PATH='/usr/bin')
        def send():
            process = subprocess.Popen([executable, *args], env=env, cwd=home,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, close_fds=True)
            self.apps[app] = Application(process, document=document)

        def verify():
            running = self.apps[app]
            identity = process_identity(running.process.pid)
            if identity[3] != os.path.realpath(executable):
                raise Refused('process_identity_changed')
            running.identity = identity
            observed = self.window_list(app)
            if not observed['windows']:
                raise Refused('window_not_found')
            semantic = observed['windows'][0]['semantic']
            if app in ('editor', 'calculator') and semantic != 'correlated':
                raise Refused('semantic_not_ready')
            return dict(app=app, windows=len(observed['windows']), semantic=semantic)

        return Prepared(send, lambda: wait_for(verify, timeout=18))

    def prepare_operation(self, method, app, params):
        if method in ('app.launch', 'app.open_document'):
            return self.prepare_launch(app, params.get('document'))
        if method == 'app.close':
            return self.prepare_close(app)
        if method == 'workspace.write':
            name, text = self.workspace.prepare(params['path'], params['text'])
            return Prepared(lambda: self.workspace.write(name, text),
                            lambda: self.workspace.confirm(name, text))
        return self.operations.prepare(method, app, params)

    def verify_document(self, app, frame):
        document = self.apps[app].document
        self.workspace.file_path(document)
        expected = f'{document} ({self.workspace.path}) - Text Editor'
        if (frame.name or '').lstrip('*• ') != expected:
            raise Refused('editor_document_changed')
        return document

    def document_contents(self, target):
        path = self.verify_document(target.app, target.frame)
        documents = [child for _, child in walk(target.frame)
                     if child and {'editable', 'multi_line', 'showing'} <= state_flags(child)
                     and 'Text' in child.get_interfaces()]
        if len(documents) != 1:
            raise Refused('editor_document_ambiguous')
        query = documents[0].queryText()
        if not 0 <= query.characterCount <= 3000:
            raise Refused('workspace_size_limit')
        return path, query.getText(0, query.characterCount)

    def action_effect(self, policy, target, role, name, action):
        if ('invoke' in policy.effects and action == 'click'
                and role in ('push button', 'button') and len(name) == 1 and name in '0123456789'):
            before = texts(target.frame)
            return lambda: self.verify_digit(target.app, target, before, name)
        if action == 'page.save' and action in policy.effects and role == 'frame':
            document, buffer = self.document_contents(target)
            # GtkSourceView appends an implicit final newline on disk.
            expected = buffer + '\n'
            if expected == self.workspace.read(document):
                raise Refused('no_change')
            return lambda: wait_for(lambda: self.workspace.confirm(document, expected), timeout=4)
        raise Refused('operation_outside_app_policy')

    def prepare_close(self, app):
        application = self.process(app)
        if application.document:
            records, frame, _, _ = self.match(app)
            if not records or frame is None:
                raise Refused('window_unavailable_or_ambiguous')
            document, buffer = self.document_contents(Target(app, records[0], frame, None))
            saved = self.workspace.read(document)
            if saved != buffer + '\n' and not (saved == buffer == ''):
                raise Refused('document_has_unsaved_changes')

        def send():
            self.process(app).process.terminate()

        def verify():
            application.process.wait(timeout=5)
            if any(row['pid'] == application.process.pid for row in windows(sway('get_tree'))):
                raise Refused('window_still_present')
            return dict(app=app, state='stopped')

        return Prepared(send, lambda: wait_for(verify, timeout=7))

    def verify_digit(self, app, target, before, digit):
        def verify():
            records, frame, _, _ = self.match(app)
            if target.window not in records or frame != target.frame:
                raise Refused('window_changed')
            actual = texts(frame)
            changes = [key for key in before if actual.get(key) != before[key]]
            if set(actual) != set(before) or len(changes) != 1:
                raise Refused('result_not_confirmed')
            key = changes[0]
            expected = digit if before[key] in ('', '0') else before[key] + digit
            if actual[key] != expected:
                raise Refused('result_not_confirmed')
            return dict(display=actual[key])
        return wait_for(verify, timeout=3)

    @staticmethod
    def send(prepared):
        if prepared.send() is False:
            raise Refused('submission_not_acknowledged')

    @staticmethod
    def confirm(prepared):
        return prepared.verify()
