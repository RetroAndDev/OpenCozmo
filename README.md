# 🤖 OpenCozmo

> An open-source ecosystem to revive, extend and unleash the original Anki Cozmo robot.

OpenCozmo is a community-driven project that recreates the software environment of the **Anki Cozmo** robot from scratch, building on top of the existing hardware. Since Anki shut down in 2019, the official app has been slowly dying — OpenCozmo aims to give Cozmo a second life, and then some.

The project does **not** modify the robot itself (*but the charging station will eventually see some upgrades - see [Hardware Vision](#-hardware-vision-long-term-concept) for details*). Everything happens around Cozmo.

---

## 📋 Status

> **Last updated**: _1 March 2026_

| Component | Status | Notes |
|---|---|---|
| WebSocket API | 🔬 Research / WIP | Architecture design phase |
| Flutter App | 🔬 Research / WIP | Architecture design phase |
| Headless Brain | 🔬 Research / WIP | Architecture design phase |
| Code Lab | 🔬 Research / WIP | Block set definition in progress |
| Hardware Station | 💡 Concept | Long-term vision |

**Legend:** 💡 Concept · 🔬 Research/WIP · 🚧 In Development · ✅ Stable · ⚠️ Broken

> I am currently in the early research and architecture design phase. The WebSocket API is the first piece to be built, as it is the foundation for everything else. I'm testing the PyCozmo library, mapping out the API endpoints, and building a simple proof-of-concept server that can control the robot and stream sensor data.

---

## 🧩 Architecture Overview

OpenCozmo is split into three main components that can work independently or together.

```
┌─────────────────────────────────────────────────┐
│              Flutter App (Client)               │
│         iOS · Android · Desktop · (Web)         │
└────────────────────┬────────────────────────────┘
                     │ WebSocket
          ┌──────────┴───────────┐
          │                      │
   ┌──────▼──────┐      ┌────────▼────────┐
   │  On-Device  │      │ Remote "Server" │
   |  Embedded   │      │   (RPi, etc.)   │
   │  API Mode   │      │  Ethernet+WiFi  |
   │ (no setup)  │      │ (be autonomous) │
   └──────┬──────┘      └────────┬────────┘
          │                      │
          └──────────┬───────────┘
                     │ PyCozmo
              ┌──────▼──────┐
              │ Cozmo Robot │
              │  (WiFi AP)  │
              └─────────────┘
```

### Deployment Modes

**Embedded mode** — The WebSocket API is bundled directly inside the Flutter app. The device connects directly to Cozmo's WiFi network. Simple, zero setup, works like the original app. Downside: the host device loses its internet connection (unless it has a second network interface like Ethernet on a laptop).

**Server mode** — The API runs on a dedicated machine (e.g. Raspberry Pi) with both WiFi (toward Cozmo) and Ethernet (toward your local network / internet). The Flutter app discovers the server on the LAN and communicates with it. This unlocks internet-connected features, persistent automation, and enables the Headless Brain mode.

---

## 📦 Components

### 1. 🐍 WebSocket API

**Stack:** Python · WebSocket (`websockets`) · [PyCozmo](https://github.com/zayfod/pycozmo)

The backbone of the whole ecosystem. This Python server exposes a clean WebSocket interface to control the robot, read its sensors, and stream its camera feed. It abstracts all the complexity of PyCozmo's low-level WiFi protocol behind a simple, language-agnostic API that any client can consume as JSON messages.

**Key responsibilities:**
- Full robot control: movement, animations, audio, face expressions, lift/head
- Real-time sensor data streaming: cliff sensors, accelerometer, battery level, cube state
- Camera feed forwarding (MJPEG or base64 frames over WebSocket)
- Cube interaction events
- OpenAI-compatible LLM relay (forwards requests to a configured endpoint)
- Can run embedded (bundled in the Flutter app via a sidecar process) or as a standalone server

---

### 2. 📱 Flutter Application

**Stack:** Flutter (Dart) · WebSocket client · Blockly

The user-facing interface. The app connects to the WebSocket API (either embedded or remote) and provides a rich set of interactions. It is designed to replicate and extend the original Anki app experience.

#### Code Lab

The main focus of the first milestone. A visual block-based programming environment (inspired by Scratch / Google Blockly) that lets anyone program Cozmo without writing code. It is not a 1:1 clone of the original Anki Code Lab — it is a modernized, extended reimagining of it.

**Built-in block categories:**
- Movement & navigation
- Animations & expressions
- Sounds & speech (TTS)
- Cube interactions
- Conditionals, loops, variables
- Timers and delays

**Extension blocks (new):**
- `Ask LLM` — sends a prompt to the configured LLM endpoint and uses the response (e.g. to make Cozmo say something)
- `Search the Web` — performs a web search and injects the result into the program flow
- `Send GET/POST Request` — generic HTTP block for integrations with any external service
- `Wait for voice command` — trigger blocks from speech (requires the hardware station microphone or device mic - as Cozmo has no built-in mic)
- `Play from URL` — stream audio from a URL through Cozmo's speaker

**Other app features (roadmap):**
- Live sensor dashboard
- Camera viewer with face detection overlay
- Behavior & mood monitor
- Server discovery on local network (mDNS/Zeroconf)

---

### 3. 🧠 Headless Brain

**Stack:** Python · WebSocket client · OpenAI-compatible API

A standalone Python runtime designed to run on a server (Raspberry Pi or any always-on machine) with no display. It connects to the WebSocket API and drives Cozmo autonomously based on configurable behaviors and LLM integration.

This is where Cozmo stops being a toy and becomes a proper AI-powered companion.

**Features:**
- Plugin-based behavior system: drop a Python file in `/plugins` and the brain loads it automatically
- Persistent memory: the brain remembers interactions, faces it has seen, and user preferences across reboots
- LLM integration via any OpenAI-compatible endpoint (Mistral API, Ollama, OpenAI, LM Studio, etc.) — the user configures the URL and key
- Scheduled behaviors: "greet me every morning", "go to sleep at 23:00", "react to motion detected by camera"
- Event-driven architecture: react to sensor events in real time
- Optional voice input via microphone (hardware station or USB mic required - again, Cozmo has no built-in mic)
- Optional Home Assistant / MQTT integration for smart home automation
- Optional n8n integration for connecting to thousands of other services

---

## 🔧 Technology Stack

| Layer | Technology | Reason |
|---|---|---|
| Robot communication | [PyCozmo](https://github.com/zayfod/pycozmo) | Reverse-engineered protocol, no app needed |
| API server | Python + `websockets` | Simple, async, works great on RPi |
| App UI | Flutter (Dart) | Single codebase for iOS, Android, Desktop |
| Visual programming | - | - |
| LLM integration | OpenAI-compatible REST | Provider-agnostic, works with Mistral, Ollama, OpenAI... |
| Local discovery | mDNS / Zeroconf (`zeroconf` lib) | Zero-config server discovery on LAN |

---

## 💡 Hardware Vision (Long-term Concept)

> This section describes a future hardware extension, not a current priority.<br>
> And if it hypothetically comes to life, it will be designed as an optional add-on that can work with the existing Cozmo robots without any modifications. And will **NOT BE SOLD**, you will have to build it yourself following the plans.

The goal is to create a **custom docking station** embedding a **Raspberry Pi Compute Module 4 or 5**, transforming the Cozmo setup into a self-contained, internet-connected companion — with no extra cables, no phone required.

**Station features (concept):**
- RPi CM4/5 handles all computation and network bridging (with maybe a special version for regular Raspberry Pi with less features)
- **Ethernet port** (PoE-compatible) for internet access and power
- **USB-C** for robot charging and Pi power
- **Integrated microphone** for local voice transcription — Cozmo has no built-in mic, this adds it externally while leaving the robot unmodified *(but will not be as powerful as a built-in mic as you will not be near the station all the time)*
- **Internal battery** to make the robot portable: powers the Pi and/or the robot depending on charge level
- Clean enclosure designed to match Cozmo's aesthetic

**Cube redesign (concept):**
The original cubes use LR1 batteries which are expensive and hard to find. The plan is to redesign them with an integrated **Li-ion cell** and a USB-C charging port, keeping the same form factor and radio communication.

---

## 🗺️ Roadmap (Rough)

> A detailed roadmap with timelines will be published once the initial research phase is complete and I have a better understanding of the technical challenges and scope. But here is a rough outline of the major milestones:

- [ ] WebSocket API: core motor and animation control
- [ ] WebSocket API: sensor streaming
- [ ] WebSocket API: camera feed
- [ ] Flutter app: basic connection screen + manual control
- [ ] Code Lab: core block set
- [ ] Code Lab: LLM and HTTP extension blocks
- [ ] Headless Brain: plugin architecture
- [ ] Headless Brain: LLM personality loop
- [ ] Headless Brain: persistent memory
- [ ] App: server auto-discovery (mDNS)
- [ ] Hardware station: prototype

---

## 💡 What about Vector or the new DDL Cozmo (aka Cozmo 2.0) ?

OpenCozmo is focused on the original Cozmo robot as I do not own a Vector or the new DDL Cozmo.
The original Cozmo has a unique charm and a strong community that I want to support. However, the architecture of OpenCozmo is designed to be modular and adaptable, so in the future, it could potentially be extended to support other Anki/Digital Dream Labs robots if there is enough interest and access to the hardware as it is quite expensive.
Contributions to add support for Vector or the new Cozmo are welcome, but it is not a current priority.

## 🙏 Credits & Prior Art

- [PyCozmo](https://github.com/zayfod/pycozmo) by @zayfod — the reverse-engineered Python SDK that makes all of this possible
- [Anki](https://anki.com) — original creators of Cozmo (RIP)
- The Cozmo community for keeping the dream alive

---

## ⚖️ License

OpenCozmo is licensed under the **GNU General Public License v3.0**. See [LICENSE](LICENSE) for details.

---

> _OpenCozmo is an independent community project. It is not affiliated with, endorsed by, or connected to Anki or Digital Dream Labs in any way._