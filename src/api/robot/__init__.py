"""
robot/ — PyCozmo abstraction layer.

This package is the ONLY place in the codebase that imports pycozmo directly.
All other modules (handlers, brain client, etc.) go through controller.py.

Shared state
------------
A single `pycozmo.Client` instance is created by `controller.connect()` at
startup and stored in this module as `_client`. The sub-modules (sensors,
camera, cubes) import it from here so they all share the same connection.

    from . import _client   # inside this package only

Outside this package, nobody touches pycozmo — they call controller.*
"""

from .controller import connect, disconnect, get_client

__all__ = ["connect", "disconnect", "get_client"]
