# SPDX-License-Identifier: Apache-2.0
import time
import unittest
from unittest.mock import Mock, patch

from experiments.m1_1.semantic import (
    Reference, Rejected, button, click_index, correlate, texts, validate, wait_for, windows,
)


class Node:
    def __init__(self, role='frame', name='', children=(), pid=42):
        self.role, self.name, self.children, self.pid = role, name, list(children), pid
        self.childCount = len(self.children)

    def __iter__(self):
        return iter(self.children)

    def __getitem__(self, index):
        return self.children[index]

    def getRoleName(self):
        return self.role

    def get_process_id(self):
        return self.pid


class CorrelationTests(unittest.TestCase):
    def setUp(self):
        self.window = dict(id=1, pid=42, app_id='org.gnome.Calculator', shell='xdg_shell')
        self.frame = Node()
        self.app = Node('application', 'gnome-calculator', [self.frame])

    def test_join_by_pid_unique_frame(self):
        self.assertEqual(correlate([self.window], [self.app], 42),
                         (self.window, self.app, self.frame))

    def test_title_or_name_is_insufficient(self):
        self.app.pid = 99
        with self.assertRaisesRegex(Rejected, 'tree_missing'):
            correlate([self.window], [self.app], 42)

    def test_missing_pid_or_window(self):
        for records in ([], [dict(self.window, pid=None)], [dict(self.window, pid=99)]):
            with self.subTest(records=records), self.assertRaises(Rejected):
                correlate(records, [self.app], 42)

    def test_duplicate_window_tree_or_frame(self):
        cases = [([self.window]*2, [self.app]), ([self.window], [self.app]*2),
                 ([self.window], [Node(children=[self.frame]*2)])]
        for records, apps in cases:
            with self.subTest(records=records), self.assertRaises(Rejected):
                correlate(records, apps, 42)

    def test_wrong_application_or_backend(self):
        for field, value in [('app_id', 'other'), ('shell', 'xwayland')]:
            with self.subTest(field=field), self.assertRaises(Rejected):
                correlate([dict(self.window, **{field: value})], [self.app], 42)

    def test_nested_floating_window_discovery(self):
        tree = dict(nodes=[dict(floating_nodes=[self.window])])
        self.assertEqual(windows(tree), [self.window])


class DispatchTests(unittest.TestCase):
    def reference(self):
        node = Mock()
        node.get_interfaces.return_value = ['Action']
        action = node.queryAction.return_value
        action.nActions = 1
        action.getName.return_value = 'click'
        action.doAction.return_value = True
        return Reference((42, '100', 1000, '/usr/bin/gnome-calculator'), {},
                         object(), object(), node, (), time.monotonic()+10)

    def test_expired_or_invalidated_never_touches_adapter(self):
        for mode in ('invalidate', 'deadline'):
            ref = self.reference()
            if mode == 'invalidate':
                ref.invalidate()
            else:
                ref.deadline = 0
            check = Mock()
            with self.assertRaisesRegex(Rejected, 'expired_reference'):
                ref.dispatch(check)
            check.assert_not_called()
            ref.node.queryAction.assert_not_called()

    def test_changed_lifecycle_prevents_action(self):
        ref = self.reference()
        check = Mock(side_effect=Rejected('process_identity_changed'))
        with self.assertRaises(Rejected):
            ref.dispatch(check)
        self.assertFalse(ref.valid)
        ref.node.queryAction.assert_not_called()

    def test_pid_reuse_rejected_before_tree_or_action(self):
        ref = self.reference()
        process = Mock(pid=42)
        process.poll.return_value = None
        with patch('experiments.m1_1.semantic.select.select', return_value=([], [], [])), \
             patch('experiments.m1_1.semantic.process_identity', return_value=(42, '200', 1000, '/usr/bin/gnome-calculator')):
            with self.assertRaisesRegex(Rejected, 'process_identity_changed'):
                ref.dispatch(lambda r: validate(r, process, 12, Mock()))
        ref.node.queryAction.assert_not_called()

    def test_no_interface_no_click_duplicate_click(self):
        for interfaces, names in [([], []), (['Action'], []),
                                   (['Action'], ['press']), (['Action'], ['click', 'click'])]:
            ref = self.reference()
            ref.node.get_interfaces.return_value = interfaces
            action = ref.node.queryAction.return_value
            action.nActions = len(names)
            action.getName.side_effect = names
            with self.subTest(names=names), self.assertRaises(Rejected):
                ref.dispatch(Mock())
            action.doAction.assert_not_called()

    def test_action_invoked_once_no_mutation_retry(self):
        ref = self.reference()
        self.assertEqual(ref.dispatch(Mock()), ['click'])
        ref.node.queryAction.return_value.doAction.assert_called_once_with(0)

    def test_false_return_is_failure(self):
        ref = self.reference()
        ref.node.queryAction.return_value.doAction.return_value = False
        with self.assertRaisesRegex(Rejected, 'action_not_accepted'):
            ref.dispatch(Mock())
        ref.node.queryAction.return_value.doAction.assert_called_once()


class ObservationTests(unittest.TestCase):
    def test_missing_or_duplicate_button(self):
        for children in ([], [Node('button', '7')]*2):
            with self.assertRaises(Rejected):
                button(Node(children=children))

    def test_button_label_cannot_verify_result(self):
        label = Node('label', '7')
        self.assertEqual(texts(Node(children=[label])), {})

    def test_bounded_retry(self):
        read = Mock(side_effect=Rejected('not_ready'))
        with self.assertRaisesRegex(Rejected, 'readiness_timeout'):
            wait_for(read, timeout=.01)
        self.assertEqual(read.call_count, 1)


if __name__ == '__main__':
    unittest.main()
