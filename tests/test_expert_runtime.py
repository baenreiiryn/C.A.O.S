import tempfile
from unittest.mock import patch
import unittest
from pathlib import Path
from types import SimpleNamespace

from caos.domain import MarketBar
from caos.expert_runtime import (
    ManagedExpertRuntime,
    RemoteForecastExpert,
    RemoteSentimentExpert,
)


class FakeNewsAnalyzer:
    def __init__(self):
        self.sentiment_expert = None


class ExpertRuntimeTests(unittest.TestCase):
    def test_configure_attaches_remote_oracles_to_caos(self):
        caos = SimpleNamespace(
            forecast_experts={},
            sentiment_expert=None,
            news_analyzer=FakeNewsAnalyzer(),
        )
        with tempfile.TemporaryDirectory() as d:
            runtime = ManagedExpertRuntime(
                caos,
                Path(d),
                app_version="0.8.9",
            )
            runtime._alive = lambda: False
            status = runtime.configure(
                ["kronos", "finbert"]
            )
            self.assertEqual(
                set(caos.forecast_experts),
                {"kronos"},
            )
            self.assertEqual(
                caos.sentiment_expert.name,
                "modernfinbert",
            )
            self.assertIs(
                caos.news_analyzer.sentiment_expert,
                caos.sentiment_expert,
            )
            self.assertIs(
                caos.expert_runtime,
                runtime,
            )
            self.assertEqual(
                status["configured"],
                ["kronos", "finbert"],
            )

    def test_remote_forecast_roundtrips_result_shape(self):
        class Runtime:
            def request(
                self,
                path,
                payload,
                *,
                timeout,
            ):
                self.path = path
                self.payload = payload
                self.timeout = timeout
                return {
                    "model": "kronos-small",
                    "symbol": "BTCUSDT",
                    "horizon": 3,
                    "last_close": 100.0,
                    "forecast_close": 102.0,
                    "expected_return_pct": 2.0,
                    "lower_return_pct": None,
                    "upper_return_pct": None,
                    "path_volatility_pct": 0.5,
                    "metadata": {},
                }

        runtime = Runtime()
        expert = RemoteForecastExpert(
            runtime,
            "kronos",
            "kronos-small",
        )
        bars = [
            MarketBar(
                ts=1,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=1000.0,
            )
        ]
        result = expert.forecast(
            "BTCUSDT",
            bars,
            3,
        )
        self.assertEqual(
            result.model,
            "kronos-small",
        )
        self.assertEqual(
            runtime.path,
            "/forecast",
        )
        self.assertEqual(
            runtime.payload["expert"],
            "kronos",
        )
        self.assertEqual(
            runtime.payload["bars"][0]["close"],
            100.0,
        )

    def test_remote_sentiment_roundtrips_result_shape(self):
        class Runtime:
            def request(
                self,
                path,
                payload,
                *,
                timeout,
            ):
                return {
                    "model": "modernfinbert",
                    "label": "NEGATIVE",
                    "score": 0.9,
                    "signed_score": -0.9,
                    "metadata": {},
                }

        expert = RemoteSentimentExpert(
            Runtime()
        )
        result = expert.classify(
            "earnings miss"
        )
        self.assertEqual(
            result.label,
            "NEGATIVE",
        )
        self.assertAlmostEqual(
            result.signed_score,
            -0.9,
        )

    def test_start_uses_actual_bundled_executable_directory_as_cwd(self):
        caos = SimpleNamespace(
            forecast_experts={},
            sentiment_expert=None,
            news_analyzer=None,
        )
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bundled = root / "app" / "experts-runtime"
            bundled.mkdir(parents=True)
            exe = bundled / "caos-experts.exe"
            exe.write_bytes(b"exe")

            runtime = ManagedExpertRuntime(
                caos,
                root / "data",
                app_version="0.8.10",
                bundled_runtime_dir=bundled,
            )

            alive_calls = {"count": 0}

            def fake_alive():
                alive_calls["count"] += 1
                return alive_calls["count"] >= 2

            runtime._alive = fake_alive

            class FakeProcess:
                def poll(self):
                    return None

            with patch(
                "caos.expert_runtime.subprocess.Popen",
                return_value=FakeProcess(),
            ) as popen:
                runtime.start()

            kwargs = popen.call_args.kwargs
            self.assertEqual(
                Path(kwargs["cwd"]),
                bundled,
            )
            self.assertEqual(
                Path(popen.call_args.args[0][0]),
                exe,
            )
            self.assertNotEqual(
                Path(kwargs["cwd"]),
                runtime.runtime_dir,
            )

    def test_bundled_runtime_is_detected_without_copying(self):
        caos = SimpleNamespace(
            forecast_experts={},
            sentiment_expert=None,
            news_analyzer=None,
        )
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bundled = root / "app" / "experts-runtime"
            bundled.mkdir(parents=True)
            exe = bundled / "caos-experts.exe"
            exe.write_bytes(b"exe")
            runtime = ManagedExpertRuntime(
                caos,
                root / "data",
                app_version="0.8.9",
                bundled_runtime_dir=bundled,
            )
            runtime._alive = lambda: False
            self.assertTrue(runtime.installed())
            self.assertEqual(
                runtime.executable,
                exe,
            )
            self.assertEqual(
                runtime.status()["runtime_dir"],
                str(bundled),
            )


if __name__ == "__main__":
    unittest.main()
