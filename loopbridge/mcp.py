# SPDX-License-Identifier: Apache-2.0
"""Local MCP stdio adapter. Every operation passes through one Bridge connection."""
import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import socket
import sys

from .__main__ import read_private
from .protocol import Fault, RPC, unique_object

MCP_VERSION = '2025-11-25'
SUPPORTED = (MCP_VERSION, '2025-06-18')
MAX_MESSAGE = 65536
SESSION_URI = 'loopbridge://session/'
LEASE = 'lease epoch generation:i'


@dataclass(frozen=True)
class Tool:
    method: str
    description: str
    fields: str = ''
    mutation: bool = False

    def schema(self):
        props = {}
        for entry in self.fields.split():
            name, _, kind = entry.partition(':')
            props[name] = {'type': 'integer' if kind == 'i' else 'string'}
        return dict(type='object', properties=props, required=list(props), additionalProperties=False)

    def valid(self, args):
        props = self.schema()['properties']
        return (type(args) is dict and set(args) == set(props) and
                all(type(args[key]) is (int if value['type'] == 'integer' else str)
                    for key, value in props.items()))


def write(method, description, extra):
    return Tool(method, description, f'session {LEASE} {extra}', True)


TOOLS = {
    'sessions_list': Tool('discover', 'List authorized sessions.'),
    'session_features': Tool('session.features', 'Inspect backend availability and limits.', 'session'),
    'session_recovery_status': Tool('session.recovery', 'Read recovery eligibility as an authorized administrator.',
                                    'session'),
    'session_snapshot': Tool('snapshot', 'Read phase, epoch and available capabilities.', 'session'),
    'apps_list': Tool('app.list', 'List visible supervised application profiles.', 'session'),
    'windows_list': Tool('window.list', 'List identified windows and fresh window references.', 'session app'),
    'lease_acquire': Tool('acquire', 'Acquire a bounded session lease in seconds.', 'session ttl:i', True),
    'lease_release': write('release', 'Release this connection’s lease.', ''),
    'web_open': write('web.open', 'Start a fresh private Firefox instance for the packaged local site.', 'app'),
    'web_navigate': write('web.navigate', 'Navigate to a named authorized local page.', 'ref page'),
    'web_discover': Tool('web.discover', 'Read local page identity, observable controls and table rows.', 'session ref'),
    'web_set_text': write('web.set_text', 'Replace text in a live authorized web field.', 'ref text'),
    'web_select': write('web.select', 'Select an advertised option value.', 'ref option'),
    'web_activate': write('web.activate', 'Activate an observed local form submit button or link.', 'ref'),
    'workspace_list': Tool('workspace.list_at', 'List an authorized workspace directory. Use an empty directory for the root.',
                           'session directory offset:i'),
    'workspace_read': Tool('workspace.read', 'Read an authorized workspace UTF-8 file.', 'session path'),
    'workspace_write': write('workspace.write', 'Write an authorized workspace UTF-8 file.', 'path text'),
    'element_tree': Tool('element.tree', 'Read one page of scoped AT-SPI elements.', 'session ref offset:i depth:i'),
    'element_search': Tool('element.search', 'Search the scoped tree by native role, name or action.',
                           'session ref query offset:i'),
    'element_find': Tool('element.find', 'Find a unique AT-SPI target. Empty filters impose no constraint.',
                         'session ref role name interface action'),
    'element_get_text': Tool('element.get_text', 'Read text from a live scoped AT-SPI element.', 'session ref'),
    'app_open_document': write('app.open_document', 'Open an authorized workspace document in the supervised editor.',
                               'app document'),
    'app_close': write('app.close', 'Stop an application supervised by this service.', 'app'),
    'element_set_text': write('element.set_text', 'Edit a live scoped AT-SPI text element.', 'ref text'),
    'element_invoke': write('element.invoke', 'Invoke an effect verified by application policy.', 'ref action'),
    'teach_search': Tool('teach.search', 'Find saved notes by meaning. Revision zero selects any current revision.',
                         'session app query revision:i offset:i'),
    'teach_resolve': Tool('teach.resolve', 'Resolve one annotation to a fresh scoped target.', 'session ref annotation'),
    'operation_status': Tool('operation.status', 'Read the known status of this principal’s operation.', 'session operation'),
}


class RpcError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


class Server:
    def __init__(self, bridge):
        self.bridge = bridge
        self.initialized = False
        self.ready = False
        self.disconnected = False

    def call_tool(self, params):
        name = params.get('name')
        tool = TOOLS.get(name) if isinstance(name, str) else None
        if tool is None:
            raise RpcError(-32602, 'unknown_tool')
        arguments = params.get('arguments', {})
        if not tool.valid(arguments):
            raise RpcError(-32602, 'invalid_tool_arguments')
        try:
            if self.disconnected:
                result = dict(status='unavailable', reason='bridge_connection_closed')
            else:
                result = self.bridge.call(tool.method, **arguments)
        except Fault as error:
            result = dict(status='refused', reason=error.message, bridgeCode=error.code)
        except (OSError, EOFError, AssertionError, ValueError):
            self.disconnected = True
            result = dict(status='unknown' if tool.mutation else 'unavailable',
                          reason='bridge_response_missing')
        return dict(structuredContent=result, content=[dict(type='text', text=json.dumps(result))],
                    isError=result.get('status') in ('refused', 'unknown', 'unavailable'))

    def request(self, method, params):
        if method == 'ping':
            return {}
        if method == 'initialize':
            if (self.initialized or type(params.get('protocolVersion')) is not str
                    or type(params.get('capabilities')) is not dict
                    or type(params.get('clientInfo')) is not dict):
                raise RpcError(-32602, 'invalid_initialization')
            self.initialized = True
            requested = params['protocolVersion']
            return dict(protocolVersion=requested if requested in SUPPORTED else MCP_VERSION,
                        serverInfo=dict(name='LoopBridge', version='0.5'),
                        capabilities=dict(tools={}, resources={}))
        if not self.ready:
            raise RpcError(-32002, 'not_initialized')
        if method == 'tools/list':
            if params.get('cursor') is not None:
                raise RpcError(-32602, 'invalid_cursor')
            return dict(tools=[dict(name=name, description=tool.description, inputSchema=tool.schema(),
                                    outputSchema={'type': 'object'})
                               for name, tool in TOOLS.items()])
        if method == 'tools/call':
            return self.call_tool(params)
        if method == 'resources/list':
            if params.get('cursor') is not None:
                raise RpcError(-32602, 'invalid_cursor')
            sessions = self.bridge.call('discover')['sessions']
            return dict(resources=[dict(uri=SESSION_URI + key, name=key, mimeType='application/json')
                                   for key in sessions])
        if method == 'resources/templates/list':
            return dict(resourceTemplates=[])
        if method == 'resources/read':
            uri = params.get('uri')
            if not isinstance(uri, str) or not re.fullmatch(r'loopbridge://session/[a-z0-9_-]{1,48}', uri):
                raise RpcError(-32602, 'unknown_resource')
            session = uri.removeprefix(SESSION_URI)
            if session not in self.bridge.call('discover')['sessions']:
                raise RpcError(-32002, 'resource_unavailable')
            snapshot = self.bridge.call('snapshot', session=session)
            return dict(contents=[dict(uri=uri, mimeType='application/json', text=json.dumps(snapshot))])
        raise RpcError(-32601, 'method_not_found')

    def message(self, raw):
        response = dict(jsonrpc='2.0', id=None)
        try:
            try:
                def reject_non_json(_):
                    raise ValueError('invalid_json_constant')
                document = raw.decode('utf-8') if isinstance(raw, bytes) else raw
                msg = json.loads(document, object_pairs_hook=unique_object, parse_constant=reject_non_json)
            except (ValueError, RecursionError):
                raise RpcError(-32700, 'parse_error') from None
            if (type(msg) is not dict or msg.get('jsonrpc') != '2.0'
                    or type(msg.get('method')) is not str or type(msg.get('params', {})) is not dict
                    or ('id' in msg and type(msg['id']) not in (int, str))):
                raise RpcError(-32600, 'invalid_request')
            if 'id' not in msg:
                if msg['method'] == 'notifications/initialized' and self.initialized:
                    self.ready = True
                return None
            response['id'] = msg['id']
            response['result'] = self.request(msg['method'], msg.get('params', {}))
        except RpcError as error:
            response['error'] = dict(code=error.code, message=error.message)
        except Fault:
            response['error'] = dict(code=-32002, message='resource_unavailable')
        except (OSError, EOFError, AssertionError, ValueError):
            self.disconnected = True
            response['error'] = dict(code=-32002, message='bridge_unavailable')
        return response

    def serve(self, incoming, outgoing):
        while line := incoming.readline(MAX_MESSAGE + 1):
            if len(line) > MAX_MESSAGE or not line.endswith(b'\n'):
                return
            response = self.message(line)
            if response is not None:
                outgoing.write(json.dumps(response, allow_nan=False).encode() + b'\n')
                outgoing.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    args = parser.parse_args()
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(20)
            sock.connect(args.socket)
            bridge = RPC(sock)
            bridge.call('auth', credential=read_private(args.token_file).rstrip('\n'))
            Server(bridge).serve(sys.stdin.buffer, sys.stdout.buffer)
    except (OSError, EOFError, Fault, ValueError):
        print('LoopBridge MCP connection unavailable', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
