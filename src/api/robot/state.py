"""
robot/state.py — In-memory robot state tracker.

Holds the last known state of the robot updated from PyCozmo events.
This is read-only for external code; it's updated by the sensor event handlers.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
from pycozmo.client import Client as PyCozmoClient
from pycozmo.util import Pose
from pycozmo.robot import RobotOrientation

logger = logging.getLogger(__name__)


@dataclass
class BatteryState:
    """Battery information."""
    voltage: float = 0.0  # volts
    level: float = 0.0    # normalized [0.0 .. 1.0]

@dataclass
class Vector3:
    """Robot pose in space."""
    x: Optional[float] = None  # mm
    y: Optional[float] = None  # mm
    z: Optional[float] = None  # mm

@dataclass
class RobotState:
    """Complete snapshot of the robot's state."""
    battery: BatteryState = field(default_factory=BatteryState)
    pose: Pose = field(default_factory=lambda: Pose(0, 0, 0, 0, 0, 0, 1))
    pose_pitch: float = 0.0  # degrees
    lift_height_mm: float = 0.0
    head_angle_deg: float = 0.0
    cliff_detected: bool = False
    picked_up: bool = False
    falling: bool = False
    accelerometer: Vector3 = field(default_factory=Vector3)
    gyroscope: Vector3 = field(default_factory=Vector3)
    right_wheel_speed: Optional[float] = None  # mm/s
    left_wheel_speed: Optional[float] = None   # mm/s
    orientation: Optional[RobotOrientation] = None

    def get_json(self) -> dict:
        """Return the current robot state as a JSON-serializable dict."""
        return {
            "battery": {
                "voltage": self.battery.voltage,
                "level": self.battery.level,
            },
            "pose": {
                "position": {
                    "x": self.pose.position.x,
                    "y": self.pose.position.y,
                    "z": self.pose.position.z
                },
                "rotation": {
                    "q0": self.pose.rotation.q0,
                    "q1": self.pose.rotation.q1,
                    "q2": self.pose.rotation.q2,
                    "q3": self.pose.rotation.q3
                },
                "origin_id": self.pose.origin_id,
                "is_accurate": self.pose.is_accurate,
            },
            "pose_pitch": self.pose_pitch,
            "lift_height_mm": self.lift_height_mm,
            "head_angle_deg": self.head_angle_deg,
            "cliff_detected": self.cliff_detected,
            "picked_up": self.picked_up,
            "falling": self.falling,
            "accelerometer": {
                "x": self.accelerometer.x,
                "y": self.accelerometer.y,
                "z": self.accelerometer.z,
            },
            "gyroscope": {
                "x": self.gyroscope.x,
                "y": self.gyroscope.y,
                "z": self.gyroscope.z,
            },
            "right_wheel_speed": self.right_wheel_speed,
            "left_wheel_speed": self.left_wheel_speed,
            "orientation": self.orientation.name if self.orientation else None,
        }


# Global state holder — updated by sensor event handlers
_state = RobotState()

def get_state() -> RobotState:
    """Return a snapshot of the current robot state."""
    return _state

def update_state_from_cli(cli : PyCozmoClient) -> None:
    """Update the global robot state with new information."""
    global _state
    _state = RobotState(
        battery=BatteryState(
            voltage=cli.battery_voltage,
            level=round(max(0.0, min(1.0, (cli.battery_voltage - 3.5) / 0.7)), 2),
        ),
        pose=cli.pose,
        pose_pitch=cli.pose_pitch.degrees,
        lift_height_mm=cli.lift_position.height.mm,
        head_angle_deg=cli.head_angle.degrees,
        cliff_detected=_state.cliff_detected,  # updated by cliff event handlers
        picked_up=cli.robot_picked_up,
        falling=_state.falling,  # updated by falling event handlers
        accelerometer=cli.accel,
        gyroscope=cli.gyro,
        right_wheel_speed=cli.right_wheel_speed.mmps,
        left_wheel_speed=cli.left_wheel_speed.mmps,
        orientation=cli.robot_orientation,
    )

def update_cliff_state(cliff_detected: bool) -> None:
    """Update the cliff detection state."""
    global _state
    _state.cliff_detected = cliff_detected

def update_falling_state(falling: bool) -> None:
    """Update the falling state."""
    global _state
    _state.falling = falling

def update_picked_up_state(picked_up: bool) -> None:
    """Update the picked up state."""
    global _state
    _state.picked_up = picked_up