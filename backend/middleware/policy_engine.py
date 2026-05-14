"""
Policy Engine for Aegis Twin MVP
Implements governance and versioning for security policies.
"""

import uuid
import yaml
import os
from typing import Dict, List, Optional, Any
from datetime import datetime
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class PolicyEngine:
    """
    Governance & Versioning policy engine.

    Manages version-controlled security policies that determine
    which trajectory executions are allowed or denied.
    """

    def __init__(self, policies_dir: Optional[str] = None):
        """
        Initialize the policy engine.

        Args:
            policies_dir: Directory containing policy YAML files.
                         If None, uses default location from architecture.
        """
        if policies_dir is None:
            # Default to data/policies as per architecture
            self.policies_dir = os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "data",
                "policies"
            )
        else:
            self.policies_dir = policies_dir

        # Ensure policies directory exists
        os.makedirs(self.policies_dir, exist_ok=True)

        # In-memory cache of loaded policies
        self._policy_cache: Dict[str, Dict] = {}
        self._policy_versions: Dict[str, List[str]] = defaultdict(list)

        # Load existing policies
        self._load_policies()

        logger.info(f"PolicyEngine initialized with policies from {self.policies_dir}")

    def _load_policies(self):
        """Load all policy YAML files from the policies directory."""
        try:
            for filename in os.listdir(self.policies_dir):
                if filename.endswith('.yaml') or filename.endswith('.yml'):
                    policy_path = os.path.join(self.policies_dir, filename)
                    self._load_policy_file(policy_path)
        except Exception as e:
            logger.error(f"Error loading policies: {e}")

    def _load_policy_file(self, policy_path: str):
        """Load a single policy YAML file."""
        try:
            with open(policy_path, 'r') as f:
                policy_data = yaml.safe_load(f)

            if not policy_data:
                return

            # Extract policy identifiers
            policy_id = policy_data.get('policy_id')
            policy_version = policy_data.get('policy_version')

            if not policy_id or not policy_version:
                logger.warning(f"Policy missing id or version in {policy_path}")
                return

            # Cache the policy
            cache_key = f"{policy_id}:{policy_version}"
            self._policy_cache[cache_key] = policy_data

            # Track versions
            if policy_version not in self._policy_versions[policy_id]:
                self._policy_versions[policy_id].append(policy_version)
                # Keep versions sorted
                self._policy_versions[policy_id].sort()

            logger.debug(f"Loaded policy {policy_id} version {policy_version}")

        except Exception as e:
            logger.error(f"Error loading policy file {policy_path}: {e}")

    def get_policy(self, policy_id: str, version: Optional[str] = None) -> Optional[Dict]:
        """
        Get a specific policy by ID and version.

        Args:
            policy_id: ID of the policy to retrieve
            version: Specific version to retrieve. If None, gets latest version.

        Returns:
            Policy dictionary or None if not found
        """
        if version is None:
            # Get latest version
            versions = self._policy_versions.get(policy_id, [])
            if not versions:
                return None
            version = versions[-1]  # Latest version

        cache_key = f"{policy_id}:{version}"
        return self._policy_cache.get(cache_key)

    def evaluate_trajectory(
        self,
        trajectory_data: Dict,
        policy_id: Optional[str] = None
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Evaluate a trajectory against applicable policies.

        Args:
            trajectory_data: Dictionary containing trajectory information
            policy_id: Specific policy to check against. If None, checks all relevant policies.

        Returns:
            Tuple of (is_allowed, violated_rule, policy_version)
        """
        try:
            # For MVP, we'll implement a simple velocity-based policy check
            # In a full implementation, this would evaluate complex rule conditions

            # Extract trajectory parameters for evaluation
            target = trajectory_data.get('target', {})
            velocity = trajectory_data.get('velocity', 0.0)  # mm/s or similar units

            # Check if we have a specific policy to evaluate against
            if policy_id:
                policy = self.get_policy(policy_id)
                if policy:
                    allowed, violated_rule = self._evaluate_policy_against_trajectory(
                        policy, trajectory_data
                    )
                    return allowed, violated_rule, policy.get('policy_version')

            # Otherwise, check all policies that might apply
            # For simplicity in MVP, we'll check a default safety policy
            default_policy_id = "pol_safe_velocity"
            policy = self.get_policy(default_policy_id)
            if policy:
                allowed, violated_rule = self._evaluate_policy_against_trajectory(
                    policy, trajectory_data
                )
                if not allowed:  # If violated, return the violation
                    return False, violated_rule, policy.get('policy_version')

            # If no policies are violated, allow by default
            return True, None, "default"

        except Exception as e:
            logger.error(f"Error evaluating trajectory: {e}")
            # Fail safe - deny if we can't evaluate
            return False, "policy_evaluation_error", None

    def _evaluate_policy_against_trajectory(
        self,
        policy: Dict,
        trajectory_data: Dict
    ) -> tuple[bool, Optional[str]]:
        """
        Evaluate a trajectory against a specific policy.

        Args:
            policy: Policy dictionary from YAML
            trajectory_data: Trajectory data to evaluate

        Returns:
            Tuple of (is_allowed, violated_rule)
        """
        try:
            # Extract policy condition
            condition = policy.get('condition', {})
            condition_type = condition.get('type')

            if condition_type == 'parameter_threshold':
                # Evaluate parameter threshold rule
                rules = condition.get('rules', [])
                for rule in rules:
                    parameter = rule.get('parameter')
                    max_value = rule.get('max')
                    min_value = rule.get('min')  # Optional minimum

                    # Get the parameter value from trajectory data
                    actual_value = trajectory_data.get(parameter, 0)

                    # Check maximum threshold
                    if max_value is not None and actual_value > max_value:
                        return False, policy.get('policy_id')

                    # Check minimum threshold if specified
                    if min_value is not None and actual_value < min_value:
                        return False, policy.get('policy_id')

            # Add other condition types as needed
            # For MVP, we'll keep it simple

            # If we get here, no violations found
            return True, None

        except Exception as e:
            logger.error(f"Error evaluating policy: {e}")
            return False, "policy_evaluation_error"

    def create_policy(
        self,
        policy_id: str,
        policy_version: str,
        created_at: Optional[str] = None,
        severity: str = "MEDIUM",
        owner: str = "security_team",
        action: str = "ALLOW",
        condition: Optional[Dict] = None
    ) -> bool:
        """
        Create a new policy and save it to disk.

        Args:
            policy_id: Unique identifier for the policy
            policy_version: Version string (e.g., v1.0.0)
            created_at: Timestamp (ISO format). If None, uses current time.
            severity: Policy severity level
            owner: Policy owner
            action: Default action (ALLOW/DENY)
            condition: Condition dictionary for rule evaluation

        Returns:
            True if policy was created successfully
        """
        try:
            if created_at is None:
                created_at = datetime.utcnow().isoformat() + 'Z'

            policy_data = {
                'policy_id': policy_id,
                'policy_version': policy_version,
                'created_at': created_at,
                'severity': severity,
                'owner': owner,
                'action': action,
                'condition': condition or {}
            }

            # Create filename
            filename = f"{policy_id}_{policy_version}.yaml"
            policy_path = os.path.join(self.policies_dir, filename)

            # Save to YAML file
            with open(policy_path, 'w') as f:
                yaml.dump(policy_data, f, default_flow_style=False, sort_keys=False)

            # Update cache
            cache_key = f"{policy_id}:{policy_version}"
            self._policy_cache[cache_key] = policy_data

            # Update version tracking
            if policy_version not in self._policy_versions[policy_id]:
                self._policy_versions[policy_id].append(policy_version)
                self._policy_versions[policy_id].sort()

            logger.info(f"Created policy {policy_id} version {policy_version}")
            return True

        except Exception as e:
            logger.error(f"Error creating policy: {e}")
            return False

    def get_policy_versions(self, policy_id: str) -> List[str]:
        """Get all versions of a specific policy."""
        return self._policy_versions.get(policy_id, [])

    def get_latest_policy_version(self, policy_id: str) -> Optional[str]:
        """Get the latest version of a specific policy."""
        versions = self.get_policy_versions(policy_id)
        return versions[-1] if versions else None

    def list_all_policies(self) -> Dict[str, List[str]]:
        """List all policies and their versions."""
        return dict(self._policy_versions)


# Convenience function for creating a policy engine
def create_policy_engine(policies_dir: Optional[str] = None) -> PolicyEngine:
    """Create and return a new PolicyEngine instance."""
    return PolicyEngine(policies_dir)


# Initialize default policies if none exist
def initialize_default_policies(policies_dir: Optional[str] = None):
    """Create default safety policies if the policies directory is empty."""
    engine = PolicyEngine(policies_dir)

    # Check if we have any policies
    if not engine.list_all_policies():
        # Create a default velocity safety policy
        engine.create_policy(
            policy_id="pol_safe_velocity",
            policy_version="v1.0.0",
            severity="CRITICAL",
            owner="security_team",
            action="DENY",
            condition={
                "type": "parameter_threshold",
                "rules": [
                    {
                        "parameter": "velocity",
                        "max": 500.0  # mm/s - safe maximum velocity
                    }
                ]
            }
        )

        # Create a workspace boundary policy
        engine.create_policy(
            policy_id="pol_safe_workspace",
            policy_version="v1.0.0",
            severity="CRITICAL",
            owner="security_team",
            action="DENY",
            condition={
                "type": "parameter_threshold",
                "rules": [
                    {
                        "parameter": "distance_from_base",
                        "max": 800.0  # mm - maximum safe reach
                    }
                ]
            }
        )

        logger.info("Created default safety policies")


if __name__ == "__main__":
    # Test the policy engine
    logging.basicConfig(level=logging.INFO)

    engine = create_policy_engine()
    initialize_default_policies()

    # Test policy creation
    print("Testing policy engine...")

    # List policies
    policies = engine.list_all_policies()
    print(f"Policies: {policies}")

    # Test trajectory evaluation
    test_trajectory = {
        "target": {"x": 100, "y": 100, "z": 0},
        "velocity": 300.0  # Should be under limit
    }

    allowed, violated_rule, version = engine.evaluate_trajectory(test_trajectory)
    print(f"Trajectory evaluation - Allowed: {allowed}, Violated: {violated_rule}, Version: {version}")

    # Test violating trajectory
    violating_trajectory = {
        "target": {"x": 100, "y": 100, "z": 0},
        "velocity": 600.0  # Should exceed limit
    }

    allowed, violated_rule, version = engine.evaluate_trajectory(violating_trajectory)
    print(f"Violating trajectory - Allowed: {allowed}, Violated: {violated_rule}, Version: {version}")