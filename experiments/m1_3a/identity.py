# SPDX-License-Identifier: Apache-2.0
"""Ephemeral lab provisioning, NOT installation bootstrap or credential recovery."""
import hashlib
import hmac
import secrets

from experiments.m1_2.protocol import Fault


class Identities:
    def __init__(self):
        self._digests = {}

    def provision(self):
        credentials = {p: secrets.token_urlsafe(32) for p in ('owner', 'delegate', 'observer')}
        self._digests = {p: hashlib.sha256(c.encode()).digest() for p, c in credentials.items()}
        return credentials  # Trusted launcher delivers these only through private stdin.

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
