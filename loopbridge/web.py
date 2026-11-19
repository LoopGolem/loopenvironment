# SPDX-License-Identifier: Apache-2.0
"""Translate Bridge references into private browser proofs and read back effects."""
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from .adapter import Refused
from .browser_native import NativeError, site_call
from .linux_desktop import wait_for
from .semantic_operations import Prepared
from .web_native import exact_fields, member, WebError


@dataclass
class WebTarget:
    window_ref: str
    proof: dict


class Web:
    def __init__(self, desktop):
        self.desktop = desktop

    def window(self, app, ref):
        running = self.desktop.process(app)
        if app != 'browser' or not running.site:
            raise Refused('local_site_profile_required')
        self.desktop.resolve(app, ref)
        return running

    @staticmethod
    def inspect(profile):
        return site_call(profile, dict(operation='inspect'))

    def discover(self, app, ref):
        running = self.window(app, ref)
        try:
            state = self.inspect(running.profile)
        except (OSError, NativeError):
            raise Refused('web_observation_unavailable') from None
        controls = []
        for item in state['controls']:
            proof = dict(document=state['document'], url=state['url'],
                         key=item['key'], role=item['role'], name=item['name'])
            row = {key: item[key] for key in ('role', 'name', 'value')}
            row['ref'] = self.desktop.reference(WebTarget(ref, proof))
            row['options'] = [{key: option[key] for key in ('label', 'value')} for option in item['options']]
            controls.append(row)
        return dict(page=state['page'], url=state['url'], title=state['title'], controls=controls,
                    tables=state['tables'], truncated=state['truncated'], source='firefox_dom')

    def prepare(self, method, app, params):
        try:
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
        except (OSError, NativeError) as error:
            reason = str(error) if isinstance(error, NativeError) and str(error).startswith(
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
