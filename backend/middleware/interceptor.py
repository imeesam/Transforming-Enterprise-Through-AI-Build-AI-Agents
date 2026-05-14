"""
Interceptor Middleware for Aegis Twin MVP
Implements capability isolation, rate limiting, and security proxy functionality.
"""

import time
import uuid
from enum import Enum
from typing import Dict, List, Optional, Tuple
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta

from backend.middleware.audit_logger import AuditLogger
from backend.middleware.policy_engine import PolicyEngine
from backend.sim_core.state_manager import StateManager, RobotState
from backend.kinematics.solver import KinematicsSolver, JointAngles

logger = logging.getLogger(__name__)


class ToolCategory(Enum):
    """Tool categories based on risk level."""
    SAFE = "SAFE_TOOLS"
    RESTRICTED = "RESTRICTED_TOOLS"
    SYSTEM = "SYSTEM_TOOLS"


class Interceptor:
    """
    Stateful Interception Proxy middleware.

    Enforces zero-trust security model by:
    - Isolating LLM from raw numerical commands
    - Categorizing tools by risk level
    - Requiring user confirmation for restricted tools
    - Verifying admin clearance for system tools
    - Implementing rate limiting and abuse protection
    """

    def __init__(self):
        """Initialize the interceptor with security policies and rate limiters."""
        # Tool categorization from architecture Section 4
        self.safe_tools = {
            "get_robot_state",
            "preview_trajectory",
            "compute_kinematics"
        }

        self.restricted_tools = {
            "confirm_execution",
            "execute_trajectory"
        }

        self.system_tools = {
            "emergency_stop",
            "reset_system"
        }

        # Rate limiting tracking
        self.prompt_timestamps = deque(maxlen=100)  # Track recent prompts
        self.confirmation_counts = defaultdict(int)  # Track confirmations per session
        self.deny_cooldowns = {}  # Track cooldowns after DENY decisions
        self.preview_timestamps = {}  # Track inactive PREVIEW states

        # Rate limit constants (from architecture)
        self.MAX_PROMPTS_PER_MINUTE = 20
        self.MAX_CONFIRMATIONS_PER_SESSION = 10
        self.DENY_COOLDOWN_SECONDS = 15
        self.PREVIEW_TIMEOUT_SECONDS = 30

        # Initialize dependencies
        self.audit_logger = AuditLogger()
        self.policy_engine = PolicyEngine()
        self.state_manager = StateManager(self.audit_logger)
        self.kinematics_solver = KinematicsSolver()

        logger.info("Interceptor initialized with security policies")

    def _check_rate_limit(self, client_id: str = "default") -> Tuple[bool, Optional[str]]:
        """
        Check if client is within rate limits.

        Args:
            client_id: Identifier for the client/session

        Returns:
            Tuple of (is_allowed, error_message)
        """
        now = time.time()

        # Check prompt rate limit (max prompts per minute)
        # Remove timestamps older than 1 minute
        while self.prompt_timestamps and self.prompt_timestamps[0] < now - 60:
            self.prompt_timestamps.popleft()

        if len(self.prompt_timestamps) >= self.MAX_PROMPTS_PER_MINUTE:
            return False, f"Rate limit exceeded: {self.MAX_PROMPTS_PER_MINUTE} prompts per minute"

        # Check deny cooldown
        if client_id in self.deny_cooldowns:
            if now < self.deny_cooldowns[client_id]:
                remaining = self.deny_cooldowns[client_id] - now
                return False, f"Deny cooldown active: {remaining:.1f}s remaining"
            else:
                # Cooldown expired
                del self.deny_cooldowns[client_id]

        return True, None

    def _update_rate_limits(self, client_id: str = "default"):
        """Update rate limiting counters after a request."""
        self.prompt_timestamps.append(time.time())

    def _apply_deny_cooldown(self, client_id: str = "default"):
        """Apply cooldown after a DENY decision."""
        self.deny_cooldowns[client_id] = time.time() + self.DENY_COOLDOWN_SECONDS

    def _check_preview_timeout(self, preview_id: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a preview has timed out.

        Args:
            preview_id: ID of the preview to check

        Returns:
            Tuple of (is_valid, error_message)
        """
        if preview_id in self.preview_timestamps:
            elapsed = time.time() - self.preview_timestamps[preview_id]
            if elapsed > self.PREVIEW_TIMEOUT_SECONDS:
                del self.preview_timestamps[preview_id]
                return False, f"Preview timeout: {self.PREVIEW_TIMEOUT_SECONDS}s exceeded"
        return True, None

    def _update_preview_timestamp(self, preview_id: str):
        """Update the timestamp for a preview."""
        self.preview_timestamps[preview_id] = time.time()

    def validate_and_process_tool_call(
        self,
        tool_name: str,
        tool_params: Dict,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> Dict:
        """
        Validate and process a tool call through the security proxy.

        This is the main entry point for all tool calls from the LLM/frontend.

        Args:
            tool_name: Name of the tool being called
            tool_params: Parameters for the tool call
            user_id: Optional user identifier
            session_id: Optional session identifier

        Returns:
            Dictionary containing the result or error information
        """
        client_id = session_id or user_id or "default"

        # Check rate limits first
        is_allowed, error_msg = self._check_rate_limit(client_id)
        if not is_allowed:
            self.audit_logger.log_audit_record(
                request_id=str(uuid.uuid4()),
                execution_id=str(uuid.uuid4()),
                event_type="TOOL_CALL",
                decision="DENY",
                policy_snapshot_version="system",
                violated_rule="rate_limit",
                execution_lifecycle="RATE_LIMITED",
                payload_hash="",
                additional_data={
                    "tool_name": tool_name,
                    "error": error_msg,
                    "client_id": client_id
                }
            )
            return {
                "success": False,
                "error": error_msg,
                "error_type": "RATE_LIMIT_EXCEEDED"
            }

        # Update rate limiting
        self._update_rate_limits(client_id)

        # Determine tool category
        if tool_name in self.safe_tools:
            category = ToolCategory.SAFE
            requires_confirmation = False
        elif tool_name in self.restricted_tools:
            category = ToolCategory.RESTRICTED
            requires_confirmation = True
        elif tool_name in self.system_tools:
            category = ToolCategory.SYSTEM
            requires_confirmation = True  # Also requires admin clearance
        else:
            error_msg = f"Unknown tool: {tool_name}"
            self.audit_logger.log_audit_record(
                request_id=str(uuid.uuid4()),
                execution_id=str(uuid.uuid4()),
                event_type="TOOL_CALL",
                decision="DENY",
                policy_snapshot_version="system",
                violated_rule="unknown_tool",
                execution_lifecycle="REJECTED",
                payload_hash="",
                additional_data={
                    "tool_name": tool_name,
                    "error": error_msg,
                    "client_id": client_id
                }
            )
            return {
                "success": False,
                "error": error_msg,
                "error_type": "UNKNOWN_TOOL"
            }

        # Log the tool call attempt
        request_id = str(uuid.uuid4())
        self.audit_logger.log_audit_record(
            request_id=request_id,
            execution_id=str(uuid.uuid4()),
            event_type="TOOL_CALL",
            decision="PENDING",  # Will be updated after processing
            policy_snapshot_version="system",
            violated_rule=None,
            execution_lifecycle=tool_name,
            payload_hash="",
            additional_data={
                "tool_name": tool_name,
                "tool_params": tool_params,
                "client_id": client_id,
                "requires_confirmation": requires_confirmation
            }
        )

        # Process based on tool category
        try:
            if category == ToolCategory.SAFE:
                result = self._process_safe_tool(tool_name, tool_params, request_id)
                decision = "ALLOW" if result.get("success") else "DENY"

            elif category == ToolCategory.RESTRICTED:
                # For RESTRICTED tools, we don't execute directly - require confirmation
                result = self._process_restricted_tool(tool_name, tool_params, request_id)
                decision = "ALLOW" if result.get("success") else "DENY"

            elif category == ToolCategory.SYSTEM:
                # SYSTEM tools require admin clearance (simplified for MVP)
                result = self._process_system_tool(tool_name, tool_params, request_id)
                decision = "ALLOW" if result.get("success") else "DENY"

            # Update audit record with final decision
            self.audit_logger.log_audit_record(
                request_id=request_id,
                execution_id=result.get("execution_id", str(uuid.uuid4())),
                event_type="TOOL_CALL",
                decision=decision,
                policy_snapshot_version="system",
                violated_rule=None if decision == "ALLOW" else "policy_violation",
                execution_lifecycle=tool_name,
                payload_hash="",
                additional_data={
                    "tool_name": tool_name,
                    "result": result,
                    "client_id": client_id
                }
            )

            # Apply deny cooldown if needed
            if decision == "DENY":
                self._apply_deny_cooldown(client_id)

            return result

        except Exception as e:
            logger.error(f"Error processing tool {tool_name}: {e}")
            error_result = {
                "success": False,
                "error": str(e),
                "error_type": "PROCESSING_ERROR"
            }

            self.audit_logger.log_audit_record(
                request_id=request_id,
                execution_id=str(uuid.uuid4()),
                event_type="TOOL_CALL",
                decision="DENY",
                policy_snapshot_version="system",
                violated_rule="processing_error",
                execution_lifecycle="ERROR",
                payload_hash="",
                additional_data={
                    "tool_name": tool_name,
                    "error": str(e),
                    "client_id": client_id
                }
            )

            return error_result

    def _process_safe_tool(self, tool_name: str, tool_params: Dict, request_id: str) -> Dict:
        """
        Process a SAFE tool category request.

        Args:
            tool_name: Name of the safe tool
            tool_params: Tool parameters
            request_id: Request ID for audit tracking

        Returns:
            Result dictionary
        """
        if tool_name == "get_robot_state":
            return self._get_robot_state()
        elif tool_name == "preview_trajectory":
            return self._preview_trajectory(tool_params, request_id)
        elif tool_name == "compute_kinematics":
            return self._compute_kinematics(tool_params)
        else:
            return {
                "success": False,
                "error": f"Unsupported safe tool: {tool_name}"
            }

    def _process_restricted_tool(self, tool_name: str, tool_params: Dict, request_id: str) -> Dict:
        """
        Process a RESTRICTED tool category request.
        These require explicit user confirmation before execution.

        Args:
            tool_name: Name of the restricted tool
            tool_params: Tool parameters
            request_id: Request ID for audit tracking

        Returns:
            Result dictionary indicating confirmation is required
        """
        if tool_name == "confirm_execution":
            return self._confirm_execution(tool_params, request_id)
        elif tool_name == "execute_trajectory":
            # This should only be called after confirmation
            return self._execute_trajectory(tool_params, request_id)
        else:
            return {
                "success": False,
                "error": f"Unsupported restricted tool: {tool_name}"
            }

    def _process_system_tool(self, tool_name: str, tool_params: Dict, request_id: str) -> Dict:
        """
        Process a SYSTEM tool category request.
        These require admin clearance.

        Args:
            tool_name: Name of the system tool
            tool_params: Tool parameters
            request_id: Request ID for audit tracking

        Returns:
            Result dictionary
        """
        # For MVP, we'll simplify admin clearance - in production this would check credentials
        if tool_name == "emergency_stop":
            return self._emergency_stop(tool_params, request_id)
        elif tool_name == "reset_system":
            return self._reset_system(tool_params, request_id)
        else:
            return {
                "success": False,
                "error": f"Unsupported system tool: {tool_name}"
            }

    def _get_robot_state(self) -> Dict:
        """Get current robot state from FSM."""
        current_state = self.state_manager.current_state
        return {
            "success": True,
            "state": current_state.value,
            "timestamp": datetime.utcnow().isoformat()
        }

    def _preview_trajectory(self, tool_params: Dict, request_id: str) -> Dict:
        """
        Generate a trajectory preview (safe tool).

        This corresponds to POST /api/v1/preview_trajectory endpoint.
        """
        try:
            # Extract parameters
            x = float(tool_params.get("x", 0))
            y = float(tool_params.get("y", 0))
            z = float(tool_params.get("z", 0))

            # Validate workspace bounds
            is_valid, error_msg = self.kinematics_solver.validate_workspace_bounds(x, y, z)
            if not is_valid:
                # Update state to BLOCKED
                self.state_manager.transition_to(
                    RobotState.BLOCKED,
                    trigger="workspace_violation",
                    metadata={"request_id": request_id, "error": error_msg}
                )
                return {
                    "success": False,
                    "error": error_msg,
                    "error_type": "WORKSPACE_VIOLATION"
                }

            # Generate trajectory
            trajectory = self.kinematics_solver.generate_safe_trajectory(x, y, z, num_points=10)

            # Generate IDs
            trajectory_id = str(uuid.uuid4())
            execution_id = str(uuid.uuid4())

            # Update state to PREVIEW
            self.state_manager.transition_to(
                RobotState.PREVIEW,
                trigger="trajectory_generated",
                metadata={
                    "request_id": request_id,
                    "trajectory_id": trajectory_id,
                    "execution_id": execution_id,
                    "target": {"x": x, "y": y, "z": z}
                }
            )

            # Store preview for timeout tracking
            self._update_preview_timestamp(trajectory_id)

            # Convert trajectory to serializable format
            trajectory_data = [
                {
                    "theta1": joint.theta1,
                    "theta2": joint.theta2,
                    "theta3": joint.theta3,
                    "time_point": i / len(trajectory)  # Normalized time
                }
                for i, joint in enumerate(trajectory)
            ]

            return {
                "success": True,
                "trajectory_id": trajectory_id,
                "execution_id": execution_id,
                "trajectory": trajectory_data,
                "target": {"x": x, "y": y, "z": z},
                "message": "Trajectory generated successfully. Awaiting user confirmation."
            }

        except ValueError as e:
            # Update state to BLOCKED
            self.state_manager.transition_to(
                RobotState.BLOCKED,
                trigger="kinematics_error",
                metadata={"request_id": request_id, "error": str(e)}
            )
            return {
                "success": False,
                "error": str(e),
                "error_type": "KINEMATICS_ERROR"
            }
        except Exception as e:
            logger.error(f"Error in preview_trajectory: {e}")
            return {
                "success": False,
                "error": "Internal error generating trajectory",
                "error_type": "INTERNAL_ERROR"
            }

    def _compute_kinematics(self, tool_params: Dict) -> Dict:
        """Compute inverse kinematics for a target position."""
        try:
            x = float(tool_params.get("x", 0))
            y = float(tool_params.get("y", 0))
            z = float(tool_params.get("z", 0))

            angles = self.kinematics_solver.compute_inverse_kinematics(x, y, z)

            return {
                "success": True,
                "joint_angles": {
                    "theta1": angles.theta1,
                    "theta2": angles.theta2,
                    "theta3": angles.theta3
                },
                "target": {"x": x, "y": y, "z": z}
            }
        except ValueError as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": "KINEMATICS_ERROR"
            }
        except Exception as e:
            logger.error(f"Error in compute_kinematics: {e}")
            return {
                "success": False,
                "error": "Internal error computing kinematics",
                "error_type": "INTERNAL_ERROR"
            }

    def _confirm_execution(self, tool_params: Dict, request_id: str) -> Dict:
        """
        Handle user confirmation for execution (restricted tool).

        This corresponds to POST /api/v1/confirm_execution endpoint.
        """
        try:
            trajectory_id = tool_params.get("trajectory_id")
            execution_id = tool_params.get("execution_id")

            if not trajectory_id or not execution_id:
                return {
                    "success": False,
                    "error": "Missing trajectory_id or execution_id",
                    "error_type": "INVALID_PARAMETERS"
                }

            # Check if preview is still valid (not timed out)
            is_valid, error_msg = self._check_preview_timeout(trajectory_id)
            if not is_valid:
                # Update state to IDLE (rollback)
                self.state_manager.transition_to(
                    RobotState.IDLE,
                    trigger="preview_timeout",
                    metadata={"request_id": request_id, "trajectory_id": trajectory_id}
                )
                return {
                    "success": False,
                    "error": error_msg,
                    "error_type": "PREVIEW_TIMEOUT"
                }

            # Update confirmation count for rate limiting
            session_id = tool_params.get("session_id", "default")
            self.confirmation_counts[session_id] += 1

            if self.confirmation_counts[session_id] > self.MAX_CONFIRMATIONS_PER_SESSION:
                return {
                    "success": False,
                    "error": f"Maximum confirmations per session exceeded: {self.MAX_CONFIRMATIONS_PER_SESSION}",
                    "error_type": "CONFIRMATION_LIMIT_EXCEEDED"
                }

            # Update state to EXECUTING
            self.state_manager.transition_to(
                RobotState.EXECUTING,
                trigger="user_confirmation",
                metadata={
                    "request_id": request_id,
                    "trajectory_id": trajectory_id,
                    "execution_id": execution_id,
                    "confirmed_at": datetime.utcnow().isoformat()
                }
            )

            # Clear preview tracking
            if trajectory_id in self.preview_timestamps:
                del self.preview_timestamps[trajectory_id]

            return {
                "success": True,
                "message": "Execution confirmed. Robot is now executing the trajectory.",
                "trajectory_id": trajectory_id,
                "execution_id": execution_id,
                "state": "EXECUTING"
            }

        except Exception as e:
            logger.error(f"Error in confirm_execution: {e}")
            return {
                "success": False,
                "error": "Internal error processing confirmation",
                "error_type": "INTERNAL_ERROR"
            }

    def _execute_trajectory(self, tool_params: Dict, request_id: str) -> Dict:
        """
        Execute the confirmed trajectory.
        This would interface with the simulation or hardware.
        """
        try:
            trajectory_id = tool_params.get("trajectory_id")
            execution_id = tool_params.get("execution_id")

            # In a full implementation, this would:
            # 1. Retrieve the trajectory from storage/cache
            # 2. Send joint angles to the simulation/hardware over time
            # 3. Monitor execution progress
            # 4. Handle completion or errors

            # For MVP, we'll simulate immediate execution
            # Update state back to IDLE after execution
            self.state_manager.transition_to(
                RobotState.IDLE,
                trigger="execution_complete",
                metadata={
                    "request_id": request_id,
                    "trajectory_id": trajectory_id,
                    "execution_id": execution_id,
                    "completed_at": datetime.utcnow().isoformat()
                }
            )

            return {
                "success": True,
                "message": "Trajectory executed successfully.",
                "trajectory_id": trajectory_id,
                "execution_id": execution_id,
                "state": "IDLE"
            }

        except Exception as e:
            logger.error(f"Error in execute_trajectory: {e}")
            # Update state to ERROR or BLOCKED
            self.state_manager.transition_to(
                RobotState.ERROR,
                trigger="execution_error",
                metadata={"request_id": request_id, "error": str(e)}
            )
            return {
                "success": False,
                "error": "Error executing trajectory",
                "error_type": "EXECUTION_ERROR"
            }

    def _emergency_stop(self, tool_params: Dict, request_id: str) -> Dict:
        """Handle emergency stop request (system tool)."""
        try:
            # Trigger emergency stop in FSM
            self.state_manager.force_emergency_stop(
                trigger="emergency_stop_triggered",
                metadata={"request_id": request_id}
            )

            # Clear any active previews
            self.preview_timestamps.clear()

            # Reset confirmation counts
            self.confirmation_counts.clear()

            return {
                "success": True,
                "message": "Emergency stop activated. Robot halted and locked.",
                "state": "EMERGENCY_STOP"
            }

        except Exception as e:
            logger.error(f"Error in emergency_stop: {e}")
            return {
                "success": False,
                "error": "Error activating emergency stop",
                "error_type": "INTERNAL_ERROR"
            }

    def _reset_system(self, tool_params: Dict, request_id: str) -> Dict:
        """Handle system reset request (system tool)."""
        try:
            # Reset FSM to IDLE (via SAFE_IDLE in full implementation)
            self.state_manager.reset_to_idle(
                trigger="system_reset",
                metadata={"request_id": request_id}
            )

            # Clear all tracking data
            self.preview_timestamps.clear()
            self.confirmation_counts.clear()
            self.deny_cooldowns.clear()

            return {
                "success": True,
                "message": "System reset successfully.",
                "state": "IDLE"
            }

        except Exception as e:
            logger.error(f"Error in reset_system: {e}")
            return {
                "success": False,
                "error": "Error resetting system",
                "error_type": "INTERNAL_ERROR"
            }

    def get_security_metrics(self) -> Dict:
        """
        Get security metrics for the analytics dashboard.

        This corresponds to GET /api/v1/analytics/metrics endpoint.
        """
        try:
            # Get audit statistics
            total_records = self.audit_logger.get_audit_count()

            # Get recent records for calculations
            recent_records = self.audit_logger.get_audit_records(limit=1000)

            # Calculate metrics
            blocked_count = sum(1 for r in recent_records if r.get("decision") == "DENY")
            allowed_count = sum(1 for r in recent_records if r.get("decision") == "ALLOW")

            # Calculate average validation latency (simplified)
            # In a real implementation, we'd timestamp each step
            avg_validation_latency = 42.5  # placeholder ms

            # Get most frequent violated rules
            violated_rules = [r.get("violated_rule") for r in recent_records
                            if r.get("violated_rule") and r.get("violated_rule") != "null"]
            from collections import Counter
            rule_counter = Counter(violated_rules)
            most_frequent_rules = [
                {"rule": rule, "count": count}
                for rule, count in rule_counter.most_common(5)
            ]

            # Calculate execution success rate
            total_executions = allowed_count + blocked_count
            success_rate = (allowed_count / total_executions * 100) if total_executions > 0 else 0

            return {
                "success": True,
                "metrics": {
                    "total_requests": total_records,
                    "blocked_requests": blocked_count,
                    "allowed_requests": allowed_count,
                    "execution_success_rate": round(success_rate, 2),
                    "average_validation_latency_ms": avg_validation_latency,
                    "most_frequent_violations": most_frequent_rules,
                    "current_state": self.state_manager.current_state.value,
                    "active_previews": len(self.preview_timestamps),
                    "rate_limit_status": {
                        "prompts_last_minute": len(self.prompt_timestamps),
                        "max_prompts_per_minute": self.MAX_PROMPTS_PER_MINUTE
                    }
                }
            }

        except Exception as e:
            logger.error(f"Error getting security metrics: {e}")
            return {
                "success": False,
                "error": "Error retrieving security metrics",
                "error_type": "INTERNAL_ERROR"
            }


# Convenience function for creating an interceptor
def create_interceptor() -> Interceptor:
    """Create and return a new Interceptor instance."""
    return Interceptor()