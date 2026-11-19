# SPDX-License-Identifier: Apache-2.0
import os
from pathlib import Path
import tempfile
import unittest

from loopbridge.adapter import Refused
from loopbridge.broker import Connection
from loopbridge.desktop_broker import DesktopBroker
from loopbridge.identity import Identities
from loopbridge.protocol import Fault
from loopbridge.service import Journal
from loopbridge.workspace import Workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        parent = tempfile.TemporaryDirectory()
        self.addCleanup(parent.cleanup)
        self.parent = Path(parent.name)
        root = self.parent / 'workspace'
        root.mkdir(mode=0o700)
        self.root = root
        self.files = Workspace(root)
        self.addCleanup(self.files.close)

    def test_write_read_and_verify(self):
        self.files.write('report.txt', 'proof\n')
        self.assertEqual(self.files.read('report.txt'), 'proof\n')
        self.assertEqual(self.files.confirm('report.txt', 'proof\n')['bytes'], 6)
        (self.root / 'folder').mkdir()
        self.assertEqual(self.files.listing(0)['entries'],
                         [{'kind': 'directory', 'name': 'folder'}, {'kind': 'file', 'name': 'report.txt'}])

    def test_traversal_absolute_and_subdirectory_paths_refused(self):
        for name in ('../outside', '/tmp/outside', '.', '..', 'folder/report', '\x00', ''):
            with self.assertRaises(ValueError):
                self.files.prepare(name, 'proof')

    def test_symlinks_hardlinks_and_fifo_refused(self):
        outside = self.parent / 'outside'
        outside.write_text('outside')
        (self.root / 'symlink').symlink_to(outside)
        os.link(outside, self.root / 'hardlink')
        os.mkfifo(self.root / 'pipes')
        for name in ('symlink', 'hardlink', 'pipes'):
            with self.assertRaises(OSError):
                self.files.read(name)
            with self.assertRaises(OSError):
                self.files.write(name, 'changed')
        self.assertEqual(outside.read_text(), 'outside')
        self.assertEqual(self.files.listing(0)['entries'], [])

    def test_directory_replacement_prevents_editor_path_resolution(self):
        self.files.write('report.txt', 'proof')
        self.root.rename(self.parent / 'moved')
        self.root.mkdir(mode=0o700)
        with self.assertRaises(OSError):
            self.files.file_path('report.txt')


class AdapterFixture:
    source = 'test_fixture'

    def __init__(self):
        self.text = ''
        self.sends = 0
        self.busy = False

    def call(self, method, arg=None):
        if method == 'desktop.read':
            name, app, params = arg
            if name == 'window.list':
                return dict(windows=[dict(ref='native-window', app=app)])
            if name == 'element.tree':
                return dict(elements=[dict(ref='native-element', editable=True)])
            if name == 'app.info':
                return dict(app=app)
            if name == 'element.get_text':
                return dict(text=self.text)
            raise Refused('unsupported_interface')
        if method == 'desktop.prepare':
            name, app, params = arg
            if name != 'element.set_text':
                raise Refused('unsupported_interface')
            self.prepared = params['text']
        if method == 'send':
            self.sends += 1
            self.text = self.prepared
        if method == 'confirm':
            if self.busy:
                raise TimeoutError
            return dict(characters=len(self.text))


class ScopedDesktopTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.journal = Journal(Path(folder.name))
        self.adapter = AdapterFixture()
        self.identities = Identities()
        self.credentials = self.identities.provision()
        self.time = 100
        self.broker = self.new_broker()
        self.owner, self.delegate, self.observer = [self.client(principal) for principal in
                                                   ('owner', 'delegate', 'observer')]
        for principal in ('delegate', 'observer'):
            self.grant(principal, 'session.discover', '*')
            self.grant(principal, 'desktop.observe', 'app:editor')
        self.control = self.grant('delegate', 'desktop.control', 'app:editor')
        self.grant('delegate', 'app.launch', 'app:calculator')

    def new_broker(self):
        return DesktopBroker(self.identities, {'desktop': self.adapter}, os.getuid(), self.journal,
                             lambda: self.time, ('editor', 'calculator'), True)

    def client(self, principal):
        connection = Connection(os.getuid())

        def call(method, **params):
            return self.broker.handle(connection, method, {'session': 'desktop', **params})

        self.broker.handle(connection, 'auth', dict(credential=self.credentials[principal]))
        return call

    def grant(self, principal, capability, target):
        return self.owner('delegate', principal=principal, capability=capability,
                          target=target, ttl=150)['grant']

    def lease(self):
        lease = self.delegate('acquire', ttl=150)
        return dict(lease=lease['id'], epoch=lease['epoch'], generation=lease['generation'])

    def element(self, client):
        window = client('window.list', app='editor')['windows'][0]['ref']
        return client('element.tree', ref=window, offset=0, depth=10)['elements'][0]['ref']

    def test_generic_scope_success_and_denials(self):
        self.assertEqual(self.observer('app.list')['applications'], [{'app': 'editor'}])
        with self.assertRaisesRegex(Fault, '^grant_denied$'):
            self.delegate('window.list', app='calculator')
        with self.assertRaisesRegex(Fault, '^invalid_grant$'):
            self.grant('observer', 'workspace.write', 'workspace')
        lease = self.lease()
        observer_ref = self.element(self.observer)
        with self.assertRaisesRegex(Fault, '^grant_denied$'):
            self.observer('element.set_text', **lease, ref=observer_ref, text='report')
        with self.assertRaisesRegex(Fault, '^stale_reference$'):
            self.delegate('element.set_text', **lease, ref=observer_ref, text='report')
        ref = self.element(self.delegate)
        with self.assertRaisesRegex(Fault, '^grant_denied$'):
            self.delegate('element.invoke', **lease, ref=ref, action='page.save')
        refused = self.delegate('element.invoke', **lease, ref=ref, action='click')
        self.assertEqual(refused['status'], 'refused')
        self.assertEqual(self.adapter.sends, 0)
        result = self.delegate('element.set_text', **lease, ref=ref, text='report')
        self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(self.delegate('operation.status', operation=result['operation'])['status'], 'confirmed')
        with self.assertRaisesRegex(Fault, '^operation_unavailable$'):
            self.observer('operation.status', operation=result['operation'])
        self.assertEqual(self.observer('element.get_text', ref=self.element(self.observer))['text'], 'report')
        self.owner('revoke', grant=self.control)
        lease = self.lease()  # Another capability can still hold a lease.
        with self.assertRaisesRegex(Fault, '^grant_denied$'):
            self.delegate('element.set_text', **lease, ref=self.element(self.delegate), text='denied')
        self.assertEqual(self.adapter.sends, 1)

    def test_expired_reference_and_unknown_with_restart(self):
        lease = self.lease()
        ref = self.element(self.delegate)
        self.time += 20
        with self.assertRaisesRegex(Fault, '^stale_reference$'):
            self.delegate('element.set_text', **lease, ref=ref, text='report')
        self.adapter.busy = True
        result = self.delegate('element.set_text', **lease, ref=self.element(self.delegate), text='report')
        self.assertEqual(result['status'], 'unknown')
        self.broker = self.new_broker()
        self.owner = self.client('owner')
        self.assertEqual(self.owner('snapshot')['phase'], 'blocked')
        self.assertEqual(self.owner('operation.status', operation=result['operation'])['status'], 'unknown')
        with self.assertRaisesRegex(Fault, '^control_busy$'):
            self.owner('acquire', ttl=60)
        self.assertEqual(self.adapter.sends, 1)
