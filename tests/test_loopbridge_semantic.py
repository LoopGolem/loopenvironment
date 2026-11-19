# SPDX-License-Identifier: Apache-2.0
from types import SimpleNamespace
import unittest

from loopbridge.adapter import Refused
from loopbridge.semantic_operations import SemanticOperations, semantic_signature


class Accessible:
    def __init__(self, role, name='', interfaces=(), flags=('showing', 'sensitive')):
        self.role, self.name, self.interfaces, self.flags = role, name, interfaces, flags
        self.children = []
        self.selection = []
        self.currentValue, self.minimumValue, self.maximumValue = (0, 0, 10)

    @property
    def childCount(self):
        return len(self.children)

    @property
    def nSelectedChildren(self):
        return len(self.selection)

    def __getitem__(self, index):
        return self.children[index]

    def getRoleName(self):
        return self.role

    def get_interfaces(self):
        return self.interfaces

    def getState(self):
        return self

    def getStates(self):
        return [SimpleNamespace(value_name='ATSPI_STATE_' + flag.upper()) for flag in self.flags]

    def queryValue(self):
        return self

    def querySelection(self):
        return self

    def selectChild(self, index):
        self.selection = [index]
        return True

    def getSelectedChild(self, index):
        return self.children[self.selection[index]]


class Adapter:
    def __init__(self, node):
        self.node = node
        self.workspace = SimpleNamespace(file_path=self.file_path)

    @staticmethod
    def file_path(name):
        if name != 'memo.txt':
            raise FileNotFoundError

    def resolve(self, app, ref, element):
        return SimpleNamespace(signature=semantic_signature(self.node)), self.node


class CommonSemanticsTests(unittest.TestCase):
    def test_value_interface_and_policy_gate(self):
        node = Accessible('slider', interfaces=('Value',))
        semantics = SemanticOperations(Adapter(node))
        params = dict(ref='live', value=3.5)
        with self.assertRaisesRegex(Refused, 'operation_outside_app_policy'):
            semantics.prepare('element.set_value', 'files', params)
        prepared = semantics.prepare('element.set_value', 'calculator', params)
        prepared.send()
        self.assertEqual(prepared.verify(), dict(value=3.5))
        for value in (-1, 11, True):
            with self.assertRaisesRegex(Refused, 'invalid_value'):
                semantics.prepare('element.set_value', 'calculator', dict(ref='live', value=value))

    def test_projected_selection_validates_policy_and_child_identity_again(self):
        container = Accessible('table', interfaces=('Selection',))
        file = Accessible('table cell', 'memo.txt', flags=('showing', 'sensitive', 'selectable'))
        outside = Accessible('table cell', 'Personal', flags=('showing', 'sensitive', 'selectable'))
        container.children = [file, outside]
        semantics = SemanticOperations(Adapter(container))
        params = dict(ref='live', index=0)
        with self.assertRaisesRegex(Refused, 'unsupported_selection'):
            semantics.prepare('element.select', 'editor', params)
        with self.assertRaisesRegex(Refused, 'selection_outside_workspace'):
            semantics.prepare('element.select', 'files', dict(ref='live', index=1))
        prepared = semantics.prepare('element.select', 'files', params)
        container.children.reverse()
        with self.assertRaisesRegex(Refused, 'selection_target_changed'):
            prepared.send()
        container.children.reverse()
        prepared.send()
        self.assertEqual(prepared.verify(), dict(indices=[0]))
        self.assertEqual(semantics.read('element.get_selection', 'files', params)['indices'], [0])

    def test_unsupported_action_cannot_fall_back_to_arbitrary_invocation(self):
        node = Accessible('button', 'Danger', interfaces=('Action',))
        node.queryAction = lambda: SimpleNamespace(nActions=2, getName=lambda _: 'click')
        semantics = SemanticOperations(Adapter(node))
        with self.assertRaisesRegex(Refused, 'ambiguous_action'):
            semantics.prepare('element.invoke', 'calculator', dict(ref='live', action='click'))
