"""Pure text interpretation for B2.

This module deliberately has no hardware, database, network, or process-level
dependencies. Keeping recognition here makes natural-language commands easy to
unit test and change without starting the robot.
"""

import re


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
