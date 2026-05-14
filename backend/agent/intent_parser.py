"""
Gemini Intent Parser for Aegis Twin MVP
Extracts movement intent from natural language text.
"""

import re
import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ParsedIntent:
    """Represents parsed user intent for robot movement."""
    action: str  # e.g., "move", "goto", "position"
    target_coordinates: Optional[Tuple[float, float, float]]  # (x, y, z)
    confidence: float  # 0.0 to 1.0
    raw_text: str
    success: bool
    error_message: Optional[str] = None


class GeminiIntentParser:
    """
    Simplified Gemini Intent Extractor for MVP.

    In a production implementation, this would interface with the actual
    Gemini 1.5 Pro API to extract structured intents from user prompts.
    For this MVP, we use regex-based coordinate extraction as a placeholder.
    """

    def __init__(self):
        """Initialize the intent parser."""
        # Patterns for extracting coordinates from text
        # Matches formats like: "x,y,z", "(x, y, z)", "x y z", etc.
        self.coordinate_patterns = [
            # Pattern for explicit x,y,z coordinates
            r'(?:x[=:]?\s*)?(-?\d+\.?\d*)\s*[,]\s*(?:y[=:]?\s*)?(-?\d+\.?\d*)\s*[,]\s*(?:z[=:]?\s*)?(-?\d+\.?\d*)',
            # Pattern for coordinates in parentheses
            r'\(\s*(-?\d+\.?\d*)\s*[,]\s*(-?\d+\.?\d*)\s*[,]\s*(-?\d+\.?\d*)\s*\)',
            # Pattern for space-separated coordinates
            r'(?:move|go|position|at)\s+(-?\d+\.?\d*)\s+(-?\d+\.?\d*)\s+(-?\d+\.?\d*)',
        ]

        # Action keywords that indicate movement intent
        self.movement_keywords = {
            'move', 'goto', 'go to', 'position', 'set', 'place',
            'move to', 'go', 'navigate', 'translate', 'shift'
        }

        logger.info("GeminiIntentParser initialized (MVP version)")

    def parse_intent(self, user_prompt: str) -> ParsedIntent:
        """
        Parse user intent from natural language prompt.

        Args:
            user_prompt: Raw text input from user

        Returns:
            ParsedIntent object with extracted information
        """
        try:
            logger.debug(f"Parsing intent from: '{user_prompt}'")

            # Clean and normalize the input
            cleaned_prompt = user_prompt.strip().lower()

            # Check if this appears to be a movement request
            is_movement_request = any(
                keyword in cleaned_prompt
                for keyword in self.movement_keywords
            )

            if not is_movement_request:
                # Could be a question, statement, or other non-movement intent
                return ParsedIntent(
                    action="unknown",
                    target_coordinates=None,
                    confidence=0.0,
                    raw_text=user_prompt,
                    success=False,
                    error_message="No movement intent detected"
                )

            # Extract coordinates using patterns
            coordinates = self._extract_coordinates(cleaned_prompt)

            if coordinates is None:
                return ParsedIntent(
                    action="move",
                    target_coordinates=None,
                    confidence=0.0,
                    raw_text=user_prompt,
                    success=False,
                    error_message="Could not extract coordinates from prompt"
                )

            x, y, z = coordinates

            # Determine action verb
            action = self._extract_action(cleaned_prompt)

            # Calculate confidence based on match quality
            confidence = self._calculate_confidence(cleaned_prompt, coordinates, action)

            logger.info(
                f"Parsed intent: action={action}, "
                f"coordinates=({x:.3f}, {y:.3f}, {z:.3f}), "
                f"confidence={confidence:.2f}"
            )

            return ParsedIntent(
                action=action,
                target_coordinates=(x, y, z),
                confidence=confidence,
                raw_text=user_prompt,
                success=True
            )

        except Exception as e:
            logger.error(f"Error parsing intent: {e}")
            return ParsedIntent(
                action="error",
                target_coordinates=None,
                confidence=0.0,
                raw_text=user_prompt,
                success=False,
                error_message=f"Internal parsing error: {str(e)}"
            )

    def _extract_coordinates(self, text: str) -> Optional[Tuple[float, float, float]]:
        """
        Extract XYZ coordinates from text using regex patterns.

        Args:
            text: Input text to search

        Returns:
            Tuple of (x, y, z) floats or None if not found
        """
        for pattern in self.coordinate_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    x = float(match.group(1))
                    y = float(match.group(2))
                    z = float(match.group(3))
                    return (x, y, z)
                except (ValueError, IndexError):
                    continue

        return None

    def _extract_action(self, text: str) -> str:
        """
        Extract the action verb from the text.

        Args:
            text: Input text

        Returns:
            Action string (default: "move")
        """
        # Look for known action verbs
        for keyword in sorted(self.movement_keywords, key=len, reverse=True):
            if keyword in text:
                return keyword.replace(' ', '_')

        return "move"  # Default action

    def _calculate_confidence(
        self,
        text: str,
        coordinates: Tuple[float, float, float],
        action: str
    ) -> float:
        """
        Calculate confidence score for the parsed intent.

        Args:
            text: Original text
            coordinates: Extracted coordinates
            action: Extracted action

        Returns:
            Confidence score between 0.0 and 1.0
        """
        confidence = 0.0

        # Base confidence for finding coordinates
        confidence += 0.4

        # Bonus for explicit action keyword
        if action != "move":
            confidence += 0.2

        # Bonus for coordinate formatting indicators
        if any(char in text for char in ['(', ')', ',', 'x', 'y', 'z']):
            confidence += 0.2

        # Penalty for very long text (might be unrelated)
        if len(text) > 100:
            confidence -= 0.1

        # Ensure confidence is in valid range
        return max(0.0, min(1.0, confidence))

    def format_as_tool_call(self, parsed_intent: ParsedIntent) -> Dict:
        """
        Format parsed intent as a tool call for the kinematics solver.

        Args:
            parsed_intent: Parsed intent from user

        Returns:
            Dictionary suitable for tool call parameters
        """
        if not parsed_intent.success or parsed_intent.target_coordinates is None:
            return {
                "error": "Invalid intent for tool call",
                "details": parsed_intent.error_message
            }

        x, y, z = parsed_intent.target_coordinates

        return {
            "tool_name": "compute_kinematics",
            "parameters": {
                "x": x,
                "y": y,
                "z": z
            },
            "metadata": {
                "action": parsed_intent.action,
                "confidence": parsed_intent.confidence,
                "original_prompt": parsed_intent.raw_text
            }
        }


# Convenience function for creating an intent parser
def create_intent_parser() -> GeminiIntentParser:
    """Create and return a new GeminiIntentParser instance."""
    return GeminiIntentParser()


# Test function
def test_intent_parsing():
    """Test the intent parser with various inputs."""
    parser = create_intent_parser()

    test_cases = [
        "Move arm to position 0.3, 0.2, 0.1",
        "Go to coordinates (0.5, 0.3, 0.0)",
        "Position the end effector at 100 200 50",
        "Move x=0.2 y=0.1 z=0.05",
        "Hello how are you today?",
        "What is the weather?",
        "Please move the robot to point 0.4, 0.3, 0.2"
    ]

    print("Testing intent parser:")
    print("=" * 50)

    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest {i}: '{test_case}'")
        intent = parser.parse_intent(test_case)
        print(f"  Success: {intent.success}")
        if intent.success:
            print(f"  Action: {intent.action}")
            print(f"  Coordinates: {intent.target_coordinates}")
            print(f"  Confidence: {intent.confidence:.2f}")
        else:
            print(f"  Error: {intent.error_message}")


if __name__ == "__main__":
    # Run tests if executed directly
    logging.basicConfig(level=logging.INFO)
    test_intent_parsing()