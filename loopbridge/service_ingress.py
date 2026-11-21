# SPDX-License-Identifier: Apache-2.0
"""D2 local ingress contract; does not configure a cross-UID service or filesystem."""
from dataclasses import dataclass
from pathlib import Path


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
