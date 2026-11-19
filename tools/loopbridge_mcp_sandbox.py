# SPDX-License-Identifier: Apache-2.0
"""Start a stdio MCP adapter with only one Bridge endpoint and one credential."""
import argparse
import os
from pathlib import Path
import stat

ROOT = Path(__file__).resolve().parents[1]


def sandbox(socket_path, token_file):
    endpoint = socket_path.absolute()
    credential = token_file.absolute()
    if (endpoint.name != 'control.sock' or endpoint.is_symlink() or not endpoint.is_socket()
            or not stat.S_ISREG(credential.lstat().st_mode)):
        raise ValueError('invalid_client_mount')
    # Mount only the socket inode, not the directory above it.
    return ['/usr/bin/bwrap', '--unshare-all', '--unshare-user', '--disable-userns',
            '--assert-userns-disabled', '--die-with-parent', '--new-session',
            '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
            '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
            '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
            '--ro-bind', str(ROOT / 'loopbridge'), '/app/loopbridge',
            '--ro-bind', str(endpoint), '/bridge/control.sock',
            '--ro-bind', str(credential), '/identity/token', '--chdir', '/app',
            '--clearenv', '--setenv', 'PATH', '/usr/bin', '--cap-drop', 'ALL', '--',
            '/usr/bin/python3', '-B', '-m', 'loopbridge.mcp',
            '--socket', '/bridge/control.sock', '--token-file', '/identity/token']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', type=Path, required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    args = parser.parse_args()
    argv = sandbox(args.socket, args.token_file)
    os.closerange(3, os.sysconf('SC_OPEN_MAX'))
    os.execve(argv[0], argv, {'PATH': '/usr/bin'})


if __name__ == '__main__':
    main()
