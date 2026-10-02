# Sherry Desktop Sprite (雪莉桌面精灵) 🐱💜

> A cute desktop pet powered by Live2D and PyQt6. This document provides project context, architecture and development guidelines for AI coding agents.

---

## Project Overview

**Sherry Desktop Sprite** is a cross-platform desktop pet application featuring:
- **Live2D Rendering**: Real-time 2D character animation with physics and expressions
- **WebSocket Control API**: External control interface for expressions, motions, and speech
- **Sprite Brain**: Autonomous behavior system with mouse tracking and mood engine
- **TTS Voice System**: Multi-engine text-to-speech support (Edge TTS, macOS say)
- **Lip Sync**: Automatic mouth movement synchronization with speech

### Project Structure

```
desktop-spirit-v2/
├── desktop-spirit-v2-macOS/    # macOS version
└── desktop-spirit-v2-windows/  # Windows version
```

Each platform directory contains:

```
├── src/                        # Main source code
│   ├── main.py                 # Entry point
│   ├── app.py                  # Main application, starts all components
│   ├── core/                   # Core rendering and services
│   │   ├── sprite_window.py    # PyQt6 main window (transparent, always-on-top)
│   │   ├── live2d_view.py      # Live2D OpenGL rendering
│   │   ├── websocket_server.py # WebSocket server (Port 8765)
│   │   ├── tts_manager.py      # TTS manager (multi-engine support)
│   │   └── lip_sync_websocket.py # Lip sync broadcast
│   ├── brain/                  # Sprite brain (intelligent behavior)
│   │   └── sprite_brain.py     # Main brain loop (mouse follow, mood, HTTP API)
│   ├── ui/                     # UI components
│   │   └── bubble_widget.py    # Message bubble widget
│   ├── utils/                  # Utilities
│   │   └── logger.py           # Logging configuration
│   └── assets/                 # Resources
│       └── models/             # Live2D models (hanamaru default)
├── mouse_follow/               # Mouse tracking system (Windows only)
├── scripts/                    # Installation/uninstallation scripts
├── launchd/                    # macOS service configuration
├── docs/                       # Documentation
├── tests/                      # Test client
├── config.yaml                 # Configuration file
└── requirements.txt            # Python dependencies
```

---

## Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| GUI Framework | PyQt6 | Transparent window, OpenGL integration |
| Live2D | live2d-py | Live2D Cubism SDK Python bindings |
| OpenGL | PyOpenGL | Model rendering |
| WebSocket | websockets | Bidirectional communication |
| HTTP API | aiohttp | Brain HTTP interface |
| TTS | edge-tts / pyttsx3 | Speech synthesis |
| Logging | loguru | Structured logging |
| Configuration | YAML | config.yaml |

---

## Build and Test Commands

### Installation

```bash
# Install dependencies
pip3 install -r requirements.txt
```

### Run Application

```bash
# Direct run
python3 src/main.py

# Or using module
python -m src.main

# macOS with virtual environment
./start_sherry.sh              # Foreground (recommended for development)
./start_sherry.sh -b           # Background
./start_sherry.sh stop         # Stop background process
```

### Test Commands

```bash
# Run all tests
python3 tests/test_client.py all

# Interactive mode
python3 tests/test_client.py interactive

# Test specific features
python3 tests/test_client.py expression
python3 tests/test_client.py message
python3 tests/test_client.py speak
python3 tests/test_client.py motion
python3 tests/test_client.py status
```

### Service Management (macOS)

```bash
# Install as launchd service
./scripts/install.sh

# Check status
launchctl list | grep com.sherry.sprite

# View logs
tail -f ~/.sherry/sprite.log
tail -f ~/.sherry/sprite.error.log

# Stop service
launchctl stop com.sherry.sprite

# Start service
launchctl start com.sherry.sprite

# Uninstall
./scripts/uninstall.sh
```

---

## Code Style Guidelines

### Naming Conventions

- **Classes**: `PascalCase` (e.g., `SpriteBrain`, `Live2DView`)
- **Methods/Functions**: `snake_case` (e.g., `mouse_follow_loop`)
- **Constants**: `UPPER_CASE`
- **Private Methods**: Underscore prefix (e.g., `_handle_touch`)

### Comment Style

Use Chinese comments primarily (project targets Chinese users):

```python
# 🚨 【关键修复】：处理 Apple Silicon 的特殊初始化顺序
if IS_APPLE_SILICON:
    live2d.glInit()  # 必须在 init() 之前调用
```

Special markers:
- `🚨` - Important warning/critical fix
- `💜` - Sherry-related features
- `【触觉反馈】` - Touch interaction related

### Async Programming

The project extensively uses `asyncio`:
- WebSocket communication uses `async/await`
- PyQt6 signal-slot uses `QMetaObject.invokeMethod` for thread-safe calls
- Brain runs in a separate `QThread`

---

## Architecture

### Dual-Process Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Main Process                         │
│  ┌─────────────────┐    ┌─────────────────────────────┐ │
│  │ SherrySpriteWindow│   │     WebSocketServer         │ │
│  │  (PyQt6 GUI)      │◄──┤     (Port 8765)             │ │
│  │                   │   │                             │ │
│  │  ┌─────────────┐  │   │  Receives commands:         │ │
│  │  │ Live2DView  │  │   │  • expression (表情)        │ │
│  │  │ (OpenGL)    │  │   │  • motion (动作)            │ │
│  │  └─────────────┘  │   │  • speak (语音)             │ │
│  └───────────────────┘   │  • parameter_batch (参数)   │ │
│           ▲              │            ▲                │ │
│           │ Touch events │            │                │ │
│           └──────────────┘            │                │ │
│                              WebSocket                 │ │
└──────────────────────────────┼─────────────────────────┘
                               │
┌──────────────────────────────▼─────────────────────────┐
│                   Brain Thread/Process                  │
│  ┌──────────────────────────────────────────────────┐  │
│  │               SpriteBrain                         │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │  │
│  │  │ Mouse Follow│  │ Mood Engine │  │ HTTP API  │ │  │
│  │  │ (30fps)     │  │(MoodEngine) │  │(Port 8766)│ │  │
│  │  └─────────────┘  └─────────────┘  └───────────┘ │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Communication Protocol

- **WebSocket (Port 8765)**: Main control channel, JSON format
- **HTTP API (Port 8766)**: Brain REST interface for external calls

### WebSocket Message Format

```json
{
  "type": "command_type",
  "data": { ... }
}
```

### Core Commands

| Command | Description | Example Data |
|---------|-------------|--------------|
| `expression` | Change expression | `{"name": "happy"}` |
| `motion` | Trigger animation | `{"group": "tap", "index": 0}` |
| `speak` | Text-to-speech | `{"text": "Hello", "provider": "edge"}` |
| `parameter_batch` | Batch set parameters | `{"params": {"ParamAngleX": 30}}` |
| `look_at` | Eye gaze direction | `{"x": 0.5, "y": -0.3}` |
| `message` | Show bubble | `{"text": "Hello", "duration": 5000}` |
| `get_status` | Get status | `{}` |

---

## Testing Instructions

### WebSocket Test

```bash
python3 -c "
import asyncio
import websockets
import json

async def test():
    async with websockets.connect('ws://127.0.0.1:8765/sprite') as ws:
        await ws.send(json.dumps({
            'type': 'message',
            'data': {'text': 'Test message'}
        }))
        print(await ws.recv())

asyncio.run(test())
"
```

### HTTP API Test (Brain)

```bash
# Send command
POST http://127.0.0.1:8766/api/command
{"type": "speak", "data": {"text": "Hello"}}

# TTS toggle
POST http://127.0.0.1:8766/api/tts
{"action": "toggle"}  # on, off, toggle, status

# Health check
GET http://127.0.0.1:8766/health
```

---

## Configuration

### config.yaml

```yaml
sprite:
  name: "Sherry"
  window:
    width: 400
    height: 600
    opacity: 1.0
    always_on_top: true
    frameless: true
    transparent: true
  model:
    path: "src/assets/models/hanamaru"
    default_expression: "normal"

websocket:
  host: "127.0.0.1"
  port: 8765

logging:
  level: "INFO"
  file: "~/.sherry/sprite.log"
  max_size: "10MB"
  backup_count: 5
```

---

## Security Considerations

1. **WebSocket only binds to localhost** (`127.0.0.1`), not exposed externally
2. **HTTP API is also localhost-only**
3. Log files may contain user interaction data, protect `~/.sherry/` directory
4. TTS-generated temporary audio files in `/tmp`, clean up periodically

---

## Platform-Specific Notes

### macOS

- Uses `AppKit`, `Foundation`, `Quartz` for native window management
- Apple Silicon (M1/M2/M3/M4) requires special OpenGL initialization order:
  1. `live2d.glInit()`
  2. `live2d.init()`
- Service management via `launchd`

### Windows

- Uses Windows API (`ctypes`) for global mouse tracking
- Separate `mouse_follow/` module for mouse tracking functionality
- No `launchd` service management (manual execution)

---

## Key Module References

| File | Purpose |
|------|---------|
| `src/core/live2d_view.py` | `EXPRESSION_PARAM_MAP` definition, expression parameter mapping |
| `src/brain/sprite_brain.py` | Mouse follow, mood engine, touch reactions |
| `src/core/websocket_server.py` | WebSocket command handling |
| `docs/API.md` | Complete WebSocket API documentation |
| `docs/EXPRESSIONS.md` | Complete expression list (Chinese names) |
| `docs/EXPRESSION_GUIDE_FOR_AGENTS.md` | Expression system guide for AI agents |

---

## Logging

- Main program: `~/.sherry/sprite.log`
- Startup scripts: `./sprite_main.log`, `./sprite_brain.log`
- Uses `loguru` for structured logging

---

*Made with 💜 for Master*

*Last Updated: 2026-03-06*
