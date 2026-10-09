from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable


UPDATE_SCHEMA = 1
DEFAULT_REPOSITORY = "baenreiiryn/C.A.O.S"
UPDATE_MANIFEST_ASSET = "CAOS-Update.json"


class UpdateError(RuntimeError):
    pass


def _stable_release_version(value: str) -> str:
    text = str(value).strip().lower()
    if text.startswith("v"):
        text = text[1:]
    if not re.fullmatch(
        r"\d+\.\d+\.\d+",
        text,
    ):
        raise UpdateError(
            f"invalid_stable_release_version:{value}"
        )
    return text


def _version_tuple(value: str) -> tuple[int, int, int]:
    text = str(value).strip().lower()
    if text.startswith("v"):
        text = text[1:]
    core = text.split("-", 1)[0].split("+", 1)[0]
    parts = core.split(".")
    if not parts or any(
        not part.isdigit() for part in parts
    ):
        raise UpdateError(f"invalid_version:{value}")
    numbers = [int(part) for part in parts[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)  # type: ignore[return-value]


def _json_request(
    url: str,
    *,
    timeout: float = 15.0,
) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "CAOS-Trade-Company-Updater",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            return json.loads(
                response.read().decode("utf-8-sig")
            )
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as exc:
        raise UpdateError(
            f"update_request_failed:{exc}"
        ) from exc


def _download(
    url: str,
    target: Path,
    *,
    timeout: float = 180.0,
) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "CAOS-Trade-Company-Updater",
        },
        method="GET",
    )
    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary = target.with_suffix(
        target.suffix + ".part"
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            with temporary.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


class GitHubUpdateService:
    """Stable-release updater for the packaged Windows application.

    The updater downloads only the two packaged C.A.O.S executables. Persistent
    Company state, launcher settings, Windows credentials and managed Ollama
    models live outside the install directory and are intentionally untouched.
    """

    def __init__(
        self,
        *,
        current_version: str,
        data_dir: Path,
        install_dir: Path,
        company,
        execution_service=None,
        repository: str = DEFAULT_REPOSITORY,
        shutdown_callback: Callable[[], None] | None = None,
        process_id: int | None = None,
        platform_name: str | None = None,
        frozen: bool | None = None,
    ):
        self.current_version = (
            _stable_release_version(
                current_version
            )
        )
        self.data_dir = Path(data_dir)
        self.install_dir = Path(install_dir)
        self.company = company
        self.execution_service = execution_service
        self.repository = str(repository).strip()
        if "/" not in self.repository:
            raise ValueError("github_repository_required")
        self.shutdown_callback = shutdown_callback
        self.process_id = int(
            process_id
            if process_id is not None
            else os.getpid()
        )
        self.platform_name = (
            platform_name
            if platform_name is not None
            else os.name
        )
        self.frozen = (
            bool(frozen)
            if frozen is not None
            else bool(getattr(sys, "frozen", False))
        )
        self._latest: dict | None = None
        self._last_error: str | None = None
        self._checking = False
        self._lock = threading.RLock()

    @property
    def api_url(self) -> str:
        return (
            "https://api.github.com/repos/"
            f"{self.repository}/releases/latest"
        )

    @property
    def updates_dir(self) -> Path:
        return self.data_dir / "updates"

    def _asset_map(self, release: dict) -> dict[str, dict]:
        return {
            str(row.get("name")): dict(row)
            for row in release.get(
                "assets",
                [],
            )
            if isinstance(row, dict)
            and row.get("name")
        }

    def _fetch_manifest(
        self,
        release: dict,
    ) -> dict:
        assets = self._asset_map(release)
        asset = assets.get(UPDATE_MANIFEST_ASSET)
        if asset is None:
            raise UpdateError(
                "update_manifest_asset_missing"
            )
        url = str(
            asset.get("browser_download_url", "")
        ).strip()
        if not url:
            raise UpdateError(
                "update_manifest_url_missing"
            )
        manifest = _json_request(url)
        if int(manifest.get("schema", 0)) != UPDATE_SCHEMA:
            raise UpdateError(
                "unsupported_update_manifest"
            )
        version = _stable_release_version(
            str(
                manifest.get(
                    "version",
                    "",
                )
            )
        )
        tag = _stable_release_version(
            str(
                release.get(
                    "tag_name",
                    "",
                )
            )
        )
        if version != tag:
            raise UpdateError(
                "release_manifest_version_mismatch"
            )
        asset_name = str(
            manifest.get("asset", "")
        ).strip()
        sha256 = str(
            manifest.get("sha256", "")
        ).strip().lower()
        if (
            asset_name != "CAOS-Update.zip"
            or len(sha256) != 64
            or any(
                ch not in "0123456789abcdef"
                for ch in sha256
            )
        ):
            raise UpdateError(
                "invalid_update_manifest"
            )
        update_asset = assets.get(asset_name)
        if update_asset is None:
            raise UpdateError(
                "update_package_asset_missing"
            )
        download_url = str(
            update_asset.get(
                "browser_download_url",
                "",
            )
        ).strip()
        if not download_url:
            raise UpdateError(
                "update_package_url_missing"
            )
        return {
            **manifest,
            "version": version,
            "download_url": download_url,
            "release_url": release.get("html_url"),
            "release_name": release.get("name"),
            "published_at": release.get(
                "published_at"
            ),
        }

    def check(self) -> dict:
        with self._lock:
            self._checking = True
            self._last_error = None
        try:
            release = _json_request(
                self.api_url
            )
            if (
                release.get("draft")
                or release.get("prerelease")
            ):
                raise UpdateError(
                    "latest_release_is_not_stable"
                )
            manifest = self._fetch_manifest(
                release
            )
            manifest["update_available"] = (
                _version_tuple(
                    manifest["version"]
                )
                > _version_tuple(
                    self.current_version
                )
            )
            with self._lock:
                self._latest = manifest
            return self.status()
        except Exception as exc:
            with self._lock:
                self._last_error = (
                    f"{type(exc).__name__}: {exc}"
                )
            raise
        finally:
            with self._lock:
                self._checking = False

    def check_in_background(self) -> None:
        def worker() -> None:
            try:
                self.check()
            except Exception:
                pass

        threading.Thread(
            target=worker,
            name="caos-update-check",
            daemon=True,
        ).start()

    def _downloaded_path(
        self,
        version: str,
    ) -> Path:
        return (
            self.updates_dir
            / f"v{version}"
            / "CAOS-Update.zip"
        )

    def _verified_download(
        self,
        manifest: dict,
    ) -> Path | None:
        path = self._downloaded_path(
            str(manifest["version"])
        )
        if not path.exists():
            return None
        expected = str(
            manifest["sha256"]
        ).lower()
        if _sha256(path) != expected:
            path.unlink(missing_ok=True)
            return None
        return path

    def download(self) -> dict:
        with self._lock:
            manifest = (
                dict(self._latest)
                if self._latest is not None
                else None
            )
        if manifest is None:
            self.check()
            with self._lock:
                manifest = dict(
                    self._latest or {}
                )
        if not manifest.get(
            "update_available",
            False,
        ):
            return self.status()

        existing = self._verified_download(
            manifest
        )
        if existing is None:
            target = self._downloaded_path(
                str(manifest["version"])
            )
            try:
                _download(
                    str(manifest["download_url"]),
                    target,
                )
            except Exception as exc:
                target.unlink(missing_ok=True)
                with self._lock:
                    self._last_error = (
                        f"{type(exc).__name__}: {exc}"
                    )
                raise UpdateError(
                    f"update_download_failed:{exc}"
                ) from exc
            actual = _sha256(target)
            expected = str(
                manifest["sha256"]
            ).lower()
            if actual != expected:
                target.unlink(missing_ok=True)
                raise UpdateError(
                    "update_checksum_mismatch"
                )
        return self.status()

    def install_blockers(self) -> list[str]:
        blockers: list[str] = []
        state = str(
            self.company.operational_state()
        )
        if state != "stopped":
            blockers.append(
                f"company_state:{state}"
            )

        paper = getattr(
            self.company,
            "paper",
            None,
        )
        if paper is not None:
            for trader_id in list(
                getattr(
                    paper,
                    "accounts",
                    {},
                )
            ):
                try:
                    if not paper.positions_flat(
                        trader_id
                    ):
                        blockers.append(
                            "open_position:"
                            + str(trader_id)
                        )
                    if paper.has_pending_order(
                        trader_id
                    ):
                        blockers.append(
                            "pending_paper_order:"
                            + str(trader_id)
                        )
                except Exception:
                    blockers.append(
                        "paper_state_unknown:"
                        + str(trader_id)
                    )

        if self.execution_service is not None:
            try:
                external = (
                    self.execution_service.status()
                )
                if int(
                    external.get(
                        "unresolved",
                        0,
                    )
                ) > 0:
                    blockers.append(
                        "unresolved_external_execution"
                    )
                if external.get(
                    "real_open_positions"
                ):
                    blockers.append(
                        "open_real_position"
                    )
            except Exception:
                blockers.append(
                    "external_execution_state_unknown"
                )
        return sorted(set(blockers))

    def _install_supported(self) -> bool:
        return (
            self.platform_name == "nt"
            and self.frozen
        )

    def status(self) -> dict:
        with self._lock:
            latest = (
                dict(self._latest)
                if self._latest is not None
                else None
            )
            last_error = self._last_error
            checking = self._checking

        downloaded = False
        downloaded_path = None
        if latest is not None:
            verified = self._verified_download(
                latest
            )
            if verified is not None:
                downloaded = True
                downloaded_path = str(
                    verified
                )

        blockers = self.install_blockers()
        return {
            "enabled": True,
            "repository": self.repository,
            "current_version": self.current_version,
            "latest_version": (
                latest.get("version")
                if latest
                else None
            ),
            "update_available": bool(
                latest
                and latest.get(
                    "update_available",
                    False,
                )
            ),
            "checking": checking,
            "downloaded": downloaded,
            "downloaded_path": downloaded_path,
            "release_url": (
                latest.get("release_url")
                if latest
                else None
            ),
            "published_at": (
                latest.get("published_at")
                if latest
                else None
            ),
            "install_supported": (
                self._install_supported()
            ),
            "install_blockers": blockers,
            "can_install": bool(
                self._install_supported()
                and downloaded
                and not blockers
            ),
            "last_error": last_error,
        }

    def _write_install_script(
        self,
        package: Path,
        version: str,
    ) -> Path:
        update_dir = package.parent
        staging = update_dir / "staging"
        script = update_dir / "apply-update.ps1"
        app_exe = (
            self.install_dir
            / "CAOS-Trade-Company.exe"
        )
        cli_exe = self.install_dir / "caos.exe"

        def ps(value: Path | str) -> str:
            return (
                "'" + str(value).replace(
                    "'",
                    "''",
                ) + "'"
            )

        backup = update_dir / "backup"
        error_log = update_dir / "apply-error.txt"
        body = "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                f"$pidToWait = {self.process_id}",
                "try { Wait-Process -Id $pidToWait -ErrorAction SilentlyContinue } catch {}",
                f"$package = {ps(package)}",
                f"$staging = {ps(staging)}",
                f"$backup = {ps(backup)}",
                f"$errorLog = {ps(error_log)}",
                f"$app = {ps(app_exe)}",
                f"$cli = {ps(cli_exe)}",
                "Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue",
                "Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue",
                "Remove-Item -LiteralPath $errorLog -Force -ErrorAction SilentlyContinue",
                "Expand-Archive -LiteralPath $package -DestinationPath $staging -Force",
                "$newApp = Join-Path $staging 'CAOS-Trade-Company.exe'",
                "$newCli = Join-Path $staging 'caos.exe'",
                "if (-not (Test-Path -LiteralPath $newApp)) { throw 'CAOS-Trade-Company.exe missing from update package' }",
                "if (-not (Test-Path -LiteralPath $newCli)) { throw 'caos.exe missing from update package' }",
                "if ((Get-Item -LiteralPath $newApp).Length -le 0) { throw 'CAOS-Trade-Company.exe is empty' }",
                "if ((Get-Item -LiteralPath $newCli).Length -le 0) { throw 'caos.exe is empty' }",
                "New-Item -ItemType Directory -Force $backup | Out-Null",
                "$oldApp = Join-Path $backup 'CAOS-Trade-Company.exe'",
                "$oldCli = Join-Path $backup 'caos.exe'",
                "if (Test-Path -LiteralPath $app) { Copy-Item -LiteralPath $app -Destination $oldApp -Force }",
                "if (Test-Path -LiteralPath $cli) { Copy-Item -LiteralPath $cli -Destination $oldCli -Force }",
                "try {",
                "  Copy-Item -LiteralPath $newApp -Destination $app -Force",
                "  Copy-Item -LiteralPath $newCli -Destination $cli -Force",
                f"  Set-Content -LiteralPath {ps(update_dir / 'installed-version.txt')} -Value {ps(version)} -Encoding ASCII",
                "} catch {",
                "  $_ | Out-String | Set-Content -LiteralPath $errorLog -Encoding UTF8",
                "  if (Test-Path -LiteralPath $oldApp) { Copy-Item -LiteralPath $oldApp -Destination $app -Force }",
                "  if (Test-Path -LiteralPath $oldCli) { Copy-Item -LiteralPath $oldCli -Destination $cli -Force }",
                "  Start-Process -FilePath $app",
                "  exit 1",
                "}",
                "Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue",
                "Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue",
                "Start-Process -FilePath $app",
            ]
        )
        script.write_text(
            body + "\n",
            encoding="utf-8-sig",
        )
        return script

    def install_on_exit(self) -> dict:
        status = self.status()
        if not status["install_supported"]:
            raise UpdateError(
                "self_update_requires_packaged_windows_app"
            )
        if status["install_blockers"]:
            raise UpdateError(
                "update_install_blocked:"
                + ",".join(
                    status["install_blockers"]
                )
            )
        with self._lock:
            manifest = (
                dict(self._latest)
                if self._latest is not None
                else None
            )
        if manifest is None:
            raise UpdateError(
                "check_for_updates_first"
            )
        package = self._verified_download(
            manifest
        )
        if package is None:
            raise UpdateError(
                "download_update_first"
            )

        script = self._write_install_script(
            package,
            str(manifest["version"]),
        )
        creation_flags = (
            getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            )
            | getattr(
                subprocess,
                "DETACHED_PROCESS",
                0,
            )
            | getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            )
        )
        try:
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                ],
                cwd=str(script.parent),
                creationflags=creation_flags,
                close_fds=True,
            )
        except Exception as exc:
            raise UpdateError(
                f"update_launcher_failed:{exc}"
            ) from exc

        if self.shutdown_callback is not None:
            timer = threading.Timer(
                0.8,
                self.shutdown_callback,
            )
            timer.daemon = True
            timer.start()

        return {
            **status,
            "scheduled": True,
            "message": (
                "Update verified. Trade Company will close, "
                "replace the packaged executables, and relaunch."
            ),
        }
