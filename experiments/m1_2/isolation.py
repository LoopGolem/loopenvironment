# SPDX-License-Identifier: Apache-2.0
"""Fail-closed, rootless lab client profile; never mounts a session endpoint."""
from pathlib import Path
import os
import subprocess


def command(socket_dir):
    source = Path(__file__).resolve().parent
    return ['/usr/bin/bwrap', '--unshare-all', '--unshare-user', '--disable-userns',
            '--assert-userns-disabled', '--die-with-parent', '--new-session',
            '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
            '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
            '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/run',
            '--ro-bind', str(source), '/app', '--ro-bind', str(socket_dir), '/bridge',
            '--chdir', '/app', '--clearenv', '--setenv', 'PATH', '/usr/bin',
            '--cap-drop', 'ALL', '--', '/usr/bin/python3', '-B', '/app/client.py']


def launch(socket_dir):
    # stdin is the only provisioning descriptor; no token in argv, env or disk.
    # stdout/stderr are private pipes, not a controlling graphical terminal.
    return subprocess.Popen(command(socket_dir), stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            close_fds=True, env={'PATH': '/usr/bin'})


def namespaces():
    return {k: os.readlink('/proc/self/ns/' + k) for k in ('user', 'mnt', 'pid', 'net', 'ipc')}
