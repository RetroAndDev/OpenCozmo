"""
robot/state.py — In-memory robot state tracker.

Holds the last known state of the robot updated from PyCozmo events.
This is read-only for external code; it's updated by the sensor event handlers.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BatteryState:
    """Battery information."""
    voltage: float = 0.0  # volts
    level: float = 0.0    # normalized [0.0 .. 1.0]
    charging: bool = False


@dataclass
class PoseState:
    """Robot pose in space."""
    x: Optional[float] = None  # mm
    y: Optional[float] = None  # mm
    z: Optional[float] = None  # mm


@dataclass
class RobotState:
    """Complete snapshot of the robot's state."""
    battery: BatteryState = field(default_factory=BatteryState)
    pose: PoseState = field(default_factory=PoseState)
    lift_height_mm: float = 0.0
    head_angle_deg: float = 0.0
    cliff_detected: bool = False
    picked_up: bool = False
    falling: bool = False


# Global state holder — updated by sensor event handlers
_state = RobotState()


def get_state() -> RobotState:
    """Return a snapshot of the current robot state."""
    return _state


def update_battery(voltage: float, charging: bool = False) -> None:
    """Update battery information."""
    _state.battery.voltage = round(voltage, 3)
    # Rough normalized level: 3.5 V = 0%, 4.2 V = 100%
    _state.battery.level = round(max(0.0, min(1.0, (voltage - 3.5) / 0.7)), 2)
    _state.battery.charging = charging
    logger.debug("Battery updated: %.2f V (%.0f%%)", voltage, _state.battery.level * 100)


def update_lift(height_mm: float) -> None:
    """Update lift height in mm."""
    _state.lift_height_mm = round(height_mm, 1)


def update_head(angle_rad: float) -> None:
    """Update head angle from radians to degrees."""
    import math
    _state.head_angle_deg = round(math.degrees(angle_rad), 1)


def update_pose(x: Optional[float] = None, y: Optional[float] = None, z: Optional[float] = None) -> None:
    """Update robot pose."""
    if x is not None:
        _state.pose.x = round(x, 1)
    if y is not None:
        _state.pose.y = round(y, 1)
    if z is not None:
        _state.pose.z = round(z, 1)


def update_cliff_detected(detected: bool) -> None:
    """Update cliff sensor state."""
    _state.cliff_detected = detected


def update_picked_up(picked_up: bool) -> None:
    """Update picked-up state."""
    _state.picked_up = picked_up


def update_falling(falling: bool) -> None:
    """Update falling state."""
    _state.falling = falling
