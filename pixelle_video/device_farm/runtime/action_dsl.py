"""Action DSL parser and data model for device farm automation flows.

This module provides YAML-based flow definition parsing with support for:
- Multiple action types (tap, swipe, input_text, wait, screenshot, open_app, back, home)
- Verification strategies (none, screenshot_changed, manual_confirm)
- Semantic point references for device-agnostic automation
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml


class ActionType(str, Enum):
    """Supported action types in the DSL."""

    TAP = "tap"
    SWIPE = "swipe"
    INPUT_TEXT = "input_text"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    OPEN_APP = "open_app"
    BACK = "back"
    HOME = "home"
    PRESS_KEY = "press_key"
    TAP_SEQUENCE = "tap_sequence"
    CONDITIONAL = "conditional"


class VerifyType(str, Enum):
    """Verification strategies after action execution."""

    NONE = "none"
    SCREENSHOT_CHANGED = "screenshot_changed"
    MANUAL_CONFIRM = "manual_confirm"


@dataclass
class ActionStep:
    """Represents a single step in an automation flow.

    Attributes:
        id: Unique identifier for the step
        action: Type of action to perform
        point: Semantic name for the target point (e.g., "login_button")
        wait_after: Seconds to wait after action execution
        verify: Verification strategy to use
        value: Input value for input_text actions
        metadata: Additional action-specific parameters
    """

    id: str
    action: ActionType
    point: Optional[str] = None
    wait_after: float = 0.0
    verify: VerifyType = VerifyType.NONE
    value: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionStep":
        """Parse an ActionStep from a dictionary.

        Args:
            data: Dictionary containing step definition

        Returns:
            Parsed ActionStep instance

        Raises:
            ValueError: If required fields are missing or invalid
        """
        if "id" not in data:
            raise ValueError("Step must have an 'id' field")
        if "action" not in data:
            raise ValueError(f"Step '{data['id']}' must have an 'action' field")

        try:
            action = ActionType(data["action"])
        except ValueError:
            valid_actions = [a.value for a in ActionType]
            raise ValueError(
                f"Invalid action '{data['action']}' in step '{data['id']}'. "
                f"Valid actions: {valid_actions}"
            )

        verify_str = data.get("verify", "none")
        try:
            verify = VerifyType(verify_str)
        except ValueError:
            valid_verifies = [v.value for v in VerifyType]
            raise ValueError(
                f"Invalid verify type '{verify_str}' in step '{data['id']}'. "
                f"Valid types: {valid_verifies}"
            )

        # Extract known fields
        step_data = {
            "id": data["id"],
            "action": action,
            "point": data.get("point"),
            "wait_after": float(data.get("wait_after", 0.0)),
            "verify": verify,
            "value": data.get("value"),
        }

        # Store remaining fields as metadata
        metadata = {
            k: v for k, v in data.items()
            if k not in {"id", "action", "point", "wait_after", "verify", "value"}
        }
        step_data["metadata"] = metadata

        return cls(**step_data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert ActionStep to dictionary representation.

        Returns:
            Dictionary containing step definition
        """
        result = {
            "id": self.id,
            "action": self.action.value,
        }

        if self.point is not None:
            result["point"] = self.point
        if self.wait_after > 0:
            result["wait_after"] = self.wait_after
        if self.verify != VerifyType.NONE:
            result["verify"] = self.verify.value
        if self.value is not None:
            result["value"] = self.value

        # Merge metadata
        result.update(self.metadata)

        return result


@dataclass
class Flow:
    """Represents a complete automation flow.

    Attributes:
        flow_id: Unique identifier for the flow
        steps: List of action steps in execution order
        metadata: Additional flow-level metadata
    """

    flow_id: str
    steps: List[ActionStep]
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Flow":
        """Parse a Flow from a dictionary.

        Args:
            data: Dictionary containing flow definition

        Returns:
            Parsed Flow instance

        Raises:
            ValueError: If required fields are missing or invalid
        """
        if "flow_id" not in data:
            raise ValueError("Flow must have a 'flow_id' field")
        if "steps" not in data:
            raise ValueError(f"Flow '{data['flow_id']}' must have a 'steps' field")
        if not isinstance(data["steps"], list):
            raise ValueError(f"Flow '{data['flow_id']}' steps must be a list")

        steps = [ActionStep.from_dict(step_data) for step_data in data["steps"]]

        # Extract metadata (everything except flow_id and steps)
        metadata = {
            k: v for k, v in data.items()
            if k not in {"flow_id", "steps"}
        }

        return cls(
            flow_id=data["flow_id"],
            steps=steps,
            metadata=metadata,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert Flow to dictionary representation.

        Returns:
            Dictionary containing flow definition
        """
        result = {
            "flow_id": self.flow_id,
            "steps": [step.to_dict() for step in self.steps],
        }
        result.update(self.metadata)
        return result

    def get_step(self, step_id: str) -> Optional[ActionStep]:
        """Retrieve a step by its ID.

        Args:
            step_id: ID of the step to retrieve

        Returns:
            ActionStep if found, None otherwise
        """
        for step in self.steps:
            if step.id == step_id:
                return step
        return None


# Global flow registry
_flow_registry: Dict[str, Flow] = {}


def load_flow(flow_id: str, flows_dir: Optional[Union[str, Path]] = None) -> Flow:
    """Load a flow from a YAML file.

    Args:
        flow_id: ID of the flow to load
        flows_dir: Directory containing flow YAML files.
                   Defaults to config/flows relative to project root.

    Returns:
        Parsed Flow instance

    Raises:
        FileNotFoundError: If flow file doesn't exist
        ValueError: If flow definition is invalid
    """
    # Check registry first
    if flow_id in _flow_registry:
        return _flow_registry[flow_id]

    # Determine flows directory
    if flows_dir is None:
        # Default to config/flows relative to project root
        # Assume this file is in pixelle_video/device_farm/runtime/
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent.parent
        flows_dir = project_root / "config" / "flows"
    else:
        flows_dir = Path(flows_dir)

    # Try to find the flow file
    flow_file = flows_dir / f"{flow_id}.yaml"
    if not flow_file.exists():
        # Try .yml extension
        flow_file = flows_dir / f"{flow_id}.yml"
        if not flow_file.exists():
            raise FileNotFoundError(
                f"Flow file not found: {flow_id}.yaml or {flow_id}.yml in {flows_dir}"
            )

    # Load and parse YAML
    with open(flow_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Flow file {flow_file} must contain a YAML dictionary")

    # Parse flow
    flow = Flow.from_dict(data)

    # Validate flow_id matches filename
    if flow.flow_id != flow_id:
        raise ValueError(
            f"Flow ID mismatch: file is '{flow_id}' but flow_id is '{flow.flow_id}'"
        )

    # Cache in registry
    _flow_registry[flow_id] = flow

    return flow


def get_step(flow_id: str, step_id: str, flows_dir: Optional[Union[str, Path]] = None) -> Optional[ActionStep]:
    """Retrieve a specific step from a flow.

    Args:
        flow_id: ID of the flow containing the step
        step_id: ID of the step to retrieve
        flows_dir: Directory containing flow YAML files

    Returns:
        ActionStep if found, None otherwise

    Raises:
        FileNotFoundError: If flow file doesn't exist
        ValueError: If flow definition is invalid
    """
    flow = load_flow(flow_id, flows_dir)
    return flow.get_step(step_id)


def clear_registry():
    """Clear the flow registry cache. Useful for testing."""
    global _flow_registry
    _flow_registry = {}
