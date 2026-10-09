import tempfile
import unittest
from pathlib import Path

from caos.windows_app import (
    WindowsAppError,
    app_data_dir,
    default_launcher_config,
    initialize_or_restore,
    load_launcher_config,
    run_self_test,
    save_launcher_config,
    validate_launcher_config,
)


class WindowsLauncherConfigTests(unittest.TestCase):
    def test_local_appdata_is_preferred(self):
        path = app_data_dir(
            environ={"LOCALAPPDATA": r"C:\Users\Test\AppData\Local"},
            home=Path("/unused"),
        )
        self.assertEqual(
            path,
            Path(r"C:\Users\Test\AppData\Local") / "CAOS",
        )

    def test_config_roundtrip_and_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            config = default_launcher_config(data_dir=root)
            config["state_db"] = str(root / "state.db")
            saved = save_launcher_config(
                config,
                data_dir=root,
            )
            loaded = load_launcher_config(data_dir=root)
            self.assertEqual(saved, loaded)
            self.assertEqual(saved["provider"], "static")
            self.assertEqual(
                saved["targets"],
                "BTCUSDT:long:momentum",
            )
            self.assertEqual(saved["dashboard_port"], 5191)
            self.assertEqual(
                saved["market_selection_mode"],
                "auto",
            )
            self.assertEqual(
                saved["auto_candidate_limit"],
                10,
            )

    def test_validation_rejects_unsafe_or_invalid_values(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            config = default_launcher_config(data_dir=root)

            bad = dict(config)
            bad["targets"] = ""
            with self.assertRaises(WindowsAppError):
                validate_launcher_config(
                    bad,
                    data_dir=root,
                )

            bad = dict(config)
            bad["stop_floor"] = 11
            bad["trader_bucket"] = 10
            with self.assertRaises(WindowsAppError):
                validate_launcher_config(
                    bad,
                    data_dir=root,
                )

            bad = dict(config)
            bad["operational_cap"] = 0
            with self.assertRaises(WindowsAppError):
                validate_launcher_config(
                    bad,
                    data_dir=root,
                )

    def test_legacy_launcher_config_gains_news_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            legacy = default_launcher_config(
                data_dir=root
            )
            legacy.pop("news_sources", None)
            validated = validate_launcher_config(
                legacy,
                data_dir=root,
            )
            self.assertGreater(
                len(validated["news_sources"]),
                0,
            )
            self.assertTrue(
                all(
                    row["enabled"]
                    for row in validated[
                        "news_sources"
                    ]
                )
            )

    def test_legacy_launcher_config_gains_broker_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            legacy = default_launcher_config(data_dir=root)
            legacy.pop("broker_profiles", None)
            legacy.pop("active_broker_profile", None)
            validated = validate_launcher_config(
                legacy,
                data_dir=root,
            )
            self.assertEqual(
                validated["broker_profiles"],
                [],
            )
            self.assertIsNone(
                validated["active_broker_profile"]
            )

    def test_loading_legacy_file_persists_news_migration(self):
        import json

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            legacy = default_launcher_config(
                data_dir=root
            )
            legacy.pop("news_sources", None)
            path = root / "launcher.json"
            path.write_text(
                json.dumps(legacy),
                encoding="utf-8",
            )
            loaded = load_launcher_config(
                data_dir=root
            )
            self.assertGreater(
                len(loaded["news_sources"]),
                0,
            )
            persisted = json.loads(
                path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                persisted["news_sources"],
                loaded["news_sources"],
            )

    def test_launcher_config_strips_broker_secrets(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            config = default_launcher_config(
                data_dir=root
            )
            config["broker_profiles"] = [
                {
                    "id": "bybit-testnet",
                    "label": "Bybit TESTNET",
                    "provider": "bybit",
                    "environment": "testnet",
                    "api_key": "must-not-persist",
                    "api_secret": "must-not-persist",
                }
            ]
            validated = validate_launcher_config(
                config,
                data_dir=root,
            )
            self.assertEqual(
                validated["broker_profiles"],
                [
                    {
                        "id": "bybit-testnet",
                        "label": "Bybit TESTNET",
                        "provider": "bybit",
                        "environment": "testnet",
                    }
                ],
            )
            self.assertNotIn(
                "must-not-persist",
                str(validated),
            )

    def test_relative_state_db_is_placed_under_app_data(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            config = default_launcher_config(data_dir=root)
            config["state_db"] = "custom.db"
            validated = validate_launcher_config(
                config,
                data_dir=root,
            )
            self.assertEqual(
                validated["state_db"],
                str(root / "custom.db"),
            )


class WindowsLauncherRuntimeTests(unittest.TestCase):
    def test_first_run_initializes_then_restores_same_company(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            config = default_launcher_config(data_dir=root)
            config["state_db"] = str(root / "company.db")
            config["provider"] = "static"
            config["targets"] = (
                "BTCUSDT:long:momentum,"
                "ETHUSDT:long:trend"
            )

            caos, company, targets, runtime, created = (
                initialize_or_restore(config)
            )
            self.assertTrue(created)
            self.assertEqual(company.registry.slot_count(), 1)
            self.assertEqual(len(targets), 2)
            self.assertEqual(len(runtime["targets"]), 2)
            self.assertTrue(company.operations_paused)
            self.assertEqual(
                company.operational_state(),
                "stopped",
            )
            company.start_operations()
            self.assertEqual(
                company.operational_state(),
                "running",
            )
            caos.store.close()

            (
                restored_caos,
                restored_company,
                restored_targets,
                restored_runtime,
                created_again,
            ) = initialize_or_restore(config)
            self.assertFalse(created_again)
            self.assertEqual(
                restored_company.registry.slot_count(),
                1,
            )
            self.assertEqual(len(restored_targets), 2)
            self.assertEqual(
                restored_runtime["targets"],
                runtime["targets"],
            )
            self.assertTrue(
                restored_company.operations_paused
            )
            self.assertEqual(
                restored_company.operational_state(),
                "stopped",
            )
            restored_caos.store.close()

    def test_news_sources_are_passed_to_runtime_on_first_run(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            config = default_launcher_config(
                data_dir=root
            )
            config["state_db"] = str(
                root / "company.db"
            )
            config["news_sources"] = [
                {
                    "id": "custom",
                    "name": "Custom",
                    "category": "crypto",
                    "url": "https://example.com/feed",
                    "kind": "custom",
                    "enabled": True,
                    "built_in": False,
                }
            ]
            caos, _, _, _, _ = (
                initialize_or_restore(config)
            )
            self.assertIsNotNone(
                caos.news_analyzer
            )
            self.assertEqual(
                caos.news_analyzer.client.feed_urls,
                ["https://example.com/feed"],
            )
            caos.store.close()

    def test_packaged_self_test_is_side_effect_free(self):
        self.assertEqual(run_self_test(), 0)


if __name__ == "__main__":
    unittest.main()
