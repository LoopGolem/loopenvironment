#!/usr/bin/python3
# SPDX-License-Identifier: Apache-2.0
"""Validate and run a locally approved, root-controlled LoopBridge release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

RELEASES = Path('/opt/loopbridge/releases')
REVISION = re.compile('[0-9a-f]{40}')
SHA256 = re.compile('[0-9a-f]{64}')
MANIFEST = 'release.json'
HELPERS = ('helpers/effects', 'helpers/stream')
SMOKE_OPERATIONS = ('start', 'list', 'stop')
SMOKE_ADMIN_ACTIONS = tuple('admin-smoke-' + operation for operation in SMOKE_OPERATIONS)
SMOKE_CLIENT_ACTIONS = tuple('smoke-' + operation + '-client' for operation in SMOKE_OPERATIONS)
REQUIRED = {'launcher.py', 'LICENSE', 'loopbridge/__init__.py',
            'loopbridge/private_session.py', 'loopbridge/private_dbus.conf',
            'loopbridge/service_admin.py', *HELPERS}


class ReleaseError(ValueError):
    pass


def inspect_path(path, uid, gid):
    info = path.lstat()
    if (info.st_uid != uid or info.st_gid != gid or info.st_mode & 0o7022
            or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))):
        raise ReleaseError('unsafe release path ownership or mode')
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        raise ReleaseError('unsafe release file link count')
    return info


def inspect_helper(path):
    with path.open('rb') as stream:
        elf = stream.read(20)
    if (len(elf) != 20 or elf[:6] != b'\x7fELF\x02\x01' or elf[18:20] != b'\x3e\x00'
            or stat.S_IMODE(path.lstat().st_mode) != 0o755
            or os.statvfs(path).f_flag & os.ST_NOEXEC or not os.access(path, os.X_OK)):
        raise ReleaseError('invalid or non-executable x86-64 release helper')


def inventory(release, uid, gid):
    if not stat.S_ISDIR(inspect_path(release, uid, gid).st_mode):
        raise ReleaseError('release directory required')
    hashes = {}
    for path in release.rglob('*'):
        info = inspect_path(path, uid, gid)
        name = path.relative_to(release).as_posix()
        if stat.S_ISREG(info.st_mode) and name != MANIFEST:
            with path.open('rb') as stream:
                hashes[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    if not set(HELPERS) <= hashes.keys():
        raise ReleaseError('a required release helper is missing')
    if not REQUIRED <= hashes.keys():
        raise ReleaseError('incomplete release')
    for name in HELPERS:
        inspect_helper(release / name)
    return hashes


def unique_keys(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ReleaseError('duplicate release manifest entry')
    return result


def verify_release(release, digest, *, uid=0, gid=0):
    if not REVISION.fullmatch(release.name) or not SHA256.fullmatch(digest):
        raise ReleaseError('invalid release revision or approved checksum')
    checksums = inventory(release, uid, gid)
    manifest = release / MANIFEST
    info = inspect_path(manifest, uid, gid)
    if not stat.S_ISREG(info.st_mode) or info.st_size > 128 * 1024:
        raise ReleaseError('invalid release manifest')
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ReleaseError('release manifest differs from the approved checksum')
    if json.loads(raw, object_pairs_hook=unique_keys) != {
            'version': 1, 'revision': release.name, 'files': checksums}:
        raise ReleaseError('release manifest does not match the file inventory')


def require_root_directories(paths):
    for path in paths:
        if not stat.S_ISDIR(inspect_path(path, 0, 0).st_mode):
            raise ReleaseError('root-controlled directory required')


def service_account():
    import grp
    import pwd

    account = pwd.getpwnam('loopbridge-svc')
    group = grp.getgrnam('loopbridge-svc')
    if not account.pw_uid or not account.pw_gid or group.gr_gid != account.pw_gid:
        raise ReleaseError('dedicated service account and group required')
    return account


def start_service(release, client_uid):
    import pwd

    account = service_account()
    if (not account.pw_uid or os.getuid() != os.geteuid() or os.geteuid() != account.pw_uid
            or os.getgid() != os.getegid() or os.getegid() != account.pw_gid):
        raise ReleaseError('dedicated service user and group required')
    if not 0 < client_uid < 0xffffffff or pwd.getpwuid(client_uid).pw_uid != client_uid:
        raise ReleaseError('invalid configured client UID')
    runtime = Path('/run/loopbridge-private')
    ingress = Path('/run/loopbridge-ingress')
    state = Path('/var/lib/loopbridge')
    require_root_directories(set(runtime.parents) | set(ingress.parents) | set(state.parents))
    os.umask(0o077)
    sys.path.insert(0, str(release))
    from loopbridge.private_session import manage
    from loopbridge.service_bootstrap import HardenedService
    from loopbridge.service_ingress import CrossUIDIngress, PeerAdmission

    policy = PeerAdmission(account.pw_uid, frozenset((client_uid,)))
    profile = HardenedService(CrossUIDIngress(ingress, runtime, policy), state, release / 'helpers')
    manage(runtime, hardened=profile)


def administrative_action(release, digest, action, observer_verifier=None, session_id=None):
    # Only the approved installed release reaches this dispatch.
    sys.path.insert(0, str(release))
    from loopbridge import service_admin
    account = service_account()
    if action == 'ready-client':
        service_admin.ready_client(account.pw_uid, account.pw_gid)
        return
    if action in SMOKE_CLIENT_ACTIONS:
        from loopbridge.service_smoke import smoke_client
        smoke_client(account.pw_uid, account.pw_gid, action.removeprefix('smoke-').removesuffix('-client'),
                     observer_verifier, session_id)
        return
    service_admin.require_root()
    require_root_directories(set(service_admin.ADMIN.parents)
                             | set(service_admin.CREDENTIALS.parents)
                             | set(service_admin.STATE.parents)
                             | set(service_admin.RUNTIME.parents))
    if action == 'admin-init':
        service_admin.admin_initialize(account.pw_uid, account.pw_gid)
        print('administrative bootstrap initialized')
    elif action == 'admin-ready':
        service_admin.admin_ready(release, digest, account.pw_uid, account.pw_gid)
        print('authenticated empty manager ready')
    elif action in SMOKE_ADMIN_ACTIONS:
        from loopbridge.service_smoke import admin_smoke
        admin_smoke(release, digest, account.pw_uid, account.pw_gid, action.removeprefix('admin-smoke-'),
                    observer_verifier, session_id)
    else:
        raise ReleaseError('unsupported administrative action')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--client-uid', type=int)
    parser.add_argument('--observer-verifier')
    parser.add_argument('--session-id')
    parser.add_argument('--action', choices=('serve', 'verify-installed', 'admin-init', 'admin-ready', 'ready-client',
                                             *SMOKE_ADMIN_ACTIONS, *SMOKE_CLIENT_ACTIONS),
                        default='serve')
    args = parser.parse_args()
    try:
        script = Path(__file__).absolute()
        release = script.parent
        if not sys.flags.isolated or not sys.dont_write_bytecode or release.parent != RELEASES:
            raise ReleaseError('isolated Python and a versioned installed release required')
        require_root_directories(release.parents)
        verify_release(release, args.manifest_sha256)
        if (args.action not in (*SMOKE_ADMIN_ACTIONS, *SMOKE_CLIENT_ACTIONS)
                and (args.observer_verifier is not None or args.session_id is not None)):
            raise ReleaseError('smoke arguments require a smoke action')
        if args.action == 'serve':
            if args.client_uid is None:
                raise ReleaseError('configured client UID required')
            start_service(release, args.client_uid)
        else:
            if args.client_uid is not None:
                raise ReleaseError('client UID is only valid in service mode')
            if args.action == 'verify-installed':
                print('installed release verified')
            else:
                administrative_action(release, args.manifest_sha256, args.action,
                                      args.observer_verifier, args.session_id)
    except ReleaseError as error:
        print(f'loopbridge: {error}', file=sys.stderr)
        return 1
    except (ImportError, OSError, ValueError, RuntimeError, KeyError, RecursionError):
        print('loopbridge: release or hardened service bootstrap failed', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
