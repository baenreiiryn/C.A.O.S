from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


MANAGED_OLLAMA_PORT = 11435


class ManagedOllamaError(RuntimeError):
    pass


def _json_get(url: str, timeout: float = 0.75) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as exc:
        raise ManagedOllamaError(str(exc)) from exc


def _model_name(value: str) -> str:
    value = str(value).strip().lower()
    value = re.sub(r"[^a-z0-9._:/-]+", "-", value)
    value = value.strip("-/:.")
    if not value:
        raise ManagedOllamaError("model_name_required")
    return value[:120]


@dataclass(slots=True)
class ManagedOllamaRuntime:
    install_dir: Path
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = MANAGED_OLLAMA_PORT
    startup_timeout: float = 30.0
    process: subprocess.Popen | None = field(
        default=None,
        init=False,
        repr=False,
    )

    @property
    def runtime_dir(self) -> Path:
        override = os.environ.get("CAOS_OLLAMA_RUNTIME_DIR")
        if override:
            return Path(override).expanduser()
        return Path(self.install_dir) / "ollama"

    @property
    def executable(self) -> Path:
        override = os.environ.get("CAOS_OLLAMA_EXE")
        if override:
            return Path(override).expanduser()
        return self.runtime_dir / "ollama.exe"

    @property
    def models_dir(self) -> Path:
        return Path(self.data_dir) / "ollama-models"

    @property
    def log_path(self) -> Path:
        return Path(self.data_dir) / "ollama-server.log"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{int(self.port)}"

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env["OLLAMA_HOST"] = f"{self.host}:{int(self.port)}"
        env["OLLAMA_MODELS"] = str(self.models_dir)
        return env

    def _managed_process_running(self) -> bool:
        return (
            self.process is not None
            and self.process.poll() is None
        )

    def _server_version(self) -> str | None:
        try:
            payload = _json_get(
                self.base_url + "/api/version",
                timeout=0.5,
            )
        except ManagedOllamaError:
            return None
        value = payload.get("version")
        return str(value) if value else "unknown"

    def status(self) -> dict:
        version = self._server_version()
        return {
            "installed": self.executable.is_file(),
            "running": version is not None,
            "managed_process": self._managed_process_running(),
            "base_url": self.base_url,
            "runtime_dir": str(self.runtime_dir),
            "models_dir": str(self.models_dir),
            "version": version,
        }

    def start(self) -> dict:
        if self._server_version() is not None:
            return self.status()
        if not self.executable.is_file():
            raise ManagedOllamaError(
                "managed_ollama_runtime_missing"
            )

        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            )

        log = self.log_path.open("ab")
        try:
            self.process = subprocess.Popen(
                [str(self.executable), "serve"],
                cwd=str(self.runtime_dir),
                env=self._environment(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        finally:
            log.close()

        deadline = time.monotonic() + float(
            self.startup_timeout
        )
        while time.monotonic() < deadline:
            if self._server_version() is not None:
                return self.status()
            if (
                self.process is not None
                and self.process.poll() is not None
            ):
                code = self.process.returncode
                self.process = None
                raise ManagedOllamaError(
                    f"managed_ollama_exited:{code}"
                )
            time.sleep(0.2)

        self.stop()
        raise ManagedOllamaError(
            "managed_ollama_start_timeout"
        )

    def stop(self) -> dict:
        if self._managed_process_running():
            assert self.process is not None
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None
        return self.status()

    def pick_model_file(self) -> dict:
        if os.name != "nt":
            raise ManagedOllamaError(
                "native_model_picker_requires_windows"
            )
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$d=New-Object System.Windows.Forms.OpenFileDialog;"
            "$d.Title='Choose a GGUF model for C.A.O.S';"
            "$d.Filter='GGUF models (*.gguf)|*.gguf|All files (*.*)|*.*';"
            "$d.Multiselect=$false;"
            "if($d.ShowDialog() -eq "
            "[System.Windows.Forms.DialogResult]::OK)"
            "{[Console]::OutputEncoding=[Text.UTF8Encoding]::UTF8;"
            "Write-Output $d.FileName}"
        )
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-STA",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0:
            raise ManagedOllamaError(
                "model_picker_failed:"
                + (result.stderr.strip() or str(result.returncode))
            )
        path = result.stdout.strip()
        if not path:
            return {
                "selected": False,
                "path": "",
                "suggested_name": "",
            }
        source = Path(path)
        if source.suffix.lower() != ".gguf":
            raise ManagedOllamaError(
                "selected_file_must_be_gguf"
            )
        return {
            "selected": True,
            "path": str(source),
            "suggested_name": _model_name(
                "caos-" + source.stem
            ),
        }

    def import_gguf(
        self,
        source_path: str,
        *,
        model_name: str = "",
    ) -> dict:
        source = Path(str(source_path)).expanduser()
        if not source.is_file():
            raise ManagedOllamaError(
                "model_file_not_found"
            )
        if source.suffix.lower() != ".gguf":
            raise ManagedOllamaError(
                "model_file_must_be_gguf"
            )

        name = _model_name(
            model_name or ("caos-" + source.stem)
        )
        was_running = bool(
            self.status().get("running", False)
        )
        self.start()

        work = Path(self.data_dir) / "ollama-import"
        work.mkdir(parents=True, exist_ok=True)
        modelfile = work / "Modelfile"
        modelfile.write_text(
            "FROM " + source.resolve().as_posix() + "\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                str(self.executable),
                "create",
                name,
                "-f",
                str(modelfile),
            ],
            cwd=str(work),
            env=self._environment(),
            capture_output=True,
            text=True,
            timeout=7200,
            check=False,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt"
                else 0
            ),
        )
        if result.returncode != 0:
            detail = (
                result.stderr.strip()
                or result.stdout.strip()
                or str(result.returncode)
            )
            if not was_running:
                self.stop()
            raise ManagedOllamaError(
                "model_import_failed:" + detail[-1200:]
            )

        runtime = (
            self.status()
            if was_running
            else self.stop()
        )
        return {
            "model": name,
            "source_file": str(source.resolve()),
            "base_url": self.base_url,
            "runtime": runtime,
        }
