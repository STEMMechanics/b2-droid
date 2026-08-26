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
