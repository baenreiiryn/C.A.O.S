"""Trade Company layer built on top of the shared C.A.O.S engine."""

from .domain import (
    CompanyPolicy,
    Opportunity,
    OpportunityStatus,
    Trader,
    TraderMode,
    TraderStatus,
)
from .treasury import Treasury
from .registry import TraderRegistry
from .rollout import (
    STRATEGY_ROLLOUT_VERSION,
    CanaryAccount,
    StrategyRelease,
    StrategyRolloutError,
    StrategyRolloutManager,
    StrategyRolloutPolicy,
)
from .research import (
    RESEARCH_FACTORY_VERSION,
    BuiltinGridGenerator,
    CallableResearchGeneratorAdapter,
    PromotionDecision,
    QlibResearchGeneratorAdapter,
    RDAgentResearchGeneratorAdapter,
    ResearchCandidate,
    ResearchCandidateGenerator,
    ResearchEvaluation,
    ResearchFactory,
    ResearchFactoryError,
    ResearchHypothesis,
)
from .capital import CapitalAllocator
from .market import MarketAllocator, OpportunityRegistry
from .paper import CompanyPaperBook, CompanyPaperError
from .risk import CompanyRiskGovernor, CompanyRiskViolation
from .adapter import CAOSAdapter
from .company import TradeCompany
from .city import CityPresentationMapper, CityLocation
from .cell import TradeCompanyCell
from .daemon import CompanyDaemon, CompanyDaemonCycle, ScanTarget
from .control import CompanyControlPort
from .diversity import StrategyDiversity
from .improvement import ImprovementManager
from .scout import MarketScout
from .state import CompanyCheckpoint, CompanyCheckpointError
from .strategy import CompanyStrategyRegistry, CompanyStrategyError
from .supervisor import CompanySupervisor
from .training import TrainingArena, TrainingVariant

__all__ = [
    "CAOSAdapter",
    "CapitalAllocator",
    "CityPresentationMapper",
    "CityLocation",
    "CompanyDaemon",
    "CompanyDaemonCycle",
    "ScanTarget",
    "CompanyPaperBook",
    "CompanyPaperError",
    "CompanyCheckpoint",
    "CompanyCheckpointError",
    "CompanyStrategyRegistry",
    "CompanyStrategyError",
    "CompanyPolicy",
    "CompanyControlPort",
    "CompanySupervisor",
    "CompanyRiskGovernor",
    "CompanyRiskViolation",
    "ImprovementManager",
    "MarketAllocator",
    "MarketScout",
    "Opportunity",
    "OpportunityRegistry",
    "OpportunityStatus",
    "StrategyDiversity",
    "RESEARCH_FACTORY_VERSION",
    "BuiltinGridGenerator",
    "CallableResearchGeneratorAdapter",
    "PromotionDecision",
    "QlibResearchGeneratorAdapter",
    "RDAgentResearchGeneratorAdapter",
    "ResearchCandidate",
    "ResearchCandidateGenerator",
    "ResearchEvaluation",
    "ResearchFactory",
    "ResearchFactoryError",
    "ResearchHypothesis",
    "STRATEGY_ROLLOUT_VERSION",
    "CanaryAccount",
    "StrategyRelease",
    "StrategyRolloutError",
    "StrategyRolloutManager",
    "StrategyRolloutPolicy",
    "TradeCompany",
    "TradeCompanyCell",
    "TrainingArena",
    "TrainingVariant",
    "Trader",
    "TraderMode",
    "TraderRegistry",
    "TraderStatus",
    "Treasury",
]
