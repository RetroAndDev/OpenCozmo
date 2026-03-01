"""
robot/sensors.py — Sensor polling and event broadcasting.

Subscribes to PyCozmo events and forwards them as WebSocket messages to all
connected clients. Runs as a persistent background task started by server.py.

PyCozmo events used:
    EvtRobotStateUpdated    — periodic state packet (battery, motors, pose…)
    EvtCliffDetectedChange  — cliff sensor triggered / cleared
    EvtRobotPickedUpChange  — robot lifted off the ground
    EvtRobotFallingChange   — robot in free fall

Broadcasting
------------
All sensor events are pushed to a shared asyncio.Queue consumed by server.py,
which fans the message out to every connected WebSocket client. This decouples
the PyCozmo callback thread from the async WebSocket layer.
"""

import asyncio
import logging
import time
from typing import Any

import pycozmo
import pycozmo.event

from .controller import get_client
from . import state as robot_state

logger = logging.getLogger(__name__)

# Shared queue: sensors.py puts messages here, server.py fans them out.
# Created once, imported by server.py.
event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _emit(event_dict: dict[str, Any]) -> None:
    """
    Put a sensor event on the broadcast queue.
    Thread-safe: PyCozmo callbacks run in a separate thread.
    """
    try:
        event_queue.put_nowait(event_dict)
    except asyncio.QueueFull:
        logger.warning("Event queue full, dropping sensor event: %s", event_dict.get("type"))


def _ts() -> float:
    """Current Unix timestamp (seconds, float)."""
    return time.time()


# ---------------------------------------------------------------------------
# PyCozmo event handlers
# (called by PyCozmo in its own thread — must be synchronous and fast)
# ---------------------------------------------------------------------------

def _on_state_updated(cli, evt: pycozmo.event.EvtRobotStateUpdated) -> None:
    """
    Fires frequently (several times per second) with the full robot state.
    We emit battery and pose updates from here.
    """
    # Update internal robot state tracker
    robot_state.update_battery(cli.battery_voltage)
    robot_state.update_lift(cli.lift_height_mm)
    robot_state.update_head(cli.head_angle_rad)
    if hasattr(evt, "x") and hasattr(evt, "y") and hasattr(evt, "z"):
        robot_state.update_pose(evt.x, evt.y, evt.z)

    # Emit to connected clients
    state = robot_state.get_state()
    _emit({
        "type":      "event.sensor.state",
        "timestamp": _ts(),
        "battery": {
            "voltage":  state.battery.voltage,
            "level":    state.battery.level,
            "charging": state.battery.charging,
        },
        "pose": {
            "x":   state.pose.x,
            "y":   state.pose.y,
            "z":   state.pose.z,
        },
        "lift_height_mm":  state.lift_height_mm,
        "head_angle_deg":  state.head_angle_deg,
    })


def _on_cliff_detected(cli, evt: pycozmo.event.EvtCliffDetectedChange) -> None:
    """
    Fires when a cliff sensor state changes (detected or cleared).
    PyCozmo exposes four cliff sensors: front-left, front-right, back-left, back-right.
    """
    robot_state.update_cliff_detected(evt.detected)

    _emit({
        "type":      "event.sensor.cliff",
        "timestamp": _ts(),
        # evt.detected is True when at least one sensor sees a cliff
        "detected":  evt.detected,
        # Individual sensor states (bool) — attribute names from PyCozmo source
        "sensors": {
            "front_left":  getattr(evt, "front_left",  None),
            "front_right": getattr(evt, "front_right", None),
            "back_left":   getattr(evt, "back_left",   None),
            "back_right":  getattr(evt, "back_right",  None),
        },
    })


def _on_picked_up(cli, evt: pycozmo.event.EvtRobotPickedUpChange) -> None:
    """
    Fires when the robot is picked up or set back down.
    """
    robot_state.update_picked_up(evt.picked_up)

    _emit({
        "type":      "event.robot.picked_up",
        "timestamp": _ts(),
        "picked_up": evt.picked_up,
    })


def _on_falling(cli, evt: pycozmo.event.EvtRobotFallingChange) -> None:
    """
    Fires when the robot starts or stops falling.
    """
    robot_state.update_falling(evt.falling)

    _emit({
        "type":      "event.robot.falling",
        "timestamp": _ts(),
        "falling":   evt.falling,
    })


# ---------------------------------------------------------------------------
# Startup / teardown
# ---------------------------------------------------------------------------

def start() -> None:
    """
    Register all PyCozmo event handlers.
    Must be called after controller.connect() succeeds.
    Safe to call from the async event loop — PyCozmo adds handlers synchronously.
    """
    client = get_client()

    client.add_handler(pycozmo.event.EvtRobotStateUpdated,   _on_state_updated)
    client.add_handler(pycozmo.event.EvtCliffDetectedChange, _on_cliff_detected)
    client.add_handler(pycozmo.event.EvtRobotPickedUpChange, _on_picked_up)
    client.add_handler(pycozmo.event.EvtRobotFallingChange,  _on_falling)

    logger.info("Sensor event handlers registered.")


def stop() -> None:
    """
    Unregister all PyCozmo event handlers.
    Called during graceful shutdown.
    """
    try:
        client = get_client()
        client.remove_handler(pycozmo.event.EvtRobotStateUpdated,   _on_state_updated)
        client.remove_handler(pycozmo.event.EvtCliffDetectedChange, _on_cliff_detected)
        client.remove_handler(pycozmo.event.EvtRobotPickedUpChange, _on_picked_up)
        client.remove_handler(pycozmo.event.EvtRobotFallingChange,  _on_falling)
        logger.info("Sensor event handlers removed.")
    except RuntimeError:
        pass  # Already disconnected, nothing to unregister


# ---------------------------------------------------------------------------
# Broadcast loop (async — runs in the event loop, started by server.py)
# ---------------------------------------------------------------------------

async def broadcast_loop(connected_clients: set) -> None:
    """
    Drain the event_queue and send each message to all connected WebSocket clients.

    Args:
        connected_clients : The set of active WebSocket connections managed by
                            server.py. Passed by reference — mutations are visible.

    This coroutine runs forever and should be started as an asyncio.Task:
        asyncio.create_task(sensors.broadcast_loop(connected_clients))
    """
    import json

    logger.info("Sensor broadcast loop started.")

    while True:
        try:
            message = await event_queue.get()
            payload = json.dumps(message)

            # Snapshot the set to avoid "changed during iteration" errors
            clients = list(connected_clients)
            if not clients:
                continue

            # Fan out to all clients concurrently
            results = await asyncio.gather(
                *[_safe_send(ws, payload) for ws in clients],
                return_exceptions=True,
            )

            # Log any send failures (the client may have disconnected)
            for ws, result in zip(clients, results):
                if isinstance(result, Exception):
                    logger.debug(
                        "Failed to send sensor event to %s:%s — %s",
                        *ws.remote_address, result
                    )

        except asyncio.CancelledError:
            logger.info("Sensor broadcast loop stopped.")
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error in broadcast loop: %s", exc)


async def _safe_send(ws, payload: str) -> None:
    """Send a payload to a single WebSocket client, ignoring connection errors."""
    import websockets
    try:
        await ws.send(payload)
    except websockets.exceptions.ConnectionClosed:
        pass  # Will be removed from connected_clients by server.py on disconnect
