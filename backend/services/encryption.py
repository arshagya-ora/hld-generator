"""
File Encryption Service
AES-256 encryption for uploaded documents
"""
from cryptography.fernet import Fernet
from pathlib import Path
import aiofiles
import base64
from typing import Union

import logging

from config import settings

logger = logging.getLogger(__name__)


class EncryptionService:
    """
    File encryption service using Fernet (AES-256)
    """

    def __init__(self):
        """Initialize encryption service with key from settings"""
        try:
            self.cipher = Fernet(settings.ENCRYPTION_KEY.encode())
        except (ValueError, Exception) as e:
            raise RuntimeError(
                "ENCRYPTION_KEY is invalid. Files encrypted with a temporary key "
                "become permanently unreadable after restart. "
                "Generate a proper key: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
                f"Original error: {e}"
            )

    async def encrypt_file(self, input_path: Union[str, Path], output_path: Union[str, Path]) -> None:
        """
        Encrypt a file and save to output path

        Args:
            input_path: Path to plaintext file
            output_path: Path to save encrypted file

        Example:
            await encryption_service.encrypt_file("document.docx", "document.docx.enc")
        """
        input_path = Path(input_path)
        output_path = Path(output_path)

        # Read plaintext file
        async with aiofiles.open(input_path, "rb") as f:
            plaintext = await f.read()

        # Encrypt
        ciphertext = self.cipher.encrypt(plaintext)

        # Write encrypted file
        async with aiofiles.open(output_path, "wb") as f:
            await f.write(ciphertext)

    @staticmethod
    def _is_fernet_token(data: bytes) -> bool:
        """Check if bytes look like a valid Fernet token (starts with 0x80 after base64 decode)."""
        try:
            decoded = base64.urlsafe_b64decode(data + b'==')
            return len(decoded) >= 9 and decoded[0] == 0x80
        except Exception:
            return False

    async def decrypt_file(self, input_path: Union[str, Path], output_path: Union[str, Path]) -> None:
        """
        Decrypt a file and save to output path.
        If the file is not a valid Fernet token (e.g. was stored unencrypted
        during a period when encryption was misconfigured), it is passed through
        as-is with a warning.

        Args:
            input_path: Path to encrypted file
            output_path: Path to save decrypted file
        """
        input_path = Path(input_path)
        output_path = Path(output_path)

        # Read file
        async with aiofiles.open(input_path, "rb") as f:
            ciphertext = await f.read()

        # Graceful fallback: if the file is not a Fernet token, treat as plaintext
        if not self._is_fernet_token(ciphertext):
            logger.warning(
                f"File '{input_path.name}' does not appear to be encrypted "
                f"(not a valid Fernet token). Treating as plaintext - "
                f"it was likely uploaded before encryption was properly configured."
            )
            plaintext = ciphertext
        else:
            plaintext = self.cipher.decrypt(ciphertext)

        # Write output file
        async with aiofiles.open(output_path, "wb") as f:
            await f.write(plaintext)

    async def encrypt_bytes(self, data: bytes) -> bytes:
        """
        Encrypt bytes directly

        Args:
            data: Plaintext bytes

        Returns:
            Encrypted bytes
        """
        return self.cipher.encrypt(data)

    async def decrypt_bytes(self, data: bytes) -> bytes:
        """
        Decrypt bytes directly

        Args:
            data: Encrypted bytes

        Returns:
            Plaintext bytes
        """
        return self.cipher.decrypt(data)

    async def get_decrypted_file_path(self, encrypted_path: Union[str, Path]) -> Path:
        """
        Decrypt file to temporary location and return path

        Args:
            encrypted_path: Path to encrypted file

        Returns:
            Path to temporary decrypted file

        Note:
            Caller is responsible for deleting the temporary file
        """
        import os
        import tempfile

        encrypted_path = Path(encrypted_path)

        # Create temporary file
        temp_fd, temp_path = tempfile.mkstemp(suffix=encrypted_path.suffix)
        # CRITICAL: close the file descriptor immediately to avoid FD leak.
        # decrypt_file() opens the path independently via aiofiles.
        os.close(temp_fd)
        temp_path = Path(temp_path)

        # Decrypt to temporary file
        await self.decrypt_file(encrypted_path, temp_path)

        return temp_path


# Singleton instance
encryption_service = EncryptionService()


def generate_encryption_key() -> str:
    """
    Generate a new Fernet encryption key

    Returns:
        Base64-encoded 32-byte key

    Usage:
        key = generate_encryption_key()
        print(f"ENCRYPTION_KEY={key}")
        # Add to .env file
    """
    key = Fernet.generate_key()
    return key.decode()


if __name__ == "__main__":
    # Generate a new encryption key
    print("Generated encryption key:")
    print(generate_encryption_key())
    print("\nAdd this to your .env file as ENCRYPTION_KEY")
