"""
Main Entry Point for Aegis Twin MVP
FastAPI application that wires together all components:
- FSM (State Manager)
- Interceptor (Security Proxy)
- Kinematics Solver
- Gemini Intent Parser
- Policy Engine
- Audit Logger

Implements the API endpoints from Section 9 of the architecture.
"""

import uuid
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Import our components
from backend.sim_core.state_manager import StateManager, RobotState
from backend.middleware.audit_logger import AuditLogger
from backend.middleware.interceptor import Interceptor
from backend.middleware.policy_engine import PolicyEngine
from backend.agent.intent_parser import GeminiIntentParser, ParsedIntent
from backend.kinematics.solver import KinematicsSolver, JointAngles, LinkLengths

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Aegis Twin MVP API",
    description="Secure Agentic Digital Twin for Industrial Control",
    version="0.1.0"
)

# Add CORS middleware for Lovable frontend via Ngrok
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Accept all origins for Ngrok compatibility
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*", "ngrok-skip-browser-warning"],
)

# Initialize core components
state_manager = StateManager()
audit_logger = AuditLogger()
policy_engine = PolicyEngine()
interceptor = Interceptor()
intent_parser = GeminiIntentParser()
kinematics_solver = KinematicsSolver()

# Initialize default policies if needed
try:
    from backend.middleware.policy_engine import initialize_default_policies
    initialize_default_policies()
except ImportError:
    logger.warning("Could not initialize default policies")

# Pydantic models for request/response validation
class PreviewTrajectoryRequest(BaseModel):
    x: float
    y: float
    z: float

class PreviewTrajectoryResponse(BaseModel):
    success: bool
    trajectory_id: Optional[str] = None
    execution_id: Optional[str] = None
    trajectory: Optional[list] = None
    target: Optional[Dict[str, float]] = None
    message: Optional[str] = None
    error: Optional[str] = None
    error_type: Optional[str] = None

class ConfirmExecutionRequest(BaseModel):
    trajectory_id: str
    execution_id: str
    session_id: Optional[str] = "default"

class ConfirmExecutionResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    trajectory_id: Optional[str] = None
    execution_id: Optional[str] = None
    state: Optional[str] = None
    error: Optional[str] = None
    error_type: Optional[str] = None

class AnalyticsMetricsResponse(BaseModel):
    success: bool
    metrics: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_type: Optional[str] = None

class IntentParseRequest(BaseModel):
    prompt: str

class IntentParseResponse(BaseModel):
    success: bool
    action: Optional[str] = None
    target_coordinates: Optional[Dict[str, float]] = None
    confidence: Optional[float] = None
    raw_text: Optional[str] = None
    error_message: Optional[str] = None

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "Aegis Twin MVP",
        "version": "0.1.0",
        "timestamp": uuid.uuid4().hex
    }

# Section 9: POST /api/v1/preview_trajectory
@app.post("/api/v1/preview_trajectory", response_model=PreviewTrajectoryResponse)
async def preview_trajectory(request: PreviewTrajectoryRequest):
    """
    Deterministic IK calculation. Returns trajectory_id.

    This endpoint:
    1. Validates the target coordinates are within workspace bounds
    2. Generates a smooth trajectory from current position to target
    3. Returns trajectory ID for confirmation
    4. Updates FSM to PREVIEW state
    5. Logs the action for audit trail
    """
    try:
        logger.info(f"Received preview_trajectory request: {request.dict()}")

        # Generate request ID for tracking
        request_id = str(uuid.uuid4())

        # Use interceptor to process the preview_trajectory tool call
        # This handles validation, rate limiting, security checks, and audit logging
        tool_params = {
            "x": request.x,
            "y": request.y,
            "z": request.z
        }

        result = interceptor.validate_and_process_tool_call(
            tool_name="preview_trajectory",
            tool_params=tool_params,
            request_id=request_id
        )

        # Convert interceptor result to API response
        if result.get("success"):
            return PreviewTrajectoryResponse(
                success=True,
                trajectory_id=result.get("trajectory_id"),
                execution_id=result.get("execution_id"),
                trajectory=result.get("trajectory"),
                target=result.get("target"),
                message=result.get("message", "Trajectory generated successfully")
            )
        else:
            return PreviewTrajectoryResponse(
                success=False,
                error=result.get("error", "Unknown error"),
                error_type=result.get("error_type", "UNKNOWN_ERROR")
            )

    except Exception as e:
        logger.error(f"Error in preview_trajectory endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Section 9: POST /api/v1/confirm_execution
@app.post("/api/v1/confirm_execution", response_model=ConfirmExecutionResponse)
async def confirm_execution(request: ConfirmExecutionRequest):
    """
    Starts movement. Requires trajectory_id and execution_id.

    This endpoint:
    1. Validates that the trajectory preview exists and hasn't timed out
    2. Checks user confirmation rate limits
    3. Transitions FSM from PREVIEW to EXECUTING state
    4. Logs the confirmation for audit trail
    5. In a full implementation, would trigger actual trajectory execution
    """
    try:
        logger.info(f"Received confirm_execution request: {request.dict()}")

        # Generate request ID for tracking
        request_id = str(uuid.uuid4())

        # Use interceptor to process the confirm_execution tool call
        tool_params = {
            "trajectory_id": request.trajectory_id,
            "execution_id": request.execution_id,
            "session_id": request.session_id
        }

        result = interceptor.validate_and_process_tool_call(
            tool_name="confirm_execution",
            tool_params=tool_params,
            request_id=request_id
        )

        # Convert interceptor result to API response
        if result.get("success"):
            return ConfirmExecutionResponse(
                success=True,
                message=result.get("message", "Execution confirmed"),
                trajectory_id=result.get("trajectory_id"),
                execution_id=result.get("execution_id"),
                state=result.get("state", "EXECUTING")
            )
        else:
            return ConfirmExecutionResponse(
                success=False,
                error=result.get("error", "Unknown error"),
                error_type=result.get("error_type", "UNKNOWN_ERROR")
            )

    except Exception as e:
        logger.error(f"Error in confirm_execution endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Section 9: GET /api/v1/analytics/metrics
@app.get("/api/v1/analytics/metrics", response_model=AnalyticsMetricsResponse)
async def get_analytics_metrics():
    """
    Serves security metrics to the frontend dashboard.

    This endpoint:
    1. Retrieves audit statistics from the database
    2. Calculates security metrics (blocked/allowed requests, success rates, etc.)
    3. Returns formatted metrics for dashboard display
    """
    try:
        logger.info("Fetching analytics metrics")

        # Use interceptor to get security metrics
        result = interceptor.get_security_metrics()

        if result.get("success"):
            return AnalyticsMetricsResponse(
                success=True,
                metrics=result.get("metrics")
            )
        else:
            return AnalyticsMetricsResponse(
                success=False,
                error=result.get("error", "Unknown error"),
                error_type=result.get("error_type", "UNKNOWN_ERROR")
            )

    except Exception as e:
        logger.error(f"Error in get_analytics_metrics endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Additional endpoints for intent parsing (useful for testing/demo)
@app.post("/api/v1/parse_intent", response_model=IntentParseResponse)
async def parse_intent(request: IntentParseRequest):
    """
    Parse user intent from natural language (for testing/demo purposes).

    This endpoint demonstrates how the Gemini Intent Parser works.
    In production, this would be called by the frontend before sending
    coordinates to the preview_trajectory endpoint.
    """
    try:
        logger.info(f"Parsing intent: {request.prompt}")

        # Parse the user's natural language prompt
        parsed_intent: ParsedIntent = intent_parser.parse_intent(request.prompt)

        # Format response
        response = IntentParseResponse(
            success=parsed_intent.success,
            action=parsed_intent.action if parsed_intent.success else None,
            target_coordinates={
                "x": parsed_intent.target_coordinates[0],
                "y": parsed_intent.target_coordinates[1],
                "z": parsed_intent.target_coordinates[2]
            } if parsed_intent.success and parsed_intent.target_coordinates else None,
            confidence=parsed_intent.confidence if parsed_intent.success else None,
            raw_text=parsed_intent.raw_text,
            error_message=parsed_intent.error_message if not parsed_intent.success else None
        )

        return response

    except Exception as e:
        logger.error(f"Error in parse_intent endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Get current robot state (useful for debugging)
@app.get("/api/v1/robot/state")
async def get_robot_state():
    """Get current robot state from FSM."""
    try:
        current_state = state_manager.current_state
        return {
            "success": True,
            "state": current_state.value,
            "timestamp": uuid.uuid4().hex
        }
    except Exception as e:
        logger.error(f"Error getting robot state: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Emergency stop endpoint
@app.post("/api/v1/emergency_stop")
async def emergency_stop():
    """Trigger emergency stop."""
    try:
        request_id = str(uuid.uuid4())
        result = interceptor.validate_and_process_tool_call(
            tool_name="emergency_stop",
            tool_params={},
            request_id=request_id
        )

        if result.get("success"):
            return {
                "success": True,
                "message": result.get("message", "Emergency stop activated"),
                "state": result.get("state", "EMERGENCY_STOP")
            }
        else:
            raise HTTPException(
                status_code=400,
                detail=result.get("error", "Unknown error")
            )
    except Exception as e:
        logger.error(f"Error in emergency_stop endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# System reset endpoint
@app.post("/api/v1/reset_system")
async def reset_system():
    """Reset the system to IDLE state."""
    try:
        request_id = str(uuid.uuid4())
        result = interceptor.validate_and_process_tool_call(
            tool_name="reset_system",
            tool_params={},
            request_id=request_id
        )

        if result.get("success"):
            return {
                "success": True,
                "message": result.get("message", "System reset successfully"),
                "state": result.get("state", "IDLE")
            }
        else:
            raise HTTPException(
                status_code=400,
                detail=result.get("error", "Unknown error")
            )
    except Exception as e:
        logger.error(f"Error in reset_system endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Startup event
@app.on_event("startup")
async def startup_event():
    """Application startup tasks."""
    logger.info("Starting Aegis Twin MVP API...")
    logger.info(f"Initial robot state: {state_manager.current_state.value}")
    logger.info("API documentation available at /docs")

# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown tasks."""
    logger.info("Shutting down Aegis Twin MVP API...")

if __name__ == "__main__":
    # Run the application
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )