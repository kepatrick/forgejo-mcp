import base64
import uuid
from pathlib import Path

import pytest

from forgejo_mcp.credentials import CredentialCipher, CredentialKeyError


def test_credential_round_trip() -> None:
    user_id = uuid.uuid4()
    cipher = CredentialCipher(b"k" * 32, key_version=1)

    encrypted = cipher.encrypt("forgejo-secret-token", user_id)

    assert b"forgejo-secret-token" not in encrypted.ciphertext
    assert (
        cipher.decrypt(
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
            user_id=user_id,
            key_version=encrypted.key_version,
        )
        == "forgejo-secret-token"
    )


def test_cipher_binds_credential_to_user() -> None:
    cipher = CredentialCipher(b"k" * 32, key_version=1)
    encrypted = cipher.encrypt("forgejo-secret-token", uuid.uuid4())

    with pytest.raises(CredentialKeyError, match="authentication failed"):
        cipher.decrypt(
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
            user_id=uuid.uuid4(),
            key_version=1,
        )


def test_cipher_rejects_tampering() -> None:
    user_id = uuid.uuid4()
    cipher = CredentialCipher(b"k" * 32, key_version=1)
    encrypted = cipher.encrypt("forgejo-secret-token", user_id)
    tampered = bytearray(encrypted.ciphertext)
    tampered[0] ^= 1

    with pytest.raises(CredentialKeyError, match="authentication failed"):
        cipher.decrypt(
            ciphertext=bytes(tampered),
            nonce=encrypted.nonce,
            user_id=user_id,
            key_version=1,
        )


def test_load_base64_key_file(tmp_path: Path) -> None:
    path = tmp_path / "credential_key"
    path.write_bytes(base64.b64encode(b"x" * 32))

    cipher = CredentialCipher.from_file(path, key_version=3)

    assert cipher.key_version == 3


def test_reject_invalid_key_length() -> None:
    with pytest.raises(CredentialKeyError, match="32 bytes"):
        CredentialCipher(b"short", key_version=1)
