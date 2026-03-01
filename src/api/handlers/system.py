"""
handlers/system.py — System command handler

Supported message types:
    system.ping       Connectivity check.
    system.status     Return current API/robot status snapshot.
    system.disconnect Disconnect robot session gracefully.
"""

import json
import logging
from typing import Any

import websockets

from robot import controller, state as robot_state

logger = logging.getLogger(__name__)


async def handle(data: dict[str, Any], ws: websockets.ServerConnection) -> None:
    action = data.get("type", "")
    request_id = data.get("request_id")

    try:
        match action:
            case "system.ping":
                await _pong(ws, request_id)
            case "system.status":
                await _status(ws, request_id)
            case "system.disconnect":
                await controller.disconnect()
                await _send_ack(ws, action, request_id)
            case _:
                await _send_error(ws, request_id, "UNKNOWN_ACTION", f"Unknown system action: {action}")

    except RuntimeError as exc:
        logger.warning("Robot unavailable for '%s': %s", action, exc)
        await _send_error(ws, request_id, "ROBOT_UNAVAILABLE", str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error handling '%s'", action)
        await _send_error(ws, request_id, "INTERNAL_ERROR", str(exc))


async def _pong(ws: websockets.ServerConnection, request_id: str | None) -> None:
    response: dict[str, Any] = {"type": "system.pong"}
    if request_id:
        response["request_id"] = request_id
    await ws.send(json.dumps(response))


async def _status(ws: websockets.ServerConnection, request_id: str | None) -> None:
    connected = controller.is_connected()
    state = robot_state.get_state()

    status_payload: dict[str, Any] = {
        "type": "system.status.ack",
        "success": True,
        "connected": connected,
        "battery": {
            "voltage": state.battery.voltage,
            "level": state.battery.level,
            "charging": state.battery.charging,
        },
        "lift_height_mm": state.lift_height_mm,
        "head_angle_deg": state.head_angle_deg,
        "cliff_detected": state.cliff_detected,
        "picked_up": state.picked_up,
        "falling": state.falling,
        "pose": {
            "x": state.pose.x,
            "y": state.pose.y,
            "z": state.pose.z,
        },
    }

    if request_id:
        status_payload["request_id"] = request_id

    await ws.send(json.dumps(status_payload))


async def _send_ack(
    ws: websockets.ServerConnection,
    action: str,
    request_id: str | None,
) -> None:
    response: dict[str, Any] = {"type": f"{action}.ack", "success": True}
    if request_id:
        response["request_id"] = request_id
    await ws.send(json.dumps(response))


async def _send_error(
    ws: websockets.ServerConnection,
    request_id: str | None,
    code: str,
    message: str,
) -> None:
    response: dict[str, Any] = {
        "type": "system.error",
        "code": code,
        "message": message,
    }
    if request_id:
        response["request_id"] = request_id
    await ws.send(json.dumps(response))
