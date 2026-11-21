# SPDX-License-Identifier: Apache-2.0
"""Bounded byte relay to one manager-registered private Unix listener."""
from contextlib import closing, contextmanager
import os
from pathlib import Path
import select
import socket
import stat
import threading
import time

from .service_ingress import UNIX_PATH_LIMIT, path_inode, peer_uid

MAX_CONNECTIONS = 8
BUFFER_BYTES = 64 * 1024
CONNECT_TIMEOUT = 1
IDLE_TIMEOUT = 30
POLL_INTERVAL = .1


class Direction:
    def __init__(self, source, destination):
        self.source, self.destination = source, destination
        self.buffer = bytearray()
        self.eof = False

    def read(self):
        # recv() has no ancillary buffer. Linux discards SCM_RIGHTS here.
        data = self.source.recv(BUFFER_BYTES - len(self.buffer))
        self.buffer.extend(data)
        self.eof = not data
        if self.eof and not self.buffer:
            self.destination.shutdown(socket.SHUT_WR)

    def write(self):
        del self.buffer[:self.destination.send(self.buffer)]
        if self.eof and not self.buffer:
            self.destination.shutdown(socket.SHUT_WR)


def pump(client, private, stop):
    """Propagate half-close after draining; abort on error or cancellation."""
    directions = (Direction(client, private), Direction(private, client))
    for sock in (client, private):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_BYTES)
        sock.setblocking(False)
    deadline = time.monotonic() + IDLE_TIMEOUT
    while not stop.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        masks = {client: 0}  # Detect viewer close even when ingress is backpressured.
        for direction in directions:
            if not direction.eof and len(direction.buffer) < BUFFER_BYTES:
                masks[direction.source] = masks.get(direction.source, 0) | select.POLLIN
            if direction.buffer:
                masks[direction.destination] = masks.get(direction.destination, 0) | select.POLLOUT
        if all(direction.eof and not direction.buffer for direction in directions):
            return
        poll = select.poll()
        for sock, mask in masks.items():
            poll.register(sock, mask)
        events = dict(poll.poll(max(1, int(min(remaining, POLL_INTERVAL) * 1000))))
        if stop.is_set() or events.get(client.fileno(), 0) & select.POLLHUP:
            return
        if any(mask & (select.POLLERR | select.POLLNVAL) for mask in events.values()):
            return
        if events.get(private.fileno(), 0) & select.POLLHUP:
            # A fully closed Bridge can still have a final reply queued.
            requests = directions[0]
            requests.eof = True
            requests.buffer.clear()
        for direction in directions:
            incoming = events.get(direction.source.fileno(), 0)
            outgoing = events.get(direction.destination.fileno(), 0)
            try:
                if direction.buffer and outgoing & (select.POLLOUT | select.POLLHUP):
                    direction.write()
                    deadline = time.monotonic() + IDLE_TIMEOUT
                if (not direction.eof and len(direction.buffer) < BUFFER_BYTES
                        and incoming & (select.POLLIN | select.POLLHUP)):
                    direction.read()
                    deadline = time.monotonic() + IDLE_TIMEOUT
            except BlockingIOError:
                continue


class SessionRelay:
    def __init__(self, ingress, endpoint: Path, destination: Path):
        if (ingress.private_root not in destination.parents
                or len(os.fsencode(destination)) >= UNIX_PATH_LIMIT
                or destination.resolve(strict=True) != destination):
            raise ValueError('invalid_relay_destination')
        self.ingress, self.endpoint, self.destination = ingress, endpoint, destination
        self.destination_inode = self.check_destination()
        self.stop = threading.Event()

    def check_destination(self):
        info = self.destination.lstat()
        if (not stat.S_ISSOCK(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != self.ingress.policy.service_uid
                or info.st_gid != os.getegid()):
            raise ValueError('unsafe_relay_destination')
        return path_inode(info)

    def connection(self, client):
        with closing(client):
            try:
                if not self.ingress.policy.permits(peer_uid(client)) or self.stop.is_set():
                    return
                with socket.socket(socket.AF_UNIX) as private:
                    private.settimeout(CONNECT_TIMEOUT)
                    if self.check_destination() != self.destination_inode:
                        return
                    private.connect(str(self.destination))
                    if (peer_uid(private) != self.ingress.policy.service_uid
                            or self.check_destination() != self.destination_inode):
                        return
                    pump(client, private, self.stop)
            except (OSError, ValueError):
                pass  # Close both connections without logging transport contents.

    def accept(self, listener, workers):
        poll = select.poll()
        poll.register(listener, select.POLLIN)
        try:
            while not self.stop.is_set():
                if not poll.poll(int(POLL_INTERVAL * 1000)):
                    continue
                client, _ = listener.accept()
                workers[:] = [thread for thread in workers if thread.is_alive()]
                if self.stop.is_set() or len(workers) >= MAX_CONNECTIONS:
                    client.close()
                    continue
                worker = threading.Thread(target=self.connection, args=(client,))
                workers.append(worker)
                worker.start()
        except OSError:
            self.stop.set()

    @contextmanager
    def serve(self):
        workers = []
        with self.ingress.listen(self.endpoint) as listener:
            thread = threading.Thread(target=self.accept, args=(listener, workers))
            thread.start()
            try:
                yield
            finally:
                self.stop.set()
                thread.join()
                for worker in workers:
                    worker.join()
