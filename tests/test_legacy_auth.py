import hashlib
import unittest

from app.legacy_auth import hash_password, verify_password


class LegacyAuthTests(unittest.TestCase):
    def setUp(self):
        self.salt = "00" * 16

    def test_pbkdf2_password_round_trip(self):
        stored = hash_password("correct horse battery staple", self.salt)
        self.assertTrue(verify_password("correct horse battery staple", self.salt, stored))
        self.assertFalse(verify_password("wrong", self.salt, stored))

    def test_existing_sha256_account_remains_compatible(self):
        stored = hashlib.sha256(("existing-password" + self.salt).encode()).hexdigest()
        self.assertTrue(verify_password("existing-password", self.salt, stored))


if __name__ == "__main__":
    unittest.main()
