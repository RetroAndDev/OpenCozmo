# OpenCozmo — Technical Architecture & Developer Guide

> This document describes the code organization, architecture decisions, data flows, and development conventions for the OpenCozmo project.

> This is currently a WIP and things may change as the initial testing and development phase unfolds
---

## Table of Contents

1. [Repository Structure](#1-repository-structure)
2. [Component Deep Dives](#2-component-deep-dives)
   - 2.1 [WebSocket API (`api/`)](#21-websocket-api-api)
   - 2.2 [Flutter Application (`app/`)](#22-flutter-application-app)
   - 2.3 [Headless Brain (`brain/`)](#23-headless-brain-brain)
3. [Data Flow & Communication Protocol](#3-data-flow--communication-protocol)
4. [WebSocket Message Reference](#4-websocket-message-reference)
5. [LLM Integration](#5-llm-integration)
6. [Configuration System](#6-configuration-system)
7. [Development Setup](#7-development-setup)
8. [Coding Conventions](#8-coding-conventions)

---

## 1. Repository Structure

All source code lives under `src/`. Each component is self-contained with its own dependency manifest.

```
opencozmo/
├── src/
│   └── ARCHITECTURE.md         # ← this document
│   ├── api/                    # Python WebSocket API server
│   │   ├── server.py           # Entry point, WebSocket server bootstrap
│   │   ├── robot/              # PyCozmo wrappers and abstraction layer
│   │   │   ├── controller.py   # High-level robot command dispatcher
│   │   │   ├── sensors.py      # Sensor polling & event emission
│   │   │   ├── camera.py       # Camera feed capture & streaming
│   │   │   └── cubes.py        # Cube interaction handling
│   │   ├── handlers/           # One file per WebSocket message category
│   │   │   ├── motion.py
│   │   │   ├── animation.py
│   │   │   ├── audio.py
│   │   │   ├── camera.py
│   │   │   └── system.py
│   │   ├── llm/                # LLM relay module
│   │   │   └── relay.py        # Forwards prompts to OpenAI-compatible endpoint
│   │   ├── config.py           # Config loader (file + env vars)
│   │   ├── logger.py           # Centralized logging setup
│   │   └── requirements.txt    # Python dependencies
│   │
│   ├── app/                    # Flutter application
│   │   ├── lib/
│   │   │   ├── main.dart       # App entry point
│   │   │   ├── core/
│   │   │   │   ├── websocket/  # WS client, connection manager, reconnect logic
│   │   │   │   ├── config/     # App-level config (server URL, theme, etc.)
│   │   │   │   └── models/     # Shared data models (RobotState, CubeEvent...)
│   │   │   ├── features/
│   │   │   │   ├── codelab/    # Code Lab feature (Scratch/Blockly-like integration)
│   │   │   │   │   ├── blocks/ # Block definitions
│   │   │   │   │   ├── runner/ # Block execution engine
│   │   │   │   │   └── ui/     # Code Lab screens and widgets
│   │   │   │   ├── dashboard/  # Sensor live dashboard
│   │   │   │   ├── camera/     # Camera viewer screen
│   │   │   │   └── settings/   # Server config, LLM config, preferences
│   │   │   └── shared/
│   │   │       ├── widgets/    # Reusable UI components
│   │   │       └── theme/      # App theme definition
│   │   ├── assets/
│   │   │   └── blocks/         # Scratch.Blockly block JSON definitions & toolbox XML
│   │   └── pubspec.yaml
│   │
│   ├── brain/                  # Headless autonomous brain
│   │   ├── main.py             # Entry point
│   │   ├── core/
│   │   │   ├── client.py       # WebSocket client (connects to the API)
│   │   │   ├── event_bus.py    # Internal pub/sub between modules
│   │   │   └── scheduler.py    # Cron-style task scheduler
│   │   ├── memory/
│   │   │   ├── store.py        # Persistent storage interface
│   │   │   └── models.py       # Memory record schemas
│   │   ├── personality/
│   │   │   ├── engine.py       # Mood, energy state machine
│   │   │   └── llm_agent.py    # LLM interaction loop
│   │   ├── plugins/            # Drop-in behavior plugins
│   │   │   ├── _base.py        # Plugin base class (abstract)
│   │   │   └── example_greet.py
│   │   ├── config.py
│   │   └── requirements.txt
│   │
│   └── shared/                 # Shared specs & cross-component resources
│       ├── protocol.md         # WebSocket message spec (source of truth)
│       └── schemas/            # JSON schemas for all WS messages
│           ├── commands/
│           └── events/
│
└── scripts/                    # Dev & deployment utility scripts
    └── (Unknown yet)
```

---

## 2. Component Deep Dives

### 2.1 WebSocket API (`api/`)

**Language:** Python 3.11+  
**Key dependencies:** `pycozmo`, `websockets`, `asyncio`, `zeroconf`, `Pillow` (camera frames)

#### Startup sequence

```
server.py
  └─ Load config (config.py)
  └─ Connect to Cozmo via PyCozmo (robot/controller.py)
  └─ Start sensor polling loop (robot/sensors.py)
  └─ Start camera capture loop (robot/camera.py)
  └─ Advertise service via mDNS (zeroconf)
  └─ Start WebSocket server → listen for client connections
```

#### Request routing

Incoming WebSocket messages are JSON objects with a mandatory `type` field. The server routes them to the appropriate handler module:

```python
# server.py (simplified)
HANDLERS = {
    "motion.*":    handlers.motion,
    "animation.*": handlers.animation,
    "audio.*":     handlers.audio,
    "camera.*":    handlers.camera,
    "system.*":    handlers.system,
}

async def on_message(websocket, message):
    data = json.loads(message)
    handler = resolve_handler(data["type"])
    await handler(data, websocket)
```

Each handler module exposes an `async def handle(data, ws)` function.

#### PyCozmo abstraction layer (`robot/`)

Direct PyCozmo calls are **never** made outside the `robot/` package. This isolation means that if PyCozmo's API changes, or if we ever want to swap it for a different backend, only this package needs updating.

```
robot/controller.py     ← single entry point for commands
robot/sensors.py        ← polling loop + event emission
robot/camera.py         ← frame grab + JPEG encoding
robot/cubes.py          ← cube event subscriptions
```

#### Dual deployment modes

The API is designed to run in two contexts without code changes — the difference is controlled entirely by config and by how the process is launched:

| Mode | Who runs it | Network context |
|---|---|---|
| **Embedded** | Flutter app (sidecar process on the host device) | Device connects to Cozmo WiFi |
| **Server** | Always-on machine (RPi, PC...) | RPi: WiFi → Cozmo, Ethernet → LAN/Internet |

The Flutter app detects the mode from its own settings (+ current network context) and either spawns the sidecar or connects to a remote server address.

---

### 2.2 Flutter Application (`app/`)

**Language:** Dart  
**Key dependencies:** `web_socket_channel`, `provider` (state), `zeroconf` (server discovery), `shared_preferences`

#### State management

The app uses a **single global `RobotState` object** that reflects what the API pushes in real time (sensor values, battery level, cube states, connection status). All screens read from it reactively. Commands flow the other way: UI → `WebSocketService` → API.

```
UI Widget
  └─ reads: RobotState (via Provider)
  └─ calls: WebSocketService.send(command)
       └─ sends JSON over WebSocket to API
```

#### WebSocket client (`core/websocket/`)

- **Connection manager** handles the server URL, reconnection with exponential backoff, and ping/keepalive.
- **Message dispatcher** routes incoming events to the appropriate state notifiers.
- Supports both `ws://` (local/embedded) and `wss://` (remote with TLS).

#### Code Lab feature (`features/codelab/`)

Will be similar to Scratch or Blockly — users can drag and drop blocks to create simple or complex programs for Cozmo. The block definitions are stored as JSON in `assets/blocks/` and loaded workspace.
Programs will maybe be sharable via a "community gallery" screen.
The runner is a simple interpreter that walks the block tree and sends corresponding WebSocket commands to the API (or execute on-device actions)

```
Flutter UI
  └─ Workspace
      └─ Block workspace is "compiled" to a block tree
      └─ Runner interprets the block tree
      └─ Each block type maps to one or more WebSocket commands or local actions (such as if/else logic, loops, variables)
```

**Execution model:**

The runner is a simple tree-walker. It processes blocks sequentially, with `await` for async actions (e.g. waiting for Cozmo to finish an animation before moving on). Loops and conditionals are handled recursively.

```dart
// runner/block_runner.dart (simplified)
Future<void> runBlock(Block block) async {
  switch (block.type) {
    case 'motion_drive':
      await ws.send({'type': 'motion.drive', 'speed': block.getField('SPEED')});
      await Future.delayed(Duration(milliseconds: block.getField('DURATION')));
    case 'control_wait':
      await Future.delayed(Duration(milliseconds: block.getField('MS')));
    case 'llm_ask':
      final response = await ws.send({'type': 'llm.prompt', 'text': block.getField('PROMPT')});
      block.setOutput(response['text']);
    // ...
  }
  if (block.nextBlock != null) await runBlock(block.nextBlock!);
}
```

#### Server discovery

On startup, if no server URL is manually configured, the app broadcasts an mDNS query for `_opencozmo._tcp` services on the local network. Any running API instance responds, and the app connects automatically. If nothing is found, the user is prompted to either configure a manual address or enable embedded mode.

---

### 2.3 Headless Brain (`brain/`)

**Language:** Python 3.11+  
**Key dependencies:** `websockets`, `httpx` (LLM HTTP client), `apscheduler` (scheduling)

#### Architecture

The brain is event-driven. Everything communicates through an internal **event bus** (`core/event_bus.py`) rather than calling each other directly. This keeps modules decoupled and makes plugins easy to write.

> **Note** : The brain is still in the early stages of development, and the architecture may evolve as we test different approaches to autonomous behavior. The current design is a starting point based on handmade programs that will run autonomously (in Python).<br>Maybe we want support of the Block-based programming of the Code Lab in the Brain as well to make it more accessible for non-Python users?

```
main.py
  ├─ WebSocket client → connects to the API
  ├─ Event bus ← receives all robot events (sensors, cubes, camera...)
  ├─ Scheduler ← fires time-based events
  ├─ Personality engine ← subscribes to events, decides reactions
  ├─ Memory store ← persists everything to JSON for "remembering" across restarts
  ├─ LLM agent ← talks to LLM endpoint, uses memory for context
  └─ Plugin loader ← discovers and loads /plugins/*.py at startup
```

#### Plugin system

A plugin is a Python file in `brain/plugins/` that subclasses `CozmoPlugin`:

```python
# plugins/_base.py
class CozmoPlugin:
    name: str = "unnamed"
    description: str = ""

    def __init__(self, event_bus, robot_client, memory, config):
        self.bus = event_bus
        self.robot = robot_client
        self.memory = memory
        self.config = config

    async def on_load(self): pass   # called on startup
    async def on_unload(self): pass # called on shutdown
```

The plugin registers its event listeners in `on_load`. Example:

```python
# plugins/example_greet.py
class GreetPlugin(CozmoPlugin):
    name = "greet"
    description = "Greets recognized faces"

    async def on_load(self):
        self.bus.subscribe("face.recognized", self.on_face)

    async def on_face(self, event):
        name = event.get("name", "stranger")
        await self.robot.send({"type": "audio.say", "text": f"Hello, {name}!"})
```

---

## 3. Data Flow & Communication Protocol

### Typical command flow (app → robot)

```
User taps "Drive Forward"
  └─ Flutter UI calls WebSocketService.send({type: "motion.drive", speed: 200, duration_ms: 1000})
       └─ JSON sent over WebSocket
            └─ API server receives message
            └─ Routed to handlers/motion.py
            └─ handler calls robot/controller.py → drive(200)
            └─ PyCozmo sends command over Cozmo WiFi protocol
            └─ API sends back: {type: "motion.drive.ack", success: true}
```

### Typical event flow (robot → app)

```
Cozmo detects a cliff
  └─ PyCozmo emits cliff_detected event
  └─ robot/sensors.py catches it
  └─ Broadcasts to all connected WebSocket clients:
       {type: "event.cliff", side: "front_left", timestamp: 1709123456}
  └─ Flutter WebSocket client receives it
  └─ Message dispatcher updates RobotState.cliffDetected
  └─ UI reactively shows warning indicator
```

---

## 4. WebSocket Message Reference

> Full JSON schemas live in `src/shared/schemas/`. This section is a human-readable summary.

All messages are JSON objects. Every message **must** have a `type` field (string).

### Commands (client → server)

#### Motion

| Type | Fields | Description |
|---|---|---|
| `motion.drive` | `speed` (int, -500–500), `duration_ms` (int) | Drive straight |
| `motion.turn` | `angle_deg` (float), `speed` (int) | Turn in place |
| `motion.stop` | — | Immediate stop |
| `motion.set_lift` | `height` (float, 0.0–1.0) | Set lift position |
| `motion.set_head` | `angle_deg` (float, -25–44.5) | Set head angle |

#### Animation & Face

| Type | Fields | Description |
|---|---|---|
| `animation.play` | `name` (string) | Play a named animation |
| `animation.stop` | — | Stop current animation |
| `face.set_image` | `data` (base64 PNG, 128×64) | Display custom image on face |

#### Audio

| Type | Fields | Description |
|---|---|---|
| `audio.say` | `text` (string), `speed` (int, optional) | Text-to-speech |
| `audio.play` | `name` (string) | Play built-in sound |
| `audio.volume` | `level` (float, 0.0–1.0) | Set volume |

#### LLM Relay

| Type | Fields | Description |
|---|---|---|
| `llm.prompt` | `messages` (array), `max_tokens` (int, optional) | Forward a prompt to the configured LLM |

#### System

| Type | Fields | Description |
|---|---|---|
| `system.ping` | — | Check connection |
| `system.status` | — | Request full robot status snapshot |
| `system.disconnect` | — | Graceful disconnect |

### Events (server → client)

| Type | Fields | Description |
|---|---|---|
| `event.sensor.battery` | `level` (float, 0–1), `charging` (bool) | Battery update |
| `event.sensor.cliff` | `side` (string), `detected` (bool) | Cliff sensor |
| `event.sensor.accel` | `x`, `y`, `z` (floats) | Accelerometer |
| `event.cube.tap` | `cube_id` (int), `intensity` (float) | Cube tapped |
| `event.cube.moved` | `cube_id` (int) | Cube picked up or moved |
| `event.face.detected` | `face_id` (int), `expression` (string) | Face detected |
| `event.camera.frame` | `data` (base64 JPEG) | Camera frame |
| `event.robot.fell` | — | Robot fell off surface |
| `system.pong` | — | Ping response |
| `system.error` | `code` (string), `message` (string) | Error notification |

### Message envelope

```json
{
  "type": "motion.drive",
  "request_id": "abc123",
  "payload": {
    "speed": 200,
    "duration_ms": 1000
  }
}
```

The `request_id` field is optional but recommended. If present, the server echoes it in the response so the client can match replies to requests.

---

## 5. LLM Integration

OpenCozmo uses a **provider-agnostic** approach. Any API that implements the OpenAI chat completions format works:

- Mistral API (`https://api.mistral.ai/v1`)
- OpenAI (`https://api.openai.com/v1`)
- Ollama local (`http://localhost:11434/v1`)
- LM Studio (`http://localhost:1234/v1`)
- Any other compatible server

The relay in `api/llm/relay.py` simply forwards the `messages` array from the WebSocket command to the configured endpoint and streams the response back.

---

## 6. Configuration System

Both the API and the Brain use the same config loading pattern: a `config.yaml` file with optional override via environment variables. Environment variables always win.

### API config (`api/config.yaml`)

```yaml
robot:
  wifi_ssid: "Cozmo_XXXXXX"  # Auto-detected if empty

server:
  host: "0.0.0.0"
  port: 8765
  mdns_name: "opencozmo"  # Advertised as _opencozmo._tcp

camera:
  enabled: true
  fps: 15
  quality: 70             # JPEG quality (0-100)

llm:
  url: "https://api.mistral.ai/v1"
  model: "mistral-small"
  api_key: ""             # Set via env: OPENCOZMO_LLM_KEY

logging:
  level: "INFO"
```

### Brain config (`brain/config.yaml`)

```yaml
api:
  url: "ws://localhost:8765"
  reconnect_delay_s: 5

llm:
  url: "https://api.mistral.ai/v1"
  model: "mistral-small-latest"
  api_key: ""             # Set via env: OPENCOZMO_LLM_KEY
  system_prompt: |
    You are Cozmo, a small curious robot with a big personality.
    You are playful, witty, and occasionally grumpy. Keep responses short.
  max_context_turns: 20   # How many past interactions to include

memory:
  storage_path: "data/"

voice:
  enabled: false
  model: "whisper-base"   # Whisper model for local transcription
  device: "default"       # Audio input device

plugins:
  enabled: true
  directory: "plugins/"
```

---

## 7. Development Setup

### Prerequisites

- Python 3.11+
- Flutter SDK 3.x
- A Cozmo robot with its charging dock and cubes

### API server setup

```bash
cd src/api
pip install -r requirements.txt

# Do not forget to edit config.yaml

# Run (connects to Cozmo and starts WebSocket server)
python server.py
```

Make sure your machine is connected to the Cozmo's WiFi network before starting the server.
> *Note* : If you want to have access to the Internet while being connected to Cozmo's WiFi, you need a second network interface (e.g. Ethernet or a USB WiFi adapter). The API server will bind to all interfaces and be reachable from the local network at the IP address of the second interface. It can be a Ethernet connection or a wired connection via USB tethering from a smartphone.

---

## 8. Coding Conventions

### Python (API & Brain)

- Style: **PEP 8** enforced via `ruff`
- Type hints: **mandatory** on all function signatures
- Async: all I/O must be `async` / `await` — no blocking calls in the event loop
- Logging: use `logger = logging.getLogger(__name__)` in every module, never `print()`
- No direct PyCozmo calls outside `api/robot/` package
- Config must be read through `config.py`, never hardcoded

```python
# Good
async def drive(speed: int, duration_ms: int) -> bool:
    logger.debug("Sending drive command: speed=%d, duration=%dms", speed, duration_ms)
    ...

# Bad
def drive(speed, duration):
    print("driving")
    pycozmo.drive(speed)  # ← never outside robot/
```

### Dart / Flutter

- Style: `dart format` + `flutter analyze` with zero warnings tolerated when going to release
- State: no `setState` in feature-level widgets — use the chosen state manager consistently
- WebSocket: all sends go through `WebSocketService`, never raw channel access from UI
- One feature per directory under `features/` — no cross-feature imports

### WebSocket messages

- `type` field uses dot notation: `domain.action` (e.g. `motion.drive`, `event.sensor.battery`)
- All field names are `snake_case`
- Numeric values: use integers for whole values (ms, degrees as ints), floats only when fractional precision is needed (normalized 0.0–1.0 ranges)
- Never invent a new message type without adding its JSON schema to `src/shared/schemas/`

### Git

- Branch naming: `feature/short-description`, `fix/short-description`, `docs/short-description`
- Commits: imperative mood, present tense — `Add cube event handler`, not `Added` or `Adding`
- Every PR must include updates to relevant docs if the protocol or public API changes
- `main` branch is always in a runnable state (even if features are incomplete)

---

> _This document is a living specification. Update it when the architecture changes — stale docs are worse than no docs._
