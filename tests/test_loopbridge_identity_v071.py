# SPDX-License-Identifier: Apache-2.0
"""Pure-Python regression tests for the experimental V0.7.1 credential manifests."""
import hashlib
import json
import unittest

from loopbridge.identity import Identities, PRINCIPALS
from loopbridge.protocol import Fault, unique_object


class CredentialManifestTests(unittest.TestCase):
    def setUp(self):
        self.authority = Identities()
        self.tokens = self.authority.provision()
        self.manifest = self.authority.manifest()

    def test_manifest_contains_verifiers_not_bearer_tokens(self):
        self.assertEqual(set(self.manifest), {'version', 'verifiers'})
        self.assertEqual(self.manifest['version'], 1)
        self.assertEqual(set(self.manifest['verifiers']), set(PRINCIPALS))
        serialized = json.dumps(self.manifest)
        for principal in PRINCIPALS:
            token = self.tokens[principal]
            digest = self.manifest['verifiers'][principal]
            self.assertEqual(digest, hashlib.sha256(token.encode()).hexdigest())
            self.assertNotIn(token, serialized)

    def test_versioned_manifest_round_trip_authenticates_all_roles(self):
        restored = Identities()
        restored.load_manifest(json.loads(json.dumps(self.manifest), object_pairs_hook=unique_object))
        self.assertEqual(restored.manifest(), self.manifest)
        for principal in PRINCIPALS:
            self.assertEqual(restored.authenticate(self.tokens[principal]), principal)

    def test_verifier_digests_are_not_bearer_credentials(self):
        restored = Identities()
        restored.load_manifest(self.manifest)
        for digest in self.manifest['verifiers'].values():
            with self.assertRaisesRegex(Fault, '^denied$'):
                restored.authenticate(digest)
        self.assertEqual(restored.authenticate(self.tokens['owner']), 'owner')

    def test_manifest_schema_rejects_missing_extra_or_wrong_version(self):
        cases = (
            None, [], {}, {'version': 1},
            {'version': 1, 'verifiers': self.manifest['verifiers'], 'unexpected': True},
            {'version': True, 'verifiers': self.manifest['verifiers']},
            {'version': '1', 'verifiers': self.manifest['verifiers']},
            {'version': 2, 'verifiers': self.manifest['verifiers']},
        )
        for candidate in cases:
            with self.subTest(candidate=candidate):
                with self.assertRaisesRegex(ValueError, '^invalid_service_manifest$'):
                    Identities().load_manifest(candidate)

    def test_verifiers_reject_missing_extra_duplicate_and_invalid_values(self):
        valid = self.manifest['verifiers']
        candidates = (
            None, {},
            {'owner': valid['owner']},
            {**valid, 'unexpected': 'a' * 64},
            {**valid, 'owner': 'invalid'},
            {**valid, 'owner': 'A' * 64},
            {**valid, 'owner': 7},
            {**valid, 'owner': valid['delegate']},
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                with self.assertRaisesRegex(ValueError, '^invalid_credential_verifiers$'):
                    Identities().load_verifiers(candidate)

    def test_failed_reenrollment_does_not_replace_valid_verifiers(self):
        current = Identities()
        current.load_manifest(self.manifest)
        with self.assertRaisesRegex(ValueError, '^invalid_credential_verifiers$'):
            current.load_verifiers({'owner': 'a' * 64})
        self.assertEqual(current.authenticate(self.tokens['owner']), 'owner')
        self.assertEqual(current.manifest(), self.manifest)

    def test_legacy_bearer_manifest_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(ValueError, '^invalid_service_manifest$'):
            Identities().load_manifest(self.tokens)
        legacy = Identities()
        legacy.load_manifest(self.tokens, allow_legacy=True)
        self.assertEqual(legacy.authenticate(self.tokens['delegate']), 'delegate')
        self.assertEqual(legacy.manifest(), self.manifest)
        current = Identities()
        current.load_manifest(self.manifest, allow_legacy=True)
        self.assertEqual(current.authenticate(self.tokens['observer']), 'observer')

    def test_distinct_provisions_do_not_authenticate_across_instances(self):
        sibling = Identities()
        sibling_tokens = sibling.provision()
        self.assertTrue(set(self.manifest['verifiers'].values()).isdisjoint(
            set(sibling.manifest()['verifiers'].values())))
        for principal in PRINCIPALS:
            with self.assertRaisesRegex(Fault, '^denied$'):
                sibling.authenticate(self.tokens[principal])
            with self.assertRaisesRegex(Fault, '^denied$'):
                self.authority.authenticate(sibling_tokens[principal])
            self.assertEqual(sibling.authenticate(sibling_tokens[principal]), principal)

    def test_invalid_bearer_values_fail_closed(self):
        for credential in (None, '', 'not-a-token', 42, 'x' * 129):
            with self.subTest(credential=credential):
                with self.assertRaisesRegex(Fault, '^denied$'):
                    self.authority.authenticate(credential)

    def test_duplicate_json_manifest_keys_are_rejected(self):
        raw = '{"version":1,"version":1,"verifiers":{}}'
        with self.assertRaisesRegex(ValueError, '^duplicate_key$'):
            json.loads(raw, object_pairs_hook=unique_object)


if __name__ == '__main__':
    unittest.main()
