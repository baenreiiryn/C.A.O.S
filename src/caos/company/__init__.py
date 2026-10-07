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
from .risk import CompanyRiskGovernor, CompanyRiskViolation
from .adapter import CAOSAdapter
from .company import TradeCompany

__all__ = [
    "CAOSAdapter",
    "CapitalAllocator",
    "CompanyPolicy",
    "CompanyRiskGovernor",
    "CompanyRiskViolation",
    "MarketAllocator",
    "Opportunity",
    "OpportunityRegistry",
    "OpportunityStatus",
    "TradeCompany",
    "Trader",
    "TraderMode",
    "TraderRegistry",
    "TraderStatus",
    "Treasury",
]
