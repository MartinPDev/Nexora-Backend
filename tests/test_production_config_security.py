"""Production configuration fail-closed checks."""
import unittest

try:
    from app.core.config import Settings
except ImportError:
    Settings = None


@unittest.skipIf(Settings is None, "pydantic-settings is not installed")
class ProductionConfigurationTests(unittest.TestCase):
    def config(self, **overrides):
        values = {
            "app_env": "production",
            "debug": False,
            "jwt_secret": "a" * 48,
            "encryption_key": "b" * 48,
            "cors_origins": "https://beta.nexorabot.ca",
            "database_url": "postgresql+psycopg://user:secret@db.example.com/nexora",
            "_env_file": None,
        }
        values.update(overrides)
        return Settings(**values)

    def test_secure_production_configuration_allowed(self):
        self.assertEqual(self.config().app_env, "production")

    def test_debug_rejected(self):
        with self.assertRaises(ValueError):
            self.config(debug=True)

    def test_default_jwt_secret_rejected(self):
        with self.assertRaises(ValueError):
            self.config(jwt_secret="change_this")

    def test_wildcard_cors_rejected(self):
        with self.assertRaises(ValueError):
            self.config(cors_origins="*")

    def test_http_cors_rejected(self):
        with self.assertRaises(ValueError):
            self.config(cors_origins="http://example.com")

    def test_default_database_credentials_rejected(self):
        with self.assertRaises(ValueError):
            self.config(database_url="postgresql+psycopg://postgres:postgres@localhost:5432/cryptobot")

    def test_development_still_works(self):
        self.assertEqual(self.config(app_env="development", debug=True).app_env, "development")


if __name__ == "__main__":
    unittest.main()
