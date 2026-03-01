"""
robot/camera.py — Camera frame capture and streaming.

Subscribes to PyCozmo's camera event and encodes each frame as a JPEG,
then pushes it to connected WebSocket clients as a base64-encoded event.

Camera specs (Cozmo hardware):
    Resolution : 320 × 240 px
    Field of view : ~90° horizontal
    Color : greyscale only (the camera is monochrome)
    Max FPS : ~30 fps, but PyCozmo slows this down in practice

The frame rate is throttled to config["camera"]["fps"] to avoid flooding
the WebSocket connection.
"""

import asyncio
import base64
import io
import logging
import time
from typing import Any

import pycozmo
import pycozmo.event
from PIL import Image

from .controller import get_client

logger = logging.getLogger(__name__)

# Latest encoded frame — shared between the PyCozmo callback and the async layer
_latest_frame: dict[str, Any] | None = None
_frame_event = asyncio.Event()   # set each time a new frame is available


# ---------------------------------------------------------------------------
# PyCozmo camera event handler (runs in PyCozmo's thread)
# ---------------------------------------------------------------------------

def _on_camera_image(cli, evt: pycozmo.event.EvtNewRawCameraImage) -> None:
    """
    Called by PyCozmo each time a new frame arrives from the robot.
    Encodes the raw PIL image to JPEG and stores it for the async streamer.

    Note: evt.image is a PIL Image object (greyscale, 320×240).
    """
    global _latest_frame

    try:
        buf = io.BytesIO()
        # Save as JPEG — quality is set at stream start from config
        evt.image.save(buf, format="JPEG", quality=_jpeg_quality)
        frame_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        _latest_frame = {
            "type":      "event.camera.frame",
            "timestamp": time.time(),
            "width":     evt.image.width,
            "height":    evt.image.height,
            "data":      frame_b64,   # JPEG bytes, base64-encoded
        }

        # Signal the async streamer that a new frame is ready.
        # call_soon_threadsafe is required because this runs in a non-async thread.
        try:
            loop = asyncio.get_event_loop()
            loop.call_soon_threadsafe(_frame_event.set)
        except RuntimeError:
            pass  # Event loop not running — server is shutting down

    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to encode camera frame: %s", exc)


# ---------------------------------------------------------------------------
# Config (set at start())
# ---------------------------------------------------------------------------

_jpeg_quality: int = 70
_target_fps:   int = 15


# ---------------------------------------------------------------------------
# Startup / teardown
# ---------------------------------------------------------------------------

def start(config: dict) -> None:
    """
    Enable the robot camera and register the frame event handler.
    Must be called after controller.connect().

    Args:
        config : The "camera" section of the global config dict.
                 Uses: enabled, fps, quality.
    """
    global _jpeg_quality, _target_fps

    if not config.get("enabled", True):
        logger.info("Camera disabled in config, skipping.")
        return

    _jpeg_quality = int(config.get("quality", 70))
    _target_fps   = int(config.get("fps", 15))

    client = get_client()

    # Enable the camera stream on the robot side.
    # color=False because the hardware is monochrome — enabling color just adds
    # a useless conversion step on the firmware side.
    client.enable_camera(enable=True, color=False)
    client.add_handler(pycozmo.event.EvtNewRawCameraImage, _on_camera_image)

    logger.info(
        "Camera enabled. Target: %d fps, JPEG quality: %d",
        _target_fps, _jpeg_quality,
    )


def stop() -> None:
    """Disable the camera and unregister the event handler."""
    try:
        client = get_client()
        client.enable_camera(enable=False)
        client.remove_handler(pycozmo.event.EvtNewRawCameraImage, _on_camera_image)
        logger.info("Camera disabled.")
    except RuntimeError:
        pass  # Already disconnected


# ---------------------------------------------------------------------------
# Async stream loop
# ---------------------------------------------------------------------------

async def stream_loop(connected_clients: set) -> None:
    """
    Wait for new frames from the PyCozmo callback thread and fan them out to
    all connected WebSocket clients, rate-limited to config["camera"]["fps"].

    Args:
        connected_clients : The set of active WebSocket connections (same ref
                            used by sensors.broadcast_loop and server.py).

    Start as a background task in server.py:
        asyncio.create_task(camera.stream_loop(connected_clients))
    """
    import json
    import websockets

    if _target_fps <= 0:
        return

    frame_interval = 1.0 / _target_fps
    last_sent_at   = 0.0

    logger.info("Camera stream loop started (%d fps target).", _target_fps)

    while True:
        try:
            # Wait for a new frame signal (with a timeout so we don't block
            # forever if the camera stops sending — e.g. after disconnect)
            await asyncio.wait_for(_frame_event.wait(), timeout=5.0)
            _frame_event.clear()

            # Rate limiting — skip the frame if we sent one too recently
            now = time.monotonic()
            if now - last_sent_at < frame_interval:
                continue
            last_sent_at = now

            frame = _latest_frame
            if frame is None:
                continue

            payload = json.dumps(frame)
            clients = list(connected_clients)

            if not clients:
                continue

            await asyncio.gather(
                *[_safe_send(ws, payload) for ws in clients],
                return_exceptions=True,
            )

        except asyncio.TimeoutError:
            # No frame in 5s — camera may be off or robot disconnected
            logger.debug("Camera: no frame received for 5s.")

        except asyncio.CancelledError:
            logger.info("Camera stream loop stopped.")
            return

        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error in camera stream loop: %s", exc)


async def _safe_send(ws, payload: str) -> None:
    import websockets
    try:
        await ws.send(payload)
    except websockets.exceptions.ConnectionClosed:
        pass
