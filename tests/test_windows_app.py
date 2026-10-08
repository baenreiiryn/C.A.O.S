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
            restored_caos.store.close()

    def test_packaged_self_test_is_side_effect_free(self):
        self.assertEqual(run_self_test(), 0)


if __name__ == "__main__":
    unittest.main()
