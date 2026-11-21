# SPDX-License-Identifier: Apache-2.0
"""Fixed D4.2C administration local to a verified installed launcher."""
from contextlib import suppress
import fcntl
from pathlib import Path
import re
import subprocess

from . import service_admin as admin
from .identity import Identities, VERIFIER
from .presentation import CAPABILITY
from .private_session import INSTANCE_ID, NS
from .protocol import Fault
from .service import DESKTOP_SESSION

INGRESS = Path('/run/loopbridge-ingress')
GRANT_TTL = 180
EPOCH = re.compile('[0-9a-f]{32}')
ERRORS = (AssertionError, EOFError, Fault, KeyError, OSError, TypeError, ValueError)


def action_arguments(operation, observer_verifier, session_id):
    if operation == 'start' and observer_verifier and VERIFIER.fullmatch(observer_verifier) and session_id is None:
        return ('--observer-verifier', observer_verifier)
    if operation == 'list' and observer_verifier is None and session_id is None:
        return ()
    if operation == 'stop' and observer_verifier is None and session_id and INSTANCE_ID.fullmatch(session_id):
        return ('--session-id', session_id)
    raise ValueError('invalid_smoke_arguments')


def active_instances(manager):
    current = manager.call('private.list')['instances']
    if type(current) is not list:
        raise ValueError('invalid_smoke_instance_list')
    instances = []
    for status in current:
        instance_id, phase = status['id'], status['phase']
        if not INSTANCE_ID.fullmatch(instance_id) or phase not in ('ready', 'failed', 'stopped'):
            raise ValueError('invalid_smoke_instance')
        instances.append(dict(id=instance_id, phase=phase))
    return instances


def stop_instance(manager, instance_id):
    stopped = manager.call('private.stop', id=instance_id)
    archived = manager.call('private.status', id=instance_id)
    if (stopped['id'] != instance_id or stopped['phase'] != 'stopped' or stopped['exitCode'] != 0
            or stopped['blocked'] is not False or archived['id'] != instance_id
            or archived['phase'] != 'retired' or archived['blocked'] is not False
            or archived['cancellationAssumed'] is not False):
        raise ValueError('smoke_stop_not_confirmed')
    return dict(id=instance_id, phase='stopped', retired=True)


def seed_presentation(endpoint, token, uid, gid, instance_id):
    with admin.private_owner(endpoint, token, uid, gid) as owner:
        pin = owner.call('presentation.describe', session=DESKTOP_SESSION)
        if (pin['session'] != DESKTOP_SESSION or pin['privateId'] != instance_id
                or not EPOCH.fullmatch(pin['epoch']) or pin['state'] != 'available'
                or pin['input'] is not False):
            raise ValueError('smoke_presentation_unavailable')
        lease = owner.call('acquire', session=DESKTOP_SESSION, ttl=30)
        control = {key: lease[key] for key in ('epoch', 'generation')}
        control.update(session=DESKTOP_SESSION, lease=lease['id'])
        if owner.call('app.launch', **control, app='calculator')['status'] != 'confirmed':
            raise ValueError('smoke_calculator_unconfirmed')
        for capability in ('session.discover', CAPABILITY):
            owner.call('delegate', session=DESKTOP_SESSION, principal='observer',
                       capability=capability, target='*', ttl=GRANT_TTL)
        if owner.call('release', **control)['phase'] != 'idle':
            raise ValueError('smoke_control_not_idle')
    return {key: pin[key] for key in ('session', 'privateId', 'epoch')}


def smoke(runtime, ingress, token, uid, gid, operation, observer_verifier=None, session_id=None):
    action_arguments(operation, observer_verifier, session_id)
    manager_endpoint = runtime / 'manager.sock'
    if operation != 'start':
        with admin.private_owner(manager_endpoint, token, uid, gid, manager=True) as manager:
            if operation == 'list':
                return {'instances': active_instances(manager)}
            return stop_instance(manager, session_id)

    identities = Identities()
    session_owner = identities.provision()['owner']
    verifiers = identities.manifest()['verifiers']
    verifiers['observer'] = observer_verifier
    instance_id = None
    try:
        with admin.private_owner(manager_endpoint, token, uid, gid, manager=True) as manager:
            if active_instances(manager):
                raise ValueError('smoke_requires_empty_manager')
            started = manager.call('private.start', httpsHosts=[], credentialVerifiers=verifiers)
        if not INSTANCE_ID.fullmatch(started['id']):
            raise ValueError('invalid_smoke_instance')
        instance_id = started['id']
        endpoint = runtime / instance_id / 'runtime/socket/control.sock'
        public = ingress / (instance_id + '.sock')
        if (started['phase'] != 'ready' or started['blocked'] is not False
                or started['namespaces'] != dict.fromkeys(NS, True)
                or started['socket'] != str(endpoint) or started['ingressSocket'] != str(public)):
            raise ValueError('invalid_smoke_boundary')
        pin = seed_presentation(endpoint, session_owner, uid, gid, instance_id)
        return dict(**pin, ingressSocket=str(public), grantTtlSeconds=GRANT_TTL)
    except ERRORS:
        # The manager remains authoritative when a start reply was lost. The
        # operator can list active IDs and explicitly stop the affected instance.
        if instance_id is not None:
            with suppress(*ERRORS), admin.private_owner(
                    manager_endpoint, token, uid, gid, manager=True) as manager:
                stop_instance(manager, instance_id)
        raise


def admin_smoke(release, digest, uid, gid, operation, observer_verifier, session_id):
    arguments = action_arguments(operation, observer_verifier, session_id)
    admin.require_root()
    admin.protect_admin_process()
    with admin.protected_directory(admin.ADMIN, 0, 0) as admin_fd:
        fcntl.flock(admin_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        data = admin.checked_owner_data(admin_fd)
        try:
            result = admin.run_service_client(
                release, digest, uid, gid, data, 'smoke-' + operation + '-client',
                arguments=arguments, stdout=subprocess.PIPE, timeout=150)
        except subprocess.SubprocessError:
            raise ValueError('smoke_admin_timeout_inspect_active_instances') from None
    if result.returncode != 0:
        raise ValueError('smoke_admin_failed_inspect_active_instances')
    print(result.stdout.decode('ascii'), end='')


def smoke_client(uid, gid, operation, observer_verifier, session_id):
    token = admin.service_client_token(uid, gid)
    try:
        result = smoke(admin.RUNTIME, INGRESS, token, uid, gid, operation, observer_verifier, session_id)
    except ERRORS:
        raise ValueError('smoke_rpc_failed') from None
    print(admin.json_bytes(result).decode('ascii'), end='')
