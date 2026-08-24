"""
FEAR - File Encryption And Reader
==================================
Core cryptography module. No GUI code here on purpose — this file can be
tested and audited completely independently of the interface.

.fear file format
------------------
  offset  size  field
  0       4     magic bytes b"FEAR"
  4       1     format version (currently 1)
  5       1     Argon2id time_cost
  6       4     Argon2id memory_cost in KiB (big-endian uint32)
  10      1     Argon2id parallelism
  11      16    salt (random, used to derive the key from the password)
  27      12    nonce (random, used once per file for AES-256-GCM)
  39      ...   ciphertext (AES-256-GCM output: encrypted data + 16-byte tag)

The encrypted payload (before encryption) is itself:
  4 bytes big-endian length of a small JSON metadata blob, then the JSON
  bytes, then the raw original file bytes. Storing metadata *inside* the
  encrypted payload (rather than in the plaintext header) means an attacker
  without the password can't even learn the original filename.

Why these choices
------------------
- AES-256-GCM: authenticated encryption. Ciphertext can't be modified
  without the modification being detected on decrypt (protects against
  tampering, not just eavesdropping).
- Argon2id for turning the password into a key: this is the part that
  actually matters for resisting offline brute-force / forensic cracking
  attempts. Argon2id is deliberately slow and memory-hungry, which makes
  checking each candidate password thousands of times more expensive than
  a fast hash like SHA-256 would be. Cost parameters are stored per-file so
  they can be raised later without breaking files you already encrypted.
- A random salt and nonce are generated for every single file, so
  encrypting the same file twice with the same password produces
  completely different output both times.

None of this matters if the password itself is weak — see the README.
"""

import os
import json
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from argon2.low_level import hash_secret_raw, Type

MAGIC = b"FEAR"
VERSION = 1

# Argon2id cost parameters. Higher = slower to compute = harder to brute
# force, at the cost of taking longer (and more RAM) to encrypt/decrypt on
# your own machine. These are strong defaults — raise them further if
# you're willing to trade a slower unlock for more security.
DEFAULT_TIME_COST = 4                  # number of passes
DEFAULT_MEMORY_COST_KB = 256 * 1024    # 256 MiB
DEFAULT_PARALLELISM = 4                # threads

SALT_SIZE = 16
NONCE_SIZE = 12
KEY_SIZE = 32  # 256-bit key for AES-256

HEADER_SIZE = 4 + 1 + 1 + 4 + 1 + SALT_SIZE + NONCE_SIZE  # 39 bytes


class DecryptionError(Exception):
    """Wrong password, corrupted file, or a file that was tampered with."""


def derive_key(password: str, salt: bytes, time_cost: int,
                memory_cost_kb: int, parallelism: int) -> bytes:
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=time_cost,
        memory_cost=memory_cost_kb,
        parallelism=parallelism,
        hash_len=KEY_SIZE,
        type=Type.ID,  # Argon2id
    )


def encrypt_file(input_path: str, output_path: str, password: str,
                  time_cost: int = DEFAULT_TIME_COST,
                  memory_cost_kb: int = DEFAULT_MEMORY_COST_KB,
                  parallelism: int = DEFAULT_PARALLELISM) -> None:
    """Encrypt input_path, writing a .fear-format file to output_path."""
    with open(input_path, "rb") as f:
        original_bytes = f.read()

    metadata = json.dumps({
        "filename": os.path.basename(input_path),
        "size": len(original_bytes),
    }).encode("utf-8")

    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    key = derive_key(password, salt, time_cost, memory_cost_kb, parallelism)

    plaintext = struct.pack(">I", len(metadata)) + metadata + original_bytes

    try:
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=MAGIC)
    finally:
        key = b"\x00" * len(key)  # best-effort clear of this reference

    header = (
        MAGIC
        + bytes([VERSION])
        + bytes([time_cost])
        + struct.pack(">I", memory_cost_kb)
        + bytes([parallelism])
        + salt
        + nonce
    )

    with open(output_path, "wb") as f:
        f.write(header)
        f.write(ciphertext)


def _parse_header(data: bytes):
    if len(data) < HEADER_SIZE:
        raise DecryptionError("File is too small to be a valid .fear file.")
    if data[:4] != MAGIC:
        raise DecryptionError("This doesn't look like a .fear file.")
    version = data[4]
    time_cost = data[5]
    memory_cost_kb = struct.unpack(">I", data[6:10])[0]
    parallelism = data[10]
    salt = data[11:11 + SALT_SIZE]
    nonce = data[11 + SALT_SIZE:11 + SALT_SIZE + NONCE_SIZE]
    ciphertext = data[HEADER_SIZE:]
    return version, time_cost, memory_cost_kb, parallelism, salt, nonce, ciphertext


def decrypt_bytes(data: bytes, password: str):
    """Decrypt raw .fear file bytes. Returns (metadata_dict, original_bytes)."""
    version, time_cost, memory_cost_kb, parallelism, salt, nonce, ciphertext = _parse_header(data)

    key = derive_key(password, salt, time_cost, memory_cost_kb, parallelism)
    try:
        aesgcm = AESGCM(key)
        try:
            plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=MAGIC)
        except InvalidTag:
            raise DecryptionError("Incorrect password, or the file is corrupted/tampered with.")
    finally:
        key = b"\x00" * len(key)

    meta_len = struct.unpack(">I", plaintext[:4])[0]
    metadata = json.loads(plaintext[4:4 + meta_len].decode("utf-8"))
    original_bytes = plaintext[4 + meta_len:]
    return metadata, original_bytes


def decrypt_file(input_path: str, output_path: str, password: str) -> dict:
    """Decrypt a .fear file to output_path. Returns the stored metadata dict."""
    with open(input_path, "rb") as f:
        data = f.read()
    metadata, original_bytes = decrypt_bytes(data, password)
    with open(output_path, "wb") as f:
        f.write(original_bytes)
    return metadata
