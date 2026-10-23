"""State machine and path enforcement for stage orchestration."""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from reanalysis_tool.config import Config


class State(str, Enum):
    UNINITIALIZED = "UNINITIALIZED"
    PLAN_PARSED = "PLAN_PARSED"
    DATA_INVENTORIED = "DATA_INVENTORIED"
    RUNS_COMPLETE = "RUNS_COMPLETE"
    SYNTHESIZED = "SYNTHESIZED"


_ALLOWED_TRANSITIONS: dict[State, set[State]] = {
    State.UNINITIALIZED: {State.PLAN_PARSED},
    State.PLAN_PARSED: {State.DATA_INVENTORIED},
    State.DATA_INVENTORIED: {State.RUNS_COMPLETE},
    State.RUNS_COMPLETE: {State.SYNTHESIZED},
    State.SYNTHESIZED: set(),
}

_STATE_FILES: dict[State, str] = {
    State.PLAN_PARSED: "ai_work/plan_contract.json",
    State.DATA_INVENTORIED: "ai_work/data_inventory.json",
    State.RUNS_COMPLETE: "ai_work/runs",
    State.SYNTHESIZED: "ai_work/synthesis/final_report.md",
}


class StateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""


class AccessControl:
    """Enforces temporal ordering and stage gating."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._state = self._detect_state()

    @property
    def state(self) -> State:
        return self._state

    def ensure_state(self, expected: State) -> None:
        if self._state != expected:
            raise StateTransitionError(
                f"Expected state {expected.value}, but current state is {self._state.value}."
            )

    def transition_to(self, next_state: State) -> None:
        if next_state not in _ALLOWED_TRANSITIONS[self._state]:
            raise StateTransitionError(
                f"Cannot transition from {self._state.value} to {next_state.value}."
            )
        self._state = next_state

    def _detect_state(self) -> State:
        base = Path(".").resolve()
        for state, rel in _STATE_FILES.items():
            if (base / rel).exists():
                return state
        return State.UNINITIALIZED
