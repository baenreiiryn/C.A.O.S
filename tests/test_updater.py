import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from caos.updater import (
    GitHubUpdateService,
    UpdateError,
    _version_tuple,
)


class FakePaper:
    def __init__(self, *, open_position=False, pending=False):
        self.accounts = {"A": object()}
        self.open_position = open_position
        self.pending = pending

    def positions_flat(self, trader_id):
        del trader_id
        return not self.open_position

    def has_pending_order(self, trader_id):
        del trader_id
        return self.pending


class FakeCompany:
    def __init__(
        self,
        *,
        state="stopped",
        open_position=False,
        pending=False,
    ):
        self.state = state
        self.paper = FakePaper(
            open_position=open_position,
            pending=pending,
        )

    def operational_state(self):
        return self.state


class FakeExecution:
    def __init__(
        self,
        *,
        unresolved=0,
        real_open_positions=None,
    ):
        self.unresolved = unresolved
        self.real_open_positions = (
            real_open_positions or {}
        )

    def status(self):
        return {
            "unresolved": self.unresolved,
            "real_open_positions": dict(
                self.real_open_positions
            ),
        }


def release_payload(version, sha256):
    return {
        "tag_name": "v" + version,
        "draft": False,
        "prerelease": False,
        "html_url": (
            "https://github.com/baenreiiryn/"
            "C.A.O.S/releases/tag/v" + version
        ),
        "published_at": "2026-10-09T00:00:00Z",
        "assets": [
            {
                "name": "CAOS-Update.json",
                "browser_download_url": (
                    "https://example.invalid/"
                    "CAOS-Update.json"
                ),
            },
            {
                "name": "CAOS-Update.zip",
                "browser_download_url": (
                    "https://example.invalid/"
                    "CAOS-Update.zip"
                ),
            },
        ],
    }, {
        "schema": 1,
        "version": version,
        "asset": "CAOS-Update.zip",
        "sha256": sha256,
        "payload": [
            "CAOS-Trade-Company.exe",
            "caos.exe",
        ],
    }


class GitHubUpdateServiceTests(unittest.TestCase):
    def make_service(
        self,
        root,
        *,
        version="0.8.8",
        company=None,
        execution=None,
        platform_name="posix",
        frozen=False,
    ):
        return GitHubUpdateService(
            current_version=version,
            data_dir=Path(root) / "data",
            install_dir=Path(root) / "install",
            company=company or FakeCompany(),
            execution_service=(
                execution or FakeExecution()
            ),
            platform_name=platform_name,
            frozen=frozen,
            process_id=12345,
        )

    def test_version_comparison_is_semver_numeric(self):
        self.assertGreater(
            _version_tuple("0.10.0"),
            _version_tuple("0.9.9"),
        )
        self.assertEqual(
            _version_tuple("v1.2"),
            (1, 2, 0),
        )

    def test_manifest_rejects_non_stable_or_path_like_version(self):
        with tempfile.TemporaryDirectory() as d:
            payload = b"update"
            sha = hashlib.sha256(payload).hexdigest()
            release, manifest = release_payload(
                "0.8.9",
                sha,
            )
            manifest["version"] = "0.8.9-../../escape"
            service = self.make_service(d)
            with patch(
                "caos.updater._json_request",
                side_effect=[release, manifest],
            ):
                with self.assertRaises(UpdateError):
                    service.check()

    def test_check_detects_new_stable_release(self):
        with tempfile.TemporaryDirectory() as d:
            payload = b"verified update payload"
            sha = hashlib.sha256(payload).hexdigest()
            release, manifest = release_payload(
                "0.8.9",
                sha,
            )
            service = self.make_service(d)
            with patch(
                "caos.updater._json_request",
                side_effect=[release, manifest],
            ):
                status = service.check()

            self.assertTrue(
                status["update_available"]
            )
            self.assertEqual(
                status["latest_version"],
                "0.8.9",
            )
            self.assertEqual(
                status["current_version"],
                "0.8.8",
            )

    def test_download_requires_matching_sha256(self):
        with tempfile.TemporaryDirectory() as d:
            good_payload = b"good-update"
            sha = hashlib.sha256(
                good_payload
            ).hexdigest()
            release, manifest = release_payload(
                "0.8.9",
                sha,
            )
            service = self.make_service(d)

            def fake_download(url, target, **kwargs):
                del url, kwargs
                target.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                target.write_bytes(good_payload)

            with patch(
                "caos.updater._json_request",
                side_effect=[release, manifest],
            ), patch(
                "caos.updater._download",
                side_effect=fake_download,
            ):
                service.check()
                status = service.download()

            self.assertTrue(status["downloaded"])
            self.assertTrue(
                Path(
                    status["downloaded_path"]
                ).exists()
            )

            bad_service = self.make_service(
                Path(d) / "bad"
            )
            release, manifest = release_payload(
                "0.8.9",
                "0" * 64,
            )
            with patch(
                "caos.updater._json_request",
                side_effect=[release, manifest],
            ), patch(
                "caos.updater._download",
                side_effect=fake_download,
            ):
                bad_service.check()
                with self.assertRaises(UpdateError):
                    bad_service.download()

    def test_install_is_blocked_while_trading_state_is_open(self):
        with tempfile.TemporaryDirectory() as d:
            service = self.make_service(
                d,
                company=FakeCompany(
                    state="running",
                    open_position=True,
                    pending=True,
                ),
                execution=FakeExecution(
                    unresolved=1,
                    real_open_positions={
                        "A": 0.01
                    },
                ),
                platform_name="nt",
                frozen=True,
            )
            blockers = service.install_blockers()
            self.assertIn(
                "company_state:running",
                blockers,
            )
            self.assertIn(
                "open_position:A",
                blockers,
            )
            self.assertIn(
                "pending_paper_order:A",
                blockers,
            )
            self.assertIn(
                "unresolved_external_execution",
                blockers,
            )
            self.assertIn(
                "open_real_position",
                blockers,
            )

    def test_install_schedules_verified_package_after_exit(self):
        with tempfile.TemporaryDirectory() as d:
            payload = b"verified update payload"
            sha = hashlib.sha256(payload).hexdigest()
            release, manifest = release_payload(
                "0.8.9",
                sha,
            )
            service = self.make_service(
                d,
                platform_name="nt",
                frozen=True,
            )

            def fake_download(url, target, **kwargs):
                del url, kwargs
                target.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                target.write_bytes(payload)

            with patch(
                "caos.updater._json_request",
                side_effect=[release, manifest],
            ), patch(
                "caos.updater._download",
                side_effect=fake_download,
            ):
                service.check()
                service.download()

            with patch(
                "caos.updater.subprocess.Popen"
            ) as popen:
                result = service.install_on_exit()

            self.assertTrue(result["scheduled"])
            popen.assert_called_once()
            script = (
                Path(d)
                / "data"
                / "updates"
                / "v0.8.9"
                / "apply-update.ps1"
            )
            self.assertTrue(script.exists())
            body = script.read_text(
                encoding="utf-8-sig"
            )
            self.assertIn(
                "Wait-Process -Id $pidToWait",
                body,
            )
            self.assertIn(
                "CAOS-Trade-Company.exe",
                body,
            )
            self.assertIn("caos.exe", body)
            self.assertNotIn("caos.db", body)
            self.assertNotIn(
                "ollama-models",
                body,
            )

    def test_same_version_is_not_an_update(self):
        with tempfile.TemporaryDirectory() as d:
            payload = b"same"
            sha = hashlib.sha256(payload).hexdigest()
            release, manifest = release_payload(
                "0.8.8",
                sha,
            )
            service = self.make_service(d)
            with patch(
                "caos.updater._json_request",
                side_effect=[release, manifest],
            ):
                status = service.check()
            self.assertFalse(
                status["update_available"]
            )


if __name__ == "__main__":
    unittest.main()
