#!/usr/bin/python3
# SPDX-License-Identifier: Apache-2.0
"""Build or verify an unprivileged staging release from an explicit Git revision."""
import argparse
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = Path('deploy/loopbridge/launcher.py')
SOURCES = ('tools/private_wayland_effects.c', 'tools/private_wayland_stream.c')
VERIFIER = runpy.run_path(str(ROOT / LAUNCHER))


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def build(revision, output):
    commit = git('rev-parse', '--verify', '--end-of-options', revision + '^{commit}').decode().strip()
    archive = git('archive', '--format=tar', commit, 'loopbridge', 'LICENSE', str(LAUNCHER), *SOURCES)
    release = output / commit
    release.mkdir()
    try:
        with tempfile.TemporaryDirectory(dir=output) as folder:
            source = Path(folder)
            with tarfile.open(fileobj=BytesIO(archive)) as content:
                if any(not (member.isfile() or member.isdir()) for member in content.getmembers()):
                    raise ValueError('only regular files and directories may be packaged')
                content.extractall(source, filter='data')
            shutil.copytree(source / 'loopbridge', release / 'loopbridge')
            shutil.copyfile(source / LAUNCHER, release / 'launcher.py')
            shutil.copyfile(source / 'LICENSE', release / 'LICENSE')
            helpers = release / 'helpers'
            helpers.mkdir()
            for name, flags in (('effects', ['-lxkbcommon']), ('stream', ['-O2'])):
                subprocess.run(['/usr/bin/cc', '-Wall', '-Wextra', '-Werror',
                                str(source / 'tools' / f'private_wayland_{name}.c'),
                                '-lwayland-client', *flags, '-o', str(helpers / name)],
                               check=True, timeout=30, stdin=subprocess.DEVNULL)
                (helpers / name).chmod(0o755)
        for path in [release, *release.rglob('*')]:
            if path.is_dir():
                path.chmod(0o755)
            elif path.parent != helpers:
                path.chmod(0o644)
        files = VERIFIER['inventory'](release, os.geteuid(), os.getegid())
        raw = json.dumps(dict(version=1, revision=commit, files=files),
                         sort_keys=True, indent=2).encode() + b'\n'
        (release / 'release.json').write_bytes(raw)
        (release / 'release.json').chmod(0o644)
        digest = hashlib.sha256(raw).hexdigest()
        VERIFIER['verify_release'](release, digest, uid=os.geteuid(), gid=os.getegid())
        return release, digest
    except BaseException:
        shutil.rmtree(release)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('build')
    prepare.add_argument('revision')
    prepare.add_argument('output', type=Path, help='existing staging parent')
    verify = commands.add_parser('verify')
    verify.add_argument('release', type=Path)
    verify.add_argument('manifest_sha256')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('use an unprivileged staging account')
    os.umask(0o022)
    if args.command == 'build':
        release, digest = build(args.revision, args.output.resolve(strict=True))
        print(f'{digest}  {release / "release.json"}')
    else:
        VERIFIER['verify_release'](args.release, args.manifest_sha256,
                                   uid=os.geteuid(), gid=os.getegid())
        print(f'{args.release.name} verified')


if __name__ == '__main__':
    main()
