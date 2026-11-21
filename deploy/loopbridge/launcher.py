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
REQUIRED = {'launcher.py', 'LICENSE', 'loopbridge/__init__.py',
            'loopbridge/private_session.py', 'loopbridge/private_dbus.conf', *HELPERS}


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


def start_service(release, client_uid):
    import grp
    import pwd

    account = pwd.getpwnam('loopbridge-svc')
    group = grp.getgrnam('loopbridge-svc')
    if (not account.pw_uid or os.getuid() != os.geteuid() or os.geteuid() != account.pw_uid
            or os.getgid() != os.getegid() or os.getegid() != account.pw_gid
            or group.gr_gid != account.pw_gid):
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--client-uid', type=int, required=True)
    args = parser.parse_args()
    try:
        script = Path(__file__).absolute()
        release = script.parent
        if not sys.flags.isolated or not sys.dont_write_bytecode or release.parent != RELEASES:
            raise ReleaseError('isolated Python and a versioned installed release required')
        require_root_directories(release.parents)
        verify_release(release, args.manifest_sha256)
        start_service(release, args.client_uid)
    except ReleaseError as error:
        print(f'loopbridge: {error}', file=sys.stderr)
        return 1
    except (ImportError, OSError, ValueError, RuntimeError, KeyError, RecursionError):
        print('loopbridge: release or hardened service bootstrap failed', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
