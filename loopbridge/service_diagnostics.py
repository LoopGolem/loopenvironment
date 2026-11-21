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
    BROKER_BOOTSTRAP = 'broker_bootstrap'
    BROKER_STORAGE = 'broker_storage'
    BROKER_ADAPTER = 'broker_adapter'
    BROKER_LISTENERS = 'broker_listeners'
    BROKER_READY = 'broker_ready'
    DESKTOP_BOUNDARY = 'desktop_boundary'
    DESKTOP_READY_EXITED = 'desktop_ready_exited'
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


class Reason(StrEnum):
    TIMEOUT = 'readiness_timeout'
    EOF = 'readiness_eof'
    FRAME = 'readiness_frame_limit'
    ADAPTER_SPAWN = 'adapter_spawn'
    ADAPTER_WORKER_INIT = 'adapter_worker_init'
    ADAPTER_IMPORT = 'adapter_import'
    ADAPTER_CONSTRUCT = 'adapter_construct'
    ADAPTER_STARTUP_CHANNEL = 'adapter_startup_channel'
    ADAPTER_STARTUP_EOF = 'adapter_startup_eof'
    ADAPTER_STARTUP_TIMEOUT = 'adapter_startup_timeout'


ADAPTER_REASONS = frozenset((Reason.ADAPTER_SPAWN, Reason.ADAPTER_WORKER_INIT, Reason.ADAPTER_IMPORT,
                            Reason.ADAPTER_CONSTRUCT, Reason.ADAPTER_STARTUP_CHANNEL,
                            Reason.ADAPTER_STARTUP_EOF, Reason.ADAPTER_STARTUP_TIMEOUT))


class Diagnostic(RuntimeError):
    def __init__(self, phase, cleanup=Cleanup.NOT_ATTEMPTED, *, reason=None):
        self.phase = Phase(phase)
        self.cleanup = Cleanup(cleanup)
        self.reason = Reason(reason) if reason is not None else None
        if self.reason in ADAPTER_REASONS and self.phase != Phase.BROKER_ADAPTER:
            self.reason = None
        message = f'loopbridge: phase={self.phase} cleanup={self.cleanup}'
        if self.reason is not None:
            message += f' reason={self.reason}'
        super().__init__(message)

    @classmethod
    def from_child(cls, data):
        # Only a single exact, finite record is accepted. Never relay child output.
        if not data or len(data) > 128:
            return None
        try:
            prefix, phase, cleanup, *details = data.decode('ascii').split()
            if prefix == 'loopbridge:' and len(details) <= 1:
                reason = details[0].removeprefix('reason=') if details else None
                diagnostic = cls(phase.removeprefix('phase='), cleanup.removeprefix('cleanup='), reason=reason)
                if data == (str(diagnostic) + '\n').encode('ascii'):
                    return diagnostic
        except ValueError:
            pass
        return None


READINESS_PHASES = frozenset((Phase.DESKTOP_DISPLAY, Phase.DESKTOP_BROKER, Phase.BROKER_BOOTSTRAP,
                              Phase.BROKER_STORAGE, Phase.BROKER_ADAPTER, Phase.BROKER_LISTENERS,
                              Phase.BROKER_READY, Phase.DESKTOP_BOUNDARY))
STARTUP_PHASES = READINESS_PHASES | {Phase.STATE_PREPARE, Phase.DESKTOP_STARTUP,
                                     Phase.DESKTOP_READY_EXITED, Phase.RELAY_PUBLICATION}


def readiness_error(phase, reason):
    return f'error:{phase}' + (f':{reason}' if reason is not None else '')


# Private supervisor readiness pipe. These are the only failure records the
# manager accepts from that pipe.
READINESS_PROGRESS = {f'stage:{phase}'.encode('ascii'): phase for phase in READINESS_PHASES}
READINESS_ERRORS = {
    readiness_error(phase, reason).encode('ascii'): (phase, reason)
    for phase in READINESS_PHASES
    for reason in (None, Reason.TIMEOUT, Reason.EOF, Reason.FRAME,
                   *(ADAPTER_REASONS if phase == Phase.BROKER_ADAPTER else ()))
}
