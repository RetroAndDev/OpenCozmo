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
_loop: asyncio.AbstractEventLoop | None = None
_seen_first_state_event = False
_state_event_log_interval_s: float = 1.0
_state_log_last_ts: float | None = None
_state_events_since_log: int = 0
_state_changed_since_log: int = 0
_auto_broadcast_state: bool = False  # If False, don't emit robotstate events automatically


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _emit(event_dict: dict[str, Any]) -> None:
    """
    Put a sensor event on the broadcast queue.
    Thread-safe: PyCozmo callbacks run in a separate thread.
    """
    try:
        if _loop is not None:
            _loop.call_soon_threadsafe(event_queue.put_nowait, event_dict)
        else:
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

def _on_state_updated(cli : pycozmo.client.Client, *_) -> None:
    """
    Fires frequently (several times per second) with the full robot state.
    We emit battery and pose updates from here.
    """
    global _seen_first_state_event
    global _state_log_last_ts, _state_events_since_log, _state_changed_since_log

    if not _seen_first_state_event:
        _seen_first_state_event = True
        logger.info("EvtRobotStateUpdated reçu (premier paquet).")

    # Snapshot before update to detect whether global state changed
    before = robot_state.get_state().get_json()

    # Update internal robot state tracker
    robot_state.update_state_from_cli(cli)

    # Emit to connected clients
    state = robot_state.get_state()
    changed = before != state.get_json()

    _state_events_since_log += 1
    if changed:
        _state_changed_since_log += 1

    if _state_event_log_interval_s > 0:
        now = time.monotonic()
        if _state_log_last_ts is None:
            _state_log_last_ts = now
        elapsed = now - _state_log_last_ts
        if elapsed >= _state_event_log_interval_s:
            logger.info(
                "EvtRobotStateUpdated: %d reçus, %d changements sur %.2fs (~%.1f evt/s)",
                _state_events_since_log,
                _state_changed_since_log,
                elapsed,
                (_state_events_since_log / elapsed) if elapsed > 0 else 0.0,
            )
            _state_events_since_log = 0
            _state_changed_since_log = 0
            _state_log_last_ts = now

    if changed:
        logger.debug(
            "RobotState global changé: %s",
            state.get_json()
        )
    logger.debug(
        "EvtRobotStateUpdated reçu: changed=%s state: %s",
        changed,
        state.get_json()
    )

    # Only emit robotstate event if auto-broadcast is enabled
    if _auto_broadcast_state:
        payload = { "type":      "event.robotstate" }
        for key, value in state.get_json().items():
            payload[key] = value
        _emit(payload)


def _on_cliff_detected(cli, state) -> None:
    """
    Fires when a cliff sensor state changes (detected or cleared).
    PyCozmo exposes four cliff sensors: front-left, front-right, back-left, back-right.
    """
    del cli
    detected = bool(state)
    robot_state.update_cliff_state(detected)

    _emit({
        "type":      "event.sensor.cliff",
        "timestamp": _ts(),
        # evt.detected is True when at least one sensor sees a cliff
        "detected":  detected,
        # Individual sensor states (bool) — attribute names from PyCozmo source
        "sensors": {
            "front_left":  None,
            "front_right": None,
            "back_left":   None,
            "back_right":  None,
        },
    })


def _on_picked_up(cli, state) -> None:
    """
    Fires when the robot is picked up or set back down.
    """
    del cli
    picked_up = bool(state)
    robot_state.update_picked_up_state(picked_up)

    _emit({
        "type":      "event.robot.picked_up",
        "timestamp": _ts(),
        "picked_up": picked_up,
    })


def _on_falling(cli, state) -> None:
    """
    Fires when the robot starts or stops falling.
    """
    del cli
    falling = bool(state)
    robot_state.update_falling_state(falling)

    _emit({
        "type":      "event.robot.falling",
        "timestamp": _ts(),
        "falling":   falling,
    })


# ---------------------------------------------------------------------------
# Startup / teardown
# ---------------------------------------------------------------------------

def start(config: dict | None = None) -> None:
    """
    Register all PyCozmo event handlers.
    Must be called after controller.connect() succeeds.
    Safe to call from the async event loop — PyCozmo adds handlers synchronously.

    Args:
        config: Optional "sensors" section from global config.
                Uses: state_event_log_hz (default: 1.0).
                      auto_broadcast_state (default: False).
    """
    global _loop, _state_event_log_interval_s, _state_log_last_ts
    global _state_events_since_log, _state_changed_since_log, _auto_broadcast_state

    _loop = asyncio.get_running_loop()
    cfg = config or {}
    hz = float(cfg.get("state_event_log_hz", 1.0))
    _state_event_log_interval_s = (1.0 / hz) if hz > 0 else 0.0
    _state_log_last_ts = None
    _state_events_since_log = 0
    _state_changed_since_log = 0
    _auto_broadcast_state = bool(cfg.get("auto_broadcast_state", False))

    client = get_client()

    client.add_handler(pycozmo.event.EvtRobotStateUpdated,   _on_state_updated)
    client.add_handler(pycozmo.event.EvtCliffDetectedChange, _on_cliff_detected)
    client.add_handler(pycozmo.event.EvtRobotPickedUpChange, _on_picked_up)
    client.add_handler(pycozmo.event.EvtRobotFallingChange,  _on_falling)

    if hz > 0:
        logger.info("Sensor event handlers registered. State log périodique: %.2f Hz", hz)
    else:
        logger.info("Sensor event handlers registered. State log périodique désactivé (state_event_log_hz<=0).")


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
    except Exception:
        pass  # Already disconnected or client unavailable, nothing to unregister


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
