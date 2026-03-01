"""
handlers/test.py — Tests command handler

Supported message types:
    test.test_lift_cube_muscu   Test lift by lifting a cube repeatedly like a bicep curl.
"""

import asyncio
import json
import logging
import random
from typing import Any

import websockets

from robot import controller, state as robot_state

logger = logging.getLogger(__name__)


async def handle(data: dict[str, Any], ws: websockets.ServerConnection) -> None:
    action = data.get("type", "")
    request_id = data.get("request_id")

    try:
        match action:
            case "test.test_lift_cube_muscu":
                await _test_muscu(ws, request_id)
            case _:
                await _send_error(ws, request_id, "UNKNOWN_ACTION", f"Unknown test action: {action}")
                return

        await _send_ack(ws, action, request_id)

    except RuntimeError as exc:
        logger.warning("Robot unavailable for '%s': %s", action, exc)
        await _send_error(ws, request_id, "ROBOT_UNAVAILABLE", str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error handling '%s'", action)
        await _send_error(ws, request_id, "INTERNAL_ERROR", str(exc))


async def _test_muscu(ws: websockets.ServerConnection, request_id: str | None) -> None:
    response: dict[str, Any] = {"type": "test.test_lift_cube_muscu.response", "success": True}
    if request_id:
        response["request_id"] = request_id
    await ws.send(json.dumps(response))

    # Test lift by lifting a cube repeatedly like a bicep curl.
    lift_max = 90
    for _ in range(5):
        random_factor = random.uniform(0.8, 1.0)  # Add some variability to the lift height
        await controller.set_lift(lift_max * random_factor)  # up
        await asyncio.sleep(1.0)
        await controller.set_lift(44 * random_factor)  # down
        await asyncio.sleep(1.0)

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
        "type": "test.error",
        "code": code,
        "message": message,
    }
    if request_id:
        response["request_id"] = request_id
    await ws.send(json.dumps(response))
