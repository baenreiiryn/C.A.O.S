import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from caos.company import (
    CAOSAdapter,
    CallableResearchGeneratorAdapter,
    ResearchCandidateGenerator,
    ResearchFactory,
    TradeCompany,
)
from caos.company.research import (
    RESEARCH_FACTORY_VERSION,
    PromotionDecision,
    ResearchCandidate,
    ResearchEvaluation,
)
from caos.company.standalone import build_policy
from caos.domain import BacktestResult, Mandate, MarketBar, StrategySpec
from caos.llm import StaticLLM
from caos.orchestrator import CAOS
from caos.quant import RobustnessResult
from caos.store import Store


def wave_bars(n=240):
    bars = []
    prev = 100.0
    for i in range(n):
        close = 100.0 + math.sin(i / 5.0) * 8.0 + i * 0.015
        bars.append(
            MarketBar(
                i,
                prev,
                max(prev, close) + 0.3,
                min(prev, close) - 0.3,
                close,
                1000.0,
            )
        )
        prev = close
    return bars


def make_company(directory):
    store = Store(Path(directory) / "research.db")
    caos = CAOS(
        StaticLLM('{"tool":"status","args":{}}'),
        store=store,
    )
    caos.set_mandate(Mandate(1000, 50, max_position_pct=20))
    company = TradeCompany(
        CAOSAdapter(caos),
        build_policy(
            initial_company_capital=10,
            trader_initial_bucket=10,
            trader_stop_floor=3,
            default_trader_max_exposure_pct=20,
            operational_trader_cap=6,
            company_max_drawdown_pct=30,
        ),
        store=store,
    )
    company.bootstrap()
    company.engine.load_bars("BTCUSDT", wave_bars())
    return store, company


def fake_bt(name, *, pf=2.0, pnl=12.0, dd=5.0, trades=8):
    return BacktestResult(
        strategy=name,
        trades=trades,
        pnl_pct=pnl,
        win_rate_pct=62.5,
        profit_factor=pf,
        max_drawdown_pct=dd,
        expectancy_pct=1.5,
        equity_curve=[1.0, 1.12],
        trade_log=[],
    )


def fake_rb(*, passed=True):
    return RobustnessResult(
        passed=passed,
        walk_forward_positive_ratio=0.75 if passed else 0.25,
        monte_carlo_p05_pct=1.0 if passed else -40.0,
        stressed_profit_factor=1.4 if passed else 0.7,
        reasons=[] if passed else ["walk_forward"],
    )


class ResearchFactoryDomainTests(unittest.TestCase):
    def test_version_and_builtin_generator(self):
        self.assertEqual(
            RESEARCH_FACTORY_VERSION,
            "research-factory/v1",
        )
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(d)
            factory = company.research
            hypothesis = factory.submit_hypothesis(
                symbol="BTCUSDT",
                family="momentum",
                thesis="Test momentum variants.",
            )
            candidates = factory.generate_candidates(
                hypothesis.id,
                limit=3,
            )
            self.assertEqual(len(candidates), 3)
            self.assertTrue(
                all(
                    candidate.strategy.family == "momentum"
                    for candidate in candidates
                )
            )
            self.assertEqual(
                len({candidate.id for candidate in candidates}),
                3,
            )
            store.close()

    def test_external_generator_adapter_is_optional_protocol(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(d)

            def generate(hypothesis, parent, limit):
                del parent, limit
                return [
                    StrategySpec(
                        f"external_{hypothesis.id[:6]}",
                        hypothesis.family,
                        3,
                        21,
                        threshold=0.5,
                    )
                ]

            adapter = CallableResearchGeneratorAdapter(
                "fake_qlib_bridge",
                generate,
            )
            self.assertIsInstance(
                adapter,
                ResearchCandidateGenerator,
            )
            company.research.register_generator(adapter)
            hypothesis = company.research.submit_hypothesis(
                symbol="BTCUSDT",
                family="momentum",
                thesis="External candidate provider.",
                source="qlib-test-adapter",
            )
            rows = company.research.generate_candidates(
                hypothesis.id,
                generator_id="fake_qlib_bridge",
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(
                rows[0].generator,
                "fake_qlib_bridge",
            )
            store.close()

    def test_real_evaluation_uses_backtest_robustness_and_fabric_trace(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(d)
            hypothesis = company.research.submit_hypothesis(
                symbol="BTCUSDT",
                family="trend",
                thesis="Evaluate a real deterministic candidate.",
            )
            candidate = company.research.generate_candidates(
                hypothesis.id,
                limit=1,
            )[0]
            evaluation = company.research.evaluate_candidate(
                candidate.id,
                wave_bars(),
                starting_capital=10,
                cost_bps=8,
            )
            self.assertEqual(
                evaluation.candidate_id,
                candidate.id,
            )
            self.assertIn("trades", evaluation.backtest)
            self.assertIn("passed", evaluation.robustness)
            self.assertEqual(
                evaluation.execution_trace["fabric_version"],
                "execution-fabric/v1",
            )
            self.assertEqual(
                evaluation.execution_trace["entry_plans"],
                evaluation.execution_trace["exit_plans"],
            )
            store.close()


class ResearchFactoryPromotionTests(unittest.TestCase):
    def test_first_qualified_candidate_promotes_without_execution(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(d)
            slots_before = company.registry.slot_count()
            fills_before = sum(
                len(account.fills)
                for account in company.paper.accounts.values()
            )
            hypothesis = company.research.submit_hypothesis(
                symbol="BTCUSDT",
                family="momentum",
                thesis="Find first champion.",
            )
            candidate = company.research.generate_candidates(
                hypothesis.id,
                limit=1,
            )[0]

            with patch(
                "caos.company.research.backtest",
                return_value=fake_bt(candidate.strategy.name),
            ), patch(
                "caos.company.research.robustness",
                return_value=fake_rb(),
            ), patch(
                "caos.company.research.backtest_execution_trace",
                return_value={
                    "events": [
                        {"phase": "entry"},
                        {"phase": "exit"},
                    ]
                },
            ):
                company.research.evaluate_candidate(
                    candidate.id,
                    wave_bars(),
                )

            decision = company.research.tournament_and_decide(
                hypothesis.id,
                wave_bars(),
            )
            self.assertEqual(decision.status, "promoted")
            self.assertEqual(
                company.research.champions["BTCUSDT"],
                candidate.strategy_id,
            )
            self.assertIs(
                company.strategies.get(candidate.strategy_id),
                candidate.strategy,
            )
            self.assertEqual(
                company.registry.slot_count(),
                slots_before,
            )
            self.assertEqual(
                sum(
                    len(account.fills)
                    for account in company.paper.accounts.values()
                ),
                fills_before,
            )
            store.close()

    def test_challenger_promotion_and_rejection_use_training_arena(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(d)
            factory = company.research
            champion = StrategySpec(
                "champion",
                "momentum",
                3,
                21,
                threshold=1.5,
            )
            company.register_strategy(
                champion,
                strategy_id="champion",
            )
            factory.champions["BTCUSDT"] = "champion"

            hypothesis = factory.submit_hypothesis(
                symbol="BTCUSDT",
                family="momentum",
                thesis="Challenge incumbent.",
                parent_strategy_id="champion",
            )
            challenger = factory.generate_candidates(
                hypothesis.id,
                limit=1,
            )[0]
            evaluation = ResearchEvaluation(
                id="eval-1",
                candidate_id=challenger.id,
                passed=True,
                score=200.0,
                backtest=fake_bt(
                    challenger.strategy.name,
                    pf=3.0,
                    pnl=20.0,
                    dd=3.0,
                ).to_dict(),
                robustness={
                    "passed": True,
                    "walk_forward_positive_ratio": 1.0,
                    "monte_carlo_p05_pct": 2.0,
                    "stressed_profit_factor": 2.0,
                    "reasons": [],
                },
                execution_trace={},
                reasons=[],
            )
            factory.evaluations[evaluation.id] = evaluation
            challenger.evaluation_id = evaluation.id
            challenger.status = "qualified"

            experiment = company.training.run(
                "BTCUSDT",
                wave_bars(),
                [],
            ) if False else None

            fake_experiment = type(
                "Experiment",
                (),
                {
                    "id": "arena-1",
                    "results": [
                        {
                            "variant": "challenger",
                            "backtest": {
                                "profit_factor": 3.0,
                                "max_drawdown_pct": 3.0,
                            },
                            "robustness": {"passed": True},
                        },
                        {
                            "variant": "champion",
                            "backtest": {
                                "profit_factor": 1.5,
                                "max_drawdown_pct": 4.0,
                            },
                            "robustness": {"passed": True},
                        },
                    ],
                },
            )()
            with patch.object(
                company.training,
                "run",
                return_value=fake_experiment,
            ):
                decision = factory.tournament_and_decide(
                    hypothesis.id,
                    wave_bars(),
                )
            self.assertEqual(decision.status, "promoted")
            self.assertEqual(
                factory.champions["BTCUSDT"],
                challenger.strategy_id,
            )

            second = factory.submit_hypothesis(
                symbol="BTCUSDT",
                family="momentum",
                thesis="Weak challenger.",
            )
            weak = factory.generate_candidates(
                second.id,
                limit=1,
            )[0]
            weak_eval = ResearchEvaluation(
                id="eval-2",
                candidate_id=weak.id,
                passed=True,
                score=150.0,
                backtest=fake_bt(weak.strategy.name).to_dict(),
                robustness={
                    "passed": True,
                    "walk_forward_positive_ratio": 1.0,
                    "monte_carlo_p05_pct": 1.0,
                    "stressed_profit_factor": 1.2,
                    "reasons": [],
                },
                execution_trace={},
                reasons=[],
            )
            factory.evaluations[weak_eval.id] = weak_eval
            weak.evaluation_id = weak_eval.id
            weak.status = "qualified"
            losing_experiment = type(
                "Experiment",
                (),
                {
                    "id": "arena-2",
                    "results": [
                        {
                            "variant": "champion",
                            "backtest": {
                                "profit_factor": 3.0,
                                "max_drawdown_pct": 3.0,
                            },
                            "robustness": {"passed": True},
                        },
                        {
                            "variant": "challenger",
                            "backtest": {
                                "profit_factor": 1.2,
                                "max_drawdown_pct": 5.0,
                            },
                            "robustness": {"passed": True},
                        },
                    ],
                },
            )()
            with patch.object(
                company.training,
                "run",
                return_value=losing_experiment,
            ):
                rejected = factory.tournament_and_decide(
                    second.id,
                    wave_bars(),
                )
            self.assertEqual(rejected.status, "rejected")
            store.close()


class ResearchFactoryCompanyTests(unittest.TestCase):
    def test_company_research_state_survives_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(d)
            hypothesis = company.submit_research_hypothesis(
                symbol="BTCUSDT",
                family="trend",
                thesis="Persist this hypothesis.",
            )
            company.research.generate_candidates(
                hypothesis["id"],
                limit=2,
            )
            company.checkpoint()

            restored = TradeCompany(
                company.engine,
                company.policy,
                store=store,
            )
            self.assertTrue(restored.restore_checkpoint())
            self.assertEqual(
                restored.research.summary()["hypotheses"],
                1,
            )
            self.assertEqual(
                restored.research.summary()["candidates"],
                2,
            )
            store.close()

    def test_old_checkpoint_without_research_restores_empty_factory(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(d)
            company.checkpoint()
            payload = store.get_json(
                "trade_company_checkpoint_v1"
            )
            payload.pop("research", None)
            store.set_json(
                "trade_company_checkpoint_v1",
                payload,
            )
            restored = TradeCompany(
                company.engine,
                company.policy,
                store=store,
            )
            self.assertTrue(restored.restore_checkpoint())
            self.assertEqual(
                restored.research.summary()["hypotheses"],
                0,
            )
            store.close()

    def test_company_status_and_cell_metrics_include_research(self):
        with tempfile.TemporaryDirectory() as d:
            store, company = make_company(d)
            company.submit_research_hypothesis(
                symbol="BTCUSDT",
                family="trend",
                thesis="Observe research.",
            )
            status = company.status()
            self.assertEqual(
                status["research_summary"]["hypotheses"],
                1,
            )
            from caos.company.cell import TradeCompanyCell
            from caos.company.control import CompanyControlPort
            metrics = TradeCompanyCell(
                CompanyControlPort(company)
            ).get_metrics()
            self.assertEqual(
                metrics["values"]["research_hypotheses"],
                1,
            )
            store.close()


if __name__ == "__main__":
    unittest.main()
