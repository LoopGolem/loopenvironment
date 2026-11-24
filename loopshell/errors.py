# SPDX-License-Identifier: Apache-2.0
"""Stable console errors with no remote or user-provided detail."""
from enum import Enum, auto


class Error(Enum):
    INVALID_COMMAND = auto()
    UNKNOWN_COMMAND = auto()
    INPUT_LIMIT = auto()
    DISCONNECTED = auto()
    PEER_MISMATCH = auto()
    AUTHENTICATION = auto()
    OWNER_CREDENTIAL = auto()
    PERMISSION = auto()
    SESSION_UNAVAILABLE = auto()
    INVALID_RESPONSE = auto()
    TIMEOUT = auto()
    UNAVAILABLE = auto()
    REMOTE_FAILURE = auto()


class ShellError(Exception):
    def __init__(self, error):
        self.error = error
        super().__init__(error.name)
