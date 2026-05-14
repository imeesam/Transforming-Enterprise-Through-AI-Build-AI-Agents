"""
Audit Logger for Aegis Twin MVP
Initializes and manages SQLite database for traceable audit logging.
"""

import sqlite3
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
import json
import logging
from pathlib import Path


class AuditLogger:
    """
    Manages SQLite database for audit logging matching the schema in Section 5.

    The audit database stores immutable records of every trajectory execution
    for forensic consistency and replayability.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the audit logger and database.

        Args:
            db_path: Path to SQLite database file. If None, uses default location.
        """
        if db_path is None:
            # Default to data/audit.sqlite3 as per architecture
            self.db_path = Path(__file__).parent.parent.parent / "data" / "audit.sqlite3"
        else:
            self.db_path = Path(db_path)

        # Ensure data directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._logger = logging.getLogger(__name__)
        self._initialize_database()

        self._logger.info(f"Audit database initialized at {self.db_path}")

    def _initialize_database(self) -> None:
        """Create the audit table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Create audit table matching Section 5 schema
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    execution_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,  -- ISO8601 format
                    event_type TEXT NOT NULL,  -- PROMPT|TOOL_CALL|STATE_CHANGE|CONFIRMATION
                    decision TEXT NOT NULL,    -- ALLOW|DENY|QUARANTINE
                    policy_snapshot_version TEXT NOT NULL,
                    violated_rule TEXT,        -- Can be NULL
                    execution_lifecycle TEXT NOT NULL,
                    payload_hash TEXT NOT NULL, -- SHA256 hash
                    additional_data TEXT       -- JSON for extensibility
                )
            """)

            # Create indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON audit_records(timestamp)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_request_id
                ON audit_records(request_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_execution_id
                ON audit_records(execution_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_event_type
                ON audit_records(event_type)
            """)

            conn.commit()

    def log_audit_record(
        self,
        request_id: str,
        execution_id: str,
        event_type: str,
        decision: str,
        policy_snapshot_version: str,
        execution_lifecycle: str,
        payload_hash: str = "",
        violated_rule: Optional[str] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log an audit record to the database.

        Args:
            request_id: UUID for the request
            execution_id: UUID for the execution
            event_type: Type of event (PROMPT|TOOL_CALL|STATE_CHANGE|CONFIRMATION)
            decision: Decision made (ALLOW|DENY|QUARANTINE)
            policy_snapshot_version: Version of policy used (e.g., v1.3.2)
            execution_lifecycle: Lifecycle state (from FSM)
            payload_hash: SHA256 hash of the payload
            violated_rule: Rule that was violated (if any, else NULL)
            additional_data: Extra data to store as JSON
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO audit_records (
                        request_id, execution_id, timestamp, event_type,
                        decision, policy_snapshot_version, violated_rule,
                        execution_lifecycle, payload_hash, additional_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    request_id,
                    execution_id,
                    datetime.utcnow().isoformat(),
                    event_type,
                    decision,
                    policy_snapshot_version,
                    violated_rule,
                    execution_lifecycle,
                    payload_hash,
                    json.dumps(additional_data) if additional_data else None
                ))

                conn.commit()

        except Exception as e:
            self._logger.error(f"Failed to log audit record: {e}")
            raise

    def log_state_change(
        self,
        request_id: str,
        execution_id: str,
        event_type: str,
        decision: str,
        policy_snapshot_version: str,
        violated_rule: Optional[str],
        execution_lifecycle: str,
        payload_hash: str,
        additional_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log a state change event (convenience method).

        This matches the parameters expected by the StateManager.
        """
        self.log_audit_record(
            request_id=request_id,
            execution_id=execution_id,
            event_type=event_type,
            decision=decision,
            policy_snapshot_version=policy_snapshot_version,
            violated_rule=violated_rule,
            execution_lifecycle=execution_lifecycle,
            payload_hash=payload_hash,
            additional_data=additional_data
        )

    def get_audit_records(
        self,
        limit: int = 100,
        offset: int = 0,
        request_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        event_type: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        """
        Retrieve audit records with optional filtering.

        Returns:
            List of audit record dictionaries
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row  # Enable column access by name
                cursor = conn.cursor()

                query = """
                    SELECT * FROM audit_records
                    WHERE 1=1
                """
                params = []

                if request_id:
                    query += " AND request_id = ?"
                    params.append(request_id)

                if execution_id:
                    query += " AND execution_id = ?"
                    params.append(execution_id)

                if event_type:
                    query += " AND event_type = ?"
                    params.append(event_type)

                if start_time:
                    query += " AND timestamp >= ?"
                    params.append(start_time)

                if end_time:
                    query += " AND timestamp <= ?"
                    params.append(end_time)

                query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])

                cursor.execute(query, params)
                rows = cursor.fetchall()

                # Convert to list of dicts
                records = []
                for row in rows:
                    record = dict(row)
                    # Parse additional_data JSON if present
                    if record['additional_data']:
                        try:
                            record['additional_data'] = json.loads(record['additional_data'])
                        except json.JSONDecodeError:
                            pass  # Keep as string if invalid JSON
                    records.append(record)

                return records

        except Exception as e:
            self._logger.error(f"Failed to retrieve audit records: {e}")
            return []

    def get_audit_count(
        self,
        request_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        event_type: Optional[str] = None
    ) -> int:
        """Get count of audit records matching criteria."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                query = "SELECT COUNT(*) FROM audit_records WHERE 1=1"
                params = []

                if request_id:
                    query += " AND request_id = ?"
                    params.append(request_id)

                if execution_id:
                    query += " AND execution_id = ?"
                    params.append(execution_id)

                if event_type:
                    query += " AND event_type = ?"
                    params.append(event_type)

                cursor.execute(query, params)
                return cursor.fetchone()[0]

        except Exception as e:
            self._logger.error(f"Failed to get audit count: {e}")
            return 0

    def close(self) -> None:
        """Close database connections (though we use context managers)."""
        # With our current implementation using context managers per operation,
        # explicit close isn't strictly necessary, but provided for completeness.
        pass


# Convenience function for creating an audit logger
def create_audit_logger(db_path: Optional[str] = None) -> AuditLogger:
    """Create and return a new AuditLogger instance."""
    return AuditLogger(db_path)