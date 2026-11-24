# SPDX-License-Identifier: Apache-2.0
"""Client-side transport for the two allowed LoopBridge reads."""
import os
import re
import socket

from loopbridge.protocol import DeadlineChannel, Fault, VERSION
from loopbridge.service_ingress import peer_uid

from .commands import SESSION_ID
from .errors import Error, ShellError

TOKEN_LENGTH = 43
TOKEN = re.compile(r'[A-Za-z0-9_-]{43}')
PHASES = ('idle', 'controlled', 'handoff_pending', 'blocked')
SCOPED_PRINCIPALS = ('observer', 'delegate')
REPLY_FIELDS = {'jsonrpc', 'version', 'id'}
REMOTE_ERRORS = {
    (-32001, 'denied'): Error.AUTHENTICATION,
    (-32001, 'grant_denied'): Error.PERMISSION,
    (-32006, 'target_unavailable'): Error.SESSION_UNAVAILABLE,
    (-32601, 'method_not_found'): Error.UNAVAILABLE,
    (-32600, 'unsupported_version'): Error.UNAVAILABLE,
}
CLOSE_ON_ERROR = frozenset((Error.DISCONNECTED, Error.AUTHENTICATION,
                            Error.TIMEOUT, Error.INVALID_RESPONSE))


class BridgeClient:
    """A single connection. Calls are serialized by its caller."""

    def __init__(self, endpoint=None, expected_uid=None, *, timeout=3):
        self.endpoint = endpoint
        self.expected_uid = os.getuid() if expected_uid is None else expected_uid
        self.timeout = timeout
        self.principal = None
        self._channel = None
        self._sequence = 0

    def close(self):
        channel, self._channel = self._channel, None
        self.principal = None
        if channel is not None:
            channel.sock.close()

    def connect(self, credential):
        self.close()
        if self.endpoint is None:
            raise ShellError(Error.DISCONNECTED)
        if not isinstance(credential, str) or not TOKEN.fullmatch(credential):
            raise ShellError(Error.AUTHENTICATION)
        try:
            peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._channel = DeadlineChannel(peer)
            self._sequence = 0
            peer.settimeout(self.timeout)
            peer.connect(str(self.endpoint))
            if peer_uid(peer) != self.expected_uid:
                raise ShellError(Error.PEER_MISMATCH)
            identity = self._exchange('auth', {'credential': credential}).get('principal')
            if identity == 'owner':
                raise ShellError(Error.OWNER_CREDENTIAL)
            if identity not in SCOPED_PRINCIPALS:
                raise ShellError(Error.INVALID_RESPONSE)
        except (OSError, ShellError) as error:
            self.close()
            if isinstance(error, ShellError):
                raise
            reason = Error.TIMEOUT if isinstance(error, TimeoutError) else Error.DISCONNECTED
            raise ShellError(reason) from None
        self.principal = identity

    def list_sessions(self):
        sessions = self._read('discover').get('sessions')
        if (not isinstance(sessions, list)
                or any(not isinstance(sid, str) or not SESSION_ID.fullmatch(sid) for sid in sessions)
                or len(set(sessions)) != len(sessions)):
            self._invalid_response()
        return {'sessions': sessions}

    def session_status(self, session):
        if not isinstance(session, str) or not SESSION_ID.fullmatch(session):
            raise ShellError(Error.INVALID_COMMAND)
        result = self._read('snapshot', session=session)
        phase, revision = result.get('phase'), result.get('revision')
        if result.get('session') != session or phase not in PHASES or type(revision) is not int or revision < 0:
            self._invalid_response()
        return {'session': session, 'phase': phase, 'revision': revision}

    def _invalid_response(self):
        self.close()
        raise ShellError(Error.INVALID_RESPONSE)

    def _read(self, method, **params):
        if self.principal is None:
            raise ShellError(Error.DISCONNECTED)
        try:
            return self._exchange(method, params)
        except ShellError as error:
            if error.error in CLOSE_ON_ERROR:
                self.close()
            raise

    def _exchange(self, method, params):
        channel = self._channel
        if channel is None:
            raise ShellError(Error.DISCONNECTED)
        self._sequence += 1
        try:
            channel.sock.settimeout(self.timeout)
            channel.send(dict(jsonrpc='2.0', version=VERSION, id=self._sequence,
                              method=method, params=params))
            reply = channel.receive(self.timeout)
        except TimeoutError:
            raise ShellError(Error.TIMEOUT) from None
        except (EOFError, OSError):
            raise ShellError(Error.DISCONNECTED) from None
        except Fault:
            raise ShellError(Error.INVALID_RESPONSE) from None

        if (not isinstance(reply, dict) or reply.get('jsonrpc') != '2.0'
                or reply.get('version') != VERSION or type(reply.get('id')) is not int
                or reply['id'] != self._sequence):
            raise ShellError(Error.INVALID_RESPONSE)
        if set(reply) == REPLY_FIELDS | {'result'} and isinstance(reply['result'], dict):
            return reply['result']
        if set(reply) == REPLY_FIELDS | {'error'} and isinstance(reply['error'], dict):
            code, message = reply['error'].get('code'), reply['error'].get('message')
            if type(code) is int and isinstance(message, str):
                raise ShellError(REMOTE_ERRORS.get((code, message), Error.REMOTE_FAILURE))
        raise ShellError(Error.INVALID_RESPONSE)
