# SPDX-License-Identifier: Apache-2.0
"""Independent JSON-RPC MCP client. Uses only stdlib and public tool schemas."""
import argparse
import hashlib
import json
import subprocess
import time
from urllib.parse import parse_qs, urlsplit

VERSION = '2025-11-25'
SESSION = {'session': 'desktop'}


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


class Client:
    def __init__(self, argv, modern=False):
        self.modern = modern
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, close_fds=True)
        self.sequence = 0

    def __enter__(self):
        try:
            if self.modern:
                response = self.request('server/discover')
                require('2026-07-28' in response['supportedVersions'], 'unexpected_protocol')
            else:
                response = self.request('initialize', protocolVersion=VERSION, capabilities={},
                                        clientInfo=dict(name='independent-mission', version='1'))
                require(response['protocolVersion'] == VERSION, 'unexpected_protocol')
                self.write(dict(jsonrpc='2.0', method='notifications/initialized'))
            capabilities = response['capabilities']
            require('tools' in capabilities and 'resources' in capabilities, 'mcp_capabilities_missing')
            self.tools = {item['name']: item['inputSchema'] for item in self.request('tools/list')['tools']}
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdout.close()

    def write(self, message):
        self.process.stdin.write(json.dumps(message).encode() + b'\n')
        self.process.stdin.flush()

    def request(self, method, **params):
        self.sequence += 1
        if self.modern:
            params['_meta'] = {'io.modelcontextprotocol/protocolVersion': '2026-07-28',
                               'io.modelcontextprotocol/clientInfo': dict(name='independent-mission', version='1')}
        self.write(dict(jsonrpc='2.0', id=self.sequence, method=method, params=params))
        data = self.process.stdout.readline(65537)
        require(data.endswith(b'\n') and len(data) <= 65536, 'mcp_transport_closed')
        response = json.loads(data)
        require(response.get('id') == self.sequence and response.get('jsonrpc') == '2.0'
                and 'result' in response, 'unexpected_mcp_response')
        return response['result']

    def invoke(self, method, **args):
        require(method in self.tools and set(args) == set(self.tools[method]['required']), 'tool_schema_mismatch')
        result = self.request('tools/call', name=method, arguments=args)
        return result['structuredContent'], result['isError']

    def call(self, method, **args):
        result, failed = self.invoke(method, **args)
        require(not failed, result.get('reason', result.get('status', 'tool_failed')))
        return result

    def refused(self, method, **args):
        reply = self.request('tools/call', name=method, arguments=args)
        result, failed = reply['structuredContent'], reply['isError']
        require(failed and result.get('status') == 'refused', 'expected_tool_refusal')
        return result['reason']


def choose(rows, role, name):
    found = [row for row in rows if (row['role'], row['name']) == (role, name)]
    require(len(found) == 1, 'control_missing_or_ambiguous')
    return found[0]


def window(client, app):
    matches = [item['ref'] for item in client.call('windows_list', **SESSION, app=app)['windows'] if item['ref']]
    require(len(matches) == 1, 'window_missing_or_ambiguous')
    return matches[0]


def document(client):
    return client.call('web_discover', **SESSION, ref=window(client, 'browser'))


def mission(client, evidence):
    durations = evidence['secondsByStage'] = {}
    stage_start = time.monotonic()
    evidence['stage'] = 'resources'
    resources = client.request('resources/list')['resources']
    require(len(resources) == 1 and resources[0]['name'] == SESSION['session'], 'session_not_discovered')
    snapshot = json.loads(client.request('resources/read', uri=resources[0]['uri'])['contents'][0]['text'])
    require(snapshot['session'] == SESSION['session'], 'wrong_session')
    features = client.call('session_features', **SESSION)
    require('firefox_dom' in features['sources'], 'web_backend_unavailable')
    catalog = client.call('apps_list', **SESSION)['applications']
    require(any(row['app'] == 'browser' and row['web_site'] for row in catalog), 'web_backend_unavailable')
    permit = client.call('lease_acquire', **SESSION, ttl=175)
    lease = dict(**SESSION, lease=permit['id'], epoch=permit['epoch'], generation=permit['generation'])

    durations['resources'] = round(time.monotonic() - stage_start, 3)
    stage_start = time.monotonic()
    evidence['stage'] = 'browser'
    opened = client.call('web_open', **lease, app='browser')
    require(opened['status'] == 'confirmed', 'browser_not_confirmed')
    home = document(client)
    link = choose(home['controls'], 'link', 'Search records')
    evidence['outside_destination'] = client.refused('web_navigate', **lease,
        ref=window(client, 'browser'), page='https://example.invalid/')
    client.call('web_activate', **lease, ref=link['ref'])
    search = document(client)
    require(search['page'] == 'search', 'unexpected_page')
    require(not any(row['name'] == 'Private example' for row in search['controls']), 'protected_control_exposed')
    entry = choose(search['controls'], 'textbox', 'Record description')
    client.call('web_set_text', **lease, ref=entry['ref'], text='Harbor')
    evidence['stale_reference'] = client.refused('web_set_text', **lease, ref=entry['ref'], text='Other')
    field = choose(document(client)['controls'], 'combobox', 'Region')
    north = [item['value'] for item in field['options'] if item['label'] == 'North']
    require(len(north) == 1, 'region_missing')
    client.call('web_select', **lease, ref=field['ref'], option=north[0])
    action = choose(document(client)['controls'], 'button', 'Run search')
    result = client.call('web_activate', **lease, ref=action['ref'])
    require(client.call('operation_status', **SESSION, operation=result['operation'])['status'] == 'confirmed',
            'operation_not_confirmed')
    data = document(client)
    require(data['page'] == 'results' and not data['truncated'], 'results_unavailable')
    tables = [table for table in data['tables'] if table['name'] == 'Search results']
    require(len(tables) == 1 and not tables[0]['truncated'], 'results_table_unavailable')
    rows = tables[0]['rows']
    require(len(rows) == 2 and all(row[2] == 'north' for row in rows), 'unexpected_results')
    report = 'Harbor records in North\n' + '\n'.join(' | '.join(row) for row in rows) + '\n'
    evidence['browser'] = dict(rows=rows, source=data['source'], protected_control_hidden=True)

    durations['browser'] = round(time.monotonic() - stage_start, 3)
    stage_start = time.monotonic()
    evidence['stage'] = 'report'
    evidence['outside_workspace'] = client.refused('workspace_write', **lease, path='../outside.txt', text='DENIED')
    path = 'harbor-report.txt'
    client.call('workspace_write', **lease, path=path, text='')
    client.call('app_open_document', **lease, app='editor', document=path)
    ref, offset, matches = window(client, 'editor'), 0, []
    while offset is not None:
        page = client.call('element_tree', **SESSION, ref=ref, offset=offset, depth=40)
        matches.extend(row for row in page['elements'] if row['editable'] and 'multi_line' in row['state'])
        offset = page['next']
    require(len(matches) == 1, 'editor_field_ambiguous')
    client.call('element_set_text', **lease, ref=matches[0]['ref'], text=report.removesuffix('\n'))
    notes = client.call('teach_search', **SESSION, app='editor', query='document.save', revision=0, offset=0)
    require(len(notes['annotations']) == 1, 'save_annotation_unavailable')
    resolved = client.call('teach_resolve', **SESSION, ref=window(client, 'editor'),
                           annotation=notes['annotations'][0]['id'])
    require(resolved['status'] == 'matched', 'save_annotation_unresolved')
    action = resolved['annotation']['annotation']['operationHint']
    result = client.call('element_invoke', **lease, ref=resolved['element']['ref'], action=action)
    require(result['status'] == 'confirmed', 'save_unconfirmed')
    require(client.call('workspace_read', **SESSION, path=path)['text'] == report, 'report_readback_mismatch')
    evidence['report'] = dict(path=path, sha256=hashlib.sha256(report.encode()).hexdigest(),
                              annotation_match=resolved['matchQuality'], verified=True)
    durations['report'] = round(time.monotonic() - stage_start, 3)
    stage_start = time.monotonic()
    evidence['stage'] = 'web_confirmation'
    client.call('web_navigate', **lease, ref=window(client, 'browser'), page='review')
    review = document(client)
    ref = choose(review['controls'], 'textbox', 'Report reference')['ref']
    client.call('web_set_text', **lease, ref=ref, text=path)
    confirm = choose(document(client)['controls'], 'button', 'Confirm report')
    client.call('web_activate', **lease, ref=confirm['ref'])
    receipt = document(client)
    require(receipt['page'] == 'confirmation' and
            parse_qs(urlsplit(receipt['url']).query) == {'report': [path]}, 'receipt_unverified')
    evidence['browser']['report_confirmation'] = 'confirmed'
    client.call('lease_release', **lease)
    durations['web_confirmation'] = round(time.monotonic() - stage_start, 3)


def observer(client, evidence):
    evidence.update(stage='observer',
                    lease_denied=client.refused('lease_acquire', **SESSION, ttl=15),
                    workspace_denied=client.refused('workspace_read', **SESSION, path='harbor-report.txt'))
    require(evidence['lease_denied'] == evidence['workspace_denied'] == 'grant_denied', 'observer_escaped_scope')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modern', action='store_true')
    parser.add_argument('--observer', action='store_true')
    parser.add_argument('adapter', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.adapter[1:] if args.adapter and args.adapter[0] == '--' else args.adapter
    if not argv:
        parser.error('missing adapter command')
    start = time.monotonic()
    evidence = dict(result='PARTIAL', stage='mcp_start')
    try:
        with Client(argv, modern=args.modern) as client:
            (observer if args.observer else mission)(client, evidence)
            evidence.update(result='GO', stage='completed')
    except (OSError, EOFError, ValueError, RuntimeError, KeyError, TypeError) as error:
        evidence['failure'] = str(error) if type(error) is RuntimeError else type(error).__name__
    evidence['elapsed_seconds'] = round(time.monotonic() - start, 3)
    print(json.dumps(evidence), flush=True)
    return 0 if evidence['result'] == 'GO' else 1


if __name__ == '__main__':
    raise SystemExit(main())
