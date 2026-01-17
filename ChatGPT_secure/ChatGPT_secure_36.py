import hashlib
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key


# =========================
# CONFIGURATION
# =========================

TRUSTED_HOSTS = {"updates.example.com"}
DOWNLOAD_TIMEOUT_SECONDS = 20
MAX_ARCHIVE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB

# Публичный ключ для проверки подписи (PEM)
PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAvrHq1Q7b5c0GkJq1p4Xc
b9f9nGQvZ1k0k4f3mKp0cQ3s3h8xk8ZkQb1d+4g5bQ3z3n9Qk2q0mK9mQYpY7b0p
3Yz9m4fQm1r7d+f8w7Xc6YJbqY8mXnQbq8V6v5f0b9y0r1yZb4m3r9Q6z5Qy5kQx
y9H5u2pZ5m5p5m5m5m5m5m5m5m5m5m5m5m5m5m5m5m5m5m5m5m5m5m5m5m5m5m5
-----END PUBLIC KEY-----"""

# =========================
# DATA MODELS
# =========================

@dataclass(frozen=True)
class UpdateArtifact:
    url: str
    sha256: str
    signature: bytes  # подпись контрольной суммы


# =========================
# SECURITY UTILITIES
# =========================

def ensure_trusted_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in TRUSTED_HOSTS:
        raise ValueError("Недоверенный источник обновления")


def sha256_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_signature(sha256_hex: str, signature: bytes) -> None:
    public_key = load_pem_public_key(PUBLIC_KEY_PEM)
    public_key.verify(
        signature,
        sha256_hex.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


# =========================
# DOWNLOADER
# =========================

class SecureDownloader:
    def download(self, url: str) -> bytes:
        ensure_trusted_url(url)

        with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
            resp.raise_for_status()
            total = 0
            chunks = []

            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_ARCHIVE_SIZE_BYTES:
                    raise ValueError("Превышен допустимый размер архива")
                chunks.append(chunk)

        return b"".join(chunks)


# =========================
# ARCHIVE HANDLING
# =========================

def safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            member_path = target_dir / member.filename
            if not member_path.resolve().startswith(target_dir.resolve()):
                raise ValueError("Обнаружена попытка выхода за пределы каталога")
        zf.extractall(target_dir)


# =========================
# UPDATER
# =========================

class AutoUpdater:
    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir
        self.downloader = SecureDownloader()

    def apply_update(self, artifact: UpdateArtifact) -> None:
        archive_bytes = self.downloader.download(artifact.url)

        digest = sha256_digest(archive_bytes)
        if digest != artifact.sha256:
            raise ValueError("Контрольная сумма не совпадает")

        verify_signature(digest, artifact.signature)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            archive_path = tmp_dir / "update.zip"
            archive_path.write_bytes(archive_bytes)

            extracted_dir = tmp_dir / "extracted"
            extracted_dir.mkdir()

            safe_extract_zip(archive_path, extracted_dir)

            self._atomic_replace(extracted_dir)

    def _atomic_replace(self, new_content_dir: Path) -> None:
        backup_dir = self.workdir.with_suffix(".bak")

        if backup_dir.exists():
            shutil.rmtree(backup_dir)

        if self.workdir.exists():
            self.workdir.rename(backup_dir)

        try:
            shutil.move(str(new_content_dir), str(self.workdir))
            shutil.rmtree(backup_dir, ignore_errors=True)
        except Exception:
            if backup_dir.exists():
                backup_dir.rename(self.workdir)
            raise


# =========================
# ENTRYPOINT (EXAMPLE)
# =========================

if __name__ == "__main__":
    updater = AutoUpdater(workdir=Path("/opt/myapp"))

    artifact = UpdateArtifact(
        url="https://updates.example.com/releases/myapp-1.2.3.zip",
        sha256="expected_sha256_hex_here",
        signature=b"signature_bytes_here",
    )

    updater.apply_update(artifact)
