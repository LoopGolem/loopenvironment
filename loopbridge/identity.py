# SPDX-License-Identifier: Apache-2.0
"""Ephemeral lab provisioning, NOT installation bootstrap or credential recovery."""
import hashlib
import hmac
import re
import secrets

from .protocol import Fault

PRINCIPALS = ('owner', 'delegate', 'observer')
VERIFIER = re.compile('[0-9a-f]{64}')


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

    def load_manifest(self, manifest, *, allow_legacy=False):
        if allow_legacy and type(manifest) is dict and set(manifest) == set(PRINCIPALS):
            self.load(manifest)
            return
        if (type(manifest) is not dict or set(manifest) != {'version', 'verifiers'}
                or type(manifest['version']) is not int or manifest['version'] != 1):
            raise ValueError('invalid_service_manifest')
        self.load_verifiers(manifest['verifiers'])

    def load_verifiers(self, verifiers):
        if (type(verifiers) is not dict or set(verifiers) != set(PRINCIPALS)
                or any(type(digest) is not str or not VERIFIER.fullmatch(digest)
                       for digest in verifiers.values())
                or len(set(verifiers.values())) != len(PRINCIPALS)):
            raise ValueError('invalid_credential_verifiers')
        self._digests = {principal: bytes.fromhex(value) for principal, value in verifiers.items()}

    def manifest(self):
        return dict(version=1, verifiers={p: digest.hex() for p, digest in self._digests.items()})

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
