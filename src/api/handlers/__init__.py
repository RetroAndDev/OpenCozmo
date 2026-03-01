"""
handlers/ — One module per message domain.

Each module must expose:
    async def handle(data: dict, ws: websockets.ServerConnection) -> None

The router in server.py calls the right module based on the 'type' prefix.
"""

from . import motion, animation, audio, system


class _NotImplementedHandler:
    """Temporary stand-in for handlers that haven't been written yet."""

    def __init__(self, name: str):
        self._name = name

    async def handle(self, data: dict, ws) -> None:
        import json
        import logging

        logging.getLogger(__name__).warning(
            "Handler '%s' is not implemented yet (message type: %s)",
            self._name,
            data.get("type"),
        )
        await ws.send(json.dumps({
            "type": "system.error",
            "code": "NOT_IMPLEMENTED",
            "message": f"Handler '{self._name}' is not implemented yet.",
            "request_id": data.get("request_id"),
        }))


camera = _NotImplementedHandler("camera")
