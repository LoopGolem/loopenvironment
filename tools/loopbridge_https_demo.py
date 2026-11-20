# SPDX-License-Identifier: Apache-2.0
"""Check authorized, read-only HTTPS navigation through a real private Firefox."""
import argparse
from contextlib import ExitStack
import json
import re
from pathlib import Path
import shutil
import sys
import tempfile
import time
from urllib.parse import urlsplit

from loopbridge.__main__ import provision, read_private
from loopbridge.observation import observe
from loopbridge.protocol import Fault
from loopbridge.service import DESKTOP_SESSION, Journal

from .loopbridge_demo import Process
from .loopbridge_desktop_demo import grant
from .loopbridge_live_demo import LiveView
from .loopbridge_private_demo import connect_rpc
from .mcp_mission import Client, SESSION, require, window


def run(root, hosts, urls, evidence, inspect=None, submit=False, live=False, hold=0):
    with ExitStack() as stack:
        credentials = root / 'credentials'
        provision(credentials)

        def token(principal):
            return read_private(credentials / (principal + '.token')).strip()

        manager = Process(stack, [sys.executable, '-B', '-m', 'loopbridge', 'private', '--root',
                                  root / 'private', '--credentials', credentials / 'service.json'])
        require(manager.line() == b'ready\n', 'manager_not_ready')

        def admin(method, **params):
            with ExitStack() as connection:
                return connect_rpc(connection, root / 'private/manager.sock', token('owner')).call(method, **params)
        private = admin('private.start', httpsHosts=hosts)
        offline = admin('private.start')
        require(admin('private.network', id=offline['id'])['mode'] == 'offline', 'offline_default_changed')
        evidence.update(namespaces=private['namespaces'], siblingOffline=True)
        try:
            owner = connect_rpc(stack, private['socket'], token('owner'))
            viewer = None
            observation_expiry = 0

            def grant_observation():
                nonlocal observation_expiry
                with ExitStack() as scope:
                    issuer = connect_rpc(scope, private['socket'], token('owner'))
                    if live:
                        grant(issuer, 'observer', 'desktop.capture')
                    if submit:
                        grant(issuer, 'observer', 'desktop.observe', 'app:browser')
                observation_expiry = time.monotonic() + 120

            if live or submit:
                grant_observation()
            if live:
                viewer = LiveView(stack, private, credentials)
                evidence['viewer'] = [dict(stage='before_firefox', **viewer.sample())]
                time.sleep(3)

            def visual(stage):
                if viewer:
                    try:
                        evidence['viewer'].append(dict(stage=stage, **viewer.sample(after=time.monotonic(),
                                                                                     timeout=4)))
                    except RuntimeError:
                        evidence['viewer'].append(dict(stage=stage, frameUnavailable=True))

            def browser_read():
                if time.monotonic() >= observation_expiry:
                    grant_observation()
                with ExitStack() as scope:
                    peer = connect_rpc(scope, private['socket'], token('observer'))
                    items = peer.call('window.list', **SESSION, app='browser')['windows']
                    refs = [row['ref'] for row in items if row['ref']]
                    if len(refs) != 1:
                        return {}
                    return peer.call('web.discover', **SESSION, ref=refs[0])

            grant(owner, 'delegate', 'session.discover')
            for capability in ('app.launch', 'desktop.observe', 'desktop.control'):
                grant(owner, 'delegate', capability, 'app:browser')
            if submit:
                grant(owner, 'delegate', 'web.submit', 'app:browser')
            command = [sys.executable, '-B', '-m', 'tools.loopbridge_mcp_sandbox',
                       '--socket', private['socket'], '--token-file', credentials / 'delegate.token']
            with Client(command, modern=True) as client:
                permit = client.call('lease_acquire', **SESSION, ttl=175)
                lease = dict(**SESSION, lease=permit['id'], epoch=permit['epoch'], generation=permit['generation'])
                client.call('web_open_external', **lease, app='browser')
                visual('web_open_external')
                denied = client.refused('web_navigate_https', **lease, ref=window(client, 'browser'),
                                        url='https://127.0.0.1/')
                require(denied == 'web_destination_denied', 'private_address_was_not_denied')
                evidence['loopbackDenied'] = True
                for url in urls:
                    before = time.monotonic()
                    attempt = dict(requestedHost=urlsplit(url).hostname)
                    evidence['attempts'].append(attempt)
                    response, failed = client.invoke('web_navigate_https', **lease, ref=window(client, 'browser'), url=url)
                    attempt.update(status=response['status'], elapsedSeconds=round(time.monotonic() - before, 3))
                    if failed:
                        attempt['reason'] = response.get('reason', 'effect_unconfirmed')
                        break
                    data = client.call('web_discover', **SESSION, ref=window(client, 'browser'))
                    require(data['page'] == 'https' and data['url'].startswith('https://'), 'https_dom_unverified')
                    attempt.update(document=data['url'], title=data['title'], source=data['source'],
                                   controls=[{key: item[key] for key in ('role', 'name', 'kind', 'options')
                                              if key in item} for item in data['controls']])
                    visual('web_navigate_https')
                    if inspect and url == urls[-1]:
                        inspect(client, lease, data, attempt, visual, browser_read)
                evidence['result'] = 'GO' if all(row['status'] == 'confirmed' for row in evidence['attempts']) else 'PARTIAL'
                if viewer and hold:
                    time.sleep(hold)
                    visual('end_of_hold')
        finally:
            evidence['network'] = admin('private.network', id=private['id'])
            evidence['shutdown'] = admin('private.stop', id=private['id'])['phase']
            admin('private.stop', id=offline['id'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', action='append', required=True)
    parser.add_argument('--url', action='append', required=True)
    parser.add_argument('--set', nargs=2, metavar=('NAME', 'VALUE'), action='append', default=[])
    parser.add_argument('--activate', metavar='NAME', action='append', default=[])
    parser.add_argument('--test-contact-stdin', action='store_true')
    parser.add_argument('--submit-once', metavar='BUTTON_NAME')
    parser.add_argument('--with-viewer', action='store_true')
    parser.add_argument('--hold', type=int, default=0, help='seconds to keep final browser state visible')
    parser.add_argument('--observe-seconds', type=int, default=330, help='read-only post-submit observation budget')
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.hold <= 120 or not 120 <= args.observe_seconds <= 420:
        parser.error('hold must be 0–120 seconds and observation must be 120–420 seconds')
    root = Path(tempfile.mkdtemp(prefix='lb6-https-'))
    evidence = dict(result='PARTIAL', attempts=[])
    start = time.monotonic()
    contact = sys.stdin.readline(129).strip() if args.test_contact_stdin else ''
    if args.test_contact_stdin and not re.fullmatch(r'[^@\s]{1,64}@[^@\s]{1,63}', contact):
        parser.error('authorized contact missing or invalid')
    if args.submit_once and not contact:
        parser.error('submission requires an explicitly supplied test contact')

    def inspect(client, lease, data, attempt, visual, browser_read):
        if not args.set and not args.activate and not contact:
            return
        actions = attempt['interactions'] = []
        for operation, name, value in [('set', *row) for row in args.set] + [
                ('activate', name, '') for name in args.activate]:
            rows = [item for item in data['controls'] if item['name'] == name]
            require(len(rows) == 1, 'web_target_missing_or_ambiguous')
            row = rows[0]
            if operation == 'set':
                require(row['kind'] not in ('email', 'tel'), 'contact_data_requires_separate_authorization')
                response = client.call('web_set_text', **lease, ref=row['ref'], text=value)
            else:
                require(row['kind'] in ('control', 'toggle'), 'submission_requires_operator_authorization')
                response = client.call('web_activate', **lease, ref=row['ref'])
            actions.append(dict(name=name, operation=operation, result=response['status']))
            data = client.call('web_discover', **SESSION, ref=window(client, 'browser'))
            visual('web_set_text' if operation == 'set' else 'web_activate')
        if contact:
            email = [row for row in data['controls'] if row.get('kind') == 'email']
            require(len(email) == 1, 'test_contact_field_ambiguous')
            client.call('web_set_text', **lease, ref=email[0]['ref'], text=contact)
            data = client.call('web_discover', **SESSION, ref=window(client, 'browser'))
            email = [row for row in data['controls'] if row.get('kind') == 'email']
            require(len(email) == 1 and email[0]['value'] == contact, 'test_contact_readback_failed')
            attempt['authorizedTestContactVerified'] = True
            visual('test_contact_readback')
        attempt['after'] = [{key: item[key] for key in ('role', 'name', 'kind', 'state', 'options',
                                                       'required', 'valid', 'filled')}
                            for item in data['controls'] if item['kind'] not in ('link', 'email')]
        attempt['readyToSubmit'] = any(row['kind'] == 'submit' for row in data['controls']) and all(
            row['valid'] for row in data['controls'] if row['required'])
        visual('form_readback')
        if args.submit_once:
            buttons = [row for row in data['controls'] if row['kind'] == 'submit'
                       and ' '.join(row['name'].split()) == args.submit_once]
            require(len(buttons) == 1, 'submit_button_ambiguous')
            require(all(row['valid'] for row in data['controls'] if row['required']),
                    'required_fields_invalid')
            visual('before_submit')
            attempt['submission'] = dict(operatorAuthorized=True, attempts=1)
            reply, failed = client.invoke('web_submit_https', **lease, ref=buttons[0]['ref'])
            attempt['submission'].update(bridgeStatus=reply['status'],
                                         reason=reply.get('reason', ''))
            if failed and reply['status'] == 'refused':
                attempt['submission']['dispatches'] = 0
                return
            attempt['submission']['dispatches'] = 'unconfirmed' if failed else 1

            def read():
                try:
                    return browser_read()
                except (Fault, EOFError, OSError):
                    return {}

            attempt['submission']['observation'] = observe(read, timeout=args.observe_seconds, interval=2,
                on_change=lambda event: visual('observe_' + event['state']))
    try:
        run(root, args.host, args.url, evidence, inspect=inspect, submit=bool(args.submit_once),
            live=args.with_viewer, hold=args.hold)
    except (OSError, RuntimeError, EOFError, KeyError, ValueError, Fault) as error:
        evidence['failure'] = str(error) if type(error) is RuntimeError else type(error).__name__
    finally:
        if any(Journal(path).blocked(DESKTOP_SESSION) for path in root.glob('private/*/runtime')):
            shutil.rmtree(root / 'credentials', ignore_errors=True)
            evidence['blockedRootPreserved'] = True
        else:
            shutil.rmtree(root)
    evidence['elapsedSeconds'] = round(time.monotonic() - start, 3)
    with args.evidence.open('x') as output:
        print(json.dumps(evidence, indent=2, ensure_ascii=False), file=output)
    print(evidence['result'])
    return int(evidence['result'] != 'GO')


if __name__ == '__main__':
    raise SystemExit(main())
