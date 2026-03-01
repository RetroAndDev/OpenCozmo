"""
handlers/audio.py — Audio command handler

Supported message types:
    audio.say    Speak text.
    audio.play   Play a built-in sound.
    audio.volume Set volume (not yet supported by wrapper).
"""

import json
import logging
from typing import Any

import websockets

from robot import controller

logger = logging.getLogger(__name__)


async def handle(data: dict[str, Any], ws: websockets.ServerConnection) -> None:
    action = data.get("type", "")
    request_id = data.get("request_id")
    payload = data.get("payload", {})

    try:
        match action:
            case "audio.say":
                await _say(payload)
            case "audio.play":
                await _play(payload)
            case "audio.volume":
                await _set_volume(payload)
            case _:
                await _send_error(ws, request_id, "UNKNOWN_ACTION", f"Unknown audio action: {action}")
                return

        await _send_ack(ws, action, request_id)

    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Bad payload for '%s': %s", action, exc)
        await _send_error(ws, request_id, "BAD_PAYLOAD", str(exc))
    except RuntimeError as exc:
        logger.warning("Robot unavailable for '%s': %s", action, exc)
        await _send_error(ws, request_id, "ROBOT_UNAVAILABLE", str(exc))
    except NotImplementedError as exc:
        logger.warning("Unsupported audio action '%s': %s", action, exc)
        await _send_error(ws, request_id, "NOT_SUPPORTED", str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error handling '%s'", action)
        await _send_error(ws, request_id, "INTERNAL_ERROR", str(exc))


async def _say(data: dict[str, Any]) -> None:
    text = str(data["text"]).strip()
    if not text:
        raise ValueError("text must be a non-empty string")

    logger.debug("audio.say: %s", text)
    await controller.say(text)


async def _play(data: dict[str, Any]) -> None:
    name = str(data["name"]).strip()
    if not name:
        raise ValueError("name must be a non-empty string")

    logger.debug("audio.play: %s", name)
    await controller.play_audio(name)


async def _set_volume(data: dict[str, Any]) -> None:
    level = float(data["level"])
    if not 0.0 <= level <= 1.0:
        raise ValueError(f"level must be in [0.0, 1.0], got {level}")

    raise NotImplementedError("audio.volume is not supported yet by robot/controller.py")


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
