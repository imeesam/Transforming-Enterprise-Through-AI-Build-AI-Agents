"""
Deterministic 3-DOF Planar Inverse Kinematics Solver for Aegis Twin MVP.

This module provides deterministic inverse kinematics calculations for a 3-link
planar robotic arm. All calculations are deterministic and do not involve randomness.
"""

import math
from dataclasses import dataclass
from typing import List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class LinkLengths:
    """Lengths of the robotic arm links."""
    l1: float  # Length of first link (base to second joint)
    l2: float  # Length of second link (second to third joint)
    l3: float  # Length of third link (third joint to end effector)


@dataclass
class JointAngles:
    """Joint angles for the robotic arm."""
    theta1: float  # Base joint angle (radians)
    theta2: float  # Second joint angle (radians)
    theta3: float  # Third joint angle (radians)


class KinematicsSolver:
    """
    Deterministic 3-DOF planar Inverse Kinematics solver.

    Implements inverse kinematics for a 3-link planar robotic arm with
    link lengths that can be configured. The solver assumes the arm operates
    in the XY plane with Z representing height (constant for planar movement).
    """

    def __init__(self, link_lengths: Optional[LinkLengths] = None):
        """
        Initialize the kinematics solver.

        Args:
            link_lengths: Lengths of the three arm links. If None, uses default values.
                         Default values assume a reasonable arm configuration.
        """
        if link_lengths is None:
            # Default link lengths - assuming a reasonable arm configuration
            # All lengths in meters
            self.link_lengths = LinkLengths(l1=0.3, l2=0.25, l3=0.2)
        else:
            self.link_lengths = link_lengths

        # Precompute squared link lengths for efficiency
        self.l1_sq = self.link_lengths.l1 ** 2
        self.l2_sq = self.link_lengths.l2 ** 2
        self.l3_sq = self.link_lengths.l3 ** 2

        # Maximum reach (when all links are fully extended)
        self.max_reach = self.link_lengths.l1 + self.link_lengths.l2 + self.link_lengths.l3

        # Minimum reach (when links are folded)
        # For a 3-link arm, minimum reach is more complex but we can use a conservative estimate
        self.min_reach = max(0, self.link_lengths.l1 - self.link_lengths.l2 - self.link_lengths.l3)

        logger.info(f"KinematicsSolver initialized with link lengths: {self.link_lengths}")
        logger.info(f"Maximum reach: {self.max_reach:.3f}m")

    def validate_workspace_bounds(self, x: float, y: float, z: float) -> Tuple[bool, Optional[str]]:
        """
        Validate if the target coordinates are within the robot's workspace.

        Args:
            x, y, z: Target coordinates (meters)

        Returns:
            Tuple of (is_valid, error_message)
        """
        # For planar movement, we primarily care about XY plane
        # Z coordinate is checked for reasonable height limits

        # Calculate distance from base in XY plane
        xy_distance = math.sqrt(x**2 + y**2)

        # Check if point is within reachable workspace
        if xy_distance > self.max_reach:
            return False, f"Target distance {xy_distance:.3f}m exceeds maximum reach {self.max_reach:.3f}m"

        if xy_distance < self.min_reach:
            return False, f"Target distance {xy_distance:.3f}m is below minimum reach {self.min_reach:.3f}m"

        # For a 3-link planar arm, we can reach any point in the annulus between min_reach and max_reach
        # Additional constraints could be added for joint limits, but we'll keep it simple

        # Check Z coordinate - assume reasonable working height
        if abs(z) > 0.5:  # 50cm height limit
            return False, f"Z coordinate {z:.3f}m is outside reasonable height range (-0.5, 0.5)m"

        return True, None

    def compute_inverse_kinematics(self, x: float, y: float, z: float) -> JointAngles:
        """
        Compute inverse kinematics for a 3-DOF planar arm.

        This implementation uses the geometric approach for a 3-link planar arm.
        The third joint angle is used to control the end effector orientation.

        For simplicity, we'll assume the end effector should be parallel to the ground
        (theta3 = 0), which gives us a 2-DOF problem for positioning, then we can
        adjust theta3 for orientation.

        Args:
            x, y, z: Target coordinates (meters)

        Returns:
            JointAngles: The joint angles (theta1, theta2, theta3) in radians

        Raises:
            ValueError: If the target position is not reachable
        """
        # Validate workspace bounds
        is_valid, error_msg = self.validate_workspace_bounds(x, y, z)
        if not is_valid:
            raise ValueError(f"Target position not reachable: {error_msg}")

        # For planar movement in XY plane, we ignore z for position calculation
        # but we could use it for different arm configurations if needed

        # Distance from base to target in XY plane
        xy_distance = math.sqrt(x**2 + y**2)

        # Handle special case where target is at base
        if xy_distance < 1e-6:  # Very close to base
            # Arm folded up
            theta1 = 0.0
            theta2 = math.pi  # Second link folded back
            theta3 = 0.0      # End effector parallel to ground
            return JointAngles(theta1=theta1, theta2=theta2, theta3=theta3)

        # Calculate angle to target from base
        target_angle = math.atan2(y, x)

        # Law of cosines for the triangle formed by links 1 and 2
        # We're solving for the angle at the second joint
        # Using links l1 and l2 to reach distance xy_distance
        # But we have 3 links, so we need to account for l3

        # Approach: treat links 1+2 as one effective link to position the wrist
        # then use link 3 for final positioning

        # For a 3-link arm reaching for position (x,y), we can think of:
        # Positioning the wrist (end of link 2) at a point that allows
        # link 3 to reach the target

        # Let's solve this by considering the effective target for the wrist
        # We want to place the wrist such that link 3 can reach the actual target

        # For simplicity in this MVP, we'll assume the end effector points
        # in the same direction as the arm (theta3 = 0), reducing to a 2-link problem
        # for positioning, with an effective link length of l1 + l2

        # Actually, let's implement a proper 3-link IK solution

        # Method: Solve for theta1 and theta2 assuming theta3 = 0 (end effector horizontal)
        # Then we have a 2-link problem with effective target

        # When theta3 = 0, the end effector position is:
        # x = l1*cos(theta1) + l2*cos(theta1+theta2) + l3*cos(theta1+theta2+theta3)
        # y = l1*sin(theta1) + l2*sin(theta1+theta2) + l3*sin(theta1+theta2+theta3)
        # With theta3 = 0:
        # x = l1*cos(theta1) + l2*cos(theta1+theta2) + l3*cos(theta1+theta2)
        # y = l1*sin(theta1) + l2*sin(theta1+theta2) + l3*sin(theta1+theta2)
        #
        # Let psi = theta1 + theta2 (angle of links 2+3 combined)
        # Then:
        # x = l1*cos(theta1) + (l2+l3)*cos(psi)
        # y = l1*sin(theta1) + (l2+l3)*sin(psi)
        #
        # This is now a 2-link problem with link1 = l1 and link2 = l2+l3

        l1_eff = self.link_lengths.l1
        l2_eff = self.link_lengths.l2 + self.link_lengths.l3

        # Check reachability with effective links
        if xy_distance > (l1_eff + l2_eff) or xy_distance < abs(l1_eff - l2_eff):
            raise ValueError(f"Target position not reachable with current link configuration")

        # Law of cosines to find angle between link1 and link2_eff
        cos_angle2 = (xy_distance**2 - l1_eff**2 - l2_eff**2) / (2 * l1_eff * l2_eff)
        # Clamp to [-1, 1] to handle floating point errors
        cos_angle2 = max(-1, min(1, cos_angle2))
        angle2 = math.acos(cos_angle2)  # This is the angle between link1 and link2_eff

        # Calculate theta1 using law of sines/geometry
        # alpha = angle between link1 and xy_distance line
        cos_alpha = (l1_eff**2 + xy_distance**2 - l2_eff**2) / (2 * l1_eff * xy_distance)
        cos_alpha = max(-1, min(1, cos_alpha))
        alpha = math.acos(cos_alpha)

        # theta1 = target_angle +/- alpha
        # We choose the elbow-up configuration (positive angle2)
        theta1 = target_angle - alpha
        theta2 = math.pi - angle2  # Interior angle at joint 2

        # Now calculate theta3 to maintain end effector orientation
        # With theta1 and theta2 solved, we can calculate what theta3 should be
        # to reach the exact (x,y) target

        # Actual position of joint 2:
        j2x = l1_eff * math.cos(theta1)
        j2y = l1_eff * math.sin(theta1)

        # Vector from joint 2 to target:
        v2t_x = x - j2x
        v2t_y = y - j2y

        # Angle of this vector:
        v2t_angle = math.atan2(v2t_y, v2t_x)

        # theta2_eff is the angle of link 2 relative to link 1
        theta2_eff = theta2  # This is the joint angle

        # Angle of link 2 in world coordinates:
        link2_angle = theta1 + theta2_eff

        # For the end effector to point at the target, we need:
        # theta3 such that link 3 points along v2t_angle
        # link3_angle = link2_angle + theta3 = v2t_angle
        # Therefore: theta3 = v2t_angle - link2_angle
        theta3 = v2t_angle - link2_angle

        # Normalize angles to [-pi, pi] range
        theta1 = self._normalize_angle(theta1)
        theta2 = self._normalize_angle(theta2)
        theta3 = self._normalize_angle(theta3)

        return JointAngles(theta1=theta1, theta2=theta2, theta3=theta3)

    def _normalize_angle(self, angle: float) -> float:
        """Normalize angle to [-pi, pi] range."""
        while angle > math.pi:
            angle -= 2 * math.pi
        while angle < -math.pi:
            angle += 2 * math.pi
        return angle

    def generate_safe_trajectory(self, x: float, y: float, z: float,
                                num_points: int = 10) -> List[JointAngles]:
        """
        Generate a safe trajectory from current position to target position.

        For this MVP, we'll generate a straight-line trajectory in joint space
        from the home position (all joints at 0) to the target position.
        In a real implementation, this would consider current joint positions
        and potentially use cubic splines or other interpolation methods.

        Args:
            x, y, z: Target coordinates (meters)
            num_points: Number of points in the trajectory (including start and end)

        Returns:
            List[JointAngles]: List of joint angles representing the trajectory

        Raises:
            ValueError: If the target position is not reachable
        """
        # Validate target is reachable
        is_valid, error_msg = self.validate_workspace_bounds(x, y, z)
        if not is_valid:
            raise ValueError(f"Target position not reachable: {error_msg}")

        # Get target joint angles
        target_angles = self.compute_inverse_kinematics(x, y, z)

        # Home position (all joints at 0)
        home_angles = JointAngles(theta1=0.0, theta2=0.0, theta3=0.0)

        # Generate trajectory by linear interpolation in joint space
        trajectory = []
        for i in range(num_points):
            # Interpolation parameter (0 to 1)
            t = i / (num_points - 1) if num_points > 1 else 0.5

            # Linear interpolation
            theta1 = home_angles.theta1 + t * (target_angles.theta1 - home_angles.theta1)
            theta2 = home_angles.theta2 + t * (target_angles.theta2 - home_angles.theta2)
            theta3 = home_angles.theta3 + t * (target_angles.theta3 - home_angles.theta3)

            trajectory.append(JointAngles(theta1=theta1, theta2=theta2, theta3=theta3))

        logger.debug(f"Generated trajectory with {len(trajectory)} points to target ({x:.3f}, {y:.3f}, {z:.3f})")
        return trajectory

    def forward_kinematics(self, angles: JointAngles) -> Tuple[float, float, float]:
        """
        Compute forward kinematics (for validation and debugging).

        Args:
            angles: Joint angles (theta1, theta2, theta3) in radians

        Returns:
            Tuple of (x, y, z) coordinates of the end effector
        """
        l1, l2, l3 = self.link_lengths.l1, self.link_lengths.l2, self.link_lengths.l3
        t1, t2, t3 = angles.theta1, angles.theta2, angles.theta3

        x = l1 * math.cos(t1) + l2 * math.cos(t1 + t2) + l3 * math.cos(t1 + t2 + t3)
        y = l1 * math.sin(t1) + l2 * math.sin(t1 + t2) + l3 * math.sin(t1 + t2 + t3)
        z = 0.0  # Planar arm in XY plane

        return x, y, z


def create_solver(link_lengths: Optional[LinkLengths] = None) -> KinematicsSolver:
    """
    Factory function to create a KinematicsSolver instance.

    Args:
        link_lengths: Optional link lengths configuration

    Returns:
        KinematicsSolver: Configured solver instance
    """
    return KinematicsSolver(link_lengths)


# Convenience functions for direct use (as mentioned in architecture)
def compute_inverse_kinematics(x: float, y: float, z: float,
                              link_lengths: Optional[LinkLengths] = None) -> JointAngles:
    """
    Convenience function for computing inverse kinematics.

    Args:
        x, y, z: Target coordinates (meters)
        link_lengths: Optional link lengths configuration

    Returns:
        JointAngles: The joint angles (theta1, theta2, theta3) in radius
    """
    solver = create_solver(link_lengths)
    return solver.compute_inverse_kinematics(x, y, z)


def generate_safe_trajectory(x: float, y: float, z: float,
                            num_points: int = 10,
                            link_lengths: Optional[LinkLengths] = None) -> List[JointAngles]:
    """
    Convenience function for generating a safe trajectory.

    Args:
        x, y, z: Target coordinates (meters)
        num_points: Number of points in the trajectory
        link_lengths: Optional link lengths configuration

    Returns:
        List[JointAngles]: List of joint angles representing the trajectory
    """
    solver = create_solver(link_lengths)
    return solver.generate_safe_trajectory(x, y, z, num_points)


def validate_workspace_bounds(x: float, y: float, z: float,
                             link_lengths: Optional[LinkLengths] = None) -> Tuple[bool, Optional[str]]:
    """
    Convenience function for validating workspace bounds.

    Args:
        x, y, z: Target coordinates (meters)
        link_lengths: Optional link lengths configuration

    Returns:
        Tuple of (is_valid, error_message)
    """
    solver = create_solver(link_lengths)
    return solver.validate_workspace_bounds(x, y, z)


if __name__ == "__main__":
    # Simple test when run directly
    logging.basicConfig(level=logging.INFO)

    solver = KinematicsSolver()

    # Test reachable point
    try:
        x, y, z = 0.3, 0.2, 0.0
        angles = solver.compute_inverse_kinematics(x, y, z)
        print(f"Target: ({x}, {y}, {z})")
        print(f"Joint angles: theta1={angles.theta1:.3f}, theta2={angles.theta2:.3f}, theta3={angles.theta3:.3f}")

        # Verify with forward kinematics
        fx, fy, fz = solver.forward_kinematics(angles)
        print(f"Forward kinematics: ({fx:.3f}, {fy:.3f}, {fz:.3f})")
        print(f"Position error: {math.sqrt((fx-x)**2 + (fy-y)**2 + (fz-z)**2):.6f}m")

        # Generate trajectory
        trajectory = solver.generate_safe_trajectory(x, y, z, 5)
        print(f"Generated trajectory with {len(trajectory)} points")

    except ValueError as e:
        print(f"Error: {e}")

    # Test unreachable point
    try:
        x, y, z = 1.0, 1.0, 0.0  # Likely too far
        angles = solver.compute_inverse_kinematics(x, y, z)
        print(f"This should not print: {angles}")
    except ValueError as e:
        print(f"Correctly unreachable point (1.0, 1.0, 0.0): {e}")