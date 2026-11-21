# SPDX-License-Identifier: Apache-2.0
"""D2 local ingress contract; does not configure a cross-UID service or filesystem."""
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import socket
import stat


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
    if len(os.fsencode(layout.public_socket)) >= 108:
        raise ValueError('ingress_socket_path_too_long')
    with socket.socket(socket.AF_UNIX) as listener:
        created = False
        inode = None
        try:
            # bind() fails if an old file, symlink or active socket exists.
            # Never unlink the existing endpoint to "recover" automatically.
            listener.bind(str(layout.public_socket))
            created = True
            current = layout.public_socket.lstat()
            inode = (current.st_dev, current.st_ino)
            layout.public_socket.chmod(0o600)
            listener.listen(8)
            yield listener
        finally:
            if created:
                try:
                    current = layout.public_socket.lstat()
                except FileNotFoundError:
                    pass
                else:
                    # Protect a path replaced during the lifetime of the listener.
                    if (stat.S_ISSOCK(current.st_mode)
                            and inode is not None
                            and (current.st_dev, current.st_ino) == inode):
                        layout.public_socket.unlink()
