# SPDX-License-Identifier: Apache-2.0
"""Ephemeral lab provisioning, NOT installation bootstrap or credential recovery."""
import hashlib
import hmac
import re
import secrets

from .protocol import Fault

PRINCIPALS = ('owner', 'delegate', 'observer')


class Identities:
    def __init__(self):
        self._digests = {}

    def provision(self):
        credentials = {p: secrets.token_urlsafe(32) for p in PRINCIPALS}
        self.load(credentials)
        return credentials

    def load(self, credentials):
        if (type(credentials) is not dict or set(credentials) != set(PRINCIPALS)
                or any(type(c) is not str or len(c) != 43 or not c.isascii()
                       for c in credentials.values())
                or len(set(credentials.values())) != len(PRINCIPALS)):
            raise ValueError('invalid_lab_provisioning')
        self._digests = {p: hashlib.sha256(c.encode()).digest() for p, c in credentials.items()}

    def contains_credential(self, value):
        for run in re.findall(r'[A-Za-z0-9_-]{43,}', value):
            for offset in range(len(run) - 42):
                digest = hashlib.sha256(run[offset:offset + 43].encode()).digest()
                if any(hmac.compare_digest(digest, saved) for saved in self._digests.values()):
                    return True
        return False

    def authenticate(self, credential):
        if not isinstance(credential, str) or len(credential) > 128:
            raise Fault(-32001, 'denied')
        try:
            digest = hashlib.sha256(credential.encode()).digest()
        except UnicodeError:
            raise Fault(-32001, 'denied') from None
        principal = None
        for p, expected in self._digests.items():
            if hmac.compare_digest(digest, expected):
                principal = p
        if principal is None:
            raise Fault(-32001, 'denied')
        return principal
