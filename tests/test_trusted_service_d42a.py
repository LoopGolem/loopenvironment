# SPDX-License-Identifier: Apache-2.0
"""Fixture integration for dedicated-service bootstrap, lifecycle and viewing."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from functools import partial
import json
import os
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from loopbridge.desktop_broker import DesktopBroker
from loopbridge.identity import Identities
from loopbridge.presentation import CAPABILITY, FRAME_BYTES, Presentation
from loopbridge.presentation_client import LiveConnection
from loopbridge.private_session import Instance, handle, manage, manager_socket, retired_status
from loopbridge.protocol import Fault, RPC
from loopbridge.service import DESKTOP_SESSION, Journal, serve
from loopbridge.service_bootstrap import (CREDENTIAL_NAME, HardenedService, VerifierRegistry,
                                         check_systemd_object, load_systemd_manifest,
                                         read_credential_manifest)
from loopbridge.service_ingress import (ACCESS_ACL, CrossUIDIngress, PeerAdmission, bound_listener,
                                       named_user_acl, peer_uid)
from loopbridge.service_relay import SessionRelay


class ServiceFixture(unittest.TestCase):
    def setUp(self):
        self.base = Path(self.enterContext(TemporaryDirectory(prefix='d4-')))
        self.runtime = self.base / 'run'
        self.state = self.base / 'state'
        self.ingress = self.base / 'ingress'
        self.helpers = self.base / 'helpers'
        for path in (self.runtime, self.state, self.ingress, self.helpers):
            path.mkdir(mode=0o700)
        self.client_uid = 65321 if os.geteuid() != 65321 else 65322
        policy = PeerAdmission(os.geteuid(), frozenset((self.client_uid,)))
        ingress = CrossUIDIngress(self.ingress, self.runtime, policy)
        self.profile = HardenedService(ingress, self.state, self.helpers)
        os.setxattr(self.ingress, ACCESS_ACL, named_user_acl(self.client_uid, 7, 1))
        self.identities = Identities()
        self.tokens = self.identities.provision()
        self.manifest = self.identities.manifest()

    def seed(self):
        path = self.state / 'verifiers.json'
        path.write_text('{"version":1,"manager":null,"used":[]}\n')
        path.chmod(0o600)
        return path

    @staticmethod
    def new_manifest():
        identities = Identities()
        identities.provision()
        return identities.manifest()


class BootstrapTests(ServiceFixture):
    def test_fixed_systemd_origin_required(self):
        for env in ({}, {'CREDENTIALS_DIRECTORY': str(self.base)}):
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(ValueError, 'missing_systemd_credentials'):
                    load_systemd_manifest()

    def test_load_readonly_service_owned_handoff_and_refuse_legacy_data(self):
        credentials = self.base / 'credentials'
        credentials.mkdir(mode=0o700)
        manifest = credentials / CREDENTIAL_NAME
        manifest.write_text(json.dumps(self.manifest))
        manifest.chmod(0o400)
        credentials.chmod(0o500)
        self.addCleanup(credentials.chmod, 0o700)
        uid = os.geteuid()
        with self.assertRaisesRegex(ValueError, 'unsafe_systemd_credential'):
            read_credential_manifest(credentials, uid)
        with patch('loopbridge.service_bootstrap.os.fstatvfs',
                   return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
            self.assertEqual(read_credential_manifest(credentials, uid), self.manifest)
            manifest.chmod(0o440)
            with self.assertRaisesRegex(ValueError, 'unsafe_systemd_credential_access'):
                read_credential_manifest(credentials, uid)
            manifest.chmod(0o600)
            manifest.write_text(json.dumps(self.tokens))
            manifest.chmod(0o400)
            with self.assertRaisesRegex(ValueError, 'invalid_service_manifest'):
                read_credential_manifest(credentials, uid)
            credentials.chmod(0o700)
            manifest.unlink()
            manifest.symlink_to(self.seed())
            credentials.chmod(0o500)
            with self.assertRaises(OSError):
                read_credential_manifest(credentials, uid)

    def test_root_owned_handoff_requires_exact_service_acl(self):
        uid = os.geteuid()
        with patch('loopbridge.service_bootstrap.os.fstatvfs',
                   return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
            for directory, mode, access in ((False, 0o100440, 4), (True, 0o040550, 5)):
                info = SimpleNamespace(st_mode=mode, st_uid=0, st_nlink=1)
                with (patch('loopbridge.service_bootstrap.os.fstat', return_value=info),
                      patch('loopbridge.service_bootstrap.read_acl') as acl):
                    acl.return_value = named_user_acl(uid, access, access)
                    check_systemd_object(3, directory, uid)
                    acl.return_value = named_user_acl(self.client_uid, access, access)
                    with self.assertRaisesRegex(ValueError, 'unsafe_systemd_credential_access'):
                        check_systemd_object(3, directory, uid)

    def test_missing_corrupt_or_exposed_registry_refuses_bootstrap(self):
        with self.assertRaises(FileNotFoundError):
            VerifierRegistry(self.state)
        registry = self.seed()
        registry.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'unsafe_verifier_registry'):
            VerifierRegistry(self.state)
        registry.chmod(0o600)
        registry.write_text('{"version":1,"version":1,"manager":null,"used":[]}\n')
        with self.assertRaisesRegex(ValueError, 'duplicate_key'):
            VerifierRegistry(self.state)

    def test_enrollment_survives_restart_and_disallows_manager_rollback(self):
        self.seed()
        registry = VerifierRegistry(self.state)
        registry.enroll_manager(self.manifest)
        enrolled = set(self.new_manifest()['verifiers'].values())
        self.assertTrue(registry.reserve_session(enrolled))

        restarted = VerifierRegistry(self.state)
        restarted.enroll_manager(self.manifest)
        self.assertFalse(restarted.reserve_session(enrolled))
        self.assertFalse(restarted.reserve_session(set(self.manifest['verifiers'].values())))
        replacement = self.new_manifest()
        restarted.enroll_manager(replacement)
        next_start = VerifierRegistry(self.state)
        next_start.enroll_manager(replacement)
        with self.assertRaisesRegex(ValueError, 'reused_manager_verifier'):
            next_start.enroll_manager(self.manifest)

    def test_uncertain_registry_sync_blocks_starts_and_recovers_conservatively(self):
        self.seed()
        registry = VerifierRegistry(self.state)
        registry.enroll_manager(self.manifest)
        verifiers = set(self.new_manifest()['verifiers'].values())
        with patch.object(Journal, 'sync', side_effect=OSError):
            with self.assertRaises(OSError):
                registry.reserve_session(verifiers)
        with self.assertRaisesRegex(OSError, 'verifier_registry_unavailable'):
            registry.reserve_session(set(self.new_manifest()['verifiers'].values()))
        self.assertFalse(VerifierRegistry(self.state).reserve_session(verifiers))

    def test_manager_refuses_incomplete_bootstrap_without_legacy_fallback(self):
        with (patch('loopbridge.private_session.protect_process'),
              patch('loopbridge.private_session.signal.signal'),
              patch.object(HardenedService, 'require_helpers'),
              patch('loopbridge.private_session.load_systemd_manifest') as systemd,
              patch('loopbridge.private_session.read_private') as legacy):
            systemd.side_effect = ValueError('missing_systemd_credentials')
            with self.assertRaisesRegex(ValueError, 'invalid_hardened_bootstrap'):
                manage(self.runtime, self.base / 'legacy.json', hardened=self.profile)
            with self.assertRaisesRegex(ValueError, 'missing_systemd_credentials'):
                manage(self.runtime, hardened=self.profile)
            systemd.side_effect = None
            systemd.return_value = self.manifest
            with self.assertRaises(FileNotFoundError):
                manage(self.runtime, hardened=self.profile)
            legacy.assert_not_called()
        self.assertFalse(list(self.runtime.iterdir()))
        self.assertFalse(list(self.ingress.iterdir()))

    def test_missing_installed_helpers_are_rejected(self):
        with self.assertRaises(FileNotFoundError):
            self.profile.validate(self.runtime)


class ManagedSessionTests(ServiceFixture):
    def setUp(self):
        super().setUp()
        self.seed()
        self.registry = VerifierRegistry(self.state)
        self.registry.enroll_manager(self.manifest)
        (self.state / 'sessions').mkdir(mode=0o700)
        self.instances = {}

    @contextmanager
    def admin(self, registry=None):
        service, peer = socket.socketpair()
        with ThreadPoolExecutor(1) as executor, service:
            work = executor.submit(handle, service, self.runtime, self.identities, self.instances,
                                   self.manifest, True, set(), hardened=self.profile,
                                   registry=registry or self.registry)
            with peer:
                rpc = RPC(peer)
                rpc.call('auth', credential=self.tokens['owner'])
                yield rpc
            work.result(timeout=3)

    def start_fixture(self, instance, manifest):
        self.assertFalse(list(self.ingress.iterdir()), 'published before Bridge readiness')
        sockets = instance.endpoint.parent
        sockets.mkdir(mode=0o700)
        instance.ingress.enter_context(bound_listener(instance.endpoint))
        instance.ingress.enter_context(bound_listener(sockets / 'relay.sock'))
        instance.process = Mock()
        instance.process.poll.return_value = None
        instance.process.wait.return_value = 0

    def test_replacement_uses_new_route_and_preserves_prior_journal_on_restart(self):
        first_verifiers = self.new_manifest()['verifiers']
        next_verifiers = self.new_manifest()['verifiers']
        self.addCleanup(lambda: [instance.stop() for instance in self.instances.values()])
        with patch.object(Instance, 'start_desktop', autospec=True, side_effect=self.start_fixture):
            with self.admin() as rpc:
                with self.assertRaisesRegex(Fault, 'invalid_session_verifiers'):
                    rpc.call('private.start')
                first = rpc.call('private.start', credentialVerifiers=first_verifiers)
                instance = self.instances[first['id']]
                old = instance.state
                old_ingress = Path(first['ingressSocket'])
                self.assertTrue(old_ingress.is_socket())
                self.assertEqual(Path(first['socket']), instance.endpoint)
                (instance.workspace / 'fixture.txt').write_text('possible effect')
                operation = 'a' * 32
                Journal(old).mark(DESKTOP_SESSION, operation)
                status = rpc.call('private.stop', id=first['id'])
                self.assertTrue(status['blocked'])
                self.assertFalse(old_ingress.exists())
                self.assertFalse(instance.root.exists())
                self.assertEqual((instance.workspace / 'fixture.txt').read_text(), 'possible effect')

            with self.admin(VerifierRegistry(self.state)) as rpc:
                archived = rpc.call('private.status', id=first['id'])
                self.assertEqual((archived['phase'], archived['unknownOperation']), ('retired', operation))
                self.assertNotIn('ingressSocket', archived)
                with self.assertRaisesRegex(Fault, 'reused_session_verifier'):
                    rpc.call('private.start', credentialVerifiers=first_verifiers)
                replacement = rpc.call('private.start', credentialVerifiers=next_verifiers)
                self.assertNotEqual(first['id'], replacement['id'])
                self.assertNotEqual(first['ingressSocket'], replacement['ingressSocket'])
                self.assertTrue(Path(replacement['ingressSocket']).is_socket())
                self.assertTrue(Journal(old).blocked(DESKTOP_SESSION))
                rpc.call('private.stop', id=replacement['id'])
        with self.assertRaisesRegex(Fault, 'private_session_unavailable'):
            retired_status(self.state, '../../private')

    def test_publication_failure_stops_private_bridge_and_consumes_verifiers(self):
        verifiers = self.new_manifest()['verifiers']
        started = []

        def conflict(instance, manifest):
            self.start_fixture(instance, manifest)
            incumbent = self.ingress / (instance.id + '.sock')
            incumbent.write_text('incumbent')
            started.append((instance, incumbent))

        with patch.object(Instance, 'start_desktop', autospec=True, side_effect=conflict):
            with self.admin() as rpc:
                with self.assertRaisesRegex(Fault, 'private_session_failed'):
                    rpc.call('private.start', credentialVerifiers=verifiers)
                instance, incumbent = started[0]
                self.assertEqual(incumbent.read_text(), 'incumbent')
                self.assertFalse(instance.root.exists())
                instance.process.stdin.close.assert_called_once()
                with self.assertRaisesRegex(Fault, 'reused_session_verifier'):
                    rpc.call('private.start', credentialVerifiers=verifiers)
        self.assertFalse(self.instances)

    def test_hardened_manager_never_removes_occupied_admin_path(self):
        endpoint = self.runtime / 'manager.sock'
        with bound_listener(endpoint):
            inode = endpoint.stat().st_ino
            with self.assertRaises(OSError):
                with manager_socket(self.runtime, endpoint, hardened=True):
                    self.fail('replaced an existing manager listener')
            self.assertEqual(endpoint.stat().st_ino, inode)


class RelayedViewerTests(ServiceFixture):
    def setUp(self):
        super().setUp()
        self.public = self.ingress / 'viewer.sock'
        self.now = 10
        self.spawned = []
        script = self.helpers / 'synthetic_capture'
        script.write_text(
            '#!/usr/bin/python3\nimport struct, sys, time\n'
            f'sys.stdout.buffer.write(struct.pack("!BQQ", 1, 1, 1) + b"\\xa7" * {FRAME_BYTES})\n'
            'sys.stdout.buffer.flush()\ntime.sleep(30)\n')
        script.chmod(0o700)
        self.presentation = Presentation('d' * 16, script)

        def peer_for_fixture(sock):
            return self.client_uid if Path(sock.getsockname()).parent == self.ingress else peer_uid(sock)

        def spawn(*args, **kwargs):
            proc = popen(*args, **kwargs)
            self.spawned.append(proc)
            return proc

        popen = subprocess.Popen
        self.enterContext(patch('loopbridge.presentation.subprocess.Popen', side_effect=spawn))
        self.enterContext(patch.dict(os.environ, {'XDG_RUNTIME_DIR': str(self.runtime),
                                                  'WAYLAND_DISPLAY': 'synthetic'}))
        self.enterContext(patch('loopbridge.service.Adapter'))
        self.enterContext(patch('loopbridge.desktop_broker.DesktopBroker',
                                partial(DesktopBroker, clock=lambda: self.now)))
        self.private = self.enterContext(serve(self.runtime, self.identities, 'desktop',
                                               session_state=self.state, presentation=self.presentation))
        self.enterContext(patch('loopbridge.service_relay.peer_uid', side_effect=peer_for_fixture))
        relay = SessionRelay(self.profile.ingress, self.public, self.private.with_name('relay.sock'))
        self.enterContext(relay.serve())
        self.owner = self.rpc(self.private)
        self.owner.call('auth', credential=self.tokens['owner'])

    def rpc(self, endpoint):
        sock = self.enterContext(closing(socket.socket(socket.AF_UNIX)))
        sock.settimeout(2)
        sock.connect(str(endpoint))
        return RPC(sock)

    def grant_view(self):
        return self.owner.call('delegate', session=DESKTOP_SESSION, principal='observer',
                               capability=CAPABILITY, target='*', ttl=10)['grant']

    def view(self, **pin):
        rpc = self.rpc(self.public)
        rpc.call('auth', credential=self.tokens['observer'])
        desc = rpc.call('presentation.describe', session=DESKTOP_SESSION)
        identity = {'private_id': desc['privateId'], 'epoch': desc['epoch'], **pin}
        viewer = LiveConnection(self.public, self.tokens['observer'], DESKTOP_SESSION, **identity)
        self.enterContext(closing(viewer.peer))
        viewer.connect()
        return viewer

    def test_uid_admission_grants_no_authority_and_refuses_owner_principal(self):
        rpc = self.rpc(self.public)
        with self.assertRaisesRegex(Fault, '^denied$'):
            rpc.call('discover')
        for token in ('synthetic-invalid', self.tokens['owner']):
            with self.assertRaisesRegex(Fault, '^denied$'):
                rpc.call('auth', credential=token)
        self.assertEqual(rpc.call('auth', credential=self.tokens['observer'])['principal'], 'observer')
        with self.assertRaisesRegex(Fault, 'grant_denied'):
            rpc.call('presentation.describe', session=DESKTOP_SESSION)
        self.grant_view()
        with self.assertRaisesRegex(Fault, 'presentation_identity_mismatch'):
            self.view(epoch='old')
        with self.assertRaisesRegex(Fault, '^denied$'):
            rpc.call('auth', credential=self.tokens['owner'])
        with self.assertRaisesRegex(Fault, '^denied$'):
            rpc.call('presentation.describe', session=DESKTOP_SESSION)

    def test_upgrade_stream_status_and_grant_revocation_through_relay(self):
        grant = self.grant_view()
        self.owner.call('acquire', session=DESKTOP_SESSION, ttl=20)
        viewer = self.view()
        self.assertEqual(next(viewer.packets()), (1, 1, b'\xa7' * FRAME_BYTES))
        owner_lease = self.presentation.session.lease
        self.owner.call('revoke', session=DESKTOP_SESSION, grant=grant)
        with self.assertRaises(EOFError):
            viewer.read(1)
        self.spawned[0].wait(timeout=2)
        self.assertEqual(viewer.reason(), 'revoked')
        self.assertEqual(self.presentation.session.lease, owner_lease)

    def test_viewer_exit_and_grant_expiry_end_capture_without_expiring_bearer(self):
        self.grant_view()
        first = self.view()
        next(first.packets())
        first.peer.close()
        self.spawned[0].wait(timeout=2)
        self.assertEqual(first.reason(), 'viewer_disconnected')

        second = self.view()
        next(second.packets())
        self.now = 21
        with self.assertRaises(EOFError):
            second.read(1)
        self.spawned[1].wait(timeout=2)
        self.assertEqual(second.reason(), 'grant_expired')
        with self.assertRaisesRegex(Fault, 'grant_denied'):
            self.view()

    def test_replacement_refuses_prior_bearer_and_presentation_identity(self):
        self.grant_view()
        first = self.rpc(self.public)
        first.call('auth', credential=self.tokens['observer'])
        previous = first.call('presentation.describe', session=DESKTOP_SESSION)
        next_identities = Identities()
        next_tokens = next_identities.provision()
        next_state = self.state / 'new'
        next_state.mkdir(mode=0o700)
        next_presentation = Presentation('e' * 16, self.presentation.helper)
        private = self.enterContext(serve(self.runtime / 'new', next_identities, 'desktop',
                                           session_state=next_state, presentation=next_presentation))
        endpoint = self.ingress / 'new.sock'
        relay = SessionRelay(self.profile.ingress, endpoint, private.with_name('relay.sock'))
        self.enterContext(relay.serve())
        owner = self.rpc(private)
        owner.call('auth', credential=next_tokens['owner'])
        owner.call('delegate', session=DESKTOP_SESSION, principal='observer',
                   capability=CAPABILITY, target='*', ttl=10)
        observer = self.rpc(endpoint)
        with self.assertRaisesRegex(Fault, '^denied$'):
            observer.call('auth', credential=self.tokens['observer'])
        observer.call('auth', credential=next_tokens['observer'])
        with self.assertRaisesRegex(Fault, 'presentation_identity_mismatch'):
            observer.call('presentation.open', session=DESKTOP_SESSION, privateId=previous['privateId'],
                          epoch=previous['epoch'])
