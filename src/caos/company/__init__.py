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
from .capital import CapitalAllocator
from .market import MarketAllocator, OpportunityRegistry
from .paper import CompanyPaperBook, CompanyPaperError
from .risk import CompanyRiskGovernor, CompanyRiskViolation
from .adapter import CAOSAdapter
from .company import TradeCompany
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
    "TradeCompany",
    "TrainingArena",
    "TrainingVariant",
    "Trader",
    "TraderMode",
    "TraderRegistry",
    "TraderStatus",
    "Treasury",
]
