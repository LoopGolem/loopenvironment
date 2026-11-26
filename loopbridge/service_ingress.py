# SPDX-License-Identifier: Apache-2.0
"""Linux peer admission and Unix listener ownership for local ingress."""
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import socket
import stat
import struct

ACCESS_ACL = 'system.posix_acl_access'
DEFAULT_ACL = 'system.posix_acl_default'
UNIX_PATH_LIMIT = 108


def peer_identity(sock):
    credentials = struct.Struct('iII')  # Linux ucred: pid_t, uid_t, gid_t.
    return credentials.unpack(sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                               credentials.size))


def peer_uid(sock):
    return peer_identity(sock)[1]


def named_user_acl(uid, owner, user):
    """Linux ACL xattr with exactly one named user and no group/other access."""
    undefined = 0xffffffff
    entries = ((0x01, owner, undefined), (0x02, user, uid), (0x04, 0, undefined),
               (0x10, user, undefined), (0x20, 0, undefined))
    return struct.pack('<I', 2) + b''.join(struct.pack('<HHI', *entry) for entry in entries)


def read_acl(path, name=ACCESS_ACL):
    try:
        if isinstance(path, int):
            return os.getxattr(path, name)
        return os.getxattr(path, name, follow_symlinks=False)
    except OSError as error:
        if error.errno != errno.ENODATA:
            raise
        return None


def path_inode(info):
    return info.st_dev, info.st_ino


@dataclass(frozen=True)
class PeerAdmission:
    """Explicit OS peer UID allowlist; NOT a LoopBridge principal or grant."""

    service_uid: int
    allowed_uids: frozenset[int]

    def __post_init__(self):
        if (type(self.service_uid) is not int or self.service_uid < 0
                or type(self.allowed_uids) is not frozenset
                or not self.allowed_uids
                or any(type(uid) is not int or uid < 0 for uid in self.allowed_uids)):
            raise ValueError('invalid_ingress_peer_policy')

    @classmethod
    def local_only(cls, service_uid):
        return cls(service_uid, frozenset((service_uid,)))

    def permits(self, uid):
        return type(uid) is int and uid in self.allowed_uids


@dataclass(frozen=True)
class IngressLayout:
    """Lexical separation contract, not a replacement for OS ownership checks."""

    public_socket: Path
    private_root: Path

    def __post_init__(self):
        paths = (self.public_socket, self.private_root)
        if (any(not isinstance(path, Path) or not path.is_absolute()
                or '..' in path.parts or path == Path(path.anchor) for path in paths)
                or self.public_socket == self.private_root
                or self.private_root in self.public_socket.parents):
            raise ValueError('invalid_ingress_layout')


@contextmanager
def managed_ingress_listener(layout):
    """D3 same-UID lab listener. Does not provision host ownership or ACLs.

    Requires a pre-existing owner-private parent. Never removes an endpoint
    that was present before this context, and only cleans up its own socket.
    """
    if not isinstance(layout, IngressLayout):
        raise ValueError('invalid_ingress_layout')
    parent = layout.public_socket.parent
    info = parent.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError('unsafe_ingress_directory')
    if (parent.resolve(strict=True) == layout.private_root.resolve(strict=True)
            or layout.private_root.resolve(strict=True) in parent.resolve(strict=True).parents):
        raise ValueError('invalid_ingress_layout')
    with bound_listener(layout.public_socket) as listener:
        yield listener


@contextmanager
def bound_listener(endpoint, prepare=None, *, backlog=8):
    """Apply policy before listen; preserve occupied or replaced paths."""
    if len(os.fsencode(endpoint)) >= UNIX_PATH_LIMIT:
        raise ValueError('ingress_socket_path_too_long')
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(endpoint))
        inode = path_inode(endpoint.lstat())
        try:
            endpoint.chmod(0o600)
            if prepare is not None:
                prepare(endpoint)
            listener.listen(backlog)
            yield listener
        finally:
            listener.close()
            try:
                current = endpoint.lstat()
            except FileNotFoundError:
                pass
            else:
                if stat.S_ISSOCK(current.st_mode) and path_inode(current) == inode:
                    endpoint.unlink()


@dataclass(frozen=True)
class CrossUIDIngress:
    directory: Path
    private_root: Path
    policy: PeerAdmission

    def __post_init__(self):
        IngressLayout(self.directory / 'session.sock', self.private_root)
        if (not isinstance(self.policy, PeerAdmission) or self.policy.service_uid != os.geteuid()
                or not 0 < self.policy.service_uid < 0xffffffff
                or len(self.policy.allowed_uids) != 1
                or not 0 < self.client_uid < 0xffffffff
                or self.client_uid == self.policy.service_uid
                or self.directory in (self.private_root, *self.private_root.parents)):
            raise ValueError('invalid_cross_uid_ingress')

    @property
    def client_uid(self):
        return next(iter(self.policy.allowed_uids))

    def validate(self):
        info = self.directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != self.policy.service_uid
                or info.st_gid != os.getegid() or stat.S_IMODE(info.st_mode) != 0o710
                or self.directory.resolve(strict=True) != self.directory
                or self.private_root.resolve(strict=True) != self.private_root
                or read_acl(self.directory) != named_user_acl(self.client_uid, 7, 1)
                or read_acl(self.directory, DEFAULT_ACL) is not None):
            raise ValueError('unsafe_cross_uid_ingress_directory')
        return path_inode(info)

    @contextmanager
    def listen(self, endpoint):
        if endpoint.parent != self.directory:
            raise ValueError('invalid_cross_uid_endpoint')
        directory_inode = self.validate()

        def prepare(path):
            expected = named_user_acl(self.client_uid, 6, 2)
            os.setxattr(path, ACCESS_ACL, expected, follow_symlinks=False)
            info = path.lstat()
            if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != self.policy.service_uid
                    or info.st_gid != os.getegid() or stat.S_IMODE(info.st_mode) != 0o620
                    or read_acl(path) != expected or self.validate() != directory_inode):
                raise ValueError('unsafe_cross_uid_ingress_socket')

        with bound_listener(endpoint, prepare) as listener:
            yield listener
