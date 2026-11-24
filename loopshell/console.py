# SPDX-License-Identifier: Apache-2.0
"""Dispatch and text presentation for the typed console."""
import json

from .commands import Action, GRAMMAR_VERSION
from .errors import Error, ShellError

PROMPT = 'bridge> '
HELP = (
    f'Comandos da LoopShell · gramática v{GRAMMAR_VERSION}\n'
    'help   Mostra esta ajuda\n'
    'clear  Limpa o histórico\n'
    'exit   Fecha a LoopShell\n'
    'sessions list         Lista sessões autorizadas\n'
    'session status <id>   Consulta fase e revisão\n'
    'Use Conectar para autenticar com uma credencial delegada.\n'
    'Diagnóstico do sistema, sessões visuais, agentes e missões estão indisponíveis.'
)
ERROR_TEXT = {
    Error.INVALID_COMMAND: 'Sintaxe inválida. Digite help.',
    Error.UNKNOWN_COMMAND: 'Comando desconhecido. Digite help.',
    Error.INPUT_LIMIT: 'Comando excede o limite de entrada.',
    Error.DISCONNECTED: 'Cliente desconectado. Use Conectar para autenticar.',
    Error.PEER_MISMATCH: 'A identidade Linux do serviço difere do UID configurado.',
    Error.AUTHENTICATION: 'Falha de autenticação no LoopBridge.',
    Error.OWNER_CREDENTIAL: 'Use uma credencial de observador ou delegado.',
    Error.PERMISSION: 'Permissão insuficiente ou sessão não visível.',
    Error.SESSION_UNAVAILABLE: 'Sessão ou recurso indisponível.',
    Error.INVALID_RESPONSE: 'Resposta inválida do LoopBridge.',
    Error.TIMEOUT: 'Tempo de espera do LoopBridge esgotado.',
    Error.UNAVAILABLE: 'Operação indisponível nesta versão.',
    Error.REMOTE_FAILURE: 'O LoopBridge não concluiu a consulta.',
}


def dispatch(command, client):
    if command.action is Action.HELP:
        return HELP
    if command.action is Action.LIST:
        result = client.list_sessions()
    elif command.action is Action.STATUS:
        result = client.session_status(command.session)
    else:
        raise ShellError(Error.UNAVAILABLE)
    return json.dumps(result, indent=2)


def history_entry(command, text):
    # History contains canonical command names and projected results only.
    return f'{PROMPT}{command.action.value}\n{text}' if command else text
