# SPDX-License-Identifier: Apache-2.0
"""Fixed D4.2C administration local to a verified installed launcher."""
import fcntl
from pathlib import Path
import re
import subprocess
import sys

from . import service_admin as admin
from .identity import Identities, VERIFIER
from .presentation import CAPABILITY
from .private_session import INSTANCE_ID, NS
from .protocol import Fault
from .service import DESKTOP_SESSION
from .service_diagnostics import Cleanup, Diagnostic, Phase, Reason, STARTUP_PHASES

INGRESS = Path('/run/loopbridge-ingress')
GRANT_TTL = 180
EPOCH = re.compile('[0-9a-f]{32}')
ERRORS = (AssertionError, AttributeError, EOFError, Fault, KeyError, OSError, RuntimeError,
          TypeError, ValueError)


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
    phase = Phase.PRESENTATION
    try:
        with admin.private_owner(endpoint, token, uid, gid) as owner:
            pin = owner.call('presentation.describe', session=DESKTOP_SESSION)
            if (pin['session'] != DESKTOP_SESSION or pin['privateId'] != instance_id
                    or not EPOCH.fullmatch(pin['epoch']) or pin['state'] != 'available'
                    or pin['input'] is not False):
                raise Diagnostic(phase)
            phase = Phase.CONTROL_ACQUIRE
            lease = owner.call('acquire', session=DESKTOP_SESSION, ttl=30)
            control = {key: lease[key] for key in ('epoch', 'generation')}
            control.update(session=DESKTOP_SESSION, lease=lease['id'])
            phase = Phase.CALCULATOR
            launch = owner.call('app.launch', **control, app='calculator')
            if launch['status'] != 'confirmed' or launch.get('session_blocked'):
                raise Diagnostic(phase)
            phase = Phase.GRANTS
            for capability in ('session.discover', CAPABILITY):
                owner.call('delegate', session=DESKTOP_SESSION, principal='observer',
                           capability=capability, target='*', ttl=GRANT_TTL)
            phase = Phase.CONTROL_RELEASE
            if owner.call('release', **control)['phase'] != 'idle':
                raise Diagnostic(phase)
    except ERRORS:
        raise Diagnostic(phase) from None
    return {key: pin[key] for key in ('session', 'privateId', 'epoch')}


def start_fault(error):
    if error.code == -32006 and isinstance(error.message, str) and error.message in STARTUP_PHASES:
        cleanup = Cleanup.UNCONFIRMED
        reason = None
        if type(error.data) is dict and error.data.keys() <= {'cleanup', 'reason'}:
            state = error.data.get('cleanup')
            if state == Cleanup.CONFIRMED:
                cleanup = Cleanup.CONFIRMED
            elif state == Cleanup.NOT_ATTEMPTED and error.message == Phase.STATE_PREPARE:
                cleanup = Cleanup.NOT_ATTEMPTED
            reason = error.data.get('reason')
            if not isinstance(reason, str) or reason not in tuple(Reason):
                reason = None
        return Diagnostic(error.message, cleanup, reason=reason)
    if (error.code, error.message) in ((-32700, 'parse_error'), (-32600, 'frame_limit')):
        return Diagnostic(Phase.START_REPLY_LOST, Cleanup.UNCONFIRMED)
    if (error.code == -32602 and error.message in ('invalid_https_hosts', 'invalid_session_verifiers',
                                                   'reused_session_verifier', 'scoped_credentials_disabled')
            or error.code == -32006 and error.message == 'private_session_limit'):
        return Diagnostic(Phase.START_REJECTED)
    # D4.2B collapses startup and relay errors into the same RPC fault.
    return Diagnostic(Phase.MANAGER_START_UNCLASSIFIED, Cleanup.UNCONFIRMED)


def smoke(runtime, ingress, token, uid, gid, operation, observer_verifier=None, session_id=None):
    action_arguments(operation, observer_verifier, session_id)
    manager_endpoint = runtime / 'manager.sock'
    if operation != 'start':
        try:
            with admin.private_owner(manager_endpoint, token, uid, gid, manager=True) as manager:
                if operation == 'list':
                    return {'instances': active_instances(manager)}
                return stop_instance(manager, session_id)
        except ERRORS:
            if operation == 'list':
                raise Diagnostic(Phase.MANAGER_LIST) from None
            raise Diagnostic(Phase.CLEANUP, Cleanup.UNCONFIRMED) from None

    identities = Identities()
    session_owner = identities.provision()['owner']
    verifiers = identities.manifest()['verifiers']
    verifiers['observer'] = observer_verifier
    instance_id = None
    phase = Phase.MANAGER_PREFLIGHT
    try:
        with admin.private_owner(manager_endpoint, token, uid, gid, manager=True) as manager:
            if active_instances(manager):
                raise Diagnostic(Phase.MANAGER_NOT_EMPTY)
            phase = Phase.START_REPLY_LOST
            try:
                started = manager.call('private.start', httpsHosts=[], credentialVerifiers=verifiers)
            except Fault as error:
                raise start_fault(error) from None
        if not INSTANCE_ID.fullmatch(started['id']):
            raise Diagnostic(phase, Cleanup.UNCONFIRMED)
        instance_id = started['id']
        phase = Phase.DESKTOP_STARTUP
        if started['phase'] != 'ready':
            raise Diagnostic(phase)
        phase = Phase.DESKTOP_BOUNDARY
        endpoint = runtime / instance_id / 'runtime/socket/control.sock'
        public = ingress / (instance_id + '.sock')
        if (started['blocked'] is not False
                or started['namespaces'] != dict.fromkeys(NS, True)
                or started['socket'] != str(endpoint) or started['ingressSocket'] != str(public)):
            raise Diagnostic(phase)
        phase = Phase.PRESENTATION
        pin = seed_presentation(endpoint, session_owner, uid, gid, instance_id)
        return dict(**pin, ingressSocket=str(public), grantTtlSeconds=GRANT_TTL)
    except ERRORS as error:
        if isinstance(error, Diagnostic):
            failure = error
        else:
            cleanup = Cleanup.UNCONFIRMED if phase == Phase.START_REPLY_LOST else Cleanup.NOT_ATTEMPTED
            failure = Diagnostic(phase, cleanup)
        # A lost reply leaves no verified ID to stop. The operator must list.
        if instance_id is None:
            raise failure from None
        try:
            with admin.private_owner(manager_endpoint, token, uid, gid, manager=True) as manager:
                stop_instance(manager, instance_id)
        except ERRORS:
            raise Diagnostic(failure.phase, Cleanup.UNCONFIRMED, reason=failure.reason) from None
        raise Diagnostic(failure.phase, Cleanup.CONFIRMED, reason=failure.reason) from None


def admin_smoke(release, digest, uid, gid, operation, observer_verifier, session_id):
    cleanup = Cleanup.NOT_ATTEMPTED if operation == 'list' else Cleanup.UNCONFIRMED
    try:
        arguments = action_arguments(operation, observer_verifier, session_id)
        admin.require_root()
        admin.protect_admin_process()
        with admin.protected_directory(admin.ADMIN, 0, 0) as admin_fd:
            fcntl.flock(admin_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            data = admin.checked_owner_data(admin_fd)
            try:
                result = admin.run_service_client(
                    release, digest, uid, gid, data, 'smoke-' + operation + '-client',
                    arguments=arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=150)
            except subprocess.TimeoutExpired:
                raise Diagnostic(Phase.ADMIN_CLIENT_TIMEOUT, cleanup) from None
    except Diagnostic:
        raise
    except ERRORS + (subprocess.SubprocessError,):
        raise Diagnostic(Phase.ADMIN_BOOTSTRAP) from None
    if result.returncode != 0:
        raise Diagnostic.from_child(result.stderr) or Diagnostic(Phase.ADMIN_CLIENT_FAILED, cleanup)
    try:
        output = result.stdout.decode('ascii')
    except UnicodeError:
        raise Diagnostic(Phase.ADMIN_CLIENT_FAILED, cleanup) from None
    print(output, end='')


def smoke_client(uid, gid, operation, observer_verifier, session_id):
    try:
        action_arguments(operation, observer_verifier, session_id)
        token = admin.service_client_token(uid, gid)
    except ERRORS:
        raise Diagnostic(Phase.ADMIN_BOOTSTRAP) from None
    result = smoke(admin.RUNTIME, INGRESS, token, uid, gid, operation, observer_verifier, session_id)
    print(admin.json_bytes(result).decode('ascii'), end='')


def report_smoke(action, *args):
    try:
        action(*args)
    except Diagnostic as error:
        print(error, file=sys.stderr)
        return 1
    return 0
