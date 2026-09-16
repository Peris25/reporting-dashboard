from reporting.whatsapp import (
    conversation, first_timestamp, parse_export, participants, transcript_text,
)

BRACKET = (
    "[2026/09/16, 14:30:05] Alice: Hi, I cannot log in\n"
    "[2026/09/16, 14:30:40] Alice: it says wrong password\n"
    "[2026/09/16, 14:31:00] Support: Let me help\n"
)

DASH = (
    "16/09/2026, 14:30 - Messages are end-to-end encrypted.\n"
    "16/09/2026, 14:31 - Brian: Payment failed on mpesa\n"
    "this is a second line of the same message\n"
    "16/09/2026, 14:35 - Support: Checking now\n"
)


def test_parses_bracket_format():
    messages = parse_export(BRACKET)
    convo = conversation(messages)
    assert [m["sender"] for m in convo] == ["Alice", "Alice", "Support"]
    assert convo[0]["text"] == "Hi, I cannot log in"


def test_parses_dash_format_and_system_and_multiline():
    messages = parse_export(DASH)
    # The encryption notice is a system line, not part of the conversation.
    assert any(m["system"] for m in messages)
    convo = conversation(messages)
    assert convo[0]["sender"] == "Brian"
    # The continuation line is folded into the previous message.
    assert "second line" in convo[0]["text"]
    assert participants(messages) == ["Brian", "Support"]


def test_transcript_excludes_system_lines():
    transcript = transcript_text(parse_export(DASH))
    assert "end-to-end encrypted" not in transcript
    assert "Brian: Payment failed on mpesa" in transcript


def test_first_timestamp_is_earliest():
    stamp = first_timestamp(parse_export(BRACKET))
    assert stamp is not None
    assert stamp.hour == 14 and stamp.minute == 30
