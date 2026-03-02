"""
robot/controller.py — High-level PyCozmo wrapper.

Manages the robot connection lifecycle and exposes every robot command as a
clean async function. All unit conversions (degrees ↔ radians, normalized
heights, etc.) happen here so the rest of the codebase never has to think
about PyCozmo internals.

PyCozmo quick reference (units used by the library itself):
  - Wheel speeds      : mm/s  (positive = forward)
  - Turn angle        : radians
  - Turn speed        : rad/s
  - Head angle        : radians  [-0.44 .. 0.78]  ≈ [-25° .. 44.5°]
  - Lift height       : normalized float [0.0 .. 1.0]
  - Battery voltage   : volts  (fully charged ≈ 4.2 V, low ≈ 3.5 V)
"""

import asyncio
import logging
import math
import platform
import subprocess
from typing import Optional

import pycozmo
import pycozmo.lights
import pycozmo.robot
import pycozmo.util

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal state — one client for the lifetime of the process
# ---------------------------------------------------------------------------

_client: Optional[pycozmo.Client] = None
_turn_calibration_factor: float = 2.11  # Set during connect()


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------

async def connect(config: dict) -> None:
    """
    Connect to the Cozmo robot via PyCozmo.

    Must be called once at server startup before any command is issued.
    Blocks until the connection is established or raises on timeout.

    Args:
        config: The robot section of the global config dict.
                Uses: config["connect_timeout_s"]
                      config["turn_calibration_factor"]

    Raises:
        RuntimeError: If the robot can not be reached within the timeout.
    """
    global _client, _turn_calibration_factor

    timeout = int(config.get("connect_timeout_s", 10))
    _turn_calibration_factor = float(config.get("turn_calibration_factor", 2.11))

    logger.info("Connecting to Cozmo (timeout=%ds)…", timeout)

    # PyCozmo's Client is synchronous internally; we run it in a thread so we
    # don't block the asyncio event loop.
    loop = asyncio.get_event_loop()

    # Setup internal PyCozmo loging to INFO
    pycozmo.run.setup_basic_logging(log_level="NOTSET")

    def _do_connect() -> pycozmo.Client:
        client = pycozmo.Client(
            enable_animations=True,
            enable_procedural_face=False
        )
        client.start()
        client.connect()
        client.wait_for_robot()  # blocks until the robot handshake is complete
        client.load_anims() # Preload animations to avoid delays on first play
        return client

    try:
        _client = await asyncio.wait_for(
            loop.run_in_executor(None, _do_connect),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise RuntimeError(
            f"Could not connect to Cozmo within {timeout}s. "
            "Make sure the device is connected to the Cozmo WiFi network."
        )

    logger.info(
        "Robot connected. Battery: %.2f V | Firmware: %s",
        _client.battery_voltage,
        getattr(_client, "firmware_version", "unknown"),
    )


async def disconnect() -> None:
    """
    Gracefully disconnect from the robot.
    Safe to call even if never connected.
    """
    global _client
    if _client is None:
        return

    logger.info("Disconnecting from robot…")
    loop = asyncio.get_event_loop()

    def _do_disconnect() -> None:
        _client.disconnect()
        _client.stop()

    await loop.run_in_executor(None, _do_disconnect)
    _client = None
    logger.info("Robot disconnected.")


def get_client() -> pycozmo.Client:
    """
    Return the active PyCozmo client.
    Raises RuntimeError if called before connect().
    Used internally by sensors.py, camera.py, cubes.py.
    """
    if _client is None:
        raise RuntimeError(
            "Robot is not connected. Call controller.connect() first."
        )
    return _client


def _require_client() -> pycozmo.Client:
    """Shorthand used inside this module."""
    return get_client()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deg_to_rad(degrees: float) -> float:
    return degrees * math.pi / 180.0


def _run_sync(fn, *args, **kwargs):
    """
    Run a synchronous PyCozmo call in the thread pool so it doesn't block the
    asyncio event loop. Returns a coroutine.
    """
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, lambda: fn(*args, **kwargs))


# ---------------------------------------------------------------------------
# Motion commands
# ---------------------------------------------------------------------------

async def drive(speed: int, duration_ms: int) -> None:
    """
    Drive both wheels at the same speed for a fixed duration.

    Args:
        speed       : Wheel speed in mm/s. Positive = forward, negative = back.
                      PyCozmo range: roughly -500 to 500 mm/s.
        duration_ms : Duration in milliseconds. The call returns immediately —
                      the robot stops on its own after the duration.
    """
    client = _require_client()
    duration_s = duration_ms / 1000.0

    logger.debug("drive(speed=%d mm/s, duration=%.3fs)", speed, duration_s)

    # PyCozmo drive_wheels(lwheel_speed, rwheel_speed, duration)
    # duration=0 means "keep going" — we always pass an explicit duration here.
    await _run_sync(
        client.drive_wheels,
        speed,      # left wheel
        speed,      # right wheel
        duration=duration_s,
    )

async def turn(direction: int, speed: int = 100) -> None:
    """
    Turn the robot in place.

    Args:
        direction : Positive = turn left, negative = turn right.
                    The actual angle turned depends on the duration and speed.
        speed     : Turning speed in deg/s (we convert to rad/s).
                    Default: 100 deg/s.
    """
    client = _require_client()
    speed_rad = _deg_to_rad(speed)

    logger.debug("turn(direction=%d, speed=%d°/s)", direction, speed)

    # PyCozmo: drive_wheels with opposite speeds turns in place
    await _run_sync(client.turn_in_place_at_speed, direction, speed_rad)

async def turn_to(angle_deg: float, speed: int = 100) -> None:
    """
    Turn the robot in place.

    Args:
        angle_deg : Degrees to turn. Positive = counter-clockwise (left),
                    negative = clockwise (right).
                    PyCozmo expects radians internally — we convert here.
        speed     : Turning speed in deg/s (we convert to rad/s).
                    Default: 100 deg/s.
    """
    client = _require_client()
    angle_rad = _deg_to_rad(angle_deg)
    speed_rad = _deg_to_rad(speed)

    logger.debug("turn_to(angle=%.1f°, speed=%d°/s)", angle_deg, speed)

    # PyCozmo: turn_in_place(angle_rad, speed_rad)
    await _run_sync(client.turn_in_place, angle_rad, speed_rad, is_absolute=True)

async def stop() -> None:
    """
    Immediately stop all wheel movement.
    Does not affect the lift or head.
    """
    client = _require_client()
    logger.debug("stop()")

    # drive_wheels with speed=0 and no duration = immediate stop
    await _run_sync(client.stop_all_motors)


async def set_lift(height: float) -> None:
    """
    Move the lift arm to a target position.

    Args:
        height : Normalized position. 0.0 = fully lowered, 1.0 = fully raised.
                 PyCozmo accepts this directly as a normalized float.
    """
    client = _require_client()
    logger.debug("set_lift(height=%.2f)", height)

    # PyCozmo: set_lift_height(height, accel=None, max_speed=None, duration=None)
    # height is a normalized float [0.0 .. 1.0]
    await _run_sync(client.set_lift_height, height)


async def set_head(angle_deg: float) -> None:
    """
    Move Cozmo's head to a target angle.

    Args:
        angle_deg : Angle in degrees.
                    Physical range: -25° (looking down) to +44.5° (looking up).
                    PyCozmo expects radians — we convert here.
    """
    client = _require_client()
    angle_rad = _deg_to_rad(angle_deg)

    logger.debug("set_head(angle=%.1f° → %.4f rad)", angle_deg, angle_rad)

    # PyCozmo: set_head_angle(angle_rad, accel=None, max_speed=None, duration=None)
    await _run_sync(client.set_head_angle, angle_rad)


# ---------------------------------------------------------------------------
# Animation & face
# ---------------------------------------------------------------------------

async def play_animation(name: str) -> None:
    """
    Play a named animation clip.

    Built-in animation names are defined by PyCozmo (same set as the
    original Anki firmware). Examples:
        "anim_bored_01"
        "anim_happy_01"
        "anim_reacttocliff_turtlerolloff_01"

    See pycozmo.anim for the full list:
        python -c "import pycozmo; print(list(pycozmo.anim.ANIMATIONS.keys()))"

    Args:
        name : Animation clip name.

    Raises:
        ValueError: If the animation name is not known to PyCozmo.
    """
    client = _require_client()
    logger.debug("play_animation(%s)", name)

    # PyCozmo raises pycozmo.exception.PyCozmoException for unknown names
    await _run_sync(client.play_anim, name)


async def stop_animation() -> None:
    """
    Stop the current animation/action queue if supported by the backend.

    Raises:
        NotImplementedError: If the active backend does not expose a stop API.
    """
    client = _require_client()
    logger.debug("stop_animation()")

    stop_fn = getattr(client, "abort_all_actions", None)
    if callable(stop_fn):
        await _run_sync(stop_fn)
        return

    raise NotImplementedError("Stopping animations is not supported by this PyCozmo version")

def get_animation_names() -> list[str]:
    """
    Return a list of available animation names.

    This can be used to validate animation names before trying to play them.
    """
    return _require_client().get_anim_names()

async def set_face_image(png_bytes: bytes) -> None:
    """
    Display a custom image on Cozmo's face screen (128 × 64 pixels, 1-bit).

    Args:
        png_bytes : Raw PNG image bytes. Must be exactly 128×64 px.
                    Will be converted to the 1-bit format PyCozmo expects.

    Raises:
        ValueError: If the image dimensions are wrong.
    """
    from PIL import Image
    import io

    client = _require_client()

    img = Image.open(io.BytesIO(png_bytes)).convert("1")  # 1-bit grayscale

    if img.size != (128, 64):
        raise ValueError(
            f"Face image must be 128×64 px, got {img.size[0]}×{img.size[1]}"
        )

    logger.debug("set_face_image(128×64 px)")

    # PyCozmo: set_face_image(pil_image)
    await _run_sync(client.set_face_image, img)


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

async def say(text: str) -> None:
    """
    Speak text through Cozmo's speaker using the on-device TTS engine.

    Args:
        text : Text to speak. Keep it short — long strings may be truncated
               by the firmware.
    """
    client = _require_client()
    logger.debug("say(%r)", text)

    # PyCozmo: say_text(text, play_excited_animation=False, use_vectorizer=False)
    await _run_sync(client.say_text, text)


async def play_audio(name: str) -> None:
    """
    Play one of Cozmo's built-in audio clips.

    Args:
        name : Audio clip name. See pycozmo.audio for available clips.
               Example: "anim_bored_01" or use pycozmo.audio.AudioEvent members.
    """
    client = _require_client()
    logger.debug("play_audio(%s)", name)

    # PyCozmo: play_audio(audio_event) where audio_event is an AudioEvent enum
    # We accept a string and resolve it here.
    try:
        audio_event = pycozmo.audio.AudioEvent[name]
    except KeyError:
        raise ValueError(
            f"Unknown audio clip: '{name}'. "
            "See pycozmo.audio.AudioEvent for valid names."
        )

    await _run_sync(client.play_audio, audio_event)


# ---------------------------------------------------------------------------
# Lights
# ---------------------------------------------------------------------------

async def set_backpack_lights(r: float, g: float, b: float) -> None:
    """
    Set Cozmo's backpack LEDs to a solid color.

    Args:
        r, g, b : Color channels, normalized 0.0–1.0.
    """
    client = _require_client()

    # PyCozmo lights: pycozmo.lights.Light takes int values 0-255 per channel
    def _to_byte(v: float) -> int:
        return max(0, min(255, int(v * 255)))

    light = pycozmo.lights.Light(
        on_color=pycozmo.util.Color(
            red=_to_byte(r),
            green=_to_byte(g),
            blue=_to_byte(b),
        )
    )

    logger.debug("set_backpack_lights(r=%.2f, g=%.2f, b=%.2f)", r, g, b)

    # Apply to all backpack LEDs
    await _run_sync(client.set_all_backpack_lights, light)


async def set_backpack_lights_off() -> None:
    """Turn off all backpack LEDs."""
    client = _require_client()
    logger.debug("set_backpack_lights_off()")
    await _run_sync(client.set_backpack_lights_off)


# ---------------------------------------------------------------------------
# Status / telemetry (synchronous reads — safe to call from async context)
# ---------------------------------------------------------------------------

def get_battery_voltage() -> float:
    """
    Return the current battery voltage in volts.
    Fully charged ≈ 4.2 V. Low battery warning below ≈ 3.5 V.
    """
    return _require_client().battery_voltage


def get_lift_height() -> float:
    """Return current lift height as a normalized float [0.0 .. 1.0]."""
    # PyCozmo exposes lift_height_mm; convert to normalized value.
    # Physical range: 32 mm (down) to 92 mm (up) — 60 mm total travel.
    mm = _require_client().lift_height_mm
    return max(0.0, min(1.0, (mm - 32.0) / 60.0))


def get_head_angle_deg() -> float:
    """Return current head angle in degrees."""
    rad = _require_client().head_angle_rad
    return math.degrees(rad)


def is_connected() -> bool:
    """Return True if a robot connection is currently active."""
    return _client is not None
