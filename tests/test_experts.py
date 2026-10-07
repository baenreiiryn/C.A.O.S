import unittest

from caos.domain import Mandate, MarketBar
from caos.experts.base import ForecastResult, SentimentResult
from caos.experts.ensemble import ExpertEnsemble
from caos.experts.evaluation import walk_forward_evaluate
from caos.experts.registry import MODEL_CATALOG, build_experts, recommended_stack
from caos.experts.sentiment import ModernFinBERTExpert
from caos.llm import StaticLLM
from caos.orchestrator import CAOS, OrchestrationError


def linear_bars(n=180):
    bars = []
    for i in range(n):
        p = 100.0 + i
        bars.append(
            MarketBar(
                ts=1_700_000_000_000 + i * 3_600_000,
                open=p,
                high=p + 0.5,
                low=p - 0.5,
                close=p,
                volume=1000 + i,
            )
        )
    return bars


class PerfectForecast:
    name = "kronos-small"

    def forecast(self, symbol, bars, horizon):
        last = float(bars[-1].close)
        predicted = last + horizon
        return ForecastResult(
            model=self.name,
            symbol=symbol,
            horizon=horizon,
            last_close=last,
            forecast_close=predicted,
            expected_return_pct=(predicted / last - 1.0) * 100.0,
        )


class BearForecast:
    name = "chronos-2"

    def forecast(self, symbol, bars, horizon):
        last = float(bars[-1].close)
        predicted = last * 0.98
        return ForecastResult(
            model=self.name,
            symbol=symbol,
            horizon=horizon,
            last_close=last,
            forecast_close=predicted,
            expected_return_pct=-2.0,
            lower_return_pct=-3.0,
            upper_return_pct=-1.0,
        )


class FakeSentiment:
    name = "modernfinbert"

    def classify(self, text):
        return SentimentResult(
            model=self.name,
            label="POSITIVE",
            score=0.8,
            signed_score=0.8,
        )


class ExpertTests(unittest.TestCase):
    def test_catalog_uses_open_models(self):
        self.assertEqual(MODEL_CATALOG["kronos"].license, "MIT")
        self.assertEqual(MODEL_CATALOG["chronos2"].license, "Apache-2.0")
        self.assertEqual(MODEL_CATALOG["finbert"].license, "Apache-2.0")
        self.assertEqual(len(recommended_stack()), 3)

    def test_build_experts_is_lazy(self):
        forecasts, sentiment = build_experts(
            ["kronos", "chronos2", "finbert"]
        )
        self.assertEqual(set(forecasts), {"kronos", "chronos2"})
        self.assertEqual(sentiment.name, "modernfinbert")

    def test_finbert_adapter_with_fake_classifier(self):
        expert = ModernFinBERTExpert(
            classifier=lambda text: [
                {"label": "NEGATIVE", "score": 0.9}
            ]
        )
        out = expert.classify("bad earnings")
        self.assertEqual(out.label, "NEGATIVE")
        self.assertAlmostEqual(out.signed_score, -0.9)

    def test_ensemble_is_evidence_only(self):
        bars = linear_bars()
        bullish = PerfectForecast().forecast("BTCUSDT", bars, 6)
        bearish = BearForecast().forecast("BTCUSDT", bars, 6)
        sentiment = FakeSentiment().classify("good")
        out = ExpertEnsemble().combine(
            [bullish, bearish],
            sentiment,
        )
        payload = out.to_dict()
        self.assertEqual(payload["forecast_count"], 2)
        self.assertIn(
            "forecast_is_evidence_not_an_order",
            payload["notes"],
        )
        self.assertNotIn("order", payload)

    def test_walk_forward_qualifies_perfect_expert(self):
        score = walk_forward_evaluate(
            PerfectForecast(),
            "BTCUSDT",
            linear_bars(180),
            horizon=4,
            min_context=80,
            max_windows=10,
        )
        self.assertTrue(score.qualified)
        self.assertEqual(score.direction_accuracy, 1.0)
        self.assertAlmostEqual(score.mae_pct, 0.0)

    def test_orchestrator_specialists(self):
        c = CAOS(
            StaticLLM('{"tool":"status","args":{}}'),
            forecast_experts={
                "kronos": PerfectForecast(),
                "chronos2": BearForecast(),
            },
            sentiment_expert=FakeSentiment(),
        )
        c.set_mandate(Mandate(1000, 20))
        c.load_bars("BTCUSDT", linear_bars())

        one = c.tool_forecast(
            "BTCUSDT",
            expert="kronos",
            horizon=6,
        )
        self.assertGreater(one["expected_return_pct"], 0)

        ensemble = c.tool_forecast_ensemble(
            "BTCUSDT",
            horizon=6,
            news_text="earnings beat",
        )
        self.assertEqual(ensemble["forecast_count"], 2)
        self.assertEqual(
            ensemble["sentiment_signed_score"],
            0.8,
        )

        score = c.tool_evaluate_forecast_expert(
            "BTCUSDT",
            expert="kronos",
            horizon=4,
            min_context=80,
            max_windows=8,
        )
        self.assertTrue(score["qualified"])

    def test_llm_cannot_place_raw_paper_order(self):
        c = CAOS(
            StaticLLM(
                '{"tool":"paper_order","args":{"symbol":"BTCUSDT","side":"buy","notional":10,"price":100}}'
            )
        )
        c.set_mandate(Mandate(1000, 20))
        with self.assertRaises(OrchestrationError):
            c.handle("buy")


if __name__ == "__main__":
    unittest.main()
