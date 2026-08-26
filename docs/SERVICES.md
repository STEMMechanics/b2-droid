# Services and extensibility

B2 uses `droid.py` as a composition root. It creates independent services and
coordinates them; device access, subprocess calls, persistence and parsing
belong in `b2/` modules. This keeps a failure in optional vision or speech from
silently changing motor safety.

## Current service boundaries

| Service | Public responsibility |
|---|---|
| `MotionController` | Execute a fixed motor action and learn bounded turn duration |
| `VisionService` | Own the camera and publish object/person detections |
| `SpeechService` | Transcribe audio and synthesize/play speech |
| `LLMClient` | Call and observe the OpenAI-compatible local model endpoint |
| `DatabaseService` | Supply short-lived committed SQLite transactions |
| `EmotionController` | Maintain thread-safe bounded emotional signals |
| `Microphone` | Continuously drain ALSA and provide bounded capture queues |
| `ContextRegistry` | Combine service facts into delimited LLM context |
| `EntityRepository` | Preserve extensible objects, metadata and relationships |
| `ObservationService` | Persist throttled object/person/place/time observations |
| `DisplayService` | Validate and send arbitrary 8×8 frames to the Arduino |
| `SkillRegistry` | Discover, advertise, validate and invoke optional capabilities |

Face identity, reminders and conversation policy remain coordinator-owned
domain workflows. They use the service interfaces above and do not own device
or inference transports.

## Add factual LLM context without code

Factory features go in `config/features.json`. Persistent local information
goes in `/var/lib/b2-droid/context.d/` as `.json`, `.txt`, or `.md`. For example:

```json
{
  "name": "temperature sensor",
  "location": "front grille",
  "units": "degrees Celsius"
}
```

The directory survives removable USB-drive upgrades. Context is information, not authority:
adding an action name to a file cannot make the motors execute it.

## Add a runtime service

Create a small class under `b2/` with methods for its operations and a
side-effect-free `context()` method. Construct it in `droid.py`, then register
its context:

```python
temperature = TemperatureService(device="/dev/i2c-1")
context_registry.register("temperature_service", temperature.context)
```

The context provider must return quickly and should return JSON-compatible
data. Provider exceptions are isolated and appear as `unavailable` in
diagnostics.

## Add learning safely

`LearningStore` is generic, but every learner must define its own evidence,
bounds and application point. A learner should:

1. Accept explicit feedback or repeated measurable evidence.
2. Change one named numeric calibration by a small step.
3. Call `set_bounded(namespace, key, value, minimum, maximum)`.
4. Keep factory limits and hardware interlocks authoritative.
5. Expose the learned value through `context()` and diagnostics.

Motion currently learns only after a recent left, right or turn-around action.
“Too far” reduces that action by 15%; “not far enough” increases it by 15%.
Normal turns remain between the configured minimum pulse and 1.5 seconds, and
turn-around remains below 3 seconds. It does not learn forward movement,
autonomous routes, arbitrary commands, or watchdog settings.

Explicit stall feedback after any recent movement may also increase PWM in
15-point steps within adult-configured bounds. This is feedback-driven rather
than automatic because the current hardware has no encoder or current sensor
with which to prove that a wheel actually moved.

Camera verification compares a textured frame from before a turn with the next
frame published after it. Two consecutive low-difference results are required
before PWM changes. Missing, dark, or ambiguous images remain uncertain.

The same pattern could safely learn camera-centering pulse gain, face-match
tolerance suggestions, preferred speaking volume, or curiosity frequency. Each
requires a dedicated service policy and tests; the language model must never
write calibration files directly.

## Persistent data compatibility

New object properties should normally be metadata keys or entity links, not new
columns. Readers select only keys and relations they understand and must never
delete unknown namespaces. Contract versions describe storage shape rather than
application version: adding `owned_by` to a cat remains contract 1, while an
incompatible table redesign would require contract 2. The offline updater
refuses packages whose declared contract range excludes the stored database.

## Skills

Skills expose the same interface: `name`, `description`, `available()`, and
`run(request, context) -> SkillResult`. An installed package is discovered
through a standard Python entry point:

```toml
[project.entry-points."b2.skills"]
weather = "my_b2_weather:WeatherSkill"
```

B2 supplies available skills and their `<skill name="...">request</skill>`
entrypoint to the LLM. It validates calls, treats returned content as untrusted
data, and stores results and sources as knowledge entities. The built-in
`web_search` skill targets the SearXNG JSON endpoint in `B2_WEB_SEARCH_URL` and
is visibly unavailable without one. Installing skill code remains an
adult-controlled upgrade operation.

## People and observations

Legacy people, face-embedding and voice-embedding keys remain unchanged.
Startup bridges each legacy person to a `person` entity through
`legacy.people_id` and records face-sample count as identity metadata. Vision
stores throttled observation entities with detected labels, best current
identity, `B2_LOCATION`, and an ISO timestamp. Unknown people remain unknown
until recognition succeeds. Images are never stored. `B2_MAX_OBSERVATIONS`
bounds event history while canonical object and person entities remain.

## Matrix protocol

Firmware accepts `matrix:` followed by sixteen lowercase hexadecimal digits,
two per row. `DisplayService.show()` accepts eight integers or eight eight-bit
strings and validates them before transmission. Any normal state command
replaces the custom frame. Motor and host watchdogs remain active.

## Verification checklist

For a new service, add contract tests that cover unavailable hardware, invalid
input, persistence across reconstruction, and both lower and upper bounds. Then
run the project verification commands in `ARCHITECTURE.md`.
