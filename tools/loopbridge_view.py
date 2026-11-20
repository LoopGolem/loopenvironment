# SPDX-License-Identifier: Apache-2.0
"""Read an authorized PNG capture, optionally writing it to standard output."""
import argparse
import base64
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import socket
import sys

from loopbridge.__main__ import read_private
from loopbridge.protocol import Fault, RPC


def capture_frame(endpoint, token, session, expected_private_id=None, expected_epoch=None):
    with socket.socket(socket.AF_UNIX) as peer:
        peer.connect(endpoint)
        bridge = RPC(peer)
        bridge.call('auth', credential=token)
        frame = bridge.call('session.capture', session=session)
        private_id = frame.get('privateId')
        if (not private_id or (expected_private_id and private_id != expected_private_id)
                or (expected_epoch and frame.get('epoch') != expected_epoch)):
            raise ValueError('private_session_identity_mismatch')
        if (frame.get('mimeType') != 'image/png'
                or (frame.get('width'), frame.get('height')) != (800, 600)
                or not 1 <= frame['chunks'] <= 128 or not 1 <= frame['bytes'] <= 512 * 1024):
            raise ValueError('invalid_capture_metadata')
        png = b''.join(base64.b64decode(bridge.call('session.capture.read', session=session,
                                                   ref=frame['ref'], index=index)['data'], validate=True)
                       for index in range(frame['chunks']))
        if (len(png) != frame['bytes'] or not png.startswith(b'\x89PNG\r\n\x1a\n')
                or hashlib.sha256(png).hexdigest() != frame['sha256']):
            raise ValueError('invalid_capture_integrity')
        return dict(data=png, privateId=private_id, epoch=frame['epoch'], revision=frame['revision'],
                    sha256=frame['sha256'],
                    capturedAt=datetime.now(timezone.utc).isoformat(), width=frame['width'],
                    height=frame['height'])


def capture(endpoint, token, session):
    return capture_frame(endpoint, token, session)['data']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--session', default='desktop')
    parser.add_argument('--expected-private-id')
    args = parser.parse_args()
    try:
        if sys.stdout.isatty():
            parser.error('send the PNG to a viewer or file')
        frame = capture_frame(args.socket, read_private(args.token_file).rstrip('\n'), args.session,
                              args.expected_private_id)
        sys.stdout.buffer.write(frame['data'])
    except (OSError, EOFError, Fault, ValueError, KeyError):
        print('LoopBridge capture unavailable', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
