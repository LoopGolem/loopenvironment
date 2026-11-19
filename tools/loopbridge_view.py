# SPDX-License-Identifier: Apache-2.0
"""Write one authorized PNG capture to standard output for a local viewer."""
import argparse
import base64
import hashlib
from pathlib import Path
import socket
import sys

from loopbridge.__main__ import read_private
from loopbridge.protocol import Fault, RPC


def capture(endpoint, token, session):
    with socket.socket(socket.AF_UNIX) as peer:
        peer.connect(endpoint)
        bridge = RPC(peer)
        bridge.call('auth', credential=token)
        frame = bridge.call('session.capture', session=session)
        if frame.get('mimeType') != 'image/png' or not 1 <= frame['chunks'] <= 33:
            raise ValueError('invalid_capture_metadata')
        png = b''.join(base64.b64decode(bridge.call('session.capture.read', session=session,
                                                   ref=frame['ref'], index=index)['data'], validate=True)
                       for index in range(frame['chunks']))
        if (len(png) != frame['bytes'] or not png.startswith(b'\x89PNG\r\n\x1a\n')
                or hashlib.sha256(png).hexdigest() != frame['sha256']):
            raise ValueError('invalid_capture_integrity')
        return png


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--session', default='desktop')
    args = parser.parse_args()
    try:
        if sys.stdout.isatty():
            parser.error('send the PNG to a viewer or file')
        data = capture(args.socket, read_private(args.token_file).rstrip('\n'), args.session)
        sys.stdout.buffer.write(data)
    except (OSError, EOFError, Fault, ValueError, KeyError):
        print('LoopBridge capture unavailable', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
