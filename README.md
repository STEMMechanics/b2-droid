# B2 Droid

B2 is a child-friendly, locally operated voice droid for Ubuntu. An EliteDesk
800 G3 runs speech, vision, memory, and optional Slack messaging. An Arduino
owns the safety-critical motor watchdog and animates the 8×8 face.

Developer documentation: [architecture and extension guide](docs/ARCHITECTURE.md).

## Hardware

- Arduino over USB (default `/dev/ttyACM0`, 115200 baud)
- MAX7219 8×8 matrix: DIN D11, CLK D13, CS D10
- L298N-style motor inputs: left D5/D6, right D7/D8
- USB microphone/speaker and optional V4L2 camera

The Arduino stops moving after one second without a fresh command. B2 itself
only issues short, explicit movements; this is not obstacle avoidance. Keep an
adult and a physical power cutoff nearby when children use it.

### Dynamic hardware registry

B2 persists optional hardware in its existing SQLite database and validates
every change against the fixed pin map before configuring the Arduino. Examples
of supported spoken requests include:

- “I've connected a front ultrasonic sensor with trigger on A1 and echo on A2.”
- “I've added an MCP23008 to your I2C bus at 0x20.”
- “What pins do you still have free?”
- “What hardware do you currently have connected?”
- “Scan your I2C bus.”
- “Test your front sonar.”

The fixed allocation is D0/D1 for USB serial; D3/D5/D6 and D7/D8/D9 for the
existing L298N drive controller; D10/D11/D13 for the MAX7219; and A4/A5 for
I2C. D2, D4, D12, and A0-A3 begin free. These assignments are never silently
replaced. Supported descriptors currently cover ultrasonic, analogue IR
distance, Hall sensors, compass devices, MCP23008, L298N, native servos, and
PCA9685. MCP23008 GPIO and PCA9685 channels become named child resources.

An I2C scan performs real address discovery, but an unknown address remains
unknown until its chip/driver is specified. Ordinary GPIO and analogue devices
cannot be identified automatically; B2 can only remember their declared wiring
and perform a functional read/test. Status distinguishes configured,
responding, unverified, and unavailable devices.

On every startup or Arduino reconnection B2 clears only the firmware's dynamic
table, replays the validated SQLite registry, and verifies acknowledgements.
Unavailable devices are reported rather than crashing the droid. The Arduino
does not use EEPROM for this configuration, and its motor/host watchdogs and
emergency-stop behaviour remain authoritative. See
[the architecture guide](docs/ARCHITECTURE.md#dynamic-hardware) for protocol and
safety details.

## Ubuntu installation from USB

Mount the USB drive on the EliteDesk and run the installer directly from it:

```bash
sudo bash /media/droid/YOUR_USB_NAME/B2-Droid/scripts/install.sh
```

The installer copies the application and its virtual environment into the
permanent global location `/opt/b2-droid`, creates the independent updater in
`/opt/b2-bootloader`, stores persistent data in `/var/lib/b2-droid`, and
installs systemd services. Wait for the installer to finish before removing the
USB drive; B2 does not execute application files from removable media.
On the initial network-connected
installation it builds whisper.cpp, downloads the tiny and small English
Whisper models, installs Piper and its British Alba voice, and exports the
YOLO11 nano vision model to ONNX. This can take several minutes.

B2 also expects an OpenAI-compatible local chat-completions server at
`http://127.0.0.1:8080/v1/chat/completions`. Override this with `B2_CHAT_API`
in `/etc/b2-droid.env` if your model server uses another address. By default,
the installer builds the official `llama.cpp` server with OpenBLAS and installs
Qwen2.5 1.5B Instruct Q4_K_M (about 1.12 GB). The small default is intentional
for a CPU-only EliteDesk that is simultaneously running speech and vision.
`b2-llm.service` binds only to localhost port 8080, starts before B2, and
automatically restarts after a failure.
Before doing so, `B2_INSTALL_LLM=auto` probes the configured `B2_CHAT_API`
server's `/v1/models` endpoint. A compatible running server is preserved and
the bundled model is not downloaded. If the endpoint is stopped, the installer
also looks for the modern `llama` CLI in the droid user's local bin,
`/usr/local/bin`, and `/usr/bin`. It adopts that executable into
`b2-llm.service` and runs `B2_LLM_HF_MODEL` (default
`Qwen/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M`) using `llama server -hf`. Set
`B2_INSTALL_LLM=false` only when an existing server is intentionally managed
outside B2, or `true` to force B2's bundled server.
An adopted `llama` CLI defaults to a 4096-token context and one parallel
request slot. This leaves CPU and memory for simultaneous vision and speech. Set
`B2_LLM_CONTEXT_SIZE` to tune it. B2 also retains only the latest
`B2_MAX_CONVERSATION_MESSAGES` messages (default 12).
If that endpoint is temporarily unavailable, B2 acknowledges the outage and
stores the unanswered question in `/var/lib/b2-droid/pending-ai-requests.json`.
A background worker waits for the configured delay (default 60 seconds) and
yields to foreground conversation. Once ready, the main audio loop speaks the
answer safely; queued questions therefore survive both a
model-server outage and a B2 restart. The dashboard status reports the queue as
`pending_ai_questions`.

Check the model service independently with:

```bash
systemctl status b2-llm --no-pager
journalctl -u b2-llm -n 100 --no-pager
curl http://127.0.0.1:8080/health
```
Face recognition and YOLO object recognition are installed by default. Install
optional voice identification or Slack extras inside the installed environment:

```bash
sudo -u droid /opt/b2-droid/.venv/bin/pip install '/opt/b2-droid[voices,slack]'
```

The installer compiles and uploads `arduino.ino` when the configured serial
device is connected. The defaults are `/dev/ttyACM0` and `arduino:avr:uno`.
Set `B2_ARDUINO_FQBN` for another board, or `B2_FLASH_ARDUINO=false` to skip
automatic flashing. Upload failure is reported but does not roll back the
working Ubuntu installation.

Useful commands:

```bash
sudo systemctl status b2-droid
journalctl -u b2-droid -f
sudo systemctl restart b2-droid
```

## Wi-Fi

Run `sudo ./scripts/configure-wifi.sh` at the droid. It interactively asks for
the SSID and password and passes them to NetworkManager without saving them in
this project. Ubuntu's NetworkManager stores the resulting connection securely.

## USB-drive updates

There are two supported layouts.

The simplest is to copy the complete project folder onto any normally formatted
USB drive. No filesystem label is required. The copied layout must retain:

```text
USB drive/
└── B2-Droid/
    ├── b2-source-update.json
    ├── droid.py
    ├── pyproject.toml
    ├── b2/
    └── scripts/install.sh
```

`b2-source-update.json` is the identifier. Its version must differ from the
installed version. B2 discovers an unmounted removable USB partition with
`lsblk`, mounts supported FAT, exFAT, NTFS or ext filesystems read-only, finds
the marker up to two folders deep, validates the structure, copies it to
internal staging, and installs it. Safely eject the drive after copying, insert
it into B2, and leave it connected until B2 restarts.

For checksum-based distribution, label or mount a USB drive and run:

```bash
./scripts/make-update.sh /media/YOUR_USER/B2UPDATE 0.2.1
```

`make-update.sh` creates `b2-update.tar.gz` and checksummed `b2-update.json`.
This format detects incomplete or corrupt copies and is preferable when sharing
an update with somebody else. The raw source marker is convenient but is not a
cryptographic integrity or author signature.

Insert the USB drive into B2. The dedicated
root-owned `b2-update.service` detects the removable block device, mounts it
read-only with device and executable files disabled, verifies the SHA-256
checksum, and relaunches B2. Already-mounted cards under `/media`, `/run/media`,
or `/mnt` are also detected. Any version different from the running version is
accepted, so the same mechanism supports deliberate upgrades and downgrades.
The database is backed up under `/var/lib/b2-droid/update-backups/` before every
change, and the last 50 transitions are recorded in `update-state.json`.
The small watcher lives separately in `/opt/b2-bootloader`, so downgrading the
application to a release that predates this mechanism does not remove recovery
or prevent a later USB-drive upgrade.

The first deployment of the bootloader-style watcher must be installed once
from the terminal. Older watchers cannot bootstrap the new unlabelled-drive
discovery, so restart it once after installing version 0.11 or later:

```bash
sudo bash scripts/install.sh --update .
sudo systemctl restart b2-update
systemctl status b2-update --no-pager
```

Subsequent packages can be installed by insertion alone. Keep the USB drive inserted
until B2 has restarted. A package declares the database contract range it can
read. An incompatible downgrade is refused instead of risking persistent data.

## Uninstall and clean reinstall

Run the uninstaller from the USB copy, not from `/opt/b2-droid`, because the
installed application directory is removed during the command:

```bash
sudo bash /media/droid/YOUR_USB_NAME/B2-Droid/scripts/uninstall.sh
sudo bash /media/droid/YOUR_USB_NAME/B2-Droid/scripts/install.sh
```

The default uninstall removes all B2 code, virtual environments, updater files,
and systemd units, but preserves faces, memories, learned calibration, models,
directives and `/etc/b2-droid.env`. The following irreversible variant also
deletes all persistent B2 data and configuration:

```bash
sudo bash /media/droid/YOUR_USB_NAME/B2-Droid/scripts/uninstall.sh --purge-data
```

The `droid` system account and shared Ubuntu packages are intentionally retained
because they may be used by hardware access or other software.

Each session-log line is prefixed with a local ISO-8601 timestamp including the
UTC offset and milliseconds. AI request messages also report foreground versus
background work and elapsed completion or timeout duration. Background retries
wait at least `B2_PENDING_AI_RETRY_DELAY` seconds and yield to new spoken or web
requests instead of immediately occupying the interaction lock again.

The persistent ALSA reader queues audio only while voice-activity detection is
actively consuming it. Samples produced during transcription, AI inference, or
B2's own speech are discarded at the reader rather than replayed as a future
utterance. The emergency queue is bounded to two seconds.

Checksums detect corruption but do not authenticate the author. For unattended
deployment in public spaces, add a signed-manifest scheme before trusting
unknown removable media.

Persistent recognized things use generic `entities`, `entity_metadata`, and
`entity_links` tables. A cat can retain `core.colour` and `core.name` metadata
while a later release adds an `owned_by` link to a person or a namespaced field.
Older releases simply ignore unfamiliar namespaces and relationships; they do
not rewrite or destroy them. Additive meanings stay on entity contract 1.
Only a genuinely incompatible storage redesign should increase the contract,
which then prevents downgrade to code that cannot safely read it.

## Directives and memory

`config/directives.txt` is the version-controlled factory personality and
safety policy. `/var/lib/b2-droid/directives.override.txt` is the persistent
local overlay and wins on conflicts. Put recognized adult names in
`B2_ADMIN_NAMES`, for example `B2_ADMIN_NAMES=James,Alex`. An identified adult
can then say, “B2, new directive: …”. The change becomes active after restart.

Ordinary facts and reminders remain per-person in SQLite. Directives should be
rare operating rules, not a substitute for personal memory.

## Slack

Create a Slack app with Socket Mode and `app_mentions:read`, `channels:history`,
and `chat:write` as appropriate for one private channel. Set these values only
in `/etc/b2-droid.env`:

```text
B2_SLACK_BOT_TOKEN=xoxb-...
B2_SLACK_APP_TOKEN=xapp-...
B2_SLACK_ALLOWED_CHANNEL=C0123456789
```

Install the `slack` extra and restart the service. B2 accepts messages only
from the configured channel and posts its reply there. Never commit tokens.

## Adult web chat and diagnostics

Set one adult password in `/etc/b2-droid.env`:

```text
B2_WEB_PASSWORD=use-a-long-unique-password-here
B2_WEB_USERNAME=admin
B2_WEB_HOST=0.0.0.0
B2_WEB_PORT=8088
```

The interactive installer asks for this password when it is missing. It also
installs Avahi and, when UFW is active, opens the configured dashboard TCP port.
After restarting B2, open `http://B2-IP-ADDRESS:8088` or try the machine's
hostname with `.local`, commonly `http://droid.local:8088`. Log in with username
`admin` and the configured password. Binding to `0.0.0.0` makes it available on
all IPv4 interfaces, including Ethernet, Wi-Fi, and localhost. The page offers
text chat plus live diagnostics, authenticated log downloads, stored people,
face-sample counts, memories and reminders, and Wi-Fi scanning/connection.
The authenticated page also refreshes B2's latest camera frame once per second
and tails the latest 64 KiB of activity—including heard speech, replies,
tracking, recognition, and errors. Camera images are not written to disk.
Remote chat cannot move B2 or alter directives.

If it is not reachable over Wi-Fi, diagnose the listener and address locally:

```bash
hostname -I
sudo ss -ltnp | grep ':8088'
sudo journalctl -u b2-droid -n 100 --no-pager | grep -i web
sudo ufw status
```

Use `http://ADDRESS:8088`, not HTTPS. If the log says the dashboard is disabled,
add a 12-character or longer `B2_WEB_PASSWORD` to `/etc/b2-droid.env` and run
`sudo systemctl restart b2-droid`.

Basic authentication is suitable for a trusted home or classroom LAN, but it
does not encrypt traffic. Do not expose port 8088 directly to the internet;
use Slack or a VPN for access from outside the local network.

## Facial states

The Arduino supports `idle`, `listening`, `thinking`, `waiting`, `talking`,
`curious`, `sleep`, `error`, and `booting`. Booting displays a rotating ring
while the Python runtime initializes. Once microphone calibration completes,
B2 shows its idle face and plays a short rising two-tone chime through ALSA.
Emotion changes also have distinct quiet non-verbal motifs for idle, curious,
lonely, excited, and concerned states. They play only on a real state transition
and have a 20-second cooldown. Set `B2_EMOTION_SOUNDS=false` in
`/etc/b2-droid.env` to silence them, or tune `B2_EMOTION_SOUND_COOLDOWN`.
Set `B2_READY_SOUND=false` to silence the startup chime. Set
`B2_OUTPUT_DEVICE=plughw:CARD,DEVICE` in `/etc/b2-droid.env` if `aplay`'s
default output is not B2's speaker. Startup now logs whether playback succeeded
and includes the final ALSA error when it did not. Idle blinks at irregular intervals; listening
and talking animate. Good future additions are a glance animation when a person
first appears, a low-energy breathing face after long inactivity, a puzzled
face on low transcription confidence, and a delighted face for successful
learning. Keep animations non-blocking so the motor watchdog always runs.

The Arduino displays the animated boot symbol immediately when it powers or
resets, before Ubuntu or Python is ready. While B2 runs, Python sends a serial
heartbeat every two seconds. A clean service stop sends `offline`; a crash,
stalled process, unplugged USB connection, or missing heartbeat for eight
seconds produces the same fail-safe state: motors stop and only the
bottom-right LED flashes slowly. Restarting the service returns to the boot
animation until microphone calibration completes.

Firmware 0.8 adds a separate animated download arrow for removable-media installation.
The first upgrade to this firmware may still show the old boot/offline artwork;
subsequent upgrades show `updating` until firmware upload resets the Arduino.
Python can also send a custom frame as `matrix:` plus sixteen hex digits;
`DisplayService` validates higher-level eight-row frames first.

## Knowledge and skills

B2 bridges existing people and biometric samples into its extensible entity
knowledge store without moving or renumbering original records. Vision
periodically documents detected object labels, current identity, `B2_LOCATION`,
and time, but never saves camera frames. `B2_OBSERVATION_INTERVAL` and
`B2_MAX_OBSERVATIONS` bound the history.

Optional capabilities use one discoverable skill contract. Installed Python
packages advertise entry points under `b2.skills`; B2 includes only available
skills in live model context, validates calls, and stores results and sources.
The included web-search skill requires a SearXNG JSON endpoint in
`B2_WEB_SEARCH_URL`.

The dashboard Audio tab controls B2's base voice volume and automatic volume.
By default each boot starts at 100% so a previously quiet setting cannot make
B2 appear dead; `B2_STARTUP_VOLUME_FLOOR` can lower that floor. Automatic mode
follows a slow background-noise estimate and may add up to 20
percentage points to the adult-selected base. Settings persist locally in
`/var/lib/b2-droid/audio-settings.json`. B2 limits the adjustment and ignores
speech-level peaks so a sudden sound cannot immediately force maximum volume.
B2's language model interprets natural feedback about its own volume rather
than matching a fixed phrase list. It returns a validated action to raise or
lower the base by 10%, set an exact 0–100 level, or toggle automatic volume,
while generating the acknowledgement in B2's personality. The current audio
settings are included in model context. Merely discussing volume or another
device should not change B2's speaker.

The Audio tab also discovers ALSA capture and playback hardware using
`arecord -l` and `aplay -l`, marks likely USB/webcam capture and analogue
playback choices as recommended, and allows the adult to switch them. The
Settings tab exposes a small allow-list of camera, speech, volume, and motor
safety values. It never returns passwords, API keys, or Slack tokens. Saving
writes a validated request in `/var/lib/b2-droid`; the root-owned update
watcher updates `/etc/b2-droid.env` and restarts B2 within a few seconds.

Microphone transport, voice detection and transcription are decoupled. ALSA
is continuously drained by its reader thread; when an utterance is complete,
Whisper runs in a bounded worker while voice detection continues listening.
Up to `B2_MAX_TRANSCRIPTION_CONTINUATIONS` additional utterances (default 2)
are transcribed and appended in order to the same request. This prevents a
speaker's continuation from disappearing behind the `Transcribing...` delay.
B2 still drains captured audio around its own playback so its voice is not fed
back into the conversation.

Automatic movement verification waits for the configured camera settling time
and then evaluates three fresh frames. Two frames must agree that the scene
moved before movement is confirmed; all three must agree on a stall before the
result may influence learned motor power. Mixed evidence is reported as
`uncertain` and never teaches the motors.

When B2 has asked a visible person a question and hears no response for 25
seconds, it raises the base volume by 10 and repeats the exact question once.
Persistent boosts are rate-limited to once every five minutes, and it never
repeats or raises volume when nobody is visible.

Factory capability descriptions live in `config/features.json` and are added to
every LLM request automatically. Additional installed services can publish
context without changing `droid.py`: place a `.json`, `.txt`, or `.md` file in
`/var/lib/b2-droid/context.d/`. Invalid providers are isolated and shown in
diagnostics instead of breaking conversation.

Learned calibration is stored separately in
`/var/lib/b2-droid/learned-calibration.json`. After a recent turn, explicit
feedback such as “that was too far” or “you barely moved” changes that turn's
duration by a small bounded amount. Factory/adult limits and the Arduino motor
watchdog always remain authoritative. The learned values are visible in the
dashboard and supplied to the LLM, so B2 can truthfully explain what changed.

See `docs/SERVICES.md` for the service boundaries, how to describe a new
feature to the LLM, and how to add another bounded learner. Describing a feature
does not grant it control: executable actions must still be implemented and
validated by a service.

When a person newly enters view, B2 uses the curious face and may greet them. It
asks the local AI to choose a short, personality-consistent line using the
recognized person, enrolled names, visible objects, and recent spontaneous
lines. The AI may return `SILENT` when an interruption would be repetitive. B2
only asks a visitor's name when no person has ever been enrolled locally, so a
temporary recognition miss does not cause another introduction. After a new
name is supplied, B2 quietly starts learning their face. Responses to these
questions do not require the wake phrase. `B2_CURIOSITY_COOLDOWN` controls how
soon B2 may ask another situational question while a person remains present
(default 300 seconds), while
`B2_CURIOSITY_ABSENCE_RESET` controls how long someone must be out of view to
count as a new arrival (default 8 seconds).

If the fast wake model reports blank audio or an environmental sound, B2 retries
the same recording with the accurate model by default. Set
`B2_RETRY_NOISE_TRANSCRIPTIONS=false` only if environmental false triggers make
the extra CPU cost undesirable.

B2 maintains bounded 0–100 scores for happiness, curiosity, loneliness, and
concern. Presence, recognition, conversation, inactivity, and failures move the
scores gradually; the dashboard exposes them under `emotions`. Functional faces
such as listening, thinking, talking, waiting, booting, and offline temporarily
take priority. At rest, the dominant score selects happy/idle, curious, lonely,
excited, or concerned artwork on the matrix. Emotion scores are also supplied
to the language model so wording and facial expression share the same state.

When a visible person has not interacted for `B2_EXPLORATION_IDLE_SECONDS`, B2
may make a stationary environment glance no more often than
`B2_EXPLORATION_INTERVAL`. Tracking pauses briefly so it does not immediately
undo the glance, then resumes. High curiosity can shorten the speaking cooldown,
but never below 90 seconds; the AI may still choose `SILENT`. Forward motion is
never used for investigation.

By default, face learning is transparent: after a person supplies their name,
B2 collects varied samples in the background while conversation continues. The
dashboard exposes `face_learning` progress and the final face-sample count.
Set `B2_TRANSPARENT_FACE_LEARNING=false` to restore an explicit permission and
pose flow. Face embeddings remain local in B2's SQLite database.

An identified face is retained across recognition misses while a person stays
visible. A short `B2_FACE_IDENTITY_ABSENCE_GRACE` (default 12 seconds) also
bridges momentary person-detection gaps, without assigning a departed person's
identity to a later visitor for the full identity-hold period.
The dashboard's `person_visible` value holds for 2.5 seconds across brief YOLO
misses. `person_visible_raw` shows the immediate detector result, while
`person_last_seen_age_seconds` shows how fresh the last detection is. Tune the
hold using `B2_PERSON_VISIBILITY_HOLD_SECONDS`.

Due reminders are not marked completed until delivered. B2 announces a
person-specific reminder only while that named person is visible and currently
identified; otherwise it remains active and is delivered when they return.

The language model may request only a very short `look_left` or `look_right`
turn followed by an explicit stop. Autonomous forward/reverse motion is blocked
because B2 has no obstacle sensors. With ENA/ENB jumpers installed, the motor
driver cannot regulate speed; the shorter timing reduces turn distance, not
electrical motor speed. True slow movement requires PWM wiring to ENA and ENB.

Physical commands accept natural polite forms such as “could you turn a little
left?”, “turn around”, “look at me”, and “please stop moving”. Every result is
mapped to a bounded local action; the language model cannot invent unrestricted
motor commands. “Look at me” centers a visible person or starts the wider voice
search when nobody is in frame. `B2_TURN_AROUND_SECONDS` controls the calibrated
around-turn duration. Explicit requests such as “cheer up”, “be curious”, “calm
down”, or “show me a sad face” adjust bounded emotion scores, after which the AI
responds naturally from the new state.

While waiting for an answer or acting curious, B2 centers the largest detected
person using short stationary turn pulses. If the target leaves frame, B2
briefly searches in the last-seen direction, then gives up after six seconds.
`B2_TRACK_DEAD_ZONE` controls how far off-centre a person may be, and
`B2_TRACK_INTERVAL` limits correction frequency. Set `B2_TRACK_PERSON=false`
to disable tracking or `B2_TRACK_INVERT=true` if the motor orientation makes B2
turn away from people. `B2_TRACK_WHILE_IDLE=true` keeps visual focus independent
of facial-expression changes and conversation timeouts. Centering duration is
proportional to horizontal error between `B2_TRACK_MIN_PULSE` and
`B2_TRACK_MAX_PULSE`; `B2_TRACK_PULSE_GAIN` controls the slope. While a person
remains in frame, `B2_TRACK_EFFECTIVE_DEAD_ZONE` prevents boundary jitter and
`B2_TRACK_EFFECTIVE_MIN_PULSE` ensures a requested correction is long enough
to overcome motor stiction. Opposite-direction corrections are suppressed near
the centre by `B2_TRACK_REVERSE_DEAD_ZONE`, and
`B2_TRACK_DIRECTION_CHANGE_DELAY` prevents rapid left/right reversals. With nobody in
view, B2 performs a bounded four-step right/left sweep after
`B2_IDLE_SCAN_DELAY`. Empty-room scanning uses the wider
`B2_IDLE_SWEEP_PULSE` (default 0.35 seconds), while recently-lost-person
reacquisition keeps the gentler `B2_TRACK_SEARCH_PULSE` (default 0.10 seconds).
When B2 hears intelligible speech but sees nobody, it immediately performs a
longer ten-step sweep in one direction instead of reversing after four steps.
This gives it time to find somebody behind it despite having no directional
microphone. Tune this with `B2_VOICE_SEARCH_SECONDS`,
`B2_VOICE_SEARCH_INTERVAL`, and `B2_VOICE_SEARCH_STEPS`.
After finding somebody this way, B2 holds visual attention for two minutes
before an autonomous environment glance is allowed. Tune that period with
`B2_PERSON_FOCUS_HOLD_SECONDS`. The first person encountered after each restart
receives an AI-generated acknowledgement; later check-ins may stay silent to
avoid becoming repetitive.
Tune the wider pulse with the wheels raised first because turn angle depends on
motor voltage, PWM, flooring, and wheel grip. It never drives forward while
searching.

YOLO object labels are included in every language-model context under “Objects
visible,” so B2 can reason about what it can actually see without inventing
observations. Recent curiosity prompts are stored in SQLite across restarts and
are visible in the dashboard memory diagnostics.

True slower motion requires removing the L298N ENA/ENB jumpers and wiring
ENA to Arduino D3 and ENB to D9. Ubuntu sends `B2_MOTOR_SPEED` to the Arduino at
startup (default torque floor 220/255) and applies it equally to both wheels.
`B2_MOTOR_STARTUP_FLOOR` ensures an older learned low value can still overcome
static friction. Test with the
wheels raised and increase the value if either motor cannot start. Do not leave the enable jumpers
installed when using the PWM wiring.

After any recent requested, tracking, or search movement, explicit feedback such
as “you didn't move”, “your wheels stalled”, or “you are stuck” increases the
learned PWM by 20 within `B2_MOTOR_SPEED_MIN`–`B2_MOTOR_SPEED_MAX` (defaults
110–240). The learned power survives restarts and appears in diagnostics. B2
also compares camera frames before and after turns. Two consecutive textured
frames with almost no visual change are treated as a likely stall and raise PWM
once. Dark, blank, missing, or ambiguous frames remain `uncertain` and do not
change power. Wheel encoders or motor-current sensors are still needed for
definitive physical feedback.

DC gearmotors often do not move during very short pulses because electrical
power is applied without overcoming gearbox and floor friction. All turn paths
therefore respect `B2_MIN_TURN_PULSE` (default 0.16 seconds), including AI
glances, person centering, lost-person search, idle sweep, and direct turn
commands. Increase it in 0.02-second steps with the wheels raised until every
requested turn moves reliably. `B2_MOTOR_SPEED` controls PWM torque/speed when
ENA and ENB are wired; it does not replace a sufficient pulse duration.

## Architecture and performance notes

Operational code is separated under `b2/`: configuration, directives, remote
messaging, updates, and supervision. `droid.py` still contains the real-time
conversation and identity pipeline so its behavior remains familiar.

Emotion behaviour is also separated by responsibility. `b2/emotion_model.py`
defines bounded scoring, named causes, explicit event changes, and passive
rates. `b2/emotion_effects.py` defines how scores affect the face, optional
transition sounds, and curiosity check-in timing. `b2/emotions.py` provides the
thread-safe facade used by the coordinator. The model can discuss these factual
scores but cannot invent new emotion effects or bypass physical safety rules.

The camera and inference pipeline runs on its own daemon thread and publishes a
small locked state snapshot to the audio/conversation loop. This prevents YOLO
and face recognition from blocking microphone handling while giving every AI
request the current identity, person presence, and detected-object labels. The
vision loop already downsizes face frames and runs YOLO at 320 px. Camera motor
verification requires coherent whole-frame movement, making it less likely to
mistake a person moving for chassis movement. Repeated confirmed stalls may
raise PWM only to `B2_MOTOR_SPEED_MAX`; at that limit automatic tracking and
searching pause for `B2_MOTOR_STALL_COOLDOWN` seconds. Explicit user movement
commands remain available. Wheel encoders or an IMU are still preferable to
camera-only odometry. The largest practical performance gains are using the
tiny Whisper model for wake
detection, keeping YOLO inference throttled, using an ONNX model, and disabling
face/voice extras when not needed. On this CPU, avoid increasing camera size or
running recognition every frame. A future refactor should give audio, vision,
conversation, and outputs bounded queues and explicit shutdown events.

Microphone capture also uses a dedicated reader thread and a bounded 60-second
chunk queue. Whisper and local-model inference may consume CPU without allowing
the `arecord` pipe to fill and block. Speech arriving during transcription is
therefore retained for the next utterance; if the bounded queue ever overflows,
the log explicitly reports the number of oldest chunks dropped. Every engaged
transcription is logged with its Python representation so an empty/noise result
cannot look like a silently discarded recording.
The startup log names `B2_AUDIO_DEVICE`, warns when calibration is unusually
quiet, and reports a 15-second listening peak while waiting. Compare that peak
with `B2_MIN_SPEECH_THRESHOLD` (default 100). Use `arecord -l` to select the
capture card; it is often different from `B2_OUTPUT_DEVICE`.
Speech gating defaults to 1.30 times ambient noise with one second of pre-roll,
so softly spoken opening words are retained. During proactive model generation
and B2's own speech, capture retention is paused and then reopened as a clean
answer window, preventing stale backlog and making the response timing clear.
