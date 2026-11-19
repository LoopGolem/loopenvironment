# SPDX-License-Identifier: Apache-2.0
"""Observe trusted target evidence without persisting handles or document text."""
import hashlib
from functools import lru_cache
import os

from .adapter import Refused
from .semantic_operations import actions, semantic_signature, state_flags
from .teaching import compare, match_status, normalized_ancestry

MAX_NODES = 512
MAX_DEPTH = 40
STABLE_ACTIONS = frozenset(('activate', 'check', 'click', 'expand', 'press',
                            'select', 'toggle', 'page.save'))
ROLES = frozenset(('frame', 'label', 'button', 'push button', 'toggle button',
                   'check box', 'radio button', 'combo box', 'menu item',
                   'check menu item', 'radio menu item', 'slider', 'spin button',
                   'list', 'list item', 'table', 'page tab'))


@lru_cache(maxsize=16)
def executable_digest(identity):
    path, *_ = identity
    digest = hashlib.sha256()
    with open(path, 'rb') as executable:
        for chunk in iter(lambda: executable.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


class Picker:
    def __init__(self, desktop):
        self.desktop = desktop

    def window(self, target):
        application = self.desktop.process(target.app)
        executable = application.identity[3]
        info = os.stat(executable)
        return dict(application=target.window['app_id'], build=executable_digest(
                        (executable, info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size)),
                    role=target.frame.getRoleName(), surface=target.window['shell'],
                    context='workspace_document' if application.document else 'supervised_window')

    def name(self, app, node, role):
        # Frame titles can contain paths or user text. This context is validated
        # by the supervised adapter before either teaching or matching.
        if role == 'frame':
            return 'workspace document' if self.desktop.apps[app].document else ''
        if role not in ROLES:
            return ''
        name = node.name or ''
        sanitized = self.desktop.label(app, name)
        if len(name) > 80:
            return None
        return sanitized

    def describe(self, target, window, node, ancestors):
        role, _, interfaces = semantic_signature(node)
        flags = state_flags(node)
        if role not in ROLES or 'showing' not in flags or 'protected' in flags:
            return None
        # File-manager names are redacted in its observation policy.
        if target.app in ('files', 'browser'):
            return None
        name = self.name(target.app, node, role)
        labels, overflow = actions(node, interfaces, limit=64)
        stable_actions = sorted(set(labels) & STABLE_ACTIONS)
        if (overflow or name is None or any(name is None for _, name in ancestors)
                or (not name and not stable_actions)):
            return None
        return dict(window=window, role=role, name=name,
                    interfaces=list(interfaces)[:12],
                    actions=stable_actions,
                    ancestry=ancestors, source='atspi')

    def capture(self, app, ref):
        target, node = self.desktop.resolve(app, ref, element=True)
        window = self.window(target)
        current, ancestors = target.frame, []
        for index in target.path:
            role = current.getRoleName()
            ancestors.append([role, self.name(app, current, role)])
            if role == 'password text' or 'protected' in state_flags(current):
                raise Refused('protected_element')
            current = current[index]
        if current != node:
            raise Refused('stale_reference')
        evidence = self.describe(target, window, node, ancestors)
        if evidence is None:
            raise Refused('unsupported_teaching_target')
        return dict(evidence=evidence)

    def find(self, app, ref, evidence):
        target, frame = self.desktop.resolve(app, ref)
        window = self.window(target)
        if any(window[key] != evidence['window'][key] for key in ('application', 'build')):
            return dict(status='incompatible', reason='application_or_build_changed')
        if window != evidence['window']:
            return dict(status='unresolved', reason='window_context_changed')
        pending = [((), frame, ())]
        visited, candidates, complete = 0, [], True
        # DFS with the structural context of each node. Child indexes are used
        # only to issue a fresh session ref for an independently matched node.
        while pending and visited < MAX_NODES:
            path, node, ancestry = pending.pop()
            if node is None:
                complete = False
                continue
            visited += 1
            role = node.getRoleName()
            if role == 'password text' or 'protected' in state_flags(node):
                continue
            name = self.name(app, node, role)
            if (role == evidence['role'] and name == evidence['name']
                    and normalized_ancestry(ancestry) == normalized_ancestry(evidence['ancestry'])):
                fresh = self.describe(target, window, node, list(ancestry))
                quality = compare(evidence, fresh) if fresh is not None else None
                if quality:
                    candidates.append((path, node, quality))
                    if len(candidates) == 2:
                        break
            count = node.childCount
            if count < 0 or count > 128 or (count and len(path) >= MAX_DEPTH):
                complete = False
                continue
            context = (*ancestry, [role, name])
            pending.extend(((*path, index), node[index], context)
                           for index in reversed(range(count)))
        status = match_status(len(candidates), complete and not pending)
        if status != 'matched':
            reason = ('duplicate_context' if status == 'ambiguous' else
                      'incomplete_search' if pending or not complete else 'evidence_changed')
            return dict(status=status, reason=reason)
        path, node, quality = candidates[0]
        return dict(status='matched', matchQuality=quality, element=self.desktop.describe(target, path, node),
                    criteria=['application_build', 'window_context', 'role', 'name',
                              'semantic_interfaces', 'native_actions', 'ancestry'])
