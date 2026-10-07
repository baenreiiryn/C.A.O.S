"""Optional local specialist models for C.A.O.S.

These adapters are intentionally lazy: importing C.A.O.S never downloads or loads
any Hugging Face model. Specialists produce evidence only; they cannot submit orders.
"""

from .base import ExpertUnavailable, ForecastResult, SentimentResult
from .ensemble import ExpertEnsemble
from .registry import MODEL_CATALOG, recommended_stack, build_experts

__all__ = [
    "ExpertUnavailable",
    "ForecastResult",
    "SentimentResult",
    "ExpertEnsemble",
    "MODEL_CATALOG",
    "recommended_stack",
    "build_experts",
]
