"""Wake-word parsing tests. Run: python -m pytest tests  (or python tests/test_wake.py)"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mantri import split_wake  # noqa: E402

CASES = [
    # Commands
    ("Mantri, open Firefox.", "open firefox"),
    ("Hey Mantri, volume up.", "volume up"),
    ("Hey, Mantri, volume up.", "volume up"),
    ("Mantry open Firefox.", "open firefox"),
    ("Man tree next song.", "next song"),
    ("Mantri. Open files.", "open files"),
    # Background speech around the command is dropped
    ("Mantri, next song. Mantri, next song. Mantri.", "next song"),
    ("It's 4-0! Mantri, pause.", "pause"),
    # Bare wake word
    ("Mantri.", ""),
    ("Mantri. Mantri.", ""),
    # Not addressed to Mantri: every phrase the old Jarvis model fired on, and look-alikes
    ("I'm not sure if I can get it.", None),
    ("It's 4-0!", None),
    ("I'm sorry, I'm sorry.", None),
    ("Oh, shit.", None),
    ("Bye.", None),
    ("Get triple with the moon.", None),
    ("The Chief Minister met the Mantri yesterday.", None),
    ("This is my daily mantra for focus.", None),
    ("Mukhyamantri said so.", None),
    ("Thank you.", None),
    ("", None),
]


def test_split_wake():
    for text, expected in CASES:
        assert split_wake(text) == expected, (text, split_wake(text), expected)


if __name__ == "__main__":
    test_split_wake()
    print(f"ok, {len(CASES)} cases")
