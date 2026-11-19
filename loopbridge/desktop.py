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
from . import browser
from .catalog import CATALOG
from .linux_desktop import process_identity, sway, texts, wait_for, walk, windows
from .workspace import Workspace
from .web import Web
from .web_native import page_of
from .teaching_picker import Picker
from .private_effects import Effects
from .semantic_operations import (POLICIES, Prepared, SemanticOperations, actions,
                                  semantic_signature, short, state_flags)

EDITED_DOCUMENT = 'report.txt'
PAGE = 8


@dataclass
class Application:
    process: object
    identity: tuple | None = None
    document: str | None = None
    directory: str | None = None
    profile: Path | None = None
    site: bool = False
    external: bool = False


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
        from gi.repository import GLib

        self.atspi_errors = (GLib.Error, RuntimeError, OSError, AttributeError, TypeError)
        pyatspi.setTimeout(1000, 2000)
        self.desktop = lambda: pyatspi.Registry.getDesktop(0)
        sway('get_tree')
        self.desktop()
        self.workspace = Workspace(workspace) if workspace else None
        self.profile = tempfile.TemporaryDirectory(prefix='apps-', dir=runtime)
        self.apps = {}
        self.references = OrderedDict()
        self.operations = SemanticOperations(self)
        self.picker = Picker(self)
        self.web = Web(self)
        self.effects = Effects()

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
        spec = CATALOG[app]
        if spec.profile == 'offline_fixture':
            return browser.ready()
        return (os.access(spec.executable, os.X_OK)
                and (spec.profile not in ('document', 'directory') or self.workspace is not None))

    def app_info(self, app):
        spec = CATALOG[app]
        running = self.apps.get(app)
        return dict(app=app, application_id=spec.window_id, installed=os.access(spec.executable, os.X_OK),
                    launch_supported=self.supported(app), profile=spec.profile,
                    launch_method='browser.open_fixture' if spec.profile == 'offline_fixture' else 'app.launch',
                    web_site=spec.profile == 'offline_fixture' and self.supported(app),
                    state='running' if running and running.process.poll() is None else 'stopped',
                    mutations=POLICIES[app].mutations())

    def process(self, app):
        running = self.apps.get(app)
        if running is None or running.process.poll() is not None:
            raise Refused('application_not_running')
        if app == 'browser':
            if running.identity is None:
                raise Refused('browser_identity_unavailable')
            browser.lineage(running.process.pid, running.identity[0], running.identity)
            return running
        identity = process_identity(running.process.pid)
        if identity != running.identity:
            raise Refused('process_identity_changed')
        return running

    def match(self, app):
        running = self.process(app)
        pid, ticks, _, _ = running.identity
        records = [record for record in windows(sway('get_tree')) if record['pid'] == pid]
        allowed = [record for record in records
                   if record['app_id'] == CATALOG[app].window_id and record['shell'] == 'xdg_shell']
        frame = None
        if len(allowed) == 1 and len(records) == 1:
            try:
                applications = [item for item in self.desktop() if item.get_process_id() == pid]
                if len(applications) == 1:
                    frames = [node for node in applications[0] if node.getRoleName() == 'frame']
                    frame = frames[0] if len(frames) == 1 else None
            except self.atspi_errors:
                # Sway identity is still useful while accessibility registers
                # or tears down. An inconclusive tree never gets a reference.
                pass
        return allowed[:16], frame, pid, ticks

    def reference(self, target):
        token = secrets.token_hex(16)
        self.references[token] = target
        if len(self.references) > 1024:
            self.references.popitem(last=False)
        return token

    def resolve(self, app, token, element=False):
        saved = self.references.get(token)
        if not isinstance(saved, Target) or saved.app != app or (saved.path is not None) != element:
            raise Refused('stale_reference')
        records, frame, _, _ = self.match(app)
        if saved.window not in records or frame != saved.frame or frame is None:
            raise Refused('window_unavailable_or_ambiguous')
        if self.apps[app].document:
            self.verify_document(app, frame)
        if app == 'browser' and not self.apps[app].site:
            browser.known_document(frame)
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

    def tree_start(self, app, frame):
        if app != 'browser':
            return [((), frame)]
        if self.apps[app].external:
            from .web_https import allowed
            document, uri = browser.active_document(frame)
            allowed(uri)
        else:
            document, _ = browser.known_document(frame)
        roots = [(path, node) for path, node in walk(frame) if node == document]
        if len(roots) != 1:
            raise Refused('browser_document_ambiguous')
        return roots

    def tree(self, app, token, offset, depth):
        target, frame = self.resolve(app, token)
        pending = self.tree_start(app, frame)
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

    def find(self, app, token, filters):
        target, frame = self.resolve(app, token)
        pending = self.tree_start(app, frame)
        visited, matches, complete = 0, [], True
        while pending and visited < 512:
            path, node = pending.pop()
            if node is None:
                complete = False
                continue
            visited += 1
            role, name, interfaces = semantic_signature(node)
            protected = role == 'password text' or 'protected' in state_flags(node)
            if protected:
                continue
            if ((not filters['role'] or role == filters['role'])
                    and (not filters['name'] or self.label(app, name) == filters['name'])
                    and (not filters['interface'] or filters['interface'] in interfaces)):
                labels, truncated = actions(node, interfaces, limit=64) if filters['action'] else ([], False)
                if truncated:
                    complete = False
                elif not filters['action'] or filters['action'] in labels:
                    matches.append((path, node))
                    if len(matches) == 2:
                        return dict(status='ambiguous', reason='multiple_native_candidates')
            count = node.childCount
            if count < 0 or count > 128 or (count and len(path) >= 40):
                complete = False
                continue
            pending.extend(((*path, index), node[index]) for index in reversed(range(count)))
        if not complete or pending:
            return dict(status='unresolved', reason='incomplete_tree')
        if not matches:
            return dict(status='unresolved', reason='no_native_candidate')
        path, node = matches[0]
        return dict(status='matched', element=self.describe(target, path, node), source='atspi')

    def search(self, app, token, query, offset):
        target, frame = self.resolve(app, token)
        pending = self.tree_start(app, frame)
        matches, cursor, visited, omitted = [], 0, 0, False
        query = query.strip().casefold()
        while pending and visited < 512:
            path, node = pending.pop()
            if node is None:
                omitted = True
                continue
            visited += 1
            role, name, interfaces = semantic_signature(node)
            if role == 'password text' or 'protected' in state_flags(node):
                continue
            labels, truncated = actions(node, interfaces, limit=64)
            omitted |= truncated
            label = ' '.join([role, self.label(app, name), *filter(None, labels)])
            if query in label.casefold():
                if len(matches) >= PAGE:
                    return dict(elements=matches, next=cursor, truncated=omitted, searched=visited)
                if cursor >= offset:
                    matches.append(self.describe(target, path, node))
                cursor += 1
            count = node.childCount
            if count < 0 or count > 128 or (count and len(path) >= 40):
                omitted = True
                continue
            pending.extend(((*path, index), node[index]) for index in reversed(range(count)))
        return dict(elements=matches, next=None, truncated=omitted or bool(pending), searched=visited)

    def query(self, method, app, params):
        if method == 'session.capture':
            return self.effects.acquire()
        if method == 'session.capture.read':
            return self.effects.read(params['ref'], params['index'])
        if method in ('web.discover', 'web.controls_page'):
            return self.web.discover(app, params['ref'], params.get('offset', 0))
        if method == 'teach.capture':
            return self.picker.capture(app, params['ref'])
        if method == 'teach.find':
            return self.picker.find(app, params['ref'], params['evidence'])
        if method == 'app.info':
            return self.app_info(app)
        if method == 'window.list':
            return self.window_list(app)
        if method.startswith('workspace.'):
            if method in ('workspace.list', 'workspace.list_at'):
                return self.workspace.listing(params['offset'], params.get('directory', ''))
            return dict(text=self.workspace.read(params['path']), source='workspace')
        if method == 'desktop.capture':
            self.resolve(app, params['ref'])
            raise Refused('window_capture_unavailable')
        if method == 'browser.document':
            if app != 'browser':
                raise Refused('browser_fixture_app_required')
            _, frame = self.resolve(app, params['ref'])
            _, uri = browser.known_document(frame)
            if uri == browser.FORM:
                return dict(page='form', source='atspi_document')
            return dict(page='receipt', fields=browser.receipt_fields(uri), source='atspi_document')
        if method == 'window.inspect':
            target, node = self.resolve(app, params['ref'])
            return dict(window=str(target.window['id']), role=node.getRoleName(),
                        name=self.label(app, node.name), semantic='correlated', source='atspi')
        if method == 'element.search':
            return self.search(app, params['ref'], params['query'], params['offset'])
        if method == 'element.find':
            return self.find(app, params['ref'], params)
        if method == 'element.tree':
            return self.tree(app, params['ref'], params['offset'], params['depth'])
        if method in ('element.inspect', 'element.refresh'):
            selected, node = self.resolve(app, params['ref'], element=True)
            result = self.describe(selected, selected.path, node)
            if method == 'element.inspect':
                result.pop('ref')
            return result
        return self.operations.read(method, app, params)

    def prepare_launch(self, app, document=None, directory=None):
        if not self.supported(app):
            raise Refused('launch_unsupported')
        existing = self.apps.get(app)
        if existing and existing.process.poll() is None:
            raise Refused('application_already_running')
        spec = CATALOG[app]
        if spec.profile == 'offline_fixture':
            raise Refused('launch_unsupported')
        if directory is not None and spec.profile != 'directory':
            raise Refused('unsupported_directory_launch')
        executable, args = spec.executable, list(spec.arguments)
        if any(row['app_id'] == spec.window_id for row in windows(sway('get_tree'))):
            raise Refused('external_application_already_running')
        # Single-instance GTK programs may forward argv to a background peer.
        if not spec.standalone:
            for entry in Path('/proc').iterdir():
                if not entry.name.isdecimal():
                    continue
                try:
                    if os.readlink(entry / 'exe') == os.path.realpath(executable):
                        raise Refused('external_application_already_running')
                except OSError:
                    continue
        if spec.profile == 'document':
            document = document or EDITED_DOCUMENT
            try:
                args.append(self.workspace.file_path(document))
            except (OSError, ValueError):
                raise Refused('invalid_workspace_document') from None
        elif document is not None:
            raise Refused('unsupported_document_launch')
        elif spec.profile == 'directory':
            directory = directory if directory is not None else ''
            try:
                args.append(self.workspace.directory_path(directory))
            except (OSError, ValueError):
                raise Refused('invalid_workspace_directory') from None
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
            self.apps[app] = Application(process, document=document, directory=directory)

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
            if spec.semantic_required and semantic != 'correlated':
                raise Refused('semantic_not_ready')
            evidence = dict(app=app, windows=len(observed['windows']), semantic=semantic)
            if directory is not None:
                evidence.update(directory=directory, verifier='scoped_argv_and_supervised_sway_window')
            return evidence

        return Prepared(send, lambda: wait_for(verify, timeout=18))

    def prepare_browser(self, site=False, external=False):
        try:
            args, profile = browser.launch_args(self.profile.name, site, external)
        except (OSError, KeyError, ValueError):
            raise Refused('browser_isolation_unavailable') from None

        def send():
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, close_fds=True)
            self.apps['browser'] = Application(process, profile=profile, site=site, external=external)

        def verify():
            running = self.apps['browser']
            descendants = browser.process_tree(running.process.pid)
            candidates = [row for row in windows(sway('get_tree'))
                          if row['app_id'] == CATALOG['browser'].window_id and row['pid'] in descendants]
            if len(candidates) != 1:
                raise Refused('browser_window_unavailable_or_ambiguous')
            running.identity, children = browser.lineage(running.process.pid, candidates[0]['pid'])
            records, frame, _, _ = self.match('browser')
            if len(records) != 1 or frame is None:
                raise Refused('browser_fixture_not_ready')
            if site:
                observed = self.web.inspect(profile)
                page = page_of(browser.active_document(frame)[1])
                if page != 'home' or observed['page'] != page:
                    raise Refused('browser_fixture_not_ready')
            else:
                if browser.known_document(frame)[1] != browser.FORM:
                    raise Refused('browser_fixture_not_ready')
                browser.browser_native.call(profile, 'ready')
                page = 'form'
            return dict(app='browser', page=page, semantic='correlated', network='private_namespace',
                        verified_subprocesses=children, profile='disposable')

        return Prepared(send, lambda: wait_for(verify, timeout=30))

    def prepare_operation(self, method, app, params):
        if method.startswith(('session.pointer.', 'session.keyboard.')):
            return self.effects.prepare(method.rsplit('.', 1)[1], params['ref'], params.get('x'), params.get('y'),
                                        lambda: {app.identity for app in self.apps.values()},
                                        text=params.get('text'), key=params.get('key'))
        if method in ('browser.open_fixture', 'web.open', 'web.open_external'):
            current = self.apps.get(app)
            if app != 'browser':
                raise Refused('browser_fixture_app_required')
            if current is not None and current.process.poll() is None:
                raise Refused('application_already_running')
            external = method == 'web.open_external'
            if external and not os.environ.get('LOOPBRIDGE_HTTPS_HOSTS'):
                raise Refused('external_https_disabled')
            return self.prepare_browser(site=method != 'browser.open_fixture', external=external)
        if method.startswith('web.'):
            return self.web.prepare(method, app, params)
        if method == 'input.key':
            self.resolve(app, params['ref'])
            raise Refused('target_bound_input_unavailable')
        if method in ('app.launch', 'app.open_document', 'app.open_directory'):
            return self.prepare_launch(app, params.get('document'), params.get('directory'))
        if method == 'app.close':
            return self.prepare_close(app)
        if method.startswith('workspace.'):
            try:
                if method == 'workspace.mkdir':
                    path = params['path']
                    self.workspace.require_absent(path)
                    return Prepared(lambda: self.workspace.mkdir(path),
                                    lambda: self.workspace.confirm_directory(path))
                if method == 'workspace.rename':
                    source, destination = params['source'], params['destination']
                    expected = self.workspace.prepare_rename(source, destination)
                    return Prepared(lambda: self.workspace.rename(source, destination),
                                    lambda: self.workspace.confirm_rename(source, destination, expected))
                name, text = self.workspace.prepare(params['path'], params['text'])
                return Prepared(lambda: self.workspace.write(name, text),
                                lambda: self.workspace.confirm(name, text))
            except (OSError, ValueError):
                raise Refused('workspace_path_or_operation_unavailable') from None
        return self.operations.prepare(method, app, params)

    def verify_document(self, app, frame):
        document = self.apps[app].document
        self.workspace.file_path(document)
        path = Path(document)
        expected = f'{path.name} ({self.workspace.path / path.parent}) - Text Editor'
        if (frame.name or '').lstrip('*• ') != expected:
            raise Refused('editor_document_changed')
        return document

    def document_contents(self, target, *, closing=False):
        path = self.verify_document(target.app, target.frame)
        required = {'editable', 'multi_line'} if closing else {'editable', 'multi_line', 'showing'}
        documents = [child for _, child in walk(target.frame)
                     if child and required <= state_flags(child) and 'Text' in child.get_interfaces()]
        if len(documents) != 1:
            raise Refused('editor_document_ambiguous')
        query = documents[0].queryText()
        if not 0 <= query.characterCount <= 3000:
            raise Refused('workspace_size_limit')
        return path, query.getText(0, query.characterCount), 'showing' in state_flags(documents[0])

    def action_effect(self, policy, target, role, name, action):
        if ('invoke' in policy.effects and action == 'click'
                and role in ('push button', 'button') and len(name) == 1 and name in '0123456789'):
            before = texts(target.frame)
            return lambda: self.verify_digit(target.app, target, before, name)
        if action == 'page.save' and action in policy.effects and role == 'frame':
            document, buffer, _ = self.document_contents(target)
            # GtkSourceView appends an implicit final newline on disk.
            expected = buffer + '\n'
            if expected == self.workspace.read(document):
                raise Refused('no_change')
            return lambda: wait_for(lambda: self.workspace.confirm(document, expected), timeout=4)
        raise Refused('operation_outside_app_policy')

    def prepare_close(self, app):
        application = self.process(app)
        browser_pids = browser.process_tree(application.process.pid) if app == 'browser' else {}
        editor_showing = None
        if application.document:
            records, frame, _, _ = self.match(app)
            if not records or frame is None:
                raise Refused('window_unavailable_or_ambiguous')
            # A separate LoopTeach window can change GTK's accessibility
            # showing state. Closing still requires one exact, inspectable
            # buffer and a byte-for-byte readback from the authorized file.
            document, buffer, editor_showing = self.document_contents(
                Target(app, records[0], frame, None), closing=True)
            saved = self.workspace.read(document)
            if saved != buffer + '\n' and not (saved == buffer == ''):
                raise Refused('document_has_unsaved_changes')

        def send():
            self.process(app).process.terminate()

        def verify():
            application.process.wait(timeout=5)
            if any(row['pid'] in (browser_pids or {application.process.pid})
                   for row in windows(sway('get_tree'))):
                raise Refused('window_still_present')
            state = dict(app=app, state='stopped')
            if editor_showing is not None:
                state.update(bufferVerified=True, bufferShowingBeforeClose=editor_showing)
            return state

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
