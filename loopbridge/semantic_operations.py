# SPDX-License-Identifier: Apache-2.0
"""AT-SPI operation policies and independently checked effect contracts."""
from dataclasses import dataclass
import math

from .adapter import Refused
from .linux_desktop import wait_for


@dataclass
class Prepared:
    send: object
    verify: object


@dataclass(frozen=True)
class Policy:
    text: bool = False
    document_text: bool = False
    value: bool = False
    selection_roles: frozenset = frozenset()
    workspace_selection: bool = False
    effects: tuple = ()

    def mutations(self):
        return ((['set_text'] if self.document_text else []) +
                (['set_value'] if self.value else []) +
                (['select'] if self.selection_roles else []) +
                [effect for effect in self.effects])


POLICIES = {
    'calculator': Policy(text=True, value=True, effects=('invoke',)),
    'editor': Policy(text=True, document_text=True, effects=('page.save',)),
    'files': Policy(selection_roles=frozenset(('table', 'tree table', 'layered pane')),
                    workspace_selection=True),
    'clocks': Policy(),
    'browser': Policy(),
}


def short(value, limit=80):
    return (value or '')[:limit]


def state_flags(node):
    return {flag.value_name.removeprefix('ATSPI_STATE_').lower()
            for flag in node.getState().getStates()}


def actions(node, interfaces, limit=8):
    if 'Action' not in interfaces:
        return [], False
    query = node.queryAction()
    return [query.getName(index) for index in range(min(query.nActions, limit))], query.nActions > limit


def semantic_text(node):
    text = node.queryText()
    count = text.characterCount
    return dict(text=text.getText(0, min(count, 750)), truncated=count > 750, length=count)


def semantic_signature(node):
    return node.getRoleName(), node.name, tuple(sorted(node.get_interfaces()))


class SemanticOperations:
    def __init__(self, desktop):
        self.desktop = desktop

    def selection(self, policy, node, role, interfaces):
        if 'Selection' not in interfaces or role not in policy.selection_roles:
            raise Refused('unsupported_selection')
        if not 0 <= node.childCount <= 128:
            raise Refused('selection_limit')
        return node.querySelection()

    @staticmethod
    def selected(node, selection):
        count = selection.nSelectedChildren
        if not 0 <= count <= node.childCount <= 128:
            raise Refused('selection_limit')
        elements = [selection.getSelectedChild(index) for index in range(count)]
        return [index for index in range(node.childCount) if node[index] in elements]

    def read(self, method, app, params):
        target, node = self.desktop.resolve(app, params['ref'], element=True)
        role, _, interfaces = target.signature
        policy = POLICIES[app]
        flags = state_flags(node)
        if 'protected' in flags or role == 'password text':
            raise Refused('protected_element')
        if method == 'element.actions':
            labels, truncated = actions(node, interfaces, limit=64)
            return dict(actions=[short(name, 48) for name in labels], truncated=truncated, source='atspi')
        if method == 'element.get_text' and 'Text' in interfaces and policy.text:
            if policy.document_text and 'multi_line' not in flags:
                raise Refused('operation_outside_app_policy')
            return dict(**semantic_text(node), source='atspi')
        if method == 'element.get_value' and 'Value' in interfaces and policy.value:
            value = node.queryValue()
            return dict(value=value.currentValue, minimum=value.minimumValue,
                        maximum=value.maximumValue, source='atspi')
        if method == 'element.get_selection':
            selection = self.selection(policy, node, role, interfaces)
            return dict(indices=self.selected(node, selection), source='atspi')
        raise Refused('unsupported_interface')

    def prepare(self, method, app, params):
        target, node = self.desktop.resolve(app, params['ref'], element=True)
        role, name, interfaces = target.signature
        flags = state_flags(node)
        if not {'showing', 'sensitive'} <= flags or 'protected' in flags or role == 'password text':
            raise Refused('element_unavailable')
        policy = POLICIES[app]

        def fresh():
            return self.desktop.resolve(app, params['ref'], element=True)[1]

        if method == 'element.set_text':
            if not {'EditableText', 'Text'} <= set(interfaces):
                raise Refused('unsupported_interface')
            if not policy.document_text or not {'editable', 'multi_line'} <= flags:
                raise Refused('operation_outside_app_policy')
            text = params['text']
            if len(text.encode('utf-8')) > 3000 or '\x00' in text:
                raise Refused('invalid_text')
            previous = semantic_text(node)
            if not previous['truncated'] and previous['text'] == text:
                raise Refused('no_change')

            def verify():
                query = fresh().queryText()
                if query.characterCount != len(text) or query.getText(0, len(text)) != text:
                    raise Refused('result_not_confirmed')
                return dict(characters=len(text))

            return Prepared(lambda: fresh().queryEditableText().setTextContents(text),
                            lambda: wait_for(verify, timeout=3))

        if method == 'element.set_value':
            if 'Value' not in interfaces:
                raise Refused('unsupported_interface')
            if not policy.value:
                raise Refused('operation_outside_app_policy')
            value, query = params['value'], node.queryValue()
            if type(value) not in (float, int) or not query.minimumValue <= value <= query.maximumValue:
                raise Refused('invalid_value')
            if query.currentValue == value:
                raise Refused('no_change')

            def verify():
                actual = fresh().queryValue().currentValue
                if not math.isclose(actual, value, abs_tol=1e-9):
                    raise Refused('result_not_confirmed')
                return dict(value=actual)

            return Prepared(lambda: setattr(fresh().queryValue(), 'currentValue', value),
                            lambda: wait_for(verify, timeout=3))

        if method == 'element.select':
            selection = self.selection(policy, node, role, interfaces)
            index = params['index']
            if not 0 <= index < node.childCount:
                raise Refused('invalid_selection_index')
            child = node[index]
            identity = semantic_signature(child)
            if policy.workspace_selection:
                child_role, child_name, _ = identity
                if child_role not in ('icon', 'table cell'):
                    raise Refused('selection_outside_workspace')
                try:
                    self.desktop.workspace.file_path(child_name)
                except (OSError, ValueError, TypeError):
                    raise Refused('selection_outside_workspace') from None
            child_flags = state_flags(child)
            if not {'selectable', 'showing', 'sensitive'} <= child_flags:
                raise Refused('selection_target_unavailable')
            previous = self.selected(node, selection)
            if index in previous:
                raise Refused('no_change')
            expected = sorted([*previous, index]) if 'multiselectable' in flags else [index]

            def live_selection():
                current = fresh()
                if (index >= current.childCount or current[index] != child
                        or semantic_signature(current[index]) != identity):
                    raise Refused('selection_target_changed')
                return current, self.selection(policy, current, role, interfaces)

            def verify():
                current, query = live_selection()
                if self.selected(current, query) != expected:
                    raise Refused('result_not_confirmed')
                return dict(indices=expected)

            return Prepared(lambda: live_selection()[1].selectChild(index),
                            lambda: wait_for(verify, timeout=3))

        if method == 'element.invoke':
            requested = params['action']

            def action_index(query):
                if not 0 <= query.nActions <= 64:
                    raise Refused('action_limit')
                indices = [index for index in range(query.nActions) if query.getName(index) == requested]
                if not indices:
                    raise Refused('unsupported_action')
                if len(indices) > 1:
                    raise Refused('ambiguous_action')
                return indices[0]

            if 'Action' not in interfaces:
                raise Refused('unsupported_interface')
            action_index(node.queryAction())
            verify = self.desktop.action_effect(policy, target, role, name, requested)

            def send():
                query = fresh().queryAction()
                return query.doAction(action_index(query))

            return Prepared(send, verify)
        raise Refused('unsupported_operation')
