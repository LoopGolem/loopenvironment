# SPDX-License-Identifier: Apache-2.0
"""Scope authorization and temporary reference translation for V0.5."""
import secrets

from .adapter import Refused, Unavailable
from .authority import Handle, fail
from .broker import Broker, SCHEMA
from .presentation import CAPABILITY as STREAM_CAPABILITY, SCHEMA as PRESENTATION_SCHEMA
from .protocol import VERSION
from .private_effects import available, private_id, KEYS, OUTPUT, TTL
from .teach_routes import SCHEMA as TEACH_SCHEMA, TeachRoutes

READS = {
    'session.capture': set(),
    'session.capture.read': {'ref', 'index'},
    'window.list': {'app'},
    'window.inspect': {'ref'},
    'element.tree': {'ref', 'offset', 'depth'},
    'element.find': {'ref', 'role', 'name', 'interface', 'action'},
    'element.search': {'ref', 'query', 'offset'},
    'element.actions': {'ref'},
    'element.inspect': {'ref'},
    'element.refresh': {'ref'},
    'element.get_selection': {'ref'},
    'element.get_text': {'ref'},
    'element.get_value': {'ref'},
    'workspace.list': {'offset'},
    'workspace.list_at': {'offset', 'directory'},
    'desktop.capture': {'ref'},
    'browser.document': {'ref'},
    'web.controls_page': {'ref', 'offset'},
    'web.discover': {'ref'},
    'workspace.read': {'path'},
}
WRITES = {
    'session.keyboard.type': ({'ref', 'text'}, 'desktop.input'),
    'session.keyboard.key': ({'ref', 'key'}, 'desktop.input'),
    'session.pointer.click': ({'ref', 'x', 'y'}, 'desktop.input'),
    'session.pointer.move': ({'ref', 'x', 'y'}, 'desktop.input'),
    'app.launch': ({'app'}, 'app.launch'),
    'app.open_document': ({'app', 'document'}, 'app.launch'),
    'app.open_directory': ({'app', 'directory'}, 'app.launch'),
    'browser.open_fixture': ({'app'}, 'app.launch'),
    'web.open_external': ({'app'}, 'app.launch'),
    'web.navigate_https': ({'ref', 'url'}, 'desktop.control'),
    'web.open': ({'app'}, 'app.launch'),
    'web.navigate': ({'ref', 'page'}, 'desktop.control'),
    'web.set_text': ({'ref', 'text'}, 'desktop.control'),
    'web.select': ({'ref', 'option'}, 'desktop.control'),
    'web.submit_https': ({'ref'}, 'web.submit'),
    'web.activate': ({'ref'}, 'desktop.control'),
    'input.key': ({'ref', 'key'}, 'desktop.input'),
    'app.close': ({'app'}, 'app.close'),
    'element.invoke': ({'ref', 'action'}, 'desktop.control'),
    'element.set_text': ({'ref', 'text'}, 'desktop.control'),
    'element.set_value': ({'ref', 'value'}, 'desktop.control'),
    'element.select': ({'ref', 'index'}, 'desktop.control'),
    'workspace.write': ({'path', 'text'}, 'workspace.write'),
    'workspace.mkdir': ({'path'}, 'workspace.write'),
    'workspace.rename': ({'source', 'destination'}, 'workspace.write'),
}
LEASE = {'lease', 'epoch', 'generation'}
EFFECT_REQUIREMENTS = {'page.save': (('workspace.write', 'workspace'),)}


class DesktopBroker(Broker):
    versions = ('0.2', '0.3', '0.4', '0.5', VERSION)
    connection_limits = (60, 300, 160)
    schema = {method: fields for method, fields in SCHEMA.items()
              if method not in ('invoke7',)}
    schema.update({method: fields | {'session'} for method, fields in READS.items()})
    schema.update({method: fields | {'session'} | LEASE
                   for method, (fields, _) in WRITES.items()})
    schema.update({'app.list': {'session'}, 'operation.status': {'session', 'operation'},
                   'session.features': {'session'}, 'session.recovery': {'session'},
                   'session.access': {'session'}})
    schema.update({method: fields | {'session'} for method, fields in TEACH_SCHEMA.items()})
    schema.update(PRESENTATION_SCHEMA)

    def __init__(self, *args, annotation_store=None, presentation=None, **kwargs):
        extra = (STREAM_CAPABILITY,) if presentation is not None else ()
        super().__init__(*args, extra_capabilities=extra, **kwargs)
        self.teach = TeachRoutes(self, annotation_store)
        self.presentation = presentation

    def grant_revoked(self, session, grant_id):
        if self.presentation:
            self.presentation.revoke(session, grant_id)

    def disconnect(self, connection):
        if self.presentation:
            self.presentation.disconnect(connection)
        super().disconnect(connection)

    def upgrade(self, connection, method, result, channel):
        if method == 'presentation.open':
            self.presentation.run(connection, result['stream'], channel)
            return True
        return False

    def target(self, session, connection, params, grace=0, *, capture=False):
        if 'ref' in params:
            handle = connection.handles.get(params['ref'])
            if (handle is None or handle.session != session.id or handle.epoch != session.epoch
                    or handle.revision != session.revision or handle.generation != session.generation
                    or self.clock() >= handle.expires + grace):
                fail('stale_reference', -32002)
            app, token = handle.reference
            if (app == '@capture') != capture:
                fail('stale_reference', -32002)
            return app, {**params, 'ref': token}, handle
        app = params.get('app')
        if app is not None and app not in session.catalog:
            fail('unknown_application', -32602)
        return app, params, None

    def extended(self, session, connection, method, params):
        if 'offset' in params and (type(params['offset']) is not int or not 0 <= params['offset'] <= 512):
            fail('invalid_offset', -32602)
        if 'depth' in params and (type(params['depth']) is not int or not 0 <= params['depth'] <= 40):
            fail('invalid_depth', -32602)
        if 'index' in params and (type(params['index']) is not int or not 0 <= params['index'] < 128):
            fail('invalid_selection_index', -32602)
        principal = self.authenticated(connection)
        if method in PRESENTATION_SCHEMA:
            if self.presentation is None:
                fail('presentation_unavailable', -32006)
            return self.presentation.request(session, connection, method, params)
        if method in TEACH_SCHEMA:
            return self.teach.handle(session, connection, principal, method, params)
        if method == 'session.recovery':
            with session.lock:
                session.require(principal, 'identity.admin', '*')
                try:
                    intent = self.journal.intent(session.id) if self.journal.blocked(session.id) else None
                except OSError:
                    intent = None
                return dict(phase=session.phase, policy='automatic_replacement_disabled',
                            unknownOperation=intent if not session.pending else None,
                            reuseMutableWorkspace=False, cancellationAssumed=False)
        if method == 'session.access':
            with session.lock:
                session.require(principal, 'session.discover', '*')
                targets = ('*', 'workspace', *('app:' + app for app in sorted(session.catalog)))
                return dict(scopes={cap: [scope for scope in targets if session.permits(principal, cap, scope)]
                                    for cap in self.capabilities(session, principal)})
        if method.startswith(('session.capture', 'session.pointer.', 'session.keyboard.')):
            return self.private_effect(session, connection, principal, method, params)
        if method == 'session.features':
            with session.lock:
                session.require(principal, 'session.discover', '*')
            info = dict(capture='window_capture_unavailable', input='target_bound_input_unavailable',
                        teaching='0.3', recovery='automatic_replacement_disabled',
                        sources=['atspi', 'linux_workspace', 'firefox_dom'])
            if private := private_id():
                info.update(privateId=private, capture='private_output' if available() else 'disabled',
                            input='private_pointer' if available() else 'disabled',
                            keyboard='private_keyboard' if available() else 'disabled')
                from .web_https import hosts
                info['externalHttps'] = bool(hosts())
            return info
        if method == 'operation.status':
            with session.lock:
                result = self.operations[session.id].get(params['operation'])
                if result and (result[0] == principal or session.permits(principal, 'identity.admin', '*')):
                    return dict(operation=params['operation'], status=result[1])
                if session.pending == params['operation'] and session.permits(principal, 'identity.admin', '*'):
                    return dict(operation=params['operation'], status='pending')
                try:
                    pending = self.journal.intent(session.id)
                except OSError:
                    pending = None
                if (session.phase == 'blocked' and pending == params['operation']
                        and session.permits(principal, 'identity.admin', '*')):
                    return dict(operation=pending, status='unknown')
                fail('operation_unavailable', -32002)
        with session.lock:
            grace = 100 if method == 'element.refresh' else 0
            app, arguments, handle = self.target(session, connection, params, grace)
            if method.startswith('workspace.'):
                if not session.workspace:
                    fail('workspace_disabled')
                target = 'workspace'
            else:
                target = 'app:' + app if app else '*'
        if method in WRITES:
            capability = WRITES[method][1]
            if method.startswith('workspace.'):
                observation = 'workspace.read'
            else:
                observation = (None if method in ('app.launch', 'app.close', 'app.open_document',
                                                 'app.open_directory', 'browser.open_fixture', 'web.open', 'web.open_external')
                               else 'desktop.observe')
            extra = EFFECT_REQUIREMENTS.get(params.get('action'), ())
            if method in ('app.open_document', 'app.open_directory', 'element.select'):
                extra = (('workspace.read', 'workspace'),)
            return self.dispatch(session, connection, params, 'desktop.prepare',
                                 (method, app, arguments), target, capability, observation, handle, extra)
        read_capability = ('session.discover' if method == 'app.list' else 'desktop.capture'
                           if method == 'desktop.capture' else 'workspace.read'
                           if target == 'workspace' else 'desktop.observe')
        with session.lock:
            session.require(principal, read_capability, target)
            revision = session.revision
            visible = sorted(candidate for candidate in session.catalog
                             if session.permits(principal, 'desktop.observe', 'app:' + candidate)
                             or session.permits(principal, 'app.launch', 'app:' + candidate))
        adapter = self.adapters[session.id]
        try:
            with self.io[session.id]:
                if method == 'app.list':
                    result = dict(applications=[adapter.call('desktop.read', ('app.info', key, {}))
                                                for key in visible])
                else:
                    result = adapter.call('desktop.read', (method, app, arguments))
        except Refused as error:
            fail(error.reason, -32006)
        except Unavailable:
            fail('target_unavailable', -32006)
        with session.lock:
            session.refresh()
            if revision != session.revision:
                fail('snapshot_required', -32004)
            if method == 'app.list':
                session.require(principal, 'session.discover', '*')
                result['applications'] = [item for item in result['applications']
                                          if session.permits(principal, 'desktop.observe', 'app:' + item['app'])
                                          or session.permits(principal, 'app.launch', 'app:' + item['app'])]
            else:
                session.require(principal, read_capability, target)
            if handle and self.clock() >= handle.expires + grace:
                fail('stale_reference', -32002)
            if method == 'element.find' and result.get('status') == 'matched':
                result['element']['ref'] = self.bind(session, connection, app, result['element']['ref'])
            if method == 'element.refresh':
                result['ref'] = self.bind(session, connection, app, result['ref'])
            for entry in result.get('windows', result.get('elements', result.get('controls', []))):
                if entry['ref'] is not None:
                    entry['ref'] = self.bind(session, connection, app, entry['ref'])
        return result

    def private_effect(self, session, connection, principal, method, params):
        pointer = method.startswith('session.pointer.')
        keyboard = method.startswith('session.keyboard.')
        args, handle = params, None
        with session.lock:
            session.require(principal, 'desktop.capture', '*')
            if pointer or keyboard:
                session.require(principal, 'desktop.input', '*')
            if not available():
                fail('private_effect_unavailable', -32006)
            if 'ref' in params:
                _, args, handle = self.target(session, connection, params, capture=True)
            revision = session.revision
        if pointer and not all(type(params[key]) is int and 0 <= params[key] < bound
                               for key, bound in zip(('x', 'y'), OUTPUT)):
            fail('pointer_outside_private_output', -32602)
        if method == 'session.keyboard.key' and params['key'] not in KEYS:
            fail('private_key_unsupported', -32602)
        if method == 'session.keyboard.type' and (not 0 < len(params['text']) <= 120
                or any(not 32 <= ord(char) <= 126 for char in params['text'])):
            fail('private_text_unsupported', -32602)
        if pointer or keyboard:
            return self.dispatch(session, connection, params, 'desktop.prepare', (method, None, args),
                                 '*', 'desktop.input', 'desktop.capture', handle)
        try:
            with self.io[session.id]:
                result = self.adapters[session.id].call('desktop.read', (method, None, args))
        except Refused as error:
            fail(error.reason, -32006)
        except Unavailable:
            fail('capture_unavailable', -32006)
        with session.lock:
            session.require(principal, 'desktop.capture', '*')
            if revision != session.revision or (handle and self.clock() >= handle.expires):
                fail('snapshot_required', -32004)
            if method == 'session.capture':
                result.update(ref=self.bind(session, connection, '@capture', result['ref'], TTL),
                              session=session.id, privateId=private_id(), epoch=session.epoch,
                              revision=revision)
        return result

    def require_events(self, session, principal):
        session.require(principal, 'session.discover', '*')

    def snapshot(self, session, connection):
        with session.lock:
            session.require(self.authenticated(connection), 'session.discover', '*')
            connection.snapshots[session.id] = session.epoch
            return dict(session=session.id, epoch=session.epoch, revision=session.revision,
                        generation=session.generation, phase=session.phase, cursor=session.history.seq,
                        capabilities=self.capabilities(session, connection.principal))

    def bind(self, session, connection, app, token, ttl=20):
        ref = secrets.token_hex(16)
        connection.handles[ref] = Handle(ref, session.id, session.epoch, session.generation,
                                         session.revision, self.clock() + ttl, (app, token))
        if len(connection.handles) > 768:
            connection.handles.popitem(last=False)
        return ref
