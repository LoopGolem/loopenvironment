# SPDX-License-Identifier: Apache-2.0
"""Translate Bridge references into private browser proofs and read back effects."""
from dataclasses import dataclass
import json
from urllib.parse import parse_qsl, urlsplit

from .adapter import Refused
from .browser_native import NativeError, site_call
from .linux_desktop import wait_for
from .semantic_operations import Prepared
from .web_native import exact_fields, member, WebError
from .web_https import allowed, public_url


@dataclass
class WebTarget:
    window_ref: str
    proof: dict


class Web:
    def __init__(self, desktop):
        self.desktop = desktop
        self.external_submission_started = False

    def window(self, app, ref):
        running = self.desktop.process(app)
        if app != 'browser' or not running.site:
            raise Refused('local_site_profile_required')
        self.desktop.resolve(app, ref)
        return running

    @staticmethod
    def inspect(profile):
        return site_call(profile, dict(operation='inspect'))

    @staticmethod
    def external_state(profile):
        return site_call(profile, dict(operation='inspect_external'))

    def discover(self, app, ref, offset=0):
        running = self.window(app, ref)
        try:
            if running.external:
                try:
                    state = self.external_state(running.profile)
                except NativeError as error:
                    if str(error) != 'web_destination_denied':
                        raise
                    state = self.inspect(running.profile)
            else:
                state = self.inspect(running.profile)
        except (OSError, NativeError):
            raise Refused('web_observation_unavailable') from None
        controls = []
        next_offset = None
        items = state['controls']
        if state['page'] == 'https':
            items = sorted(items, key=lambda row: row['kind'] == 'link')
        bytes_used = 0
        for index, item in enumerate(items[offset:], start=offset):
            proof = dict(document=state['document'], url=state['url'],
                         key=item['key'], role=item['role'], name=item['name'])
            row = {key: item[key] for key in ('role', 'name', 'value')}
            row['ref'] = self.desktop.reference(WebTarget(ref, proof))
            row['options'] = [{key: option[key] for key in ('label', 'value')} for option in item['options']]
            if state['page'] == 'https':
                row.update(kind=item['kind'], state=item['state'], required=item['required'],
                           valid=item['valid'], filled=bool(item['value']))
                if item['destination']:
                    row['destination'] = public_url(item['destination'])
                # Keep each Bridge frame bounded. Applications with a larger
                # tree retain their ordinary AT-SPI search surface.
                row['options'] = row['options'][:12]
                bytes_used += len(json.dumps(row, ensure_ascii=True))
                if len(controls) >= 20 or bytes_used > 4800:
                    next_offset = index
                    break
            controls.append(row)
        url = public_url(state['url']) if state['page'] == 'https' else state['url']
        if state['page'] == 'https':
            return dict(page=state['page'], url=url, title=state['title'], controls=controls,
                        notices=state['notices'][:3], headings=state['headings'][:4],
                        truncated=state['truncated'], next=next_offset,
                        source='firefox_dom')
        return dict(page=state['page'], url=url, title=state['title'], controls=controls,
                    tables=state['tables'], truncated=state['truncated'], source='firefox_dom')

    def prepare_https(self, method, app, params):
        if method == 'web.submit_https' and self.external_submission_started:
            raise Refused('web_submit_already_attempted')
        if method == 'web.navigate_https':
            token = params['ref']
            running = self.window(app, token)
            if not running.external:
                raise Refused('external_https_disabled')
            allowed(params['url'])
            try:
                prior = self.external_state(running.profile)
            except NativeError as error:
                if str(error) != 'web_destination_denied':
                    raise
                prior = self.inspect(running.profile)
            request = dict(operation='navigate_https', destination=params['url'],
                           document=prior['document'], url=prior['url'])
        else:
            saved = self.desktop.references.get(params['ref'])
            if not isinstance(saved, WebTarget):
                raise Refused('stale_web_reference')
            token = saved.window_ref
            running = self.window(app, token)
            if not running.external:
                raise Refused('external_https_disabled')
            operation = {'web.set_text': 'external_text', 'web.select': 'external_select',
                         'web.activate': 'external_activate', 'web.submit_https': 'external_submit'}[method]
            request = dict(operation=operation, **saved.proof)
            if method in ('web.set_text', 'web.select'):
                request['value'] = params['text'] if method == 'web.set_text' else params['option']
        expected = site_call(running.profile, {**request, 'preview': True})

        def send():
            self.window(app, token)
            if method == 'web.submit_https':
                self.external_submission_started = True
            site_call(running.profile, {**request, 'expected': expected})

        def verify():
            self.window(app, token)
            state = self.external_state(running.profile)
            if method == 'web.submit_https':
                # A status message or widget can signal only that the page
                # started a check. No general commercial receipt is available.
                if state['document'] == request['document']:
                    raise Refused('web_submission_outcome_unverified')
                return dict(verifier='fresh_firefox_response_document', url=public_url(state['url']),
                            commercialOutcome='requires_independent_review')
            if method == 'web.navigate_https' or expected.get('kind') == 'link':
                if state['document'] == request['document']:
                    raise Refused('web_navigation_unconfirmed')
                allowed(state['url'])
                # A redirect may change the path on an allowed host.
                return dict(page='https', url=public_url(state['url']), title=state['title'],
                            verifier='fresh_firefox_https_document')
            if method == 'web.activate':
                changed = (state['document'] != request['document'] or state['url'] != request['url']
                           or not any(row['key'] == request['key'] and row['state'] == expected['state']
                                      and row['value'] == expected['before'] for row in state['controls']))
                if not changed:
                    raise Refused('web_mutation_unconfirmed')
                return dict(verifier='firefox_document_or_control_changed')
            row = member(state, request)
            if row['value'] != expected['value']:
                raise Refused('web_mutation_unconfirmed')
            return dict(role=row['role'], name=row['name'], value=row['value'], verifier='firefox_readback')

        return Prepared(send, lambda: wait_for(verify, timeout=16 if method == 'web.submit_https' else 5))

    def prepare(self, method, app, params):
        try:
            if method == 'web.navigate_https':
                return self.prepare_https(method, app, params)
            saved = self.desktop.references.get(params['ref'])
            if isinstance(saved, WebTarget) and saved.proof['url'].startswith('https://'):
                return self.prepare_https(method, app, params)
            if method == 'web.navigate':
                token = params['ref']
                running = self.window(app, token)
                state = self.inspect(running.profile)
                request = dict(operation='navigate', page=params['page'],
                               document=state['document'], url=state['url'])
            else:
                saved = self.desktop.references.get(params['ref'])
                if not isinstance(saved, WebTarget):
                    raise Refused('stale_web_reference')
                token = saved.window_ref
                running = self.window(app, token)
                operation = {'web.set_text': 'text', 'web.select': 'select', 'web.activate': 'activate'}[method]
                request = dict(operation=operation, **saved.proof)
                if operation != 'activate':
                    request['value'] = params['text'] if operation == 'text' else params['option']
            expected = site_call(running.profile, {**request, 'preview': True})
        except (OSError, NativeError, WebError) as error:
            reason = str(error) if isinstance(error, (NativeError, WebError)) and str(error).startswith(
                ('web_', 'stale_', 'no_change')) else 'web_preparation_unavailable'
            raise Refused(reason) from None

        def send():
            self.window(app, token)
            site_call(running.profile, {**request, 'expected': expected})

        def verify():
            self.window(app, token)
            state = self.inspect(running.profile)
            if method in ('web.navigate', 'web.activate'):
                actual, goal = urlsplit(state['url']), urlsplit(expected['url'])
                if ((actual.scheme, actual.netloc, actual.path) != (goal.scheme, goal.netloc, goal.path)
                        or state['document'] == request['document']
                        or not exact_fields(state['url'], expected['fields'] or parse_qsl(
                            goal.query, keep_blank_values=True, max_num_fields=24))):
                    raise Refused('web_navigation_unconfirmed')
                return dict(page=state['page'], url=state['url'], verifier='fresh_firefox_document')
            try:
                row = member(state, request)
            except WebError:
                raise Refused('web_mutation_unconfirmed') from None
            if row['value'] != expected['value']:
                raise Refused('web_mutation_unconfirmed')
            return dict(role=row['role'], name=row['name'], value=row['value'], verifier='firefox_readback')

        return Prepared(send, lambda: wait_for(verify, timeout=5))
