"""
server.py — OpenCozmo WebSocket API entry point.

Startup sequence:
    1. Bootstrap logging (early, so everything below is captured)
    2. Load config (creates config.yaml with defaults if missing)
    3. Connect to Cozmo via PyCozmo             ← TODO
    4. Start sensor polling loop                ← TODO
    5. Start camera capture loop                ← TODO
    6. Advertise service via mDNS               ← TODO
    7. Start WebSocket server → accept clients
"""

import asyncio
import json
import logging

import websockets
import websockets.exceptions

import logger as log_setup
import config as cfg
from handlers import motion, animation, audio, camera as camera_handler, system
from robot import controller, sensors, camera as robot_camera

# ── Bootstrap ─────────────────────────────────────────────────────────────────

# Step 1 — Early logging with a temporary level; will be reconfigured after
# config is loaded (in case the config file sets a different level).
log_setup.setup(level="DEBUG")
_log = logging.getLogger(__name__)

# Step 2 — Load config (creates the file if absent)
config = cfg.load()

# Reconfigure logging with the level from config
log_setup.setup(
    level=config["logging"]["level"],
    output_dir=config["logging"].get("output_dir"),
)
_log.info("OpenCozmo API starting up.")


# ── Router ────────────────────────────────────────────────────────────────────

# Maps a message type prefix to its handler module.
# The router strips the prefix and passes the full message to handler.handle().
#
# Convention: "domain.action" → the domain is the prefix before the first dot.
_HANDLERS = {
    "motion":    motion,
    "animation": animation,
    "audio":     audio,
    "camera":    camera_handler,
    "system":    system,
}

_connected_clients: set[websockets.ServerConnection] = set()


def _resolve_handler(message_type: str):
    """
    Return the handler module for a given message type, or None if unknown.

    Examples:
        "motion.drive"      → handlers.motion
        "audio.say"         → handlers.audio
        "unknown.whatever"  → None
    """
    domain = message_type.split(".")[0]
    return _HANDLERS.get(domain)


# ── Connection handler ─────────────────────────────────────────────────────────

async def _on_connect(websocket: websockets.ServerConnection) -> None:
    """Called once per client connection. Runs until the client disconnects."""
    client = websocket.remote_address
    _connected_clients.add(websocket)
    _log.info("Client connected: %s", client)

    try:
        async for raw in websocket:
            await _on_message(raw, websocket)
    except websockets.exceptions.ConnectionClosedOK:
        _log.info("Client disconnected cleanly: %s", client)
    except websockets.exceptions.ConnectionClosedError as exc:
        _log.warning("Client connection lost: %s — %s", client, exc)
    except Exception:
        _log.exception("Unexpected error in connection handler for %s", client)
    finally:
        _connected_clients.discard(websocket)
        _log.info("Connection closed: %s", client)


async def _on_message(raw: str | bytes, websocket: websockets.ServerConnection) -> None:
    """Parse a raw incoming message and dispatch it to the right handler."""

    # 1 — Parse JSON
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log.warning("Received invalid JSON: %s", exc)
        await _send_error(websocket, None, "INVALID_JSON", "Message is not valid JSON.")
        return

    if not isinstance(data, dict):
        await _send_error(websocket, None, "INVALID_FORMAT", "Message must be a JSON object.")
        return

    # 2 — Extract type
    message_type: str = data.get("type", "")
    if not message_type:
        await _send_error(websocket, data.get("request_id"), "MISSING_TYPE", "Message must have a 'type' field.")
        return

    _log.debug("→ %s (request_id=%s)", message_type, data.get("request_id"))

    # 3 — Resolve handler
    handler = _resolve_handler(message_type)
    if handler is None:
        _log.warning("No handler for message type: '%s'", message_type)
        await _send_error(
            websocket,
            data.get("request_id"),
            "UNKNOWN_TYPE",
            f"No handler registered for message type '{message_type}'.",
        )
        return

    # 4 — Dispatch
    await handler.handle(data, websocket)


async def _send_error(
    websocket: websockets.ServerConnection,
    request_id: str | None,
    code: str,
    message: str,
) -> None:
    payload: dict = {"type": "system.error", "code": code, "message": message}
    if request_id:
        payload["request_id"] = request_id
    try:
        await websocket.send(json.dumps(payload))
    except websockets.exceptions.ConnectionClosed:
        pass  # Client already gone, nothing to do


# ── Entry point ────────────────────────────────────────────────────────────────

async def main() -> None:
    host: str = config["server"]["host"]
    port: int = int(config["server"]["port"])

    background_tasks: list[asyncio.Task] = []

    await controller.connect(config.get("robot", {}))

    try:
        sensors.start()
        #cubes.start()

        background_tasks.append(asyncio.create_task(sensors.broadcast_loop(_connected_clients)))

        robot_camera.start(config.get("camera", {}))
        if config.get("camera", {}).get("enabled", True):
            background_tasks.append(asyncio.create_task(robot_camera.stream_loop(_connected_clients)))

        _log.info("WebSocket server listening on ws://%s:%d", host, port)

        async with websockets.serve(_on_connect, host, port):
            await asyncio.Future()  # Run forever
    finally:
        for task in background_tasks:
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)

        robot_camera.stop()
        #cubes.stop()
        sensors.stop()
        await controller.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _log.info("Shutdown requested — bye.")
