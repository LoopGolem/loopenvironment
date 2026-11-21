# SPDX-License-Identifier: Apache-2.0
"""Fixed diagnostic values for the private manager and installed admin client."""
from enum import StrEnum


class Phase(StrEnum):
    ADMIN_BOOTSTRAP = 'admin_bootstrap'
    ADMIN_CLIENT_FAILED = 'admin_client_failed'
    ADMIN_CLIENT_TIMEOUT = 'admin_client_timeout'
    MANAGER_PREFLIGHT = 'manager_preflight'
    MANAGER_NOT_EMPTY = 'manager_not_empty'
    MANAGER_LIST = 'manager_list'
    START_REJECTED = 'start_rejected'
    START_REPLY_LOST = 'start_reply_lost'
    MANAGER_START_UNCLASSIFIED = 'manager_start_unclassified'
    STATE_PREPARE = 'state_prepare'
    DESKTOP_STARTUP = 'desktop_startup'
    DESKTOP_DISPLAY = 'desktop_display'
    DESKTOP_BROKER = 'desktop_broker'
    DESKTOP_BOUNDARY = 'desktop_boundary'
    RELAY_PUBLICATION = 'relay_publication'
    PRESENTATION = 'presentation'
    CONTROL_ACQUIRE = 'control_acquire'
    CALCULATOR = 'calculator'
    GRANTS = 'grants'
    CONTROL_RELEASE = 'control_release'
    CLEANUP = 'cleanup'


class Cleanup(StrEnum):
    NOT_ATTEMPTED = 'not_attempted'
    CONFIRMED = 'confirmed'
    UNCONFIRMED = 'unconfirmed'


class Diagnostic(RuntimeError):
    def __init__(self, phase, cleanup=Cleanup.NOT_ATTEMPTED):
        self.phase = Phase(phase)
        self.cleanup = Cleanup(cleanup)
        super().__init__(f'loopbridge: phase={self.phase} cleanup={self.cleanup}')

    @classmethod
    def from_child(cls, data):
        # Only a single exact, finite record is accepted. Never relay child output.
        if not data or len(data) > 100:
            return None
        try:
            prefix, phase, cleanup = data.decode('ascii').split()
            if prefix == 'loopbridge:':
                diagnostic = cls(phase.removeprefix('phase='), cleanup.removeprefix('cleanup='))
                if data == (str(diagnostic) + '\n').encode('ascii'):
                    return diagnostic
        except ValueError:
            pass
        return None


STARTUP_PHASES = frozenset((Phase.STATE_PREPARE, Phase.DESKTOP_STARTUP, Phase.DESKTOP_DISPLAY,
                            Phase.DESKTOP_BROKER, Phase.DESKTOP_BOUNDARY, Phase.RELAY_PUBLICATION))

# Private supervisor readiness pipe. These are the only failure records the
# manager accepts from that pipe.
READINESS_ERRORS = {
    f'error:{phase}\n'.encode('ascii'): phase
    for phase in (Phase.DESKTOP_DISPLAY, Phase.DESKTOP_BROKER, Phase.DESKTOP_BOUNDARY)
}
