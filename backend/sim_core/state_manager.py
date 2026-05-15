"""
State Manager for Aegis Twin MVP
Implements the explicit Finite State Machine for robot operational status.
"""

from enum import Enum
from typing import Optional, Callable
from dataclasses import dataclass
from datetime import datetime
import logging

from backend.middleware.audit_logger import AuditLogger


class RobotState(Enum):
    """Finite State Machine states for robot operational status."""
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    VALIDATING = "VALIDATING"
    PREVIEW = "PREVIEW"
    EXECUTING = "EXECUTING"
    BLOCKED = "BLOCKED"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"


@dataclass
class StateTransition:
    """Represents a state transition in the FSM."""
    from_state: RobotState
    to_state: RobotState
    timestamp: datetime
    trigger: str
    metadata: Optional[dict] = None


class StateManager:
    """
    Manages the robot's operational state machine and logs transitions.

    The FSM governs the robot's operational status throughout the execution lifecycle.
    """

    def __init__(self, audit_logger: Optional[AuditLogger] = None):
        self._current_state = RobotState.IDLE
        self._audit_logger = audit_logger or AuditLogger()
        self._state_change_callbacks: list[Callable[[RobotState, RobotState], None]] = []
        self._logger = logging.getLogger(__name__)

        # Log initial state
        self._log_state_transition(
            from_state=None,
            to_state=self._current_state,
            trigger="initialization"
        )

    @property
    def current_state(self) -> RobotState:
        """Get the current state of the FSM."""
        return self._current_state

    def add_state_change_callback(self, callback: Callable[[RobotState, RobotState], None]) -> None:
        """Add a callback to be notified of state changes."""
        self._state_change_callbacks.append(callback)

    def transition_to(
        self,
        new_state: RobotState,
        trigger: str = "",
        metadata: Optional[dict] = None
    ) -> bool:
        """
        Transition to a new state.

        Args:
            new_state: The state to transition to
            trigger: Description of what triggered the transition
            metadata: Additional data to log with the transition

        Returns:
            True if transition was successful, False if invalid
        """
        if not self._is_valid_transition(new_state):
            self._logger.warning(
                f"Invalid state transition from {self._current_state.value} to {new_state.value}"
            )
            return False

        old_state = self._current_state
        self._current_state = new_state

        # Log the transition
        self._log_state_transition(
            from_state=old_state,
            to_state=new_state,
            trigger=trigger,
            metadata=metadata
        )

        # Notify callbacks
        for callback in self._state_change_callbacks:
            try:
                callback(old_state, new_state)
            except Exception as e:
                self._logger.error(f"Error in state change callback: {e}")

        self._logger.info(
            f"State transition: {old_state.value} -> {new_state.value} "
            f"(trigger: {trigger})"
        )
        return True

    def _is_valid_transition(self, new_state: RobotState) -> bool:
        """
        Check if a transition to new_state is valid based on FSM rules.

        Based on the state diagram in architecture.md:
        [*] --> IDLE
        IDLE --> PLANNING : Intent Parsed
        PLANNING --> VALIDATING : Trajectory Generated
        VALIDATING --> PREVIEW : Proxy ALLOW
        VALIDATING --> BLOCKED : Proxy DENY
        PREVIEW --> EXECUTING : User Confirms
        PREVIEW --> ROLLBACK_PENDING : User Cancels / Timeout
        EXECUTING --> IDLE : Execution Complete
        EXECUTING --> EMERGENCY_STOP : Safe Halt Triggered
        BLOCKED --> IDLE : Reset
        ROLLBACK_PENDING --> IDLE : State Cleared
        EMERGENCY_STOP --> SAFE_IDLE : Admin Override
        SAFE_IDLE --> IDLE : System Reset
        """
        # Define valid transitions
        valid_transitions = {
            RobotState.IDLE: {
                RobotState.PLANNING,
                RobotState.EMERGENCY_STOP,  # Can go to E-Stop from any state
            },
            RobotState.PLANNING: {
                RobotState.VALIDATING,
                RobotState.BLOCKED,
                RobotState.EMERGENCY_STOP,
            },
            RobotState.VALIDATING: {
                RobotState.PREVIEW,
                RobotState.BLOCKED,
                RobotState.EMERGENCY_STOP,
            },
            RobotState.PREVIEW: {
                RobotState.EXECUTING,
                RobotState.ROLLBACK_PENDING,
                RobotState.EMERGENCY_STOP,
            },
            RobotState.EXECUTING: {
                RobotState.IDLE,
                RobotState.EMERGENCY_STOP,
            },
            RobotState.BLOCKED: {
                RobotState.IDLE,
                RobotState.EMERGENCY_STOP,
            },
            RobotState.ROLLBACK_PENDING: {
                RobotState.IDLE,
            },
            RobotState.EMERGENCY_STOP: {
                RobotState.IDLE,  # Simplified - in reality goes to SAFE_IDLE first
            },
        }

        # Emergency stop can be triggered from any state
        if new_state == RobotState.EMERGENCY_STOP:
            return True

        return new_state in valid_transitions.get(self._current_state, set())

    def _log_state_transition(
        self,
        from_state: Optional[RobotState],
        to_state: RobotState,
        trigger: str,
        metadata: Optional[dict] = None
    ) -> None:
        """Log a state transition to the audit database."""
        transition = StateTransition(
            from_state=from_state or RobotState.IDLE,  # For initial state
            to_state=to_state,
            timestamp=datetime.utcnow(),
            trigger=trigger,
            metadata=metadata or {}
        )

        # Log to audit system
        policy_snapshot_version = transition.metadata.get("policy_snapshot_version", "system")
        violated_rule = transition.metadata.get("violated_rule")
        self._audit_logger.log_state_change(
            request_id=transition.metadata.get("request_id", "system"),
            execution_id=transition.metadata.get("execution_id", "system"),
            event_type="STATE_CHANGE",
            decision="DENY" if to_state in {RobotState.BLOCKED, RobotState.EMERGENCY_STOP} else "ALLOW",
            policy_snapshot_version=policy_snapshot_version,
            violated_rule=violated_rule,
            execution_lifecycle=to_state.value,

            payload_hash="",
            additional_data={
                "from_state": from_state.value if from_state else None,
                "to_state": to_state.value,
                "trigger": trigger,
                **(transition.metadata or {})
            }
        )

    def force_emergency_stop(self, trigger: str = "manual_trigger") -> None:
        """Force an immediate transition to EMERGENCY_STOP state."""
        self.transition_to(RobotState.EMERGENCY_STOP, trigger=trigger)

    def reset_to_idle(self, trigger: str = "reset") -> None:
        """Reset the FSM to IDLE state."""
        self.transition_to(RobotState.IDLE, trigger=trigger)


# Convenience function for creating a state manager
def create_state_manager() -> StateManager:
    """Create and return a new StateManager instance."""
    return StateManager()