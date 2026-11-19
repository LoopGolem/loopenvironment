# SPDX-License-Identifier: Apache-2.0
"""Bounded observation and pointer submission on a managed private output."""
import base64
import hashlib
import os
from pathlib import Path
import re
import secrets
import struct
import subprocess
import time
import zlib

from .adapter import Refused
from .linux_desktop import process_identity, sway
from .semantic_operations import Prepared

OUTPUT = (800, 600)
IMAGE = (240, 180)
CHUNK = 4096
TTL = 20
HELPER = '/private/effects'


def private_id():
    value = os.environ.get('LOOPBRIDGE_PRIVATE_ID', '')
    if (re.fullmatch('[a-f0-9]{16}', value) and os.environ.get('XDG_RUNTIME_DIR') == '/private/run'
            and Path(os.environ.get('SWAYSOCK', '')).parent == Path('/private/run')
            and Path('/private/run/session-bus').is_socket()):
        return value
    return None


def available():
    return bool(private_id() and os.access(HELPER, os.X_OK))


def png(rgb):
    width, height = IMAGE
    if len(rgb) != width * height * 3:
        raise Refused('capture_invalid_size')

    def chunk(kind, body):
        payload = kind + body
        return struct.pack('>I', len(body)) + payload + struct.pack('>I', zlib.crc32(payload))

    row = width * 3
    scan = b''.join(b'\0' + rgb[index:index + row] for index in range(0, len(rgb), row))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(scan, 6)) + chunk(b'IEND', b''))


def run(*args):
    return subprocess.run([HELPER, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, timeout=4, check=True).stdout


def scene():
    outputs = sway('get_outputs')
    visible = [o for o in outputs if o.get('active')]
    if len(visible) != 1:
        raise Refused('private_output_ambiguous')
    output = visible[0]
    rect = output['rect']
    if (output.get('name'), output.get('scale'), output.get('transform'),
            *(rect[key] for key in ('x', 'y', 'width', 'height'))) != (
            'HEADLESS-1', 1, 'normal', 0, 0, *OUTPUT):
        raise Refused('private_output_changed')

    def windows(node):
        if node.get('pid') and node.get('visible') is True:
            rect = node['rect']
            yield (node['id'], process_identity(node['pid']), node.get('focused', False),
                   tuple(rect[key] for key in ('x', 'y', 'width', 'height')))
        for child in node.get('nodes', []) + node.get('floating_nodes', []):
            yield from windows(child)

    return tuple(windows(sway('get_tree')))


class Effects:
    def __init__(self):
        self.frames = {}

    def acquire(self):
        before = scene()
        contents = png(run('frame'))
        if not available() or scene() != before:
            raise Refused('private_scene_changed')
        token = secrets.token_hex(16)
        self.frames = {key: frame for key, frame in self.frames.items() if frame[0] > time.monotonic()}
        if len(self.frames) >= 4:
            self.frames.pop(next(iter(self.frames)))
        self.frames[token] = (time.monotonic() + TTL, contents, before)
        return dict(ref=token, ttlSeconds=TTL, width=IMAGE[0], height=IMAGE[1],
                    outputWidth=OUTPUT[0], outputHeight=OUTPUT[1], mimeType='image/png',
                    bytes=len(contents), sha256=hashlib.sha256(contents).hexdigest(),
                    chunks=(len(contents) + CHUNK - 1) // CHUNK, source='private_sway_output')

    def frame(self, token):
        frame = self.frames.get(token)
        if not frame or time.monotonic() >= frame[0]:
            self.frames.pop(token, None)
            raise Refused('capture_expired')
        return frame

    def read(self, token, index):
        data = self.frame(token)[1]
        if index * CHUNK >= len(data):
            raise Refused('capture_chunk_unavailable')
        contents = data[index * CHUNK:(index + 1) * CHUNK]
        return dict(index=index, encoding='base64', data=base64.b64encode(contents).decode())

    def prepare(self, command, token, x, y, controlled):
        expected = self.frame(token)[2]

        def validate():
            self.frame(token)
            if not available() or scene() != expected:
                raise Refused('private_scene_changed')
            if len(expected) != 1:
                raise Refused('private_target_ambiguous')
            _, identity, focused, (left, top, width, height) = expected[0]
            if (not focused or identity not in controlled() or
                    not (left <= x < left + width and top <= y < top + height)):
                raise Refused('private_target_unavailable')

        def submit():
            validate()
            run(command, str(x), str(y))

        validate()
        return Prepared(submit, lambda: dict(delivery='wayland_roundtrip',
                                             applicationOutcome='unverified'))
