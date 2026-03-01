"""
handlers/motion.py — Motion command handler

Supported message types:
    motion.drive    Drive straight at a given speed for a duration.
    motion.turn     Turn in place by a given angle.
    motion.stop     Immediate full stop.
    motion.set_lift Set lift height (normalized 0.0–1.0).
    motion.set_head Set head angle in degrees.
"""

import logging
from typing import Any

import websockets

from robot import controller

logger = logging.getLogger(__name__)


async def handle(data: dict[str, Any], ws: websockets.ServerConnection) -> None:
    """
    Entry point called by the router for any message whose type starts with 'motion.'.
    Dispatches to the appropriate sub-handler and sends back an ack.
    """
    action = data.get("type", "")
    request_id = data.get("request_id")
    payload = data.get("payload", {})

    try:
        match action:
            case "motion.drive":
                await _drive(payload)
            case "motion.turn":
                await _turn(payload)
            case "motion.stop":
                await _stop()
            case "motion.set_lift":
                await _set_lift(payload)
            case "motion.set_head":
                await _set_head(payload)
            case _:
                await _send_error(ws, request_id, "UNKNOWN_ACTION", f"Unknown motion action: {action}")
                return

        await _send_ack(ws, action, request_id)

    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Bad payload for '%s': %s", action, exc)
        await _send_error(ws, request_id, "BAD_PAYLOAD", str(exc))
    except RuntimeError as exc:
        logger.warning("Robot unavailable for '%s': %s", action, exc)
        await _send_error(ws, request_id, "ROBOT_UNAVAILABLE", str(exc))
    except Exception as exc:
        logger.exception("Unexpected error handling '%s'", action)
        await _send_error(ws, request_id, "INTERNAL_ERROR", str(exc))


# ── Sub-handlers ──────────────────────────────────────────────────────────────

async def _drive(data: dict[str, Any]) -> None:
    speed: int = int(data["speed"])
    duration_ms: int = int(data["duration_ms"])

    if not -500 <= speed <= 500:
        raise ValueError(f"speed must be in [-500, 500], got {speed}")
    if duration_ms < 0:
        raise ValueError(f"duration_ms must be positive, got {duration_ms}")

    logger.debug("drive: speed=%d, duration_ms=%d", speed, duration_ms)
    await controller.drive(speed, duration_ms)


async def _turn(data: dict[str, Any]) -> None:
    angle_deg: float = float(data["angle_deg"])
    speed: int = int(data.get("speed", 100))

    logger.debug("turn: angle=%.1f°, speed=%d", angle_deg, speed)
    await controller.turn(angle_deg, speed)


async def _stop() -> None:
    logger.debug("stop")
    await controller.stop()


async def _set_lift(data: dict[str, Any]) -> None:
    height: float = float(data["height"])

    if not 0.0 <= height <= 1.0:
        raise ValueError(f"height must be in [0.0, 1.0], got {height}")

    logger.debug("set_lift: height=%.2f", height)
    await controller.set_lift(height)


async def _set_head(data: dict[str, Any]) -> None:
    angle_deg: float = float(data["angle_deg"])

    if not -25.0 <= angle_deg <= 44.5:
        raise ValueError(f"angle_deg must be in [-25, 44.5], got {angle_deg}")

    logger.debug("set_head: angle=%.1f°", angle_deg)
    await controller.set_head(angle_deg)


# ── Response helpers ───────────────────────────────────────────────────────────

import json  # noqa: E402 — kept here to not pollute the top-level imports


async def _send_ack(
    ws: websockets.ServerConnection,
    action: str,
    request_id: str | None,
) -> None:
    payload: dict[str, Any] = {"type": f"{action}.ack", "success": True}
    if request_id:
        payload["request_id"] = request_id
    await ws.send(json.dumps(payload))


async def _send_error(
    ws: websockets.ServerConnection,
    request_id: str | None,
    code: str,
    message: str,
) -> None:
    payload: dict[str, Any] = {
        "type": "system.error",
        "code": code,
        "message": message,
    }
    if request_id:
        payload["request_id"] = request_id
    await ws.send(json.dumps(payload))
