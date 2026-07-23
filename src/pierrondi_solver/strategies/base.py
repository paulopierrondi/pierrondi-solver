"""Strategy interface."""
from __future__ import annotations

from typing import Protocol

from ..models import ChallengeType, SolveRequest, StrategyOutcome


class Strategy(Protocol):
    name: str
    provider: str

    def supports(self, challenge_type: ChallengeType) -> bool: ...

    def solve(self, request: SolveRequest) -> StrategyOutcome: ...
