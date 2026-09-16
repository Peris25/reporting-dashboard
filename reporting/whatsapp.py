"""Parse WhatsApp chat exports into structured messages.

WhatsApp's "Export chat" produces a text file whose exact line format varies by
phone locale and platform. This handles the common shapes:

    [2026/09/16, 14:30:05] Alice: Message text
    16/09/2026, 14:30 - Alice: Message text
    9/16/26, 2:30 PM - Alice: Message text

Lines without a recognised header are treated as continuations of the previous
message (WhatsApp wraps long or multi-line messages this way). Lines that carry
a timestamp but no "Sender:" part are system notices (encryption note, joins,
and so on) and are kept out of the conversation transcript.
"""

from __future__ import annotations

import re

import pandas as pd

# A timestamp such as "16/09/2026, 14:30" or "9/16/26, 2:30 PM" or "2026.09.16, 14:30:05".
_TS = r"\d{1,4}[./-]\d{1,2}[./-]\d{1,4},?\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:[APap]\.?[Mm]\.?)?"

# Bracketed form: "[ts] rest"
_BRACKET = re.compile(rf"^[‎‏]*\[(?P<ts>{_TS})\]\s*(?P<rest>.*)$")
# Dash form: "ts - rest"
_DASH = re.compile(rf"^[‎‏]*(?P<ts>{_TS})\s+[-–]\s+(?P<rest>.*)$")
# "Sender: text" (a sender name has no colon and is reasonably short).
_SENDER = re.compile(r"^(?P<sender>[^:]{1,80}):\s(?P<text>.*)$", re.DOTALL)


def _match_header(line):
    for pattern in (_BRACKET, _DASH):
        match = pattern.match(line)
        if match:
            return match.group("ts").strip(), match.group("rest")
    return None


def parse_export(text):
    """Return a list of {timestamp, sender, text, system} dicts, in order."""
    messages = []
    for raw_line in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip("\n")
        header = _match_header(line)
        if header is None:
            # Continuation of the previous message.
            if messages and line.strip():
                messages[-1]["text"] = f"{messages[-1]['text']}\n{line}".strip()
            continue
        timestamp, rest = header
        sender_match = _SENDER.match(rest)
        if sender_match:
            messages.append({
                "timestamp": timestamp,
                "sender": sender_match.group("sender").strip(),
                "text": sender_match.group("text").strip(),
                "system": False,
            })
        else:
            messages.append({"timestamp": timestamp, "sender": "", "text": rest.strip(), "system": True})
    return messages


def conversation(messages):
    """Only the real (non-system) messages that carry a sender."""
    return [m for m in messages if not m["system"] and m["sender"]]


def transcript_text(messages):
    """A clean transcript for a model or a heuristic to read."""
    return "\n".join(f"{m['sender']}: {m['text']}" for m in conversation(messages))


def participants(messages):
    seen = []
    for message in conversation(messages):
        if message["sender"] not in seen:
            seen.append(message["sender"])
    return seen


def parse_timestamp(value, *, dayfirst=True):
    """Best-effort parse of a WhatsApp timestamp to a pandas Timestamp (or NaT)."""
    return pd.to_datetime(str(value).strip(), errors="coerce", dayfirst=dayfirst)


def first_timestamp(messages, *, dayfirst=True):
    """The earliest parseable timestamp in the conversation, or None."""
    stamps = [parse_timestamp(m["timestamp"], dayfirst=dayfirst) for m in messages if m["timestamp"]]
    stamps = [s for s in stamps if pd.notna(s)]
    return min(stamps) if stamps else None
