"""Pure text interpretation for B2.

This module deliberately has no hardware, database, network, or process-level
dependencies. Keeping recognition here makes natural-language commands easy to
unit test and change without starting the robot.
"""

import re


def parse_hardware_intent(text):
    """Parse conservative hardware commands into deterministic candidates.

    Complex/ambiguous descriptions deliberately return ``None`` so a model may
    propose the same schema; HardwareRegistry must still validate that proposal.
    """
    lowered = text.lower().strip().rstrip(".?!")
    if re.search(r"\b(?:what hardware|list (?:the )?hardware|hardware (?:is|do you (?:currently )?have).*(?:connected|configured))\b", lowered):
        return {"action": "list"}
    if re.search(r"\b(?:what|which) (?:pins|resources).*(?:free|available)|list (?:free|available) (?:pins|resources)\b", lowered):
        return {"action": "resources"}
    if re.search(r"\bscan (?:your |the )?i2c bus\b", lowered):
        return {"action": "scan_i2c"}
    match = re.search(r"\b(?:test|read) (?:your |the )?([a-z][a-z0-9_ ]*)$", lowered)
    if match:
        name = re.sub(r"\s+", "_", match.group(1))
        name = {"front_sonar": "front_sonar", "front_sonar_sensor": "front_sonar"}.get(name, name)
        return {"action": "test" if lowered.startswith("test") else "read", "name": name}
    match = re.search(r"\b(?:remove|disconnect|forget) (?:your |the )?([a-z][a-z0-9_ ]*)$", lowered)
    if match:
        return {"action": "remove", "name": re.sub(r"\s+", "_", match.group(1))}

    sonar = re.search(
        r"(?:connected|added|installed).*?(?:(front|rear|left|right) )?ultrasonic(?: sensor)?"
        r".*?trigger (?:on|to) (d(?:[0-9]|1[0-3])|a[0-5]).*?echo (?:on|to) (d(?:[0-9]|1[0-3])|a[0-5])",
        lowered,
    )
    if sonar:
        position = sonar.group(1) or "new"
        return {"action": "add", "candidate": {
            "friendly_name": f"{position}_sonar", "device_type": "ultrasonic",
            "pins": {"trigger": sonar.group(2).upper(), "echo": sonar.group(3).upper()},
        }}
    ir = re.search(r"(?:connected|added|installed).*?(?:(front|rear|left|right) )?ir distance sensor.*?(?:on|to) (a[0-5])", lowered)
    if ir:
        return {"action": "add", "candidate": {
            "friendly_name": f"{ir.group(1) or 'new'}_ir", "device_type": "ir_distance",
            "pins": {"analogue": ir.group(2).upper()},
        }}
    bus = re.search(r"(?:added|connected|installed) (?:an? )?(mcp23008|pca9685)(?:.*?(0x[0-9a-f]{2}|\d+))?", lowered)
    if bus:
        kind = bus.group(1)
        candidate = {"friendly_name": f"{kind}_1", "device_type": kind, "pins": {}}
        if bus.group(2):
            candidate["i2c_address"] = bus.group(2)
        return {"action": "add", "candidate": candidate}
    extra_motor = re.search(
        r"(?:connected|added|installed) (?:another |an? )?l298n.*?"
        r"(?:using|on) (mcp23008(?:_[a-z0-9_]+)?) pins? ([0-7]) through ([0-7])",
        lowered,
    )
    if extra_motor:
        start, end = int(extra_motor.group(2)), int(extra_motor.group(3))
        if end - start == 3:
            parent = extra_motor.group(1)
            if parent == "mcp23008":
                parent = "mcp23008_1"
            return {"action": "add", "candidate": {
                "friendly_name": "l298n_2", "device_type": "l298n",
                "pins": {role: f"{parent}:GP{pin}" for role, pin in zip(
                    ("in1", "in2", "in3", "in4"), range(start, end + 1)
                )},
            }}
    return None


def validate_hardware_candidate(payload):
    """Reject malformed model envelopes before the registry sees them."""
    if not isinstance(payload, dict) or payload.get("action") not in {
        "add", "remove", "list", "resources", "scan_i2c", "test", "read"
    }:
        raise ValueError("malformed hardware intent")
    if payload["action"] == "add" and not isinstance(payload.get("candidate"), dict):
        raise ValueError("add hardware intent requires a candidate object")
    if payload["action"] in {"remove", "test", "read"} and not isinstance(payload.get("name"), str):
        raise ValueError(f"{payload['action']} hardware intent requires a name")
    return payload


NOISE_LABELS = {
    "[BLANK_AUDIO]", "[SILENCE]", "[NO SPEECH]", "[NOISE]", "[MUSIC]",
    "(SILENCE)", "(NOISE)", "(MUSIC)", "(BOOM)", "(GUN SHOTS)",
    "(GUNSHOTS)", "(APPLAUSE)", "(LAUGHTER)", "(BACKGROUND NOISE)",
}


def is_noise(text):
    """Return whether Whisper output contains no actionable speech."""
    if not text:
        return True
    cleaned = text.strip()
    if cleaned.upper() in NOISE_LABELS:
        return True
    return bool(re.fullmatch(r"\s*[\[(].+?[\])]\s*", cleaned))


def contains_b2(text):
    """Return whether text contains a supported B2 wake-name spelling."""
    if not text:
        return False
    return bool(re.search(
        r"\b(?:hey\s+)?(?:a\s*)?(?:b[\s\-]*2|bee\s+two|be\s+two)\b",
        text, re.IGNORECASE,
    ))


def clean_user_text(text):
    """Remove a leading wake phrase while preserving the user's request."""
    return re.sub(
        r"^\s*(?:hey\s+)?(?:a\s*)?(?:b[\s\-]*2|bee\s+two|be\s+two)"
        r"[,.:;!?\s-]*", "", text, flags=re.IGNORECASE,
    ).strip()


def extract_wake_request(text):
    """Return text following a B2 wake phrase, or ``None`` if absent."""
    if not text:
        return None
    match = re.search(
        r"\b(?:hey\s+)?(?:a\s*)?(?:b[\s\-]*2|bee\s+two|be\s+two)\b",
        text, flags=re.IGNORECASE,
    )
    if not match:
        return None
    return re.sub(r"^[\s,.:;!?-]+", "", text[match.end():]).strip()


def is_ip_address_request(text):
    """Recognise requests for B2's current network address."""
    lowered = text.lower()
    return bool(
        re.search(r"\bip(?:v4)?(?:\s+address)?\b", lowered)
        or re.search(r"\bnetwork address\b", lowered)
        or re.search(r"\bhow (?:do|can) i connect to you\b", lowered)
    )


def check_drive_command(text):
    """Map an explicit natural request to one bounded motion command."""
    cleaned = re.sub(r"[.!?]+$", "", text.lower().strip())
    cleaned = re.sub(r"^please\s+", "", cleaned)
    cleaned = re.sub(
        r"^(?:(?:can|could|would|will)\s+you|i(?:'d| would)\s+like\s+you\s+to)\s+",
        "", cleaned,
    )
    cleaned = re.sub(r"\s+please$", "", cleaned)
    patterns = (
        (r"(?:find|face|look at|turn (?:towards|toward)?)\s+(?:me|the speaker)", "find_person"),
        (r"(?:move|go|drive)\s+(?:forward|forwards|ahead)", "forward"),
        (r"(?:move|go|drive)\s+(?:back|backward|backwards|in reverse)", "reverse"),
        (r"(?:turn|spin|rotate|move|look)\s+(?:a little\s+|slightly\s+)?left", "left"),
        (r"(?:turn|spin|rotate|move|look)\s+(?:a little\s+|slightly\s+)?right", "right"),
        (r"(?:turn|spin|rotate)\s+(?:all the way\s+)?around", "turn_around"),
    )
    for pattern, command in patterns:
        if re.fullmatch(pattern, cleaned):
            return command
    return "stop" if cleaned in {"stop", "halt", "stop moving"} else None


def emotion_changes_for_request(text):
    """Return bounded score deltas requested explicitly by the speaker."""
    lowered = text.lower()
    rules = (
        (r"\b(?:cheer up|be happy|feel happier|show (?:me )?a happy face)\b",
         (("happiness", 25), ("loneliness", -15), ("concern", -10))),
        (r"\b(?:be curious|feel curious|show (?:me )?a curious face)\b",
         (("curiosity", 25),)),
        (r"\b(?:calm down|don't worry|do not worry|feel calmer)\b",
         (("concern", -30),)),
        (r"\b(?:act sad|look sad|show (?:me )?a sad face)\b",
         (("loneliness", 25), ("happiness", -15))),
    )
    for pattern, changes in rules:
        if re.search(pattern, lowered):
            return changes
    return ()


def is_disengagement(text):
    """Recognise a speaker explicitly telling B2 a conversation is not for it."""
    return bool(re.search(
        r"\b(?:i(?:'m| am) (?:not talking to you|talking to (?!you\b).+)|"
        r"that wasn't for you|leave us alone)\b",
        text, re.IGNORECASE,
    ))


def extract_person_name(text):
    """Extract a conservative short name from an answer to a name prompt."""
    cleaned = re.sub(r"^just\s+", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"[.!?]+$", "", cleaned)
    patterns = (
        r"^(?:my name is|my name's|i am|i'm|call me)\s+([A-Za-z][A-Za-z '-]{0,40})$",
        r"^([A-Za-z][A-Za-z '-]{0,40})$",
    )
    blocked_words = {
        "remember", "learn", "enrol", "enroll", "face", "voice", "memory",
        "remind", "reminder", "move", "drive", "turn", "stop", "forward",
        "backward", "reverse", "left", "right", "camera", "sleep", "wake",
    }
    for pattern in patterns:
        match = re.match(pattern, cleaned, flags=re.IGNORECASE)
        if not match:
            continue
        name = " ".join(match.group(1).split())
        words = set(re.findall(r"[a-z]+", name.lower()))
        if (
            name.lower() not in {
                "yes", "no", "please", "thanks", "thank you", "unknown",
                "nobody", "someone",
            }
            and not words.intersection(blocked_words)
            and len(name.split()) <= 3
        ):
            return name
    return None


def face_request_name(text):
    """Return an optional supplied name and whether face learning was requested."""
    if not (
        re.search(r"\b(?:remember|learn|enrol|enroll)\b", text, re.IGNORECASE)
        and re.search(r"\b(?:my|this) face\b", text, re.IGNORECASE)
    ):
        return None, False
    match = re.search(
        r"\bmy name(?: is|'s)\s+([A-Za-z][A-Za-z '-]{0,40}?)(?:[.!?]|$)",
        text, flags=re.IGNORECASE,
    ) or re.search(
        r"\b(?:as|for)\s+([A-Za-z][A-Za-z '-]{0,40})[.!?]*$",
        text, flags=re.IGNORECASE,
    )
    return ((" ".join(match.group(1).split()), True) if match else (None, True))


def reply_expects_answer(reply):
    """Use punctuation as the conservative follow-up-listening signal."""
    return bool(reply and reply.strip().endswith("?"))


def obvious_followup(text):
    """Recognise short phrases that clearly continue B2's last response."""
    lowered = text.lower().strip()
    return any(lowered.startswith(phrase) for phrase in (
        "what about", "how about", "what's this", "what is this",
        "what about now", "and now", "what about this", "what about that",
        "and this", "and that", "why", "how come", "tell me more", "really",
        "are you sure",
    ))
