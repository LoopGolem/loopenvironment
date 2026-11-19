# SPDX-License-Identifier: Apache-2.0
import os
from pathlib import Path
import tempfile
import unittest

from loopbridge.adapter import Refused
from loopbridge.browser import allowed_text, receipt_fields
from loopbridge.browser_native import ELEMENT, FORM, Marionette, NativeError
from loopbridge.teaching import AnnotationStore
from loopbridge.workspace import Workspace


class NativeWorkspaceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.parent = Path(directory.name)
        self.root = self.parent / 'workspace'
        self.root.mkdir(mode=0o700)
        self.workspace = Workspace(self.root)
        self.addCleanup(self.workspace.close)

    def test_create_list_and_rename_without_replacing_existing_data(self):
        self.workspace.mkdir('drafts')
        self.workspace.mkdir('review')
        self.workspace.write('drafts/memo.txt', 'draft\n')
        self.assertEqual(self.workspace.listing(0, 'drafts')['entries'],
                         [{'name': 'memo.txt', 'kind': 'file'}])
        expected = self.workspace.prepare_rename('drafts/memo.txt', 'review/report.txt')
        self.workspace.rename('drafts/memo.txt', 'review/report.txt')
        self.assertEqual(self.workspace.confirm_rename('drafts/memo.txt', 'review/report.txt',
                                                      expected)['verifier'], 'linux_dirfd_readback')
        self.workspace.write('drafts/memo.txt', 'different\n')
        with self.assertRaises(FileExistsError):
            self.workspace.prepare_rename('drafts/memo.txt', 'review/report.txt')
        self.assertEqual(self.workspace.read('review/report.txt'), 'draft\n')

    def test_reject_intermediate_symlink_and_untrusted_directory(self):
        outside = self.parent / 'outside'
        outside.mkdir(mode=0o700)
        (outside / 'data').write_text('private')
        (self.root / 'escape').symlink_to(outside, target_is_directory=True)
        (self.root / 'shared').mkdir(mode=0o700)
        os.chmod(self.root / 'shared', 0o777)
        for path in ('escape/data', 'shared/data'):
            with self.assertRaises(OSError):
                self.workspace.prepare(path, 'replacement')
        with self.assertRaises(OSError):
            self.workspace.directory_path('escape')
        self.assertEqual((outside / 'data').read_text(), 'private')


class BrowserFixtureTests(unittest.TestCase):
    def test_receipt_validates_exact_field_set_and_fictional_input_shape(self):
        self.assertEqual(receipt_fields('file:///fixture/receipt.html?name=Sample+Operator&category=beta'),
                         {'name': 'Sample Operator', 'category': 'beta'})
        for query in ('name=x&category=alpha&name=y', 'name=x&category=gamma',
                      'name=x%0A%3C&category=beta', 'name=x&category=beta&extra=a'):
            with self.assertRaises(Refused):
                receipt_fields('file:///fixture/receipt.html?' + query)
        for text in ('<demo>', 'mailto:someone', 'a' * 41, ''):
            with self.assertRaises(Refused):
                allowed_text(text)


    def test_native_effects_allow_only_exact_fixture_and_fixed_dom_addresses(self):
        native = object.__new__(Marionette)
        dispatched = []

        def call(method, params=None):
            dispatched.append((method, params))
            return {
                'WebDriver:GetCurrentURL': {'value': FORM},
                'WebDriver:GetWindowHandles': {'value': ['private-tab']},
                'WebDriver:FindElement': {'value': {ELEMENT: 'fixture-element'}},
            }.get(method)

        native.call = call
        native.apply(['text', 'Demo Operator'])
        self.assertEqual(dispatched[-2], ('WebDriver:FindElement',
                                         {'using': 'css selector', 'value': '#demo-name'}))
        self.assertEqual(dispatched[-1], ('WebDriver:ElementSendKeys',
                                         {'id': 'fixture-element', 'text': 'Demo Operator'}))
        for operation in (['navigate', 'about:config'], ['radio', '#private-field'],
                          ['submit', 'other'], ['text', '<script>']):
            with self.assertRaises(NativeError):
                native.apply(operation)
        self.assertEqual(sum(method.startswith('WebDriver:Element') for method, _ in dispatched), 1)

    def test_native_effects_refuse_wrong_document_or_multiple_windows(self):
        native = object.__new__(Marionette)
        for url, tabs in [('about:config', ['tab']), (FORM, ['one', 'two'])]:
            native.call = lambda method, params=None: {
                'WebDriver:GetCurrentURL': {'value': url},
                'WebDriver:GetWindowHandles': {'value': tabs},
            }[method]
            with self.assertRaisesRegex(NativeError, 'document'):
                native.apply(['submit', ''])


class AnnotationSearchTests(unittest.TestCase):
    def test_casefold_and_current_revision_filter_preserve_app_and_session_scope(self):
        with tempfile.TemporaryDirectory() as root:
            store = AnnotationStore(Path(root) / 'test.sqlite3')
            body = dict(meaning='document.save', operationHint='page.save', warnings='', conditions='')
            record = store.create('desktop', 'editor', {}, body, 'observer')
            store.create('desktop', 'files', {}, body, 'owner')
            store.create('other', 'editor', {}, body, 'owner')
            store.revise('desktop', 'editor', record['id'], 1, 'owner', review='approved')
            self.assertEqual(store.search('desktop', 'editor', 'DOCUMENT', 1, 0)['annotations'], [])
            matches = store.search('desktop', 'editor', 'DOCUMENT', 2, 0)['annotations']
            self.assertEqual([row['id'] for row in matches], [record['id']])
