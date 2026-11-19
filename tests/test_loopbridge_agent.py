# SPDX-License-Identifier: Apache-2.0
import io
import json
import unittest

from loopbridge.mcp import MCP_VERSION, Server, TOOLS
from loopbridge.protocol import Fault
from loopbridge.web_native import WebError, exact_fields, member, page_of, plan


class Bridge:
    def __init__(self):
        self.calls = []
        self.outcome = None

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == 'discover':
            return dict(sessions=['desktop'])
        if method == 'snapshot':
            return dict(session=params['session'], phase='idle')
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome or dict(status='confirmed')


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.bridge = Bridge()
        self.server = Server(self.bridge)
        self.sequence = 0

    def request(self, method, **params):
        self.sequence += 1
        return self.server.message(json.dumps(dict(jsonrpc='2.0', id=self.sequence,
                                                  method=method, params=params)))

    def initialize(self, version=MCP_VERSION):
        initialized = self.request('initialize', protocolVersion=version, capabilities={},
                                   clientInfo=dict(name='test', version='1'))
        notice = self.server.message('{"jsonrpc":"2.0","method":"notifications/initialized"}')
        self.assertIsNone(notice)
        return initialized['result']

    def test_lifecycle_schema_and_resources_obey_bridge_authority(self):
        self.assertEqual(self.request('tools/list')['error']['code'], -32002)
        self.assertEqual(self.initialize('2025-06-18')['protocolVersion'], '2025-06-18')
        tools = self.request('tools/list')['result']['tools']
        self.assertEqual({row['name'] for row in tools}, set(TOOLS))
        self.assertTrue(all(row['inputSchema']['additionalProperties'] is False for row in tools))
        result = self.request('resources/list')['result']['resources']
        uri = result[0]['uri']
        snapshot = self.request('resources/read', uri=uri)['result']['contents'][0]
        self.assertEqual(json.loads(snapshot['text'])['session'], 'desktop')
        self.assertEqual(self.request('resources/read', uri='file:///etc/passwd')['error']['code'], -32602)
        self.assertNotIn('delegate', TOOLS)
        denied = self.request('tools/call', name='lease_acquire', arguments=dict(session='desktop', ttl=True))
        self.assertEqual(denied['error']['code'], -32602)
        self.assertEqual(self.bridge.calls[-1][0], 'snapshot')

    def test_forwards_refusal_and_unknown_without_retry_or_reauthorization(self):
        self.initialize()
        params = dict(session='desktop', lease='lease', epoch='epoch', generation=1, ref='live')
        self.bridge.outcome = Fault(-32001, 'grant_denied')
        result = self.request('tools/call', name='web_activate', arguments=params)['result']
        self.assertTrue(result['isError'])
        self.assertEqual(result['structuredContent']['reason'], 'grant_denied')
        self.bridge.outcome = dict(status='unknown', operation='operation-1')
        result = self.request('tools/call', name='web_activate', arguments=params)['result']
        self.assertTrue(result['isError'])
        self.assertEqual(result['structuredContent']['operation'], 'operation-1')
        self.bridge.outcome = EOFError()
        result = self.request('tools/call', name='web_activate', arguments=params)['result']
        self.assertEqual(result['structuredContent']['status'], 'unknown')
        result = self.request('tools/call', name='web_activate', arguments=params)['result']
        self.assertEqual(result['structuredContent']['status'], 'unavailable')
        self.assertEqual(self.bridge.calls, [('web.activate', params)] * 3)

    def test_stdio_lines_do_not_respond_to_notifications(self):
        incoming = io.BytesIO(
            b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
            b'{"jsonrpc":"2.0","method":"notifications/cancelled"}\n'
            b'not-json\n')
        outgoing = io.BytesIO()
        self.server.serve(incoming, outgoing)
        messages = [json.loads(row) for row in outgoing.getvalue().splitlines()]
        self.assertEqual(messages[0]['result'], {})
        self.assertEqual(messages[1]['error']['code'], -32700)
        self.assertEqual(len(messages), 2)
        utf16 = '{"jsonrpc":"2.0","id":1,"method":"ping"}'.encode('utf-16')
        self.assertEqual(self.server.message(utf16)['error']['code'], -32700)


class WebPolicyTests(unittest.TestCase):
    url = 'file:///fixture/site/search.html'

    def setUp(self):
        self.proof = dict(document='new', url=self.url, key='opaque', role='textbox', name='Description')
        self.state = dict(document='new', url=self.url,
                          controls=[dict(key='opaque', role='textbox', name='Description', value='')])

    def test_allowlist_and_verified_get_fields(self):
        self.assertEqual(page_of('file:///fixture/site/results.html?query=Harbor'), 'results')
        for url in ('https://example.invalid/', 'file:///etc/passwd', self.url + '#fragment',
                    'file:///fixture/site/../site/search.html', 'file://host/fixture/site/search.html'):
            with self.assertRaises(WebError):
                page_of(url)
        self.assertTrue(exact_fields(self.url + '?empty=&note=Two+words', [('note', 'Two words'), ('empty', '')]))
        self.assertFalse(exact_fields(self.url + '?note=x&note=y', [('note', 'x')]))

    def test_refuses_changed_document_and_same_id_changed_role(self):
        result = plan(self.state, dict(operation='text', value='Harbor', **self.proof))
        self.assertEqual(result['key'], 'opaque')
        with self.assertRaisesRegex(WebError, 'stale_web_document'):
            member({**self.state, 'document': 'different'}, self.proof)
        self.state['controls'][0]['role'] = 'button'
        with self.assertRaisesRegex(WebError, 'stale_web_control'):
            member(self.state, self.proof)
        with self.assertRaises(WebError):
            plan(self.state, dict(operation='navigate', page='file:///etc/passwd',
                                  document='new', url=self.url))


class ReplacementBoundaryTests(unittest.TestCase):
    def test_separate_runtime_epochs_do_not_reuse_blocked_lease_ref_or_workspace(self):
        from pathlib import Path
        import os
        import tempfile

        from loopbridge.broker import Connection
        from loopbridge.desktop_broker import DesktopBroker
        from loopbridge.identity import Identities
        from loopbridge.service import Journal
        from loopbridge.workspace import Workspace

        identities = Identities()
        credentials = identities.provision()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old, new = root / 'old', root / 'new'
            old.mkdir(mode=0o700)
            new.mkdir(mode=0o700)
            journals = [Journal(path) for path in (old, new)]

            def boot(journal):
                instance = DesktopBroker(identities, {'desktop': object()}, os.getuid(),
                                         journal, catalog=('editor',), workspace=True)
                client = Connection(os.getuid())
                instance.handle(client, 'auth', dict(credential=credentials['owner']))

                def call(method, **params):
                    return instance.handle(client, method, dict(session='desktop', **params))

                return instance, client, call

            broker, prior, call = boot(journals[0])
            lease = call('acquire', ttl=30)
            ref = broker.bind(broker.sessions['desktop'], prior, 'editor', 'old-backend-reference')
            journals[0].mark('desktop', 'a' * 32)
            _, _, blocked = boot(journals[0])
            recovery = blocked('session.recovery')
            self.assertEqual(recovery['phase'], 'blocked')
            self.assertEqual(recovery['unknownOperation'], 'a' * 32)
            self.assertFalse(recovery['cancellationAssumed'])
            self.assertEqual(recovery['policy'], 'automatic_replacement_disabled')
            with self.assertRaisesRegex(Fault, 'control_busy'):
                blocked('acquire', ttl=30)

            _, _, fresh = boot(journals[1])
            new_lease = fresh('acquire', ttl=30)
            self.assertNotEqual(new_lease['epoch'], lease['epoch'])
            with self.assertRaisesRegex(Fault, 'stale_lease'):
                fresh('release', lease=lease['id'], epoch=lease['epoch'], generation=lease['generation'])
            with self.assertRaisesRegex(Fault, 'stale_reference'):
                fresh('element.refresh', ref=ref)
            # A synthetic late write in the old workspace remains attributable to the old root.
            original_fs, replacement_fs = Workspace(old), Workspace(new)
            try:
                original_fs.write('late.txt', 'Old effect')
                self.assertTrue(journals[0].blocked('desktop'))
                self.assertFalse(journals[1].blocked('desktop'))
                self.assertEqual(replacement_fs.listing(0)['entries'], [])
            finally:
                original_fs.close()
                replacement_fs.close()
