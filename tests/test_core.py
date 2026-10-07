import unittest

from caos.broker import PaperBroker
from caos.compliance import (
    ComplianceEngine,
    ComplianceViolation,
)
from caos.domain import (
    Mandate,
    MarketBar,
    OrderRequest,
    StrategySpec,
)
from caos.llm import StaticLLM
from caos.orchestrator import CAOS, OrchestrationError
from caos.quant import backtest, market_regime
from caos.risk import RiskEngine, RiskViolation
from caos.supervisor import divergence


def trend_bars(n=160):
    bars = []
    p = 100.0
    for i in range(n):
        import math
        nxt = p * (
            1
            + (
                0.10
                + 0.55 * math.sin(i / 4.0)
            )
            / 100
        )
        bars.append(
            MarketBar(
                i,
                p,
                max(p, nxt),
                min(p, nxt),
                nxt,
                1000,
            )
        )
        p = nxt
    return bars


class CoreTests(unittest.TestCase):
    def test_mandate_validation(self):
        with self.assertRaises(ValueError):
            Mandate(0, 10)
        self.assertEqual(
            Mandate(100, 10).max_position_pct,
            20,
        )

    def test_risk_position_cap_and_kill(self):
        risk = RiskEngine(
            Mandate(
                100,
                20,
                max_position_pct=20,
            )
        )
        risk.validate(
            OrderRequest(
                "BTC",
                "buy",
                20,
                100,
                "s",
            )
        )
        with self.assertRaises(RiskViolation):
            risk.validate(
                OrderRequest(
                    "BTC",
                    "buy",
                    20.01,
                    100,
                    "s",
                )
            )
        risk.kill()
        with self.assertRaises(RiskViolation):
            risk.validate(
                OrderRequest(
                    "BTC",
                    "buy",
                    1,
                    100,
                    "s",
                )
            )
        with self.assertRaises(RiskViolation):
            risk.reset_kill_switch_human_only(
                human_confirmation=False
            )
        risk.reset_kill_switch_human_only(
            human_confirmation=True
        )
        self.assertFalse(
            risk.state.kill_switch
        )

    def test_compliance_requires_human_action(self):
        c = ComplianceEngine()
        from caos.domain import Mode
        with self.assertRaises(
            ComplianceViolation
        ):
            c.allow_mode(Mode.LIVE)
        with self.assertRaises(
            ComplianceViolation
        ):
            c.human_arm_live(
                confirmation="yes"
            )
        c.human_arm_live(
            confirmation="ARM LIVE"
        )
        c.allow_mode(Mode.LIVE)

    def test_paper_broker(self):
        risk = RiskEngine(
            Mandate(
                1000,
                20,
                max_position_pct=20,
            )
        )
        b = PaperBroker(
            risk,
            fee_bps=0,
        )
        f = b.execute(
            OrderRequest(
                "ETH",
                "buy",
                100,
                50,
                "demo",
            )
        )
        self.assertEqual(f.notional, 100)
        self.assertAlmostEqual(
            b.cash,
            900,
        )
        self.assertAlmostEqual(
            b.equity({"ETH": 50}),
            1000,
        )

    def test_backtest_and_regime(self):
        bars = trend_bars()
        r = backtest(
            StrategySpec(
                "x",
                "trend",
                3,
                12,
            ),
            bars,
            cost_bps=0,
        )
        self.assertGreaterEqual(
            r.trades,
            1,
        )
        self.assertEqual(
            len(r.equity_curve),
            r.trades + 1,
        )
        reg = market_regime(bars)
        self.assertIn(
            reg["regime"],
            {
                "trend_up",
                "trend_down",
                "range",
            },
        )

    def test_orchestrator_requires_mandate_for_mining(self):
        c = CAOS(
            StaticLLM(
                '{"tool":"mine","args":{"symbol":"BTC"}}'
            )
        )
        c.load_bars(
            "BTC",
            trend_bars(),
        )
        with self.assertRaises(
            OrchestrationError
        ):
            c.handle("mine BTC")

    def test_orchestrator_local_llm_dispatch(self):
        c = CAOS(
            StaticLLM(
                'prefix {"tool":"market_regime",'
                '"args":{"symbol":"BTC"}} suffix'
            )
        )
        c.set_mandate(
            Mandate(
                1000,
                20,
            )
        )
        c.load_bars(
            "BTC",
            trend_bars(),
        )
        out = c.handle("analyze BTC")
        self.assertEqual(
            out["tool"],
            "market_regime",
        )

    def test_orchestrator_blocks_forbidden_tool(self):
        c = CAOS(
            StaticLLM(
                '{"tool":"human_arm_live","args":{}}'
            )
        )
        c.set_mandate(
            Mandate(
                1000,
                20,
            )
        )
        with self.assertRaises(
            OrchestrationError
        ):
            c.handle("arm live")

    def test_divergence(self):
        expected = backtest(
            StrategySpec(
                "x",
                "trend",
                3,
                12,
            ),
            trend_bars(),
            0,
        )
        d = divergence(
            expected,
            [
                1,
                -0.5,
                1.2,
                -0.3,
                0.8,
                0.2,
            ],
        )
        self.assertIn(
            d.status,
            {
                "aligned",
                "watch",
                "diverged",
            },
        )
        self.assertGreaterEqual(
            d.score,
            0,
        )
        self.assertLessEqual(
            d.score,
            1,
        )


if __name__ == "__main__":
    unittest.main()
