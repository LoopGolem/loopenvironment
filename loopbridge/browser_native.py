# SPDX-License-Identifier: Apache-2.0
"""Fixed Firefox fixture operations on the browser-private loopback listener.

There is no external WebDriver endpoint or generic protocol forwarding.
"""
import json
import os
import re
import socket
import stat
import threading

FORM = 'file:///fixture/form.html'
ELEMENT = 'element-6066-11e4-a52e-4f735466cecf'
SOCKET = '/home/browser/.native.sock'
PORT = 2828
MAX_PACKET = 32768
SITE_LIMIT = 24000


class NativeError(RuntimeError):
    pass


def received(stream, length):
    data = bytearray()
    while len(data) < length:
        part = stream.recv(length - len(data))
        if not part:
            raise NativeError('closed')
        data.extend(part)
    return data


class Marionette:
    def __init__(self):
        self.socket = socket.create_connection(('127.0.0.1', PORT), timeout=3)
        if os.environ.get('LOOPBRIDGE_HTTPS_HOSTS'):
            self.socket.settimeout(7)
        self.seq = 0
        try:
            hello = self.read()
            if hello != {'applicationType': 'gecko', 'marionetteProtocol': 3}:
                raise NativeError('protocol')
            self.call('WebDriver:NewSession', {'alwaysMatch': {'pageLoadStrategy': 'eager'}})
        except BaseException:
            self.socket.close()
            raise

    def read(self):
        prefix = bytearray()
        while len(prefix) < 6:
            part = received(self.socket, 1)
            if part == b':':
                break
            prefix.extend(part)
        if not prefix.isdigit() or not 0 < int(prefix) <= MAX_PACKET:
            raise NativeError('frame')
        return json.loads(received(self.socket, int(prefix)))

    def call(self, method, params=None):
        self.seq += 1
        raw = json.dumps([0, self.seq, method, params or {}], separators=(',', ':')).encode()
        self.socket.sendall(str(len(raw)).encode() + b':' + raw)
        reply = self.read()
        if not isinstance(reply, list) or len(reply) != 4 or reply[:3] != [1, self.seq, None]:
            raise NativeError('command_' + method.removeprefix('WebDriver:'))
        return reply[3]

    @staticmethod
    def unwrap(result):
        return result.get('value', result) if isinstance(result, dict) else result

    def apply(self, request):
        operation, value = request
        if operation == 'ready':
            return
        if (self.unwrap(self.call('WebDriver:GetCurrentURL')) != FORM
                or len(self.unwrap(self.call('WebDriver:GetWindowHandles'))) != 1):
            raise NativeError('document')
        if operation == 'text':
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ]{0,39}', value):
                raise NativeError('text')
            selector, command = '#demo-name', 'WebDriver:ElementSendKeys'
        elif operation == 'radio' and value in ('alpha', 'beta'):
            selector, command = '#' + value, 'WebDriver:ElementClick'
        elif operation == 'submit' and value == '':
            selector, command = '#submit', 'WebDriver:ElementClick'
        else:
            raise NativeError('policy')
        element = self.unwrap(self.call('WebDriver:FindElement', {'using': 'css selector', 'value': selector}))
        fields = {'id': element[ELEMENT]}
        if operation == 'text':
            fields['text'] = value
        self.call(command, fields)


def serve():
    session = None
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(SOCKET)
        os.chmod(SOCKET, 0o600)
        listener.listen(2)
        while True:
            peer, _ = listener.accept()
            with peer:
                peer.settimeout(4)
                site = os.environ.get('LOOPBRIDGE_SITE') == '1'
                try:
                    length = int.from_bytes(received(peer, 2), 'big')
                    if not 0 < length <= (4096 if site else 512):
                        raise NativeError('request')
                    request = json.loads(received(peer, length))
                    if session is None:
                        session = Marionette()
                    if site:
                        from web_native import execute, snapshot
                        if type(request) is not dict or not isinstance(request.get('operation'), str):
                            raise NativeError('request')
                        op = request['operation']
                        if os.environ.get('LOOPBRIDGE_HTTPS_HOSTS') and (
                                op in ('inspect_external', 'navigate_https') or op.startswith('external_')):
                            from web_https import execute as execute_https
                            result = execute_https(session, request, snapshot)
                        else:
                            result = execute(session, request)
                        site_reply(peer, dict(result=result))
                    else:
                        if (not isinstance(request, list) or len(request) != 2
                                or any(type(item) is not str or len(item) > 40 for item in request)):
                            raise NativeError('request')
                        session.apply(request)
                        peer.sendall(b'1')
                except (NativeError, OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                    detail = (str(error) if isinstance(error, NativeError)
                              else 'transport_' + str(error.errno) if isinstance(error, OSError)
                              else 'invalid_reply')
                    try:
                        if site:
                            from web_native import WebError
                            site_reply(peer, dict(error=str(error) if isinstance(error, WebError) else detail))
                        else:
                            peer.sendall(b'0' + detail.encode()[:80])
                    except OSError:
                        pass


def start():
    threading.Thread(target=serve, name='fixture-native', daemon=True).start()


def call(folder, operation, value=''):
    target = folder / '.native.sock'
    info = target.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise NativeError('private_socket')
    request = json.dumps([operation, value]).encode()
    with socket.socket(socket.AF_UNIX) as peer:
        peer.settimeout(9)
        peer.connect(str(target))
        peer.sendall(len(request).to_bytes(2, 'big') + request)
        receipt = peer.recv(128)
        if receipt != b'1':
            raise NativeError(receipt[1:].decode(errors='replace') if receipt else 'request_unverified')


def site_reply(peer, response):
    data = json.dumps(response).encode()
    if len(data) > SITE_LIMIT:
        data = b'{"error":"web_response_limit"}'
    peer.sendall(len(data).to_bytes(2, 'big') + data)


def site_call(folder, request):
    target = folder / '.native.sock'
    info = target.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise NativeError('private_socket')
    data = json.dumps(request).encode()
    if len(data) > 4096:
        raise NativeError('web_request_limit')
    with socket.socket(socket.AF_UNIX) as peer:
        peer.settimeout(9)
        peer.connect(str(target))
        peer.sendall(len(data).to_bytes(2, 'big') + data)
        size = int.from_bytes(received(peer, 2), 'big')
        if not 0 < size <= SITE_LIMIT:
            raise NativeError('web_response_limit')
        response = json.loads(received(peer, size))
    if 'error' in response:
        raise NativeError(response['error'])
    return response['result']
