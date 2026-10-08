from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Callable, Protocol, runtime_checkable
from uuid import uuid4

from ..domain import Mandate, MarketBar, StrategySpec
from ..execution_fabric import EXECUTION_FABRIC_VERSION
from ..quant import backtest, backtest_execution_trace, robustness
from .strategy import CompanyStrategyRegistry
from .training import TrainingArena, TrainingExperiment, TrainingVariant


RESEARCH_FACTORY_VERSION = "research-factory/v1"
SUPPORTED_FAMILIES = {
    "trend",
    "mean_reversion",
    "breakout",
    "momentum",
}


class ResearchFactoryError(RuntimeError):
    pass


@dataclass(slots=True)
class ResearchHypothesis:
    id: str
    symbol: str
    family: str
    thesis: str
    source: str = "manual"
    parent_strategy_id: str | None = None
    status: str = "proposed"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ResearchCandidate:
    id: str
    hypothesis_id: str
    strategy_id: str
    generator: str
    strategy: StrategySpec
    status: str = "generated"
    evaluation_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "hypothesis_id": self.hypothesis_id,
            "strategy_id": self.strategy_id,
            "generator": self.generator,
            "strategy": asdict(self.strategy),
            "status": self.status,
            "evaluation_id": self.evaluation_id,
        }


@dataclass(slots=True)
class ResearchEvaluation:
    id: str
    candidate_id: str
    passed: bool
    score: float
    backtest: dict
    robustness: dict
    execution_trace: dict
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class PromotionDecision:
    id: str
    symbol: str
    candidate_id: str | None
    candidate_strategy_id: str | None
    prior_champion_strategy_id: str | None
    status: str
    reason: str
    experiment_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@runtime_checkable
class ResearchCandidateGenerator(Protocol):
    name: str

    def generate(
        self,
        hypothesis: ResearchHypothesis,
        *,
        parent: StrategySpec | None = None,
        limit: int = 12,
    ) -> list[StrategySpec]: ...


class BuiltinGridGenerator:
    """Small deterministic local generator with no external dependency."""

    name = "builtin_grid"

    @staticmethod
    def _named(
        hypothesis: ResearchHypothesis,
        index: int,
        *,
        family: str,
        fast: int,
        slow: int,
        stop_loss_pct: float,
        take_profit_pct: float,
        threshold: float,
    ) -> StrategySpec:
        return StrategySpec(
            name=(
                f"rf_{hypothesis.id[:8]}_"
                f"{family}_{index:02d}"
            ),
            family=family,
            fast=fast,
            slow=slow,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            threshold=threshold,
        )

    def generate(
        self,
        hypothesis: ResearchHypothesis,
        *,
        parent: StrategySpec | None = None,
        limit: int = 12,
    ) -> list[StrategySpec]:
        limit = max(1, min(int(limit), 64))
        family = hypothesis.family
        specs: list[StrategySpec] = []

        if parent is not None and parent.family == family:
            fasts = sorted(
                {
                    max(2, parent.fast - 2),
                    parent.fast,
                    parent.fast + 2,
                }
            )
            slows = sorted(
                {
                    max(parent.fast + 2, parent.slow - 8),
                    parent.slow,
                    parent.slow + 8,
                }
            )
            thresholds = sorted(
                {
                    max(0.0, parent.threshold * 0.75),
                    parent.threshold,
                    parent.threshold * 1.25,
                }
            )
            for fast in fasts:
                for slow in slows:
                    if fast >= slow:
                        continue
                    for threshold in thresholds:
                        specs.append(
                            self._named(
                                hypothesis,
                                len(specs),
                                family=family,
                                fast=fast,
                                slow=slow,
                                stop_loss_pct=parent.stop_loss_pct,
                                take_profit_pct=parent.take_profit_pct,
                                threshold=threshold,
                            )
                        )
                        if len(specs) >= limit:
                            return specs

        grids = {
            "trend": [
                (3, 18, 2.0, 4.0, 0.0),
                (5, 21, 2.0, 4.0, 0.0),
                (5, 34, 2.0, 4.5, 0.0),
                (8, 34, 2.5, 5.0, 0.0),
                (8, 55, 2.5, 5.0, 0.0),
            ],
            "momentum": [
                (3, 12, 2.0, 4.0, 0.5),
                (5, 18, 2.0, 4.0, 0.75),
                (8, 24, 2.0, 4.5, 1.0),
                (8, 34, 2.5, 5.0, 1.5),
                (13, 48, 2.5, 5.0, 2.0),
            ],
            "mean_reversion": [
                (3, 14, 2.0, 3.0, 1.25),
                (5, 20, 2.5, 3.0, 1.5),
                (5, 30, 2.5, 3.5, 1.75),
                (8, 40, 3.0, 4.0, 2.0),
            ],
            "breakout": [
                (5, 20, 2.0, 4.0, 0.0),
                (8, 30, 2.5, 5.0, 0.0),
                (10, 40, 2.5, 5.0, 0.0),
                (13, 60, 3.0, 6.0, 0.0),
            ],
        }
        for row in grids[family]:
            specs.append(
                self._named(
                    hypothesis,
                    len(specs),
                    family=family,
                    fast=row[0],
                    slow=row[1],
                    stop_loss_pct=row[2],
                    take_profit_pct=row[3],
                    threshold=row[4],
                )
            )
            if len(specs) >= limit:
                break
        return specs


class CallableResearchGeneratorAdapter:
    """Optional bridge for Qlib, RD-Agent or any future external generator.

    The external dependency stays outside C.A.O.S. The callback must return
    validated StrategySpec objects; the Research Factory still performs all
    deterministic evaluation and promotion gates.
    """

    def __init__(
        self,
        name: str,
        generate_fn: Callable[
            [ResearchHypothesis, StrategySpec | None, int],
            list[StrategySpec],
        ],
    ):
        if not name:
            raise ValueError("generator_name_required")
        self.name = name
        self._generate_fn = generate_fn

    def generate(
        self,
        hypothesis: ResearchHypothesis,
        *,
        parent: StrategySpec | None = None,
        limit: int = 12,
    ) -> list[StrategySpec]:
        rows = self._generate_fn(
            hypothesis,
            parent,
            max(1, min(int(limit), 64)),
        )
        if not isinstance(rows, list):
            raise ResearchFactoryError(
                "external_generator_must_return_list"
            )
        for spec in rows:
            if not isinstance(spec, StrategySpec):
                raise ResearchFactoryError(
                    "external_generator_returned_invalid_strategy"
                )
        return rows


def _candidate_id(
    hypothesis_id: str,
    generator: str,
    spec: StrategySpec,
) -> str:
    payload = json.dumps(
        {
            "hypothesis_id": hypothesis_id,
            "generator": generator,
            "strategy": asdict(spec),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "candidate-" + hashlib.sha256(payload).hexdigest()[:24]


class ResearchFactory:
    """Controlled strategy research pipeline.

    Promotion changes only the strategy registry/champion catalog. It never
    assigns a Trader, allocates capital, or executes a trade.
    """

    def __init__(
        self,
        strategies: CompanyStrategyRegistry,
        training: TrainingArena,
    ):
        self.strategies = strategies
        self.training = training
        self.hypotheses: dict[str, ResearchHypothesis] = {}
        self.candidates: dict[str, ResearchCandidate] = {}
        self.evaluations: dict[str, ResearchEvaluation] = {}
        self.champions: dict[str, str] = {}
        self.decisions: list[PromotionDecision] = []
        self.generators: dict[str, ResearchCandidateGenerator] = {}
        self.register_generator(BuiltinGridGenerator())

    def register_generator(
        self,
        generator: ResearchCandidateGenerator,
    ) -> str:
        if not isinstance(generator, ResearchCandidateGenerator):
            raise ResearchFactoryError("invalid_research_generator")
        name = str(generator.name)
        if not name:
            raise ResearchFactoryError("generator_name_required")
        self.generators[name] = generator
        return name

    def submit_hypothesis(
        self,
        *,
        symbol: str,
        family: str,
        thesis: str,
        source: str = "manual",
        parent_strategy_id: str | None = None,
    ) -> ResearchHypothesis:
        family = family.strip().lower()
        if family not in SUPPORTED_FAMILIES:
            raise ResearchFactoryError("unsupported_strategy_family")
        symbol = symbol.strip().upper()
        if not symbol:
            raise ResearchFactoryError("research_symbol_required")
        if not thesis.strip():
            raise ResearchFactoryError("research_thesis_required")
        if parent_strategy_id is not None:
            self.strategies.get(parent_strategy_id)
        hypothesis = ResearchHypothesis(
            id=uuid4().hex,
            symbol=symbol,
            family=family,
            thesis=thesis.strip(),
            source=source.strip() or "manual",
            parent_strategy_id=parent_strategy_id,
        )
        self.hypotheses[hypothesis.id] = hypothesis
        return hypothesis

    def generate_candidates(
        self,
        hypothesis_id: str,
        *,
        generator_id: str = "builtin_grid",
        limit: int = 12,
    ) -> list[ResearchCandidate]:
        try:
            hypothesis = self.hypotheses[hypothesis_id]
        except KeyError as exc:
            raise ResearchFactoryError(
                "unknown_research_hypothesis"
            ) from exc
        try:
            generator = self.generators[generator_id]
        except KeyError as exc:
            raise ResearchFactoryError(
                "unknown_research_generator"
            ) from exc
        parent = (
            self.strategies.get(hypothesis.parent_strategy_id)
            if hypothesis.parent_strategy_id
            else None
        )
        specs = generator.generate(
            hypothesis,
            parent=parent,
            limit=limit,
        )
        if not specs:
            hypothesis.status = "no_candidates"
            return []
        created: list[ResearchCandidate] = []
        for spec in specs:
            if spec.family != hypothesis.family:
                raise ResearchFactoryError(
                    "candidate_family_mismatch"
                )
            candidate_id = _candidate_id(
                hypothesis.id,
                generator_id,
                spec,
            )
            strategy_id = f"research:{candidate_id}"
            existing = self.candidates.get(candidate_id)
            if existing is not None:
                created.append(existing)
                continue
            candidate = ResearchCandidate(
                id=candidate_id,
                hypothesis_id=hypothesis.id,
                strategy_id=strategy_id,
                generator=generator_id,
                strategy=spec,
            )
            self.candidates[candidate.id] = candidate
            created.append(candidate)
        hypothesis.status = "candidates_generated"
        return created

    @staticmethod
    def _score(
        backtest_row: dict,
        robustness_row: dict,
    ) -> float:
        passed_bonus = 100.0 if robustness_row["passed"] else 0.0
        pf = min(float(backtest_row["profit_factor"]), 20.0)
        pnl = float(backtest_row["pnl_pct"])
        drawdown = float(backtest_row["max_drawdown_pct"])
        trades = int(backtest_row["trades"])
        return (
            passed_bonus
            + pf * 10.0
            + pnl * 0.25
            - drawdown * 0.5
            + min(trades, 100) * 0.02
        )

    def evaluate_candidate(
        self,
        candidate_id: str,
        bars: list[MarketBar],
        *,
        starting_capital: float = 10.0,
        cost_bps: float = 8.0,
        max_drawdown_pct: float = 30.0,
        max_position_pct: float = 20.0,
    ) -> ResearchEvaluation:
        try:
            candidate = self.candidates[candidate_id]
        except KeyError as exc:
            raise ResearchFactoryError(
                "unknown_research_candidate"
            ) from exc
        if not bars:
            raise ResearchFactoryError("research_market_data_required")
        mandate = Mandate(
            starting_capital,
            max_drawdown_pct,
            max_position_pct=max_position_pct,
        )
        bt = backtest(
            candidate.strategy,
            bars,
            cost_bps=cost_bps,
        )
        rb = robustness(
            candidate.strategy,
            bars,
            mandate,
            cost_bps=cost_bps,
        )
        trace = backtest_execution_trace(
            candidate.strategy,
            bars,
            symbol=self.hypotheses[
                candidate.hypothesis_id
            ].symbol,
            requested_weight=max_position_pct / 100.0,
            equity=starting_capital,
            max_notional=(
                starting_capital
                * max_position_pct
                / 100.0
            ),
            cost_bps=cost_bps,
        )
        evaluation = ResearchEvaluation(
            id=uuid4().hex,
            candidate_id=candidate.id,
            passed=bool(rb.passed),
            score=self._score(
                bt.to_dict(),
                asdict(rb),
            ),
            backtest=bt.to_dict(),
            robustness=asdict(rb),
            execution_trace={
                "fabric_version": EXECUTION_FABRIC_VERSION,
                "events": len(trace["events"]),
                "entry_plans": sum(
                    1
                    for row in trace["events"]
                    if row["phase"] == "entry"
                ),
                "exit_plans": sum(
                    1
                    for row in trace["events"]
                    if row["phase"] == "exit"
                ),
            },
            reasons=list(rb.reasons),
        )
        self.evaluations[evaluation.id] = evaluation
        candidate.evaluation_id = evaluation.id
        candidate.status = (
            "qualified" if evaluation.passed else "rejected"
        )
        return evaluation

    def _qualified_candidates(
        self,
        hypothesis_id: str,
    ) -> list[ResearchCandidate]:
        rows = []
        for candidate in self.candidates.values():
            if (
                candidate.hypothesis_id == hypothesis_id
                and candidate.evaluation_id
            ):
                evaluation = self.evaluations[
                    candidate.evaluation_id
                ]
                if evaluation.passed:
                    rows.append(candidate)
        rows.sort(
            key=lambda candidate: self.evaluations[
                candidate.evaluation_id or ""
            ].score,
            reverse=True,
        )
        return rows

    def _record_decision(
        self,
        *,
        symbol: str,
        candidate: ResearchCandidate | None,
        prior_champion: str | None,
        status: str,
        reason: str,
        experiment_id: str | None = None,
    ) -> PromotionDecision:
        decision = PromotionDecision(
            id=uuid4().hex,
            symbol=symbol.upper(),
            candidate_id=candidate.id if candidate else None,
            candidate_strategy_id=(
                candidate.strategy_id if candidate else None
            ),
            prior_champion_strategy_id=prior_champion,
            status=status,
            reason=reason,
            experiment_id=experiment_id,
        )
        self.decisions.append(decision)
        return decision

    def tournament_and_decide(
        self,
        hypothesis_id: str,
        bars: list[MarketBar],
        *,
        starting_capital: float = 10.0,
        cost_bps: float = 8.0,
        max_drawdown_pct: float = 30.0,
        max_position_pct: float = 20.0,
        min_profit_factor_gain: float = 0.0,
        max_drawdown_regression_pct: float = 1.0,
    ) -> PromotionDecision:
        hypothesis = self.hypotheses[hypothesis_id]
        qualified = self._qualified_candidates(hypothesis_id)
        prior_champion = self.champions.get(hypothesis.symbol)
        if not qualified:
            hypothesis.status = "rejected"
            return self._record_decision(
                symbol=hypothesis.symbol,
                candidate=None,
                prior_champion=prior_champion,
                status="rejected",
                reason="no_qualified_candidates",
            )

        challenger = qualified[0]
        if prior_champion is None:
            self.strategies.register(
                challenger.strategy,
                strategy_id=challenger.strategy_id,
            )
            self.champions[hypothesis.symbol] = (
                challenger.strategy_id
            )
            challenger.status = "promoted"
            hypothesis.status = "completed"
            return self._record_decision(
                symbol=hypothesis.symbol,
                candidate=challenger,
                prior_champion=None,
                status="promoted",
                reason="first_qualified_champion",
            )

        champion_spec = self.strategies.get(prior_champion)
        variants = [
            TrainingVariant("champion", champion_spec),
            TrainingVariant("challenger", challenger.strategy),
        ]
        experiment = self.training.run(
            hypothesis.symbol,
            bars,
            variants,
            starting_capital=starting_capital,
            cost_bps=cost_bps,
            max_drawdown_pct=max_drawdown_pct,
            max_position_pct=max_position_pct,
        )
        rows = {
            row["variant"]: row
            for row in experiment.results
        }
        champion_row = rows["champion"]
        challenger_row = rows["challenger"]
        challenger_first = (
            experiment.results[0]["variant"] == "challenger"
        )
        challenger_pf = float(
            challenger_row["backtest"]["profit_factor"]
        )
        champion_pf = float(
            champion_row["backtest"]["profit_factor"]
        )
        challenger_dd = float(
            challenger_row["backtest"]["max_drawdown_pct"]
        )
        champion_dd = float(
            champion_row["backtest"]["max_drawdown_pct"]
        )
        promote = (
            challenger_first
            and bool(challenger_row["robustness"]["passed"])
            and challenger_pf
            >= champion_pf + float(min_profit_factor_gain)
            and challenger_dd
            <= champion_dd
            + float(max_drawdown_regression_pct)
        )

        if promote:
            self.strategies.register(
                challenger.strategy,
                strategy_id=challenger.strategy_id,
            )
            self.champions[hypothesis.symbol] = (
                challenger.strategy_id
            )
            challenger.status = "promoted"
            hypothesis.status = "completed"
            return self._record_decision(
                symbol=hypothesis.symbol,
                candidate=challenger,
                prior_champion=prior_champion,
                status="promoted",
                reason="challenger_won_fair_tournament",
                experiment_id=experiment.id,
            )

        challenger.status = "rejected"
        hypothesis.status = "completed"
        return self._record_decision(
            symbol=hypothesis.symbol,
            candidate=challenger,
            prior_champion=prior_champion,
            status="rejected",
            reason="champion_retained",
            experiment_id=experiment.id,
        )

    def run_cycle(
        self,
        hypothesis_id: str,
        bars: list[MarketBar],
        *,
        generator_id: str = "builtin_grid",
        candidate_limit: int = 12,
        starting_capital: float = 10.0,
        cost_bps: float = 8.0,
        max_drawdown_pct: float = 30.0,
        max_position_pct: float = 20.0,
    ) -> dict:
        candidates = self.generate_candidates(
            hypothesis_id,
            generator_id=generator_id,
            limit=candidate_limit,
        )
        evaluations = [
            self.evaluate_candidate(
                candidate.id,
                bars,
                starting_capital=starting_capital,
                cost_bps=cost_bps,
                max_drawdown_pct=max_drawdown_pct,
                max_position_pct=max_position_pct,
            )
            for candidate in candidates
        ]
        decision = self.tournament_and_decide(
            hypothesis_id,
            bars,
            starting_capital=starting_capital,
            cost_bps=cost_bps,
            max_drawdown_pct=max_drawdown_pct,
            max_position_pct=max_position_pct,
        )
        return {
            "version": RESEARCH_FACTORY_VERSION,
            "hypothesis": self.hypotheses[
                hypothesis_id
            ].to_dict(),
            "candidates": [
                candidate.to_dict()
                for candidate in candidates
            ],
            "evaluations": [
                evaluation.to_dict()
                for evaluation in evaluations
            ],
            "promotion": decision.to_dict(),
        }

    def snapshot(self) -> dict:
        return {
            "version": RESEARCH_FACTORY_VERSION,
            "hypotheses": {
                key: row.to_dict()
                for key, row in self.hypotheses.items()
            },
            "candidates": {
                key: row.to_dict()
                for key, row in self.candidates.items()
            },
            "evaluations": {
                key: row.to_dict()
                for key, row in self.evaluations.items()
            },
            "champions": dict(self.champions),
            "decisions": [
                row.to_dict()
                for row in self.decisions
            ],
            "generators": sorted(self.generators),
        }

    def restore(self, snapshot: dict) -> None:
        if not snapshot:
            return
        version = snapshot.get(
            "version",
            RESEARCH_FACTORY_VERSION,
        )
        if version != RESEARCH_FACTORY_VERSION:
            raise ResearchFactoryError(
                "unsupported_research_factory_version"
            )
        self.hypotheses = {
            key: ResearchHypothesis(**row)
            for key, row in snapshot.get(
                "hypotheses",
                {},
            ).items()
        }
        self.candidates = {}
        for key, row in snapshot.get(
            "candidates",
            {},
        ).items():
            payload = dict(row)
            payload["strategy"] = StrategySpec(
                **payload["strategy"]
            )
            self.candidates[key] = ResearchCandidate(
                **payload
            )
        self.evaluations = {
            key: ResearchEvaluation(**row)
            for key, row in snapshot.get(
                "evaluations",
                {},
            ).items()
        }
        self.champions = {
            str(symbol): str(strategy_id)
            for symbol, strategy_id in snapshot.get(
                "champions",
                {},
            ).items()
        }
        self.decisions = [
            PromotionDecision(**row)
            for row in snapshot.get("decisions", [])
        ]

    def summary(self) -> dict:
        statuses: dict[str, int] = {}
        for candidate in self.candidates.values():
            statuses[candidate.status] = (
                statuses.get(candidate.status, 0) + 1
            )
        return {
            "version": RESEARCH_FACTORY_VERSION,
            "hypotheses": len(self.hypotheses),
            "candidates": len(self.candidates),
            "candidate_statuses": statuses,
            "evaluations": len(self.evaluations),
            "champions": dict(self.champions),
            "promotion_decisions": len(self.decisions),
            "generators": sorted(self.generators),
        }
