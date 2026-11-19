# SPDX-License-Identifier: Apache-2.0
"""Exact-host CONNECT egress. The desktop and browser retain private network namespaces."""
import hashlib
import ipaddress
import json
import re
import select
import socket
from socketserver import BaseRequestHandler, TCPServer, ThreadingMixIn, UnixStreamServer
import threading
import time
from urllib.parse import unquote, urlsplit

HOST = re.compile(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}')
DENIED_SEGMENTS = frozenset(('admin', 'administration', 'internal', 'wp-admin', 'actuator'))
UNIX_PROXY = '/private/https.sock'
BROWSER_PROXY = '/run/browser/https.sock'
BROWSER_PORT = 8181
MAX_BYTES = 48 * 1024 * 1024


def hostname(value):
    if not isinstance(value, str) or not HOST.fullmatch(value) or value.endswith(
            ('.local', '.localhost', '.internal', '.lan', '.home', '.onion', '.test')):
        raise ValueError('invalid_https_host')
    return value


def destinations(values):
    if not isinstance(values, list) or len(values) > 24:
        raise ValueError('invalid_https_hosts')
    return frozenset(hostname(value) for value in values)


def https_url(raw, hosts):
    if (not isinstance(raw, str) or not 1 <= len(raw) <= 512
            or any(ord(char) <= 32 or ord(char) >= 127 for char in raw) or '\\' in raw):
        raise ValueError('web_destination_denied')
    uri = urlsplit(raw)
    if uri.scheme != 'https' or uri.netloc not in hosts or uri.fragment:
        raise ValueError('web_destination_denied')
    path = uri.path
    for _ in range(3):
        path = unquote(path)
    if (set(re.split(r'[/;\\]', path.lower())) & DENIED_SEGMENTS
            or '%' in path or '\\' in path or any(ord(char) < 32 for char in path)):
        raise ValueError('web_destination_denied')
    return uri


def public_ip(raw):
    address = ipaddress.ip_address(raw)
    return (address.is_global and not address.is_multicast and not address.is_reserved
            and not address.is_loopback and not address.is_link_local
            and (address.version == 4 or address in ipaddress.ip_network('2000::/3'))
            and getattr(address, 'ipv4_mapped', None) is None
            and getattr(address, 'sixtofour', None) is None
            and getattr(address, 'teredo', None) is None)


def connect(host):
    # Use the DNS answer exactly once, then connect to one of those numeric
    # endpoints. Mixed public/private answers fail closed.
    rows = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not rows or not all(family in (socket.AF_INET, socket.AF_INET6) and public_ip(addr[0])
                           for family, _, _, _, addr in rows):
        raise ValueError('non_public_dns_answer')
    for family, kind, protocol, _, address in rows[:8]:
        peer = socket.socket(family, kind, protocol)
        try:
            peer.settimeout(3)
            peer.connect(address)
            return peer
        except OSError:
            peer.close()
    raise OSError('upstream_tcp_failed')


def relay(left, right):
    peers = {left: right, right: left}
    total = 0
    deadline = time.monotonic() + 120
    for peer in peers:
        peer.settimeout(5)
    while peers and time.monotonic() < deadline and total < MAX_BYTES:
        ready, _, _ = select.select(list(peers), [], [], 10)
        if not ready:
            return
        for source in ready:
            target = peers[source]
            data = source.recv(min(32768, MAX_BYTES - total))
            if not data:
                del peers[source]
                target.shutdown(socket.SHUT_WR)
                continue
            target.sendall(data)
            total += len(data)


def read_connect(peer):
    peer.settimeout(4)
    deadline = time.monotonic() + 5
    header = bytearray()
    while not header.endswith(b'\r\n\r\n'):
        if len(header) >= 4096 or time.monotonic() >= deadline:
            raise ValueError('header_limit')
        data = peer.recv(1)
        if not data:
            raise ValueError('truncated_request')
        header.extend(data)
    line = header.split(b'\r\n', 1)[0].decode('ascii')
    match = re.fullmatch(r'CONNECT ([a-z0-9.-]+):443 HTTP/1\.[01]', line)
    if not match:
        raise ValueError('connect_https_required')
    return hostname(match[1])


class BoundedThreads(ThreadingMixIn):
    daemon_threads = True
    block_on_close = False

    def process_request(self, request, address):
        if not self.limit.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.limit.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.limit.release()

    def handle_error(self, request, address):
        pass  # No request, exception or URL text goes into logs.


class Egress(BoundedThreads, UnixStreamServer):
    def __init__(self, path, hosts):
        self.hosts = hosts
        self.limit = threading.BoundedSemaphore(16)
        self.events = []
        self.lock = threading.Lock()
        super().__init__(str(path), Tunnel)
        path.chmod(0o600)

    def record(self, host, status):
        with self.lock:
            destination = (host if host in self.hosts else
                           hashlib.sha256(host.encode()).hexdigest()[:12] if host else None)
            self.events.append(dict(destination=destination, outcome=status))
            del self.events[:-48]

    def snapshot(self):
        with self.lock:
            return list(self.events)


class Tunnel(BaseRequestHandler):
    def handle(self):
        host = None
        try:
            host = read_connect(self.request)
            if host not in self.server.hosts:
                self.deny(host, 'host_denied', b'403 Forbidden')
                return
            remote = connect(host)
        except socket.gaierror:
            self.deny(host, 'dns_failure', b'502 Bad Gateway')
            return
        except ValueError as error:
            self.deny(host, 'non_public_dns' if str(error) == 'non_public_dns_answer' else 'request_denied',
                      b'403 Forbidden')
            return
        except OSError:
            self.deny(host, 'tcp_failure', b'502 Bad Gateway')
            return
        with remote:
            self.server.record(host, 'tcp_connected')
            try:
                self.request.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                relay(self.request, remote)
            except OSError:
                pass

    def deny(self, host, outcome, status):
        self.server.record(host, outcome)
        try:
            self.request.sendall(b'HTTP/1.1 ' + status + b'\r\nContent-Length: 0\r\n\r\n')
        except OSError:
            pass


class Forward(BoundedThreads, TCPServer):
    allow_reuse_address = True

    def __init__(self, path=BROWSER_PROXY, port=BROWSER_PORT):
        self.path = path
        self.limit = threading.BoundedSemaphore(16)
        super().__init__(('127.0.0.1', port), ForwardPeer)


class ForwardPeer(BaseRequestHandler):
    def handle(self):
        try:
            with socket.socket(socket.AF_UNIX) as peer:
                peer.settimeout(4)
                peer.connect(self.server.path)
                relay(self.request, peer)
        except OSError:
            pass
