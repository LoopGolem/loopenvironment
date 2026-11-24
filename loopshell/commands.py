# SPDX-License-Identifier: Apache-2.0
"""Versioned grammar for a single line of typed LoopShell commands."""
from dataclasses import dataclass
from enum import Enum
import re

from .errors import Error, ShellError

GRAMMAR_VERSION = 3
MAX_INPUT = 256
# Current Bridge session IDs are short logical names, distinct from credentials.
SESSION_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,31}')
UNAVAILABLE_GROUPS = frozenset(('agent', 'agents', 'mission', 'missions', 'system',
                                'acquire', 'control', 'lease'))


class Action(Enum):
    HELP = 'help'
    CLEAR = 'clear'
    EXIT = 'exit'
    LIST = 'sessions list'
    STATUS = 'session status'
    OBSERVE = 'session observe'
    ACTIVITY = 'session activity'

    @property
    def remote(self):
        return self in (Action.LIST, Action.STATUS)


@dataclass(frozen=True)
class Command:
    action: Action
    session: str | None = None


def parse(line):
    if len(line) > MAX_INPUT:
        raise ShellError(Error.INPUT_LIMIT)
    if any(char != '\t' and not ' ' <= char <= '~' for char in line):
        raise ShellError(Error.INVALID_COMMAND)
    words = line.split()
    if not words:
        return None
    if words[0] in UNAVAILABLE_GROUPS:
        raise ShellError(Error.UNAVAILABLE)

    for action in Action:
        prefix = action.value.split()
        if words[:len(prefix)] != prefix:
            continue
        args = words[len(prefix):]
        if action in (Action.STATUS, Action.OBSERVE, Action.ACTIVITY):
            if len(args) != 1 or not SESSION_ID.fullmatch(args[0]):
                raise ShellError(Error.INVALID_COMMAND)
            return Command(action, args[0])
        if args:
            raise ShellError(Error.INVALID_COMMAND)
        return Command(action)
    raise ShellError(Error.UNKNOWN_COMMAND)
