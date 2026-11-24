# SPDX-License-Identifier: Apache-2.0
"""Presentation states independent of the GTK render and transport threads."""
from enum import Enum, auto

HEARTBEAT_NS = 2_500_000_000
STATIC_NS = 2_000_000_000


class ViewerState(Enum):
    CONNECTING = auto()
    FIRST_FRAME = auto()
    LIVE = auto()
    STATIC = auto()
    STALLED = auto()
    DENIED = auto()
    REVOKED = auto()
    REPLACED = auto()
    ENDED = auto()
    UNAVAILABLE = auto()
    DISCONNECTED = auto()


STATE_TEXT = {
    ViewerState.CONNECTING: 'CONECTANDO',
    ViewerState.FIRST_FRAME: 'AGUARDANDO PRIMEIRO QUADRO',
    ViewerState.LIVE: 'AO VIVO',
    ViewerState.STATIC: 'IMAGEM ESTÁTICA · conexão saudável',
    ViewerState.STALLED: 'TRANSMISSÃO CONGELADA · sem heartbeat',
    ViewerState.DENIED: 'PERMISSÃO NEGADA',
    ViewerState.REVOKED: 'AUTORIZAÇÃO REVOGADA OU EXPIRADA',
    ViewerState.REPLACED: 'SESSÃO SUBSTITUÍDA OU IDENTIDADE DIVERGENTE',
    ViewerState.ENDED: 'SESSÃO ENCERRADA',
    ViewerState.UNAVAILABLE: 'TRANSMISSÃO INDISPONÍVEL',
    ViewerState.DISCONNECTED: 'DESCONECTADO',
}
FAILURE_STATE = {
    'denied': ViewerState.DENIED,
    'grant_denied': ViewerState.DENIED,
    'presentation_principal_mismatch': ViewerState.DENIED,
    'revoked': ViewerState.REVOKED,
    'grant_expired': ViewerState.REVOKED,
    'presentation_identity_mismatch': ViewerState.REPLACED,
    'session_ended': ViewerState.ENDED,
    'heartbeat_timeout': ViewerState.STALLED,
    'capture_unresponsive': ViewerState.STALLED,
    'presentation_unavailable': ViewerState.UNAVAILABLE,
    'presentation_limit': ViewerState.UNAVAILABLE,
    'method_not_found': ViewerState.UNAVAILABLE,
    'invalid_presentation_response': ViewerState.UNAVAILABLE,
}


def terminal_reason(reason):
    if isinstance(reason, str) and reason in FAILURE_STATE.keys() | {
        'connection_lost', 'session_ended_or_unreachable', 'capture_failed',
        'slow_viewer', 'unexpected_media_input', 'viewer_disconnected',
    }:
        return reason
    return 'connection_lost'


def viewer_state(now, *, connected, painted, packet, change, failure):
    if failure:
        return FAILURE_STATE.get(failure, ViewerState.DISCONNECTED)
    if connected is None:
        return ViewerState.CONNECTING
    if now - (packet if packet is not None else connected) >= HEARTBEAT_NS:
        return ViewerState.STALLED
    if painted is None:
        return ViewerState.FIRST_FRAME
    if change is not None and now - change >= STATIC_NS:
        return ViewerState.STATIC
    return ViewerState.LIVE
