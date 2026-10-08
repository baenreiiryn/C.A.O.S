import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from caos.ollama_runtime import (
    ManagedOllamaError,
    ManagedOllamaRuntime,
)


class ManagedOllamaRuntimeTests(unittest.TestCase):
    def make_runtime(self, root: Path) -> ManagedOllamaRuntime:
        runtime_dir = root / "install" / "ollama"
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "ollama.exe").write_bytes(b"stub")
        return ManagedOllamaRuntime(
            root / "install",
            root / "data",
            startup_timeout=1.0,
        )

    def test_status_reports_bundled_runtime_without_starting_it(self):
        with tempfile.TemporaryDirectory() as d:
            runtime = self.make_runtime(Path(d))
            with patch(
                "caos.ollama_runtime._json_get",
                side_effect=ManagedOllamaError("offline"),
            ):
                status = runtime.status()
            self.assertTrue(status["installed"])
            self.assertFalse(status["running"])
            self.assertEqual(
                status["base_url"],
                "http://127.0.0.1:11435",
            )
            self.assertTrue(
                status["models_dir"].endswith(
                    "ollama-models"
                )
            )

    def test_start_uses_isolated_host_and_model_store(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            runtime = self.make_runtime(root)
            proc = Mock()
            proc.poll.return_value = None
            proc.returncode = None
            calls = {"count": 0}

            def version(*_args, **_kwargs):
                calls["count"] += 1
                if calls["count"] < 2:
                    raise ManagedOllamaError("not ready")
                return {"version": "0.test"}

            with patch(
                "caos.ollama_runtime._json_get",
                side_effect=version,
            ), patch(
                "caos.ollama_runtime.subprocess.Popen",
                return_value=proc,
            ) as popen:
                status = runtime.start()

            self.assertTrue(status["running"])
            args, kwargs = popen.call_args
            self.assertEqual(
                args[0],
                [
                    str(runtime.executable),
                    "serve",
                ],
            )
            self.assertEqual(
                kwargs["env"]["OLLAMA_HOST"],
                "127.0.0.1:11435",
            )
            self.assertEqual(
                kwargs["env"]["OLLAMA_MODELS"],
                str(runtime.models_dir),
            )

    def test_import_gguf_creates_modelfile_and_calls_ollama_create(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            runtime = self.make_runtime(root)
            model = root / "models" / "My Model.Q4_K_M.gguf"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"gguf")

            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="success",
                stderr="",
            )
            with patch.object(
                runtime,
                "start",
                return_value={"running": True},
            ), patch.object(
                runtime,
                "status",
                return_value={"running": True},
            ), patch(
                "caos.ollama_runtime.subprocess.run",
                return_value=completed,
            ) as run:
                result = runtime.import_gguf(
                    str(model),
                    model_name="Trade Brain",
                )

            self.assertEqual(
                result["model"],
                "trade-brain",
            )
            modelfile = (
                runtime.data_dir
                / "ollama-import"
                / "Modelfile"
            )
            self.assertIn(
                model.resolve().as_posix(),
                modelfile.read_text(encoding="utf-8"),
            )
            command = run.call_args.args[0]
            self.assertEqual(
                command[:3],
                [
                    str(runtime.executable),
                    "create",
                    "trade-brain",
                ],
            )

    def test_import_rejects_non_gguf(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            runtime = self.make_runtime(root)
            model = root / "model.bin"
            model.write_bytes(b"x")
            with self.assertRaises(ManagedOllamaError):
                runtime.import_gguf(str(model))


if __name__ == "__main__":
    unittest.main()
