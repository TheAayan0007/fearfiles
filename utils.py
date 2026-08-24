"""
FEAR - small UI-side helper functions (password strength estimate, secure
temp-file deletion). Kept separate from crypto_core.py so that file stays
minimal and easy to audit on its own.
"""

import os
import re


def password_strength_score(password: str) -> int:
    """Rough 0-100 password strength estimate based on length and character
    variety. This is a simple heuristic, not real entropy estimation — a
    high score means 'probably reasonable', not a guarantee. Swapping in a
    library like `zxcvbn` later would give a much more realistic estimate
    (it catches things like "Password123!" looking strong here but being
    an extremely common pattern in real cracking dictionaries).
    """
    if not password:
        return 0
    score = min(len(password) * 4, 40)
    variety = sum([
        bool(re.search(r"[a-z]", password)),
        bool(re.search(r"[A-Z]", password)),
        bool(re.search(r"[0-9]", password)),
        bool(re.search(r"[^a-zA-Z0-9]", password)),
    ])
    score += variety * 15
    return min(score, 100)


def strength_label(score: int) -> str:
    if score < 30:
        return "Weak"
    if score < 60:
        return "Okay"
    if score < 85:
        return "Strong"
    return "Very strong"


def secure_delete(path: str, passes: int = 1) -> None:
    """Best-effort overwrite-then-delete of a temp file.

    Important caveat: on SSDs and modern filesystems (wear leveling,
    copy-on-write, journaling) an in-place overwrite is not guaranteed to
    reach the original physical storage location, so this is a reasonable
    precaution, not a forensic guarantee. Full-disk encryption on the
    machine you run FEAR on is the real defense against "leftover
    decrypted bytes on disk" concerns.
    """
    try:
        length = os.path.getsize(path)
        with open(path, "r+b") as f:
            for _ in range(passes):
                f.seek(0)
                f.write(os.urandom(length))
                f.flush()
                os.fsync(f.fileno())
    finally:
        if os.path.exists(path):
            os.remove(path)
