from __future__ import annotations

import io
import unittest
from pathlib import Path

from app_config import (
    AppConfig,
    hash_password,
    load_app_config,
    upload_within_limit,
    verify_password,
)


class AppConfigTest(unittest.TestCase):
    def test_default_config_is_local_and_debug_off(self) -> None:
        config = load_app_config({})

        self.assertEqual(config.app_env, "local")
        self.assertFalse(config.auth_enabled)
        self.assertFalse(config.debug_exports)
        self.assertEqual(config.max_upload_mb, 100)

    def test_data_dir_env_override(self) -> None:
        config = load_app_config({"DATA_DIR": "/tmp/budget-data"})

        self.assertEqual(config.data_dir, Path("/tmp/budget-data"))

    def test_exports_dir_env_override(self) -> None:
        config = load_app_config({"EXPORTS_DIR": "/tmp/budget-exports"})

        self.assertEqual(config.exports_dir, Path("/tmp/budget-exports"))

    def test_auth_disabled_by_default_for_local_dev(self) -> None:
        self.assertFalse(load_app_config({}).auth_enabled)

    def test_auth_enabled_requires_password(self) -> None:
        with self.assertRaises(ValueError):
            load_app_config({"APP_AUTH_ENABLED": "1"}, validate=True)

    def test_plain_password_verification(self) -> None:
        config = load_app_config({"APP_AUTH_ENABLED": "1", "APP_PASSWORD": "secret"}, validate=True)

        self.assertTrue(verify_password("secret", config))
        self.assertFalse(verify_password("wrong", config))

    def test_hashed_password_verification(self) -> None:
        config = load_app_config(
            {
                "APP_AUTH_ENABLED": "1",
                "APP_PASSWORD_HASH": hash_password("secret"),
            },
            validate=True,
        )

        self.assertTrue(verify_password("secret", config))
        self.assertFalse(verify_password("wrong", config))

    def test_upload_limit_allows_small_file(self) -> None:
        fake_file = io.BytesIO(b"a" * 1024)
        config = AppConfig("local", False, "admin", "", "", "", False, Path("data"), Path("exports"), 1)

        ok, _, _ = upload_within_limit(fake_file, config)

        self.assertTrue(ok)

    def test_upload_limit_blocks_large_file(self) -> None:
        fake_file = io.BytesIO(b"a" * (2 * 1024 * 1024))
        config = AppConfig("local", False, "admin", "", "", "", False, Path("data"), Path("exports"), 1)

        ok, _, _ = upload_within_limit(fake_file, config)

        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
