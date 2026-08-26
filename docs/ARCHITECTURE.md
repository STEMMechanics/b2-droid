# B2 architecture

## Design goals

B2 separates replaceable platform services from the behaviour coordinator.
Hardware and external processes are accessed through small modules; pure text
interpretation never imports hardware. Safety checks remain deterministic and
local rather than relying on language-model output.

## Runtime flow

```text
systemd -> b2-update (root, removable-media installer)
        `-> b2.supervisor -> droid.py coordinator
                            |-- b2.audio_capture -> ALSA / arecord
                            |-- b2.speech        -> whisper.cpp / Piper / aplay
                            |-- b2.commands      -> pure text decisions
                            |-- b2.network       -> ip / nmcli
                            |-- b2.sounds        -> WAV / aplay
                            |-- b2.web           -> adult dashboard
                            |-- b2.remote        -> optional Slack
                            |-- b2.storage       -> SQLite transactions
                            |-- b2.hardware      -> validated runtime hardware
                            |-- b2.vision        -> camera / YOLO detections
                            |-- serial           -> Arduino safety controller
                            |-- whisper.cpp      -> transcription
                            `-- llama-server     -> conversation
```

The unprivileged dashboard cannot edit `/etc` or invoke systemd. Runtime
configuration changes use an allow-listed request file in the persistent data
directory. The root update watcher revalidates that request, atomically updates
only approved environment keys, and restarts the application service.

The Arduino owns the motor timeout and LED animation. Ubuntu may request only a
bounded movement; loss of heartbeats causes the Arduino to stop the motors.

Language-model inference is routed in-process through the LiteLLM SDK. The
dashboard-managed connection list is read for each request, so priority changes
do not require a restart. `local-ai` points to the managed llama.cpp service and
is the factory default. Enabled routes are tried by ascending priority and then
fall back on provider errors or timeouts. API keys are write-only through the
dashboard and the route file is mode 0600. Model routing changes language
interpretation only: deterministic commands and safety validation do not move
into the model layer.

## Python modules

| Module | Responsibility |
|---|---|
| `droid.py` | Composition root and live behaviour coordination |
| `b2/audio_capture.py` | ALSA transport, capture windows and WAV helpers |
| `b2/commands.py` | Wake, noise, movement, emotion and intent parsing |
| `b2/context.py` | Context-provider registry, feature catalog and drop-in fragments |
| `b2/emotions.py` | Thread-safe bounded emotion scores and face selection |
| `b2/learning.py` | Persistent learned calibration under factory safety limits |
| `b2/llm.py` | One observable OpenAI-compatible inference transport |
| `b2/llm_routes.py` | Validated LiteLLM connections, secret redaction and ordered fallback |
| `b2/motion.py` | Bounded motion execution and explicit-feedback learning |
| `b2/network.py` | Local IP discovery and NetworkManager operations |
| `b2/sounds.py` | Generated startup and emotional motifs |
| `b2/web.py` | Authenticated dashboard and diagnostic API |
| `b2/remote.py` | Optional remote text transport |
| `b2/speech.py` | Whisper transcription and resilient Piper/ALSA output |
| `b2/directives.py` | Factory directives plus persistent override |
| `b2/updater.py` | Verified removable-media updates |
| `b2/updater_daemon.py` | Privileged read-only removable-drive discovery and update lifecycle |
| `b2/entities.py` | Forward-compatible entities, metadata and relationships |
| `b2/observations.py` | Throttled place/person/object observation history |
| `b2/skills.py` | Common skill contract, discovery and optional web search |
| `b2/display.py` | Validated dynamic 8×8 Arduino frames |
| `b2/supervisor.py` | Child lifecycle, session logs and updates |
| `b2/audio_capture.py` | Persistent ALSA reader and bounded PCM transport |
| `b2/speech.py` | Whisper transcription and Piper/ALSA playback |
| `b2/motion_vision.py` | Camera-frame evidence for chassis movement |
| `b2/config.py` | Shared application/data/config paths |
| `b2/storage.py` | Short-lived transactional SQLite connections |
| `b2/hardware_registry.py` | SQLite hardware inventory, capability descriptors and deterministic resource validation |
| `b2/hardware_protocol.py` | Acknowledged line protocol for runtime Arduino configuration and readings |
| `b2/hardware.py` | Provisioning, discovery, tests, readings and concise hardware context |
| `b2/vision.py` | Camera ownership and object/person detection snapshots |

`droid.py` remains the composition root because conversation, identity, vision,
emotion and motion coordinate shared live state. New pure parsing, transports,
or integrations belong under `b2/`; do not add another parser or subprocess
transport directly to the coordinator.

## State and concurrency

- The main thread owns voice activity and conversation flow.
- The vision thread publishes snapshots under `vision_lock`.
- The microphone drains ALSA continuously but queues only during capture.
- Pending AI retries yield to foreground requests and take `interaction_lock`.
- `motor_lock` serializes wheel actions; `serial_lock` protects Arduino writes.
- SQLite connections are short-lived context managers and never cross threads.

## Extension rules

1. Put pure recognition in `b2.commands` and test it before wiring it in.
2. Wrap new devices/services in a module with a narrow interface.
3. Pass callbacks into UIs/transports; they must not import `droid.py`.
4. Keep forward/reverse motion deterministic and explicitly requested.
5. Add settings to `config/b2.env.example` and document units/defaults.
6. Store mutable data under `B2_DATA_DIR`, never inside application code.
7. Preserve compatibility with existing `/etc/b2-droid.env` files.

## Context and new capabilities

`config/features.json` is the factory catalog supplied to the LLM. Add a feature
there when it ships with B2. Local or experimental services can add a `.json`,
`.txt`, or `.md` fragment under `/var/lib/b2-droid/context.d/`; it is included
automatically and survives application updates. Runtime services register live
providers with `ContextRegistry`. Provider failures are isolated and reported
as unavailable rather than breaking a conversation.

## Learning

Learned calibration lives in
`/var/lib/b2-droid/learned-calibration.json`, separate from factory defaults,
adult environment configuration, directives, and memories. A service may learn
only within hard-coded or adult-configured safety bounds. `MotionController`
currently learns left/right/around duration after a recent turn and explicit
feedback such as “too far” or “not far enough.” It cannot learn autonomous
navigation, bypass the Arduino watchdog, or create a new action. Learned values
are visible in dashboard diagnostics and supplied to the LLM as factual context.

Domain-specific face/voice recognition and reminder repositories remain wired
by the composition root because they share the live identity transaction. Their
storage transport, parsing, external inference, emotions, motion, audio,
networking, UI, update, logging and context responsibilities are isolated.

## Verification

```bash
python -m unittest discover -s tests -v
python -m py_compile droid.py b2/*.py
bash -n scripts/*.sh
```

Arduino verification remains an installer step because it needs `arduino-cli`,
the AVR core, LedControl and attached hardware.

## Dynamic hardware

The Python `HardwareRegistry` is the persistent source of truth. Natural-language
recognition in `b2.commands` produces only a candidate intent. The deterministic
registry validates device descriptors, pin capabilities, fixed allocations,
parents and I2C addresses before SQLite is changed or a command reaches the
Arduino. Model text can never issue a raw serial or motor command.

At startup, and again after a serial reconnection, Python sends `HW:RESET` and
replays every enabled registry entry using acknowledged `HW:ADD` commands.
Failure marks affected devices unavailable without stopping B2. Arduino EEPROM
is not used. The existing motor and host watchdogs, emergency stop behaviour,
and bounded motion controller remain independent of the dynamic device table.

The Arduino Uno resource map is fixed as follows:

| Resources | Use |
|---|---|
| D0/D1 | reserved USB serial |
| D3, D5, D6 | fixed left L298N enable/direction |
| D7, D8, D9 | fixed right L298N direction/enable |
| D10, D11, D13 | fixed MAX7219 CS/data/clock |
| D2, D4, D12 | initially free native GPIO |
| A0-A3 | initially free analogue or digital resources |
| A4/A5 | shared I2C SDA/SCL bus; never allocated as ordinary pins |

Supported descriptors are `ultrasonic`, `ir_distance`, `hall_sensor`,
`compass`, `mcp23008`, `l298n`, `servo`, and `pca9685`. MCP23008 pins appear as
resources such as `mcp23008_1:GP0`; PCA9685 channels use the equivalent channel
abstraction for future servos/PWM. Additional motor controllers may be
described, but dynamic hardware commands cannot actuate them: motor operation
remains behind explicit bounded commands and Arduino watchdogs.

`HW:I2C_SCAN` performs real discovery on A4/A5. Python compares returned
addresses with registered devices and reports unknown addresses without
guessing a chip type. Ordinary GPIO and analogue devices cannot identify
themselves; they remain configured/unverified until a functional read or test
shows that they are responding. Registry status therefore distinguishes
configured, detected, responding, unverified, and unavailable states.
