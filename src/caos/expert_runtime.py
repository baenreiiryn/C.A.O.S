from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict
from pathlib import Path

from .domain import MarketBar
from .experts.base import ForecastResult, SentimentResult


EXPERT_RUNTIME_PORT = 11436
EXPERT_RUNTIME_ASSET = "CAOS-Experts-Runtime.zip"
EXPERT_RUNTIME_MANIFEST = "CAOS-Experts-Runtime.json"
EXPERT_KEYS = ("kronos", "chronos2", "finbert")
DEFAULT_EXPERTS = ("kronos", "finbert")


class ExpertRuntimeError(RuntimeError):
    pass


def _json_http(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    timeout: float = 30.0,
    token: str | None = None,
    accept: str = "application/json",
) -> dict:
    data = (
        json.dumps(payload).encode("utf-8")
        if payload is not None
        else None
    )
    headers = {
        "User-Agent": "CAOS-Expert-Runtime",
        "Content-Type": "application/json",
        "Accept": str(accept),
    }
    if token:
        headers["Authorization"] = (
            f"Bearer {str(token).strip()}"
        )
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(
            req,
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
        raise ExpertRuntimeError(
            f"expert_runtime_request_failed:{exc}"
        ) from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


class RemoteForecastExpert:
    def __init__(
        self,
        runtime: "ManagedExpertRuntime",
        key: str,
        display_name: str,
    ):
        self.runtime = runtime
        self.key = key
        self.name = display_name

    def forecast(
        self,
        symbol: str,
        bars: list[MarketBar],
        horizon: int,
    ) -> ForecastResult:
        payload = self.runtime.request(
            "/forecast",
            {
                "expert": self.key,
                "symbol": symbol,
                "horizon": int(horizon),
                "bars": [asdict(bar) for bar in bars],
            },
            timeout=180.0,
        )
        return ForecastResult(**payload)


class RemoteSentimentExpert:
    name = "modernfinbert"

    def __init__(
        self,
        runtime: "ManagedExpertRuntime",
    ):
        self.runtime = runtime

    def classify(self, text: str) -> SentimentResult:
        payload = self.runtime.request(
            "/sentiment",
            {"text": str(text)},
            timeout=120.0,
        )
        return SentimentResult(**payload)


class ManagedExpertRuntime:
    def __init__(
        self,
        caos,
        data_dir: Path,
        *,
        app_version: str,
        repository: str = "baenreiiryn/C.A.O.S",
        bundled_runtime_dir: Path | None = None,
        base_url: str = (
            f"http://127.0.0.1:{EXPERT_RUNTIME_PORT}"
        ),
        token_getter=None,
    ):
        self.caos = caos
        self.data_dir = Path(data_dir)
        self.app_version = str(app_version).lstrip("v")
        self.repository = repository
        self.base_url = base_url.rstrip("/")
        self.runtime_dir = (
            self.data_dir / "experts-runtime"
        )
        self.bundled_runtime_dir = (
            Path(bundled_runtime_dir)
            if bundled_runtime_dir is not None
            else None
        )
        self.models_dir = (
            self.data_dir / "expert-models"
        )
        self.download_dir = (
            self.data_dir / "expert-runtime-downloads"
        )
        self.log_path = (
            self.data_dir / "experts-runtime.log"
        )
        self.enabled: list[str] = []
        self.autostart = True
        self.token_getter = token_getter
        self.process: subprocess.Popen | None = None
        self._lock = threading.RLock()

    @property
    def executable(self) -> Path:
        local = self.runtime_dir / "caos-experts.exe"
        if local.exists():
            return local
        if self.bundled_runtime_dir is not None:
            bundled = (
                self.bundled_runtime_dir
                / "caos-experts.exe"
            )
            if bundled.exists():
                return bundled
        return local

    def installed(self) -> bool:
        return self.executable.exists()

    def _token(self) -> str | None:
        if self.token_getter is None:
            return None
        try:
            value = self.token_getter()
        except Exception:
            return None
        value = (
            str(value).strip()
            if value is not None
            else ""
        )
        return value or None

    def _release_url(self) -> str:
        return (
            "https://api.github.com/repos/"
            f"{self.repository}/releases/tags/"
            f"v{self.app_version}"
        )

    def _release_assets(self) -> dict[str, dict]:
        release = _json_http(
            self._release_url(),
            timeout=20.0,
            token=self._token(),
        )
        return {
            str(row.get("name")): dict(row)
            for row in release.get("assets", [])
            if isinstance(row, dict)
            and row.get("name")
        }

    def install(self) -> dict:
        assets = self._release_assets()
        manifest_asset = assets.get(
            EXPERT_RUNTIME_MANIFEST
        )
        runtime_asset = assets.get(
            EXPERT_RUNTIME_ASSET
        )
        if not manifest_asset or not runtime_asset:
            raise ExpertRuntimeError(
                "expert_runtime_release_assets_missing"
            )
        manifest_url = str(
            manifest_asset.get("url")
            or manifest_asset.get(
                "browser_download_url",
                "",
            )
        )
        manifest = _json_http(
            manifest_url,
            timeout=30.0,
            token=self._token(),
            accept="application/octet-stream",
        )
        if (
            int(manifest.get("schema", 0)) != 1
            or str(
                manifest.get("version", "")
            ).lstrip("v") != self.app_version
            or manifest.get("asset")
            != EXPERT_RUNTIME_ASSET
        ):
            raise ExpertRuntimeError(
                "invalid_expert_runtime_manifest"
            )
        expected = str(
            manifest.get("sha256", "")
        ).lower()
        if (
            len(expected) != 64
            or any(
                ch not in "0123456789abcdef"
                for ch in expected
            )
        ):
            raise ExpertRuntimeError(
                "invalid_expert_runtime_checksum"
            )

        self.download_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        target = (
            self.download_dir
            / f"v{self.app_version}"
            / EXPERT_RUNTIME_ASSET
        )
        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        partial = target.with_suffix(".part")
        runtime_url = str(
            runtime_asset.get("url")
            or runtime_asset.get(
                "browser_download_url",
                "",
            )
        )
        headers = {
            "User-Agent": "CAOS-Expert-Runtime",
            "Accept": "application/octet-stream",
        }
        token = self._token()
        if token:
            headers["Authorization"] = (
                f"Bearer {token}"
            )
        req = urllib.request.Request(
            runtime_url,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(
                req,
                timeout=600.0,
            ) as response:
                with partial.open("wb") as handle:
                    while True:
                        chunk = response.read(
                            1024 * 1024
                        )
                        if not chunk:
                            break
                        handle.write(chunk)
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise

        if _sha256(target) != expected:
            target.unlink(missing_ok=True)
            raise ExpertRuntimeError(
                "expert_runtime_checksum_mismatch"
            )

        staging = (
            self.download_dir
            / f"staging-{self.app_version}"
        )
        if staging.exists():
            import shutil

            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        with zipfile.ZipFile(target, "r") as archive:
            names = set(archive.namelist())
            allowed = {
                "caos-experts.exe",
                "LICENSE-Kronos.txt",
                "runtime-info.json",
            }
            if (
                "caos-experts.exe" not in names
                or not names.issubset(allowed)
            ):
                raise ExpertRuntimeError(
                    "unexpected_expert_runtime_payload"
                )
            archive.extractall(staging)

        import shutil

        if self.runtime_dir.exists():
            shutil.rmtree(self.runtime_dir)
        staging.replace(self.runtime_dir)
        return self.status()

    def _alive(self) -> bool:
        try:
            health = _json_http(
                self.base_url + "/health",
                timeout=1.5,
            )
            return bool(health.get("ok"))
        except Exception:
            return False

    def start(self) -> dict:
        if self._alive():
            return self.status()
        if not self.installed():
            raise ExpertRuntimeError(
                "expert_runtime_not_installed"
            )
        self.autostart = True
        self.models_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.log_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        env = dict(os.environ)
        env["HF_HOME"] = str(
            self.models_dir / "huggingface"
        )
        env["CAOS_EXPERT_MODELS_DIR"] = str(
            self.models_dir
        )
        flags = (
            getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            )
            | getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            )
        )
        executable = self.executable
        working_dir = executable.parent
        if not executable.exists():
            raise ExpertRuntimeError(
                "expert_runtime_not_installed"
            )
        if not working_dir.is_dir():
            raise ExpertRuntimeError(
                "expert_runtime_working_directory_missing"
            )
        log = self.log_path.open(
            "ab",
            buffering=0,
        )
        try:
            with self._lock:
                self.process = subprocess.Popen(
                    [
                        str(executable),
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(EXPERT_RUNTIME_PORT),
                    ],
                    cwd=str(working_dir),
                    env=env,
                    stdout=log,
                    stderr=log,
                    creationflags=flags,
                )
        finally:
            log.close()
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline:
            if self._alive():
                return self.status()
            if (
                self.process is not None
                and self.process.poll()
                is not None
            ):
                raise ExpertRuntimeError(
                    "expert_runtime_exited_during_start"
                )
            time.sleep(0.25)
        raise ExpertRuntimeError(
            "expert_runtime_start_timeout"
        )

    def stop(self) -> dict:
        try:
            if self._alive():
                self.request(
                    "/shutdown",
                    {},
                    timeout=5.0,
                )
        except Exception:
            pass
        self.autostart = False
        with self._lock:
            process = self.process
            self.process = None
        if process is not None:
            try:
                process.wait(timeout=8.0)
            except Exception:
                process.terminate()
        return self.status()

    def request(
        self,
        path: str,
        payload: dict,
        *,
        timeout: float = 120.0,
    ) -> dict:
        if not self._alive():
            if not self.autostart:
                raise ExpertRuntimeError(
                    "expert_runtime_stopped"
                )
            self.start()
        response = _json_http(
            self.base_url + path,
            method="POST",
            payload=payload,
            timeout=timeout,
        )
        if response.get("error"):
            raise ExpertRuntimeError(
                str(response["error"])
            )
        return response

    def configure(
        self,
        enabled: list[str] | tuple[str, ...],
    ) -> dict:
        normalized = []
        for raw in enabled:
            key = str(raw).strip().lower()
            if key not in EXPERT_KEYS:
                raise ExpertRuntimeError(
                    f"unknown_expert:{key}"
                )
            if key not in normalized:
                normalized.append(key)
        self.enabled = normalized

        forecasts = {}
        if "kronos" in normalized:
            forecasts["kronos"] = (
                RemoteForecastExpert(
                    self,
                    "kronos",
                    "kronos-small",
                )
            )
        if "chronos2" in normalized:
            forecasts["chronos2"] = (
                RemoteForecastExpert(
                    self,
                    "chronos2",
                    "chronos-2",
                )
            )
        sentiment = (
            RemoteSentimentExpert(self)
            if "finbert" in normalized
            else None
        )
        self.caos.forecast_experts = forecasts
        self.caos.sentiment_expert = sentiment
        self.caos.expert_runtime = self
        if getattr(
            self.caos,
            "news_analyzer",
            None,
        ) is not None:
            self.caos.news_analyzer.sentiment_expert = (
                sentiment
            )
        return self.status()

    def load_enabled(self) -> dict:
        if not self.enabled:
            return self.status()
        self.request(
            "/load",
            {"experts": list(self.enabled)},
            timeout=900.0,
        )
        return self.status()

    def unload(self) -> dict:
        if self._alive():
            self.request(
                "/unload",
                {},
                timeout=30.0,
            )
        return self.status()

    def status(self) -> dict:
        remote = None
        if self._alive():
            try:
                remote = _json_http(
                    self.base_url + "/status",
                    timeout=2.0,
                )
            except Exception:
                remote = None
        return {
            "enabled": True,
            "installed": self.installed(),
            "running": remote is not None,
            "base_url": self.base_url,
            "runtime_dir": str(
                self.executable.parent
                if self.installed()
                else self.runtime_dir
            ),
            "models_dir": str(self.models_dir),
            "log_path": str(self.log_path),
            "configured": list(self.enabled),
            "loaded": (
                list(remote.get("loaded", []))
                if remote
                else []
            ),
            "errors": (
                dict(remote.get("errors", {}))
                if remote
                else {}
            ),
            "device": (
                remote.get("device")
                if remote
                else None
            ),
            "catalog": {
                "kronos": {
                    "label": "Kronos-small",
                    "role": "financial OHLCV forecast",
                    "recommended": True,
                },
                "chronos2": {
                    "label": "Chronos-2",
                    "role": "general time-series baseline",
                    "recommended": False,
                },
                "finbert": {
                    "label": "ModernFinBERT",
                    "role": "financial news sentiment",
                    "recommended": True,
                },
            },
        }
