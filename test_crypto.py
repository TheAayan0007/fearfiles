"""
Quick correctness tests for crypto_core.py.
Run this after installing dependencies to confirm everything works on your
machine before relying on the GUI:

    python test_crypto.py
"""

import os
import time
import crypto_core

PW = "CorrectHorseBatteryStaple123!"
WRONG_PW = "totally-wrong-password"


def test_roundtrip():
    with open("_t_sample.txt", "wb") as f:
        f.write(b"Hello, this is a secret test file! 1234567890 " * 200)

    t0 = time.time()
    crypto_core.encrypt_file("_t_sample.txt", "_t_sample.txt.fear", PW)
    t1 = time.time()
    print(f"[ok] encrypted in {t1 - t0:.2f}s, size = {os.path.getsize('_t_sample.txt.fear')} bytes")

    t0 = time.time()
    metadata = crypto_core.decrypt_file("_t_sample.txt.fear", "_t_sample_out.txt", PW)
    t1 = time.time()
    print(f"[ok] decrypted in {t1 - t0:.2f}s, metadata = {metadata}")

    with open("_t_sample.txt", "rb") as f1, open("_t_sample_out.txt", "rb") as f2:
        assert f1.read() == f2.read(), "content mismatch after roundtrip!"
    print("[ok] decrypted content matches original exactly")


def test_wrong_password_rejected():
    try:
        crypto_core.decrypt_file("_t_sample.txt.fear", "_t_should_not_exist.txt", WRONG_PW)
        print("[FAIL] wrong password did not raise an error!")
    except crypto_core.DecryptionError:
        print("[ok] wrong password correctly rejected")


def test_tamper_detected():
    with open("_t_sample.txt.fear", "rb") as f:
        data = bytearray(f.read())
    data[-1] ^= 0xFF  # flip bits in the last byte of the auth tag
    with open("_t_tampered.fear", "wb") as f:
        f.write(bytes(data))
    try:
        crypto_core.decrypt_file("_t_tampered.fear", "_t_should_not_exist2.txt", PW)
        print("[FAIL] tampered file did not raise an error!")
    except crypto_core.DecryptionError:
        print("[ok] tampering correctly detected (GCM auth tag check)")


def test_bad_file_rejected():
    with open("_t_not_a_fear_file.txt", "wb") as f:
        f.write(b"just some random bytes, not a real .fear file")
    try:
        crypto_core.decrypt_file("_t_not_a_fear_file.txt", "_t_x.txt", PW)
        print("[FAIL] garbage file did not raise an error!")
    except crypto_core.DecryptionError:
        print("[ok] non-.fear file correctly rejected")


def cleanup():
    for name in ["_t_sample.txt", "_t_sample.txt.fear", "_t_sample_out.txt",
                 "_t_tampered.fear", "_t_not_a_fear_file.txt"]:
        if os.path.exists(name):
            os.remove(name)


if __name__ == "__main__":
    try:
        test_roundtrip()
        test_wrong_password_rejected()
        test_tamper_detected()
        test_bad_file_rejected()
        print("\nAll tests completed.")
    finally:
        cleanup()
