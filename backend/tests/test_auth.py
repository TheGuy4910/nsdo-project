"""
Tests for the authentication service (app/services/auth.py).

Requires passlib and python-jose, which are in requirements.txt but
not installable in the sandbox (PyPI is firewalled). The same
try/except ImportError guard used by TestSeedRuntime is applied here.

In Docker (where pip installs requirements.txt), all tests run.
In the sandbox, all tests skip with a clear message.

Token tests use a fixed test secret rather than calling get_secret_key(),
so they are deterministic regardless of environment variables.
"""

import sys
import os
import unittest
from datetime import timedelta

# Make app/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEST_SECRET = "test-secret-key-not-used-in-production"


class TestPasswordHashing(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            from passlib.context import CryptContext
            cls.passlib_available = True
        except ImportError:
            cls.passlib_available = False

    def setUp(self):
        if not self.passlib_available:
            self.skipTest("passlib not installed — auth tests skipped (will pass in Docker).")
        from app.services.auth import hash_password, verify_password
        self.hash_password   = hash_password
        self.verify_password = verify_password

    def test_hash_returns_non_empty_string(self):
        result = self.hash_password("correct-horse-battery-staple")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_hash_is_not_plaintext(self):
        plain = "correct-horse-battery-staple"
        hashed = self.hash_password(plain)
        self.assertNotEqual(plain, hashed)

    def test_hash_starts_with_bcrypt_prefix(self):
        hashed = self.hash_password("any-password")
        # bcrypt hashes always start with $2b$ or $2a$
        self.assertTrue(hashed.startswith("$2"), f"Not a bcrypt hash: {hashed[:10]}")

    def test_verify_correct_password_returns_true(self):
        plain = "my-secure-password-123"
        hashed = self.hash_password(plain)
        self.assertTrue(self.verify_password(plain, hashed))

    def test_verify_wrong_password_returns_false(self):
        hashed = self.hash_password("correct-password")
        self.assertFalse(self.verify_password("wrong-password", hashed))

    def test_verify_empty_password_returns_false(self):
        hashed = self.hash_password("correct-password")
        self.assertFalse(self.verify_password("", hashed))

    def test_verify_never_raises_on_bad_input(self):
        # verify_password must never raise — bad inputs return False
        try:
            result = self.verify_password("anything", "not-a-hash")
            self.assertFalse(result)
        except Exception as e:
            self.fail(f"verify_password raised unexpectedly: {e}")

    def test_two_hashes_of_same_password_differ(self):
        # bcrypt generates a new salt each time — same input, different output
        plain = "same-password"
        h1 = self.hash_password(plain)
        h2 = self.hash_password(plain)
        self.assertNotEqual(h1, h2)
        # But both verify correctly
        self.assertTrue(self.verify_password(plain, h1))
        self.assertTrue(self.verify_password(plain, h2))


class TestJWTTokens(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            from jose import jwt, JWTError, ExpiredSignatureError
            cls.jose_available = True
        except ImportError:
            cls.jose_available = False

    def setUp(self):
        if not self.jose_available:
            self.skipTest("python-jose not installed — JWT tests skipped (will pass in Docker).")
        from app.services.auth import create_access_token, decode_access_token, extract_username, extract_role
        self.create  = create_access_token
        self.decode  = decode_access_token
        self.get_usr = extract_username
        self.get_rol = extract_role

    def test_create_returns_string(self):
        token = self.create("alice", "admin", secret_key=TEST_SECRET)
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 10)

    def test_token_contains_subject(self):
        token = self.create("alice", "admin", secret_key=TEST_SECRET)
        payload = self.decode(token, secret_key=TEST_SECRET)
        self.assertEqual(payload["sub"], "alice")

    def test_token_contains_role(self):
        token = self.create("alice", "admin", secret_key=TEST_SECRET)
        payload = self.decode(token, secret_key=TEST_SECRET)
        self.assertEqual(payload["role"], "admin")

    def test_admin_role_in_token(self):
        token = self.create("admin_user", "admin", secret_key=TEST_SECRET)
        self.assertEqual(self.get_rol(token, secret_key=TEST_SECRET), "admin")

    def test_viewer_role_in_token(self):
        token = self.create("viewer_user", "viewer", secret_key=TEST_SECRET)
        self.assertEqual(self.get_rol(token, secret_key=TEST_SECRET), "viewer")

    def test_extract_username_returns_subject(self):
        token = self.create("bob", "viewer", secret_key=TEST_SECRET)
        self.assertEqual(self.get_usr(token, secret_key=TEST_SECRET), "bob")

    def test_extract_username_returns_none_on_invalid_token(self):
        result = self.get_usr("this.is.not.valid", secret_key=TEST_SECRET)
        self.assertIsNone(result)

    def test_extract_role_returns_none_on_invalid_token(self):
        result = self.get_rol("not.a.token", secret_key=TEST_SECRET)
        self.assertIsNone(result)

    def test_wrong_secret_raises(self):
        token = self.create("alice", "admin", secret_key=TEST_SECRET)
        from jose import JWTError
        with self.assertRaises(JWTError):
            self.decode(token, secret_key="wrong-secret")

    def test_expired_token_raises(self):
        # Create a token that expired 1 second ago
        token = self.create("alice", "admin", expires_minutes=-1, secret_key=TEST_SECRET)
        from jose import ExpiredSignatureError
        with self.assertRaises(ExpiredSignatureError):
            self.decode(token, secret_key=TEST_SECRET)

    def test_token_decode_returns_iat_and_exp(self):
        token = self.create("alice", "admin", secret_key=TEST_SECRET)
        payload = self.decode(token, secret_key=TEST_SECRET)
        self.assertIn("iat", payload)
        self.assertIn("exp", payload)
        # exp must be after iat
        self.assertGreater(payload["exp"], payload["iat"])

    def test_different_users_different_tokens(self):
        t1 = self.create("alice", "admin",  secret_key=TEST_SECRET)
        t2 = self.create("bob",   "viewer", secret_key=TEST_SECRET)
        self.assertNotEqual(t1, t2)


class TestAuthServicePure(unittest.TestCase):
    """
    Pure logic tests that do NOT require passlib or jose.
    These test the get_secret_key() fallback behaviour.
    """

    def test_dev_fallback_used_when_env_absent(self):
        """If JWT_SECRET_KEY is not set, get_secret_key() returns the dev fallback."""
        import os
        # Ensure the env var is absent for this test
        original = os.environ.pop("JWT_SECRET_KEY", None)
        try:
            from app.services.auth import get_secret_key, _DEV_FALLBACK_SECRET
            import importlib
            import app.services.auth as auth_mod
            importlib.reload(auth_mod)
            key = auth_mod.get_secret_key()
            self.assertEqual(key, _DEV_FALLBACK_SECRET)
        finally:
            if original is not None:
                os.environ["JWT_SECRET_KEY"] = original

    def test_env_var_returned_when_set(self):
        """If JWT_SECRET_KEY is set, get_secret_key() returns it."""
        import os
        os.environ["JWT_SECRET_KEY"] = "my-test-secret"
        try:
            import importlib
            import app.services.auth as auth_mod
            importlib.reload(auth_mod)
            key = auth_mod.get_secret_key()
            self.assertEqual(key, "my-test-secret")
        finally:
            del os.environ["JWT_SECRET_KEY"]


if __name__ == "__main__":
    unittest.main()
