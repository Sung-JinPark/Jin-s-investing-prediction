"""Secret-by-reference managed storage settings and free-tier quota guard."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ManagedStorageConfig:
    database_url: str
    bucket: str
    endpoint_url: str
    access_key_id: str
    secret_access_key: str
    quota_bytes: int
    hold_fraction: float = 0.80

    @classmethod
    def from_environment(cls) -> "ManagedStorageConfig":
        names = ("TSV5_DATABASE_URL", "TSV5_S3_BUCKET", "TSV5_S3_ENDPOINT", "TSV5_S3_ACCESS_KEY_ID", "TSV5_S3_SECRET_ACCESS_KEY", "TSV5_S3_QUOTA_BYTES")
        missing = [name for name in names if not os.environ.get(name)]
        if missing: raise RuntimeError(f"V5 managed storage secrets are not configured: {missing}")
        return cls(os.environ[names[0]], os.environ[names[1]], os.environ[names[2]], os.environ[names[3]], os.environ[names[4]], int(os.environ[names[5]]))

    def public_summary(self) -> dict[str, object]:
        return {"backend": "Neon PostgreSQL + Cloudflare R2 compatible", "bucket_configured": bool(self.bucket), "endpoint_configured": bool(self.endpoint_url), "quota_bytes": self.quota_bytes, "hold_fraction": self.hold_fraction}

    def assert_capacity(self, used_bytes: int, incoming_bytes: int = 0) -> None:
        if used_bytes + incoming_bytes >= int(self.quota_bytes * self.hold_fraction):
            raise RuntimeError("V5 private object store reached the registered 80% HOLD threshold")
