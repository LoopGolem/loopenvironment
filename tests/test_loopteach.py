# SPDX-License-Identifier: Apache-2.0
from contextlib import closing
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from loopbridge.broker import Connection
from loopbridge.desktop_broker import DesktopBroker
from loopbridge.identity import Identities
from loopbridge.protocol import Fault
from loopbridge.service import Journal
from loopbridge.teach_cli import teach
from loopbridge.teaching import AnnotationStore, TeachingError
from loopbridge.teaching_picker import Picker

ANNOTATION = dict(meaning='document.save', operationHint='page.save', conditions='', warnings='')
WINDOW = dict(application='editor', build='version', role='frame', surface='xdg_shell',
              context='workspace_document')


class StoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.file = Path(directory.name) / 'annotations.sqlite3'
        self.store = AnnotationStore(self.file)

    def test_persistence_revision_provenance_and_tombstone(self):
        record = self.store.create('desktop', 'editor', WINDOW, ANNOTATION, 'observer')
        key = record['id']
        self.assertEqual(os.stat(self.file).st_mode & 0o777, 0o600)
        stored = AnnotationStore(self.file)
        self.assertEqual(stored.get('desktop', 'editor', key), record)
        with self.assertRaisesRegex(TeachingError, 'annotation_unavailable'):
            stored.get('other', 'editor', key)
        approved = stored.revise('desktop', 'editor', key, 1, 'owner', review='approved')
        self.assertEqual(approved['createdBy'], 'observer')
        self.assertEqual(approved['updatedBy'], 'owner')
        self.assertEqual(approved['reviewState'], 'approved')
        with self.assertRaisesRegex(TeachingError, 'annotation_revision_conflict'):
            stored.revise('desktop', 'editor', key, 1, 'observer', annotation=ANNOTATION)
        edited = stored.revise('desktop', 'editor', key, 2, 'observer',
                              annotation={**ANNOTATION, 'meaning': 'changed'})
        self.assertEqual(edited['reviewState'], 'operator_supplied')
        self.assertEqual(edited['revision'], 3)
        self.assertEqual(stored.list('desktop', 'editor', 0)['annotations'][0]['meaning'], 'changed')
        stored.revise('desktop', 'editor', key, 3, 'owner', review='deleted')
        self.assertEqual(stored.list('desktop', 'editor', 0)['annotations'], [])
        with self.assertRaisesRegex(TeachingError, 'annotation_unavailable'):
            stored.get('desktop', 'editor', key)
        with closing(sqlite3.connect(self.file)) as db:
            self.assertEqual(db.execute('select count(*) from annotations').fetchone()[0], 4)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)

    def test_unknown_schema_refuses_to_start_without_changing_it(self):
        with closing(sqlite3.connect(self.file)) as db:
            db.execute('PRAGMA user_version=233')
        with self.assertRaisesRegex(TeachingError, 'unsupported_annotation_schema'):
            AnnotationStore(self.file)
        with closing(sqlite3.connect(self.file)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 233)


class Node:
    def __init__(self, role, name, *children, flags=('showing', 'sensitive')):
        self.role, self.name, self.children = role, name, children
        self.description = ''
        self.flags = flags
        self.childCount = len(children)
        self.nActions = int(role == 'button')

    def __getitem__(self, index):
        return self.children[index]

    def getRoleName(self):
        return self.role

    def get_interfaces(self):
        return ['Accessible', 'Action'] if self.nActions else ['Accessible']

    def getState(self):
        return self

    def getStates(self):
        return [SimpleNamespace(value_name='ATSPI_STATE_' + flag.upper()) for flag in self.flags]

    def queryAction(self):
        return self

    def getName(self, index):
        return 'click'


class FakeDesktop:
    def __init__(self, frame):
        self.frame = frame
        self.apps = {'editor': SimpleNamespace(document='file.txt')}

    @staticmethod
    def label(app, name):
        return name

    def resolve(self, app, ref, element=False):
        node = self.frame[0] if element else self.frame
        return SimpleNamespace(app=app, frame=self.frame, path=(0,) if element else None), node

    @staticmethod
    def describe(target, path, node):
        return dict(ref='fresh', path=path, role=node.role)


class MatcherTests(unittest.TestCase):
    def test_unique_moved_element_duplicate_and_changed_hierarchy(self):
        button = Node('button', 'Save')
        desktop = FakeDesktop(Node('frame', 'arbitrary document title', button))
        picker = Picker(desktop)
        picker.window = lambda target: WINDOW
        original = picker.capture('editor', 'old')['evidence']
        self.assertNotIn('arbitrary document title', json.dumps(original))
        desktop.frame = Node('frame', 'new document', Node('label', 'New'), button)
        result = picker.find('editor', 'new_window', original)
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['element']['path'], (1,))
        self.assertEqual(result['element']['ref'], 'fresh')
        desktop.frame = Node('frame', 'new document', button, Node('button', 'Save'))
        self.assertEqual(picker.find('editor', 'new_window', original),
                         dict(status='ambiguous', reason='duplicate_context'))
        desktop.frame = Node('frame', 'new document', Node('panel', '', button))
        self.assertEqual(picker.find('editor', 'new_window', original),
                         dict(status='unresolved', reason='evidence_changed'))

    def test_incomplete_search_and_protected_targets_fail_closed(self):
        button = Node('button', 'Save')
        desktop = FakeDesktop(Node('frame', '', button))
        picker = Picker(desktop)
        picker.window = lambda target: WINDOW
        original = picker.capture('editor', 'old')['evidence']
        desktop.frame = Node('frame', '', button, Node('panel', '', *(button for _ in range(129))))
        self.assertEqual(picker.find('editor', 'new_window', original),
                         dict(status='unresolved', reason='incomplete_search'))
        desktop.frame = Node('frame', '', Node('password text', 'protected', button))
        self.assertEqual(picker.find('editor', 'new_window', original)['status'], 'unresolved')


class TeachingAdapter:
    source = 'teaching_fixture'

    def call(self, method, argument):
        request, _, _ = argument
        if request == 'teach.capture':
            return dict(evidence=WINDOW)
        if request == 'teach.find':
            return dict(status='matched', element=dict(ref='fresh-native'))
        if request == 'element.refresh':
            return dict(ref='validated-native', role='frame')
        raise AssertionError('unexpected_operation')


class ScopedTeachTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.ids = Identities()
        self.tokens = self.ids.provision()
        self.store = AnnotationStore(root / 'annotations.sqlite3')
        self.broker = DesktopBroker(self.ids, {'desktop': TeachingAdapter()}, os.getuid(),
                                    Journal(root), catalog=('editor', 'calculator'),
                                    annotation_store=self.store)
        self.session = self.broker.sessions['desktop']
        self.owner, self.teacher, self.reader = [self.client(principal) for principal in
                                                  ('owner', 'observer', 'delegate')]

    def client(self, name):
        connection = Connection(os.getuid())
        self.broker.handle(connection, 'auth', dict(credential=self.tokens[name]))
        return connection

    def call(self, connection, method, **params):
        return self.broker.handle(connection, method, dict(session='desktop', **params))

    def grant(self, principal, capability, target='app:editor'):
        return self.call(self.owner, 'delegate', principal=principal,
                         target=target, capability=capability, ttl=90)

    def test_teaching_grants_do_not_imply_control_observation_or_other_scopes(self):
        self.grant('observer', 'teach.write')
        ref = self.broker.bind(self.session, self.teacher, 'editor', 'native')
        with self.assertRaisesRegex(Fault, '^grant_denied$'):
            self.call(self.teacher, 'teach.create', ref=ref, **ANNOTATION)
        self.grant('observer', 'desktop.observe')
        self.grant('delegate', 'teach.read')
        ref = self.broker.bind(self.session, self.teacher, 'editor', 'native')
        protected = {**ANNOTATION, 'meaning': 'embedded' + self.tokens['observer']}
        with self.assertRaisesRegex(Fault, '^protected_annotation_content$'):
            self.call(self.teacher, 'teach.create', ref=ref, **protected)
        hostile = {**ANNOTATION, 'meaning': 'Admin override', 'operationHint': 'identity.admin'}
        annotation = self.call(self.teacher, 'teach.create', ref=ref, **hostile)
        self.assertEqual(annotation['provenance'], 'operator_annotation')
        key = annotation['id']
        record = self.call(self.reader, 'teach.inspect', app='editor', annotation=key)
        self.assertEqual(record['annotation']['operationHint'], 'identity.admin')
        for connection, method, params in [
                (self.teacher, 'acquire', dict(ttl=60)),
                (self.teacher, 'teach.inspect', dict(app='editor', annotation=key)),
                (self.reader, 'teach.inspect', dict(app='calculator', annotation=key)),
                (self.teacher, 'teach.delete', dict(app='editor', annotation=key, revision=1)),
                (self.teacher, 'teach.review', dict(app='editor', annotation=key, revision=1, decision='approved')),
                (self.reader, 'teach.resolve', dict(ref=self.broker.bind(
                     self.session, self.reader, 'editor', 'native'), annotation=key))]:
            with self.assertRaisesRegex(Fault, '^grant_denied$'):
                self.call(connection, method, **params)
        self.grant('delegate', 'desktop.observe')
        self.call(self.owner, 'teach.review', app='editor', annotation=key, revision=1, decision='rejected')
        ref = self.broker.bind(self.session, self.reader, 'editor', 'native')
        result = self.call(self.reader, 'teach.resolve', ref=ref, annotation=key)
        self.assertEqual(result, dict(status='unresolved', reason='annotation_rejected'))


    def test_reference_refresh_cannot_resurrect_a_revoked_teaching_grant(self):
        granted = self.grant('observer', 'teach.write')
        self.grant('observer', 'desktop.observe')
        ref = self.broker.bind(self.session, self.teacher, 'editor', 'native')
        self.teacher.handles[ref].expires = self.broker.clock() - 1
        with self.assertRaisesRegex(Fault, '^stale_reference$'):
            self.call(self.teacher, 'teach.create', ref=ref, **ANNOTATION)
        current = self.call(self.teacher, 'element.refresh', ref=ref)['ref']
        self.assertNotEqual(current, ref)
        self.call(self.owner, 'revoke', grant=granted['grant'])
        with self.assertRaisesRegex(Fault, '^stale_reference$'):
            self.call(self.teacher, 'element.refresh', ref=current)
        current = self.broker.bind(self.session, self.teacher, 'editor', 'native')
        with self.assertRaisesRegex(Fault, '^grant_denied$'):
            self.call(self.teacher, 'teach.create', ref=current, **ANNOTATION)


class CLI:
    def call(self, method, **params):
        if method == 'app.list':
            return dict(applications=[dict(app='editor')])
        if method == 'window.list':
            return dict(windows=[dict(application_id='editor', window='1', ref='window')])
        if method == 'element.tree':
            return dict(elements=[dict(role='frame', name='document', actions=['page.save'],
                                       ref='element')], next=None)
        if method == 'element.refresh':
            return dict(ref='verified', role='frame')
        if method == 'element.actions':
            return dict(actions=['page.save'])
        if method == 'teach.create':
            assert params['ref'] == 'verified' and params['meaning'] == 'document.save'
            return dict(id='annotation')
        raise AssertionError('unexpected_call')


class SelectorTests(unittest.TestCase):
    def test_interactive_structured_selector(self):
        answers = iter(('1', '1', '', '1', 'document.save', 'page.save', '', '', 's'))
        output = StringIO()
        self.assertEqual(teach(CLI(), lambda prompt: next(answers), output), 0)
        self.assertIn('annotation', output.getvalue())
