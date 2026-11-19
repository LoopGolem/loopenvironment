# SPDX-License-Identifier: Apache-2.0
"""Scope authorization and temporary reference translation for V0.2."""
import secrets

from .adapter import Refused, Unavailable
from .authority import Handle, fail
from .broker import Broker, SCHEMA
from .protocol import VERSION

READS = {
    'window.list': {'app'},
    'window.inspect': {'ref'},
    'element.tree': {'ref', 'offset', 'depth'},
    'element.actions': {'ref'},
    'element.get_text': {'ref'},
    'element.get_value': {'ref'},
    'workspace.list': {'offset'},
    'workspace.read': {'path'},
}
WRITES = {
    'app.launch': ({'app'}, 'app.launch'),
    'element.invoke': ({'ref', 'action'}, 'desktop.control'),
    'element.set_text': ({'ref', 'text'}, 'desktop.control'),
    'element.set_value': ({'ref', 'value'}, 'desktop.control'),
    'workspace.write': ({'path', 'text'}, 'workspace.write'),
}
LEASE = {'lease', 'epoch', 'generation'}


class DesktopBroker(Broker):
    versions = (VERSION,)
    connection_limits = (60, 300, 160)
    schema = {method: fields for method, fields in SCHEMA.items()
              if method not in ('invoke7',)}
    schema.update({method: fields | {'session'} for method, fields in READS.items()})
    schema.update({method: fields | {'session'} | LEASE
                   for method, (fields, _) in WRITES.items()})
    schema.update({'app.list': {'session'}, 'operation.status': {'session', 'operation'}})

    def target(self, session, connection, params):
        if 'ref' in params:
            handle = connection.handles.get(params['ref'])
            if (handle is None or handle.session != session.id or handle.epoch != session.epoch
                    or handle.revision != session.revision or handle.generation != session.generation
                    or self.clock() >= handle.expires):
                fail('stale_reference', -32002)
            app, token = handle.reference
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
        principal = self.authenticated(connection)
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
            app, arguments, handle = self.target(session, connection, params)
            if method.startswith('workspace.'):
                if not session.workspace:
                    fail('workspace_disabled')
                target = 'workspace'
            else:
                target = 'app:' + app if app else '*'
        if method in WRITES:
            capability = WRITES[method][1]
            observation = {'app.launch': None, 'workspace.write': 'workspace.read'}.get(
                method, 'desktop.observe')
            extra = ()
            if app == 'editor' and method == 'element.invoke' and params['action'] == 'page.save':
                extra = (('workspace.write', 'workspace'),)
            return self.dispatch(session, connection, params, 'desktop.prepare',
                                 (method, app, arguments), target, capability, observation, handle, extra)
        with session.lock:
            session.require(principal, 'session.discover' if method == 'app.list' else
                            'workspace.read' if target == 'workspace' else 'desktop.observe', target)
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
                session.require(principal, 'workspace.read' if target == 'workspace'
                                else 'desktop.observe', target)
            if handle and self.clock() >= handle.expires:
                fail('stale_reference', -32002)
            for entry in result.get('windows', result.get('elements', [])):
                if entry['ref'] is not None:
                    entry['ref'] = self.bind(session, connection, app, entry['ref'])
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

    def bind(self, session, connection, app, token):
        ref = secrets.token_hex(16)
        connection.handles[ref] = Handle(ref, session.id, session.epoch, session.generation,
                                         session.revision, self.clock() + 20, (app, token))
        if len(connection.handles) > 768:
            connection.handles.popitem(last=False)
        return ref
