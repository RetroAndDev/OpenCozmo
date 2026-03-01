"""
robot/cubes.py — Cozmo cube event subscriptions.

Cozmo ships with up to 3 light-up cubes (officially called "Interactive Cubes").
PyCozmo exposes cube events and allows setting their LEDs.

Hardware facts:
    - Each cube has an accelerometer (detects taps and movement)
    - Each cube has 4 RGB LEDs (corners)
    - Communication: robot ↔ cube via 2.4 GHz radio (handled by PyCozmo)
    - Cube IDs: 1, 2, 3 (PyCozmo assigns them as they connect)

PyCozmo events used:
    EvtObjectTapped     — cube was tapped
    EvtObjectMovingChange — cube picked up or set down
    EvtObjectConnectChanged — cube connected or disconnected from the robot
"""

import logging
import time

import pycozmo
import pycozmo.event

from .controller import get_client
from .sensors import _emit  # reuse the same queue and emit helper

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PyCozmo event handlers
# ---------------------------------------------------------------------------

def _on_cube_tapped(cli, evt: pycozmo.event.EvtObjectTapped) -> None:
    """
    Fired when the robot detects a tap on one of its cubes.

    evt attributes:
        obj       : pycozmo LightCube object
        intensity : float  — tap intensity (rough, firmware-defined)
        count     : int    — number of taps in the burst
    """
    cube_id = getattr(evt.obj, "object_id", None)

    _emit({
        "type":      "event.cube.tap",
        "timestamp": time.time(),
        "cube_id":   cube_id,
        "intensity": round(float(getattr(evt, "intensity", 0.0)), 3),
        "count":     int(getattr(evt, "count", 1)),
    })


def _on_cube_moving(cli, evt: pycozmo.event.EvtObjectMovingChange) -> None:
    """
    Fired when a cube starts or stops moving (picked up, placed, nudged).

    evt attributes:
        obj     : pycozmo LightCube object
        moving  : bool
    """
    cube_id = getattr(evt.obj, "object_id", None)

    _emit({
        "type":      "event.cube.moving",
        "timestamp": time.time(),
        "cube_id":   cube_id,
        "moving":    bool(evt.moving),
    })


def _on_cube_connect(cli, evt: pycozmo.event.EvtObjectConnectChanged) -> None:
    """
    Fired when a cube connects or disconnects from the robot's radio.

    evt attributes:
        obj       : pycozmo LightCube object
        connected : bool
    """
    cube_id = getattr(evt.obj, "object_id", None)

    _emit({
        "type":      "event.cube.connect",
        "timestamp": time.time(),
        "cube_id":   cube_id,
        "connected": bool(evt.connected),
    })

    logger.info(
        "Cube %s %s.",
        cube_id,
        "connected" if evt.connected else "disconnected",
    )


# ---------------------------------------------------------------------------
# Startup / teardown
# ---------------------------------------------------------------------------

def start() -> None:
    """
    Register cube event handlers.
    Must be called after controller.connect().
    """
    client = get_client()

    client.add_handler(pycozmo.event.EvtObjectTapped,         _on_cube_tapped)
    client.add_handler(pycozmo.event.EvtObjectMovingChange,   _on_cube_moving)
    client.add_handler(pycozmo.event.EvtObjectConnectChanged, _on_cube_connect)

    logger.info("Cube event handlers registered.")


def stop() -> None:
    """Unregister cube event handlers on shutdown."""
    try:
        client = get_client()
        client.remove_handler(pycozmo.event.EvtObjectTapped,         _on_cube_tapped)
        client.remove_handler(pycozmo.event.EvtObjectMovingChange,   _on_cube_moving)
        client.remove_handler(pycozmo.event.EvtObjectConnectChanged, _on_cube_connect)
        logger.info("Cube event handlers removed.")
    except Exception:
        pass  # Already disconnected or client unavailable


# ---------------------------------------------------------------------------
# Cube light control (called via handlers/cubes.py when implemented)
# ---------------------------------------------------------------------------

async def set_cube_lights(cube_id: int, r: float, g: float, b: float) -> None:
    """
    Set all four LEDs of a cube to a solid color.

    Args:
        cube_id : 1, 2, or 3.
        r, g, b : Normalized color channels [0.0 .. 1.0].

    Raises:
        ValueError: If the cube ID is not known or the cube is not connected.
    """
    import asyncio
    import pycozmo.lights

    client = get_client()

    # PyCozmo exposes connected cubes via client.world.connected_light_cubes
    cube = client.world.connected_light_cubes.get(cube_id)
    if cube is None:
        raise ValueError(
            f"Cube {cube_id} is not connected. "
            f"Connected cubes: {list(client.world.connected_light_cubes.keys())}"
        )

    def _to_byte(v: float) -> int:
        return max(0, min(255, int(v * 255)))

    light = pycozmo.lights.Light(
        on_color=pycozmo.util.Color(
            red=_to_byte(r),
            green=_to_byte(g),
            blue=_to_byte(b),
        )
    )

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, cube.set_lights, light)

    logger.debug("set_cube_lights(cube_id=%d, r=%.2f, g=%.2f, b=%.2f)", cube_id, r, g, b)


async def set_cube_lights_off(cube_id: int) -> None:
    """Turn off all LEDs on a specific cube."""
    import asyncio

    client = get_client()
    cube = client.world.connected_light_cubes.get(cube_id)
    if cube is None:
        raise ValueError(f"Cube {cube_id} is not connected.")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, cube.set_lights_off)

    logger.debug("set_cube_lights_off(cube_id=%d)", cube_id)
