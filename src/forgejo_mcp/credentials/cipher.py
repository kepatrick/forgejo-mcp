import base64
import binascii
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12
KEY_BYTES = 32


class CredentialKeyError(Exception):
    pass


@dataclass(frozen=True)
class EncryptedCredential:
    ciphertext: bytes
    nonce: bytes
    key_version: int


class CredentialCipher:
    def __init__(self, key: bytes, key_version: int) -> None:
        if len(key) != KEY_BYTES:
            raise CredentialKeyError("credential encryption key must contain 32 bytes")
        self.aesgcm = AESGCM(key)
        self.key_version = key_version

    @classmethod
    def from_file(cls, path: Path, key_version: int) -> "CredentialCipher":
        try:
            encoded = path.read_bytes().strip()
        except OSError as error:
            raise CredentialKeyError("unable to read credential encryption key") from error
        try:
            key = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise CredentialKeyError("credential encryption key must be valid base64") from error
        return cls(key, key_version)

    @staticmethod
    def associated_data(user_id: uuid.UUID, key_version: int) -> bytes:
        return f"forgejo-credential:{user_id}:v{key_version}".encode()

    def encrypt(self, token: str, user_id: uuid.UUID) -> EncryptedCredential:
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = self.aesgcm.encrypt(
            nonce,
            token.encode("utf-8"),
            self.associated_data(user_id, self.key_version),
        )
        return EncryptedCredential(ciphertext, nonce, self.key_version)

    def decrypt(
        self,
        *,
        ciphertext: bytes,
        nonce: bytes,
        user_id: uuid.UUID,
        key_version: int,
    ) -> str:
        if key_version != self.key_version:
            raise CredentialKeyError("credential encryption key version is unavailable")
        try:
            plaintext = self.aesgcm.decrypt(
                nonce,
                ciphertext,
                self.associated_data(user_id, key_version),
            )
        except InvalidTag as error:
            raise CredentialKeyError("credential authentication failed") from error
        return plaintext.decode("utf-8")
