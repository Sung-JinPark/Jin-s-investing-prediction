"""Content-addressed local and S3-compatible raw object stores."""

from __future__ import annotations

import gzip
import hashlib
import io
from pathlib import Path
from typing import Any


class LocalObjectStore:
    def __init__(self, root: Path): self.root = Path(root)

    def put_raw(self, source_id: str, body: bytes, *, content_type: str, metadata: dict[str, str]) -> dict[str, Any]:
        digest = hashlib.sha256(body).hexdigest(); relative = Path("raw") / source_id / digest[:2] / f"{digest}.gz"; target = self.root / relative
        if target.is_file():
            with gzip.open(target, "rb") as handle:
                if hashlib.sha256(handle.read()).hexdigest() != digest: raise ValueError("content-addressed raw object is corrupt")
        else:
            target.parent.mkdir(parents=True, exist_ok=True); temporary = target.with_suffix(".tmp")
            stream = temporary.open("wb")
            try:
                with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as handle: handle.write(body)
            finally: stream.close()
            temporary.replace(target)
        return {"sha256": digest, "uri": relative.as_posix(), "size_bytes": len(body), "content_type": content_type, "compression": "gzip", "metadata": dict(metadata)}

    def get(self, uri: str) -> bytes:
        path = (self.root / uri).resolve()
        if self.root.resolve() not in path.parents: raise ValueError("object URI escapes store")
        with gzip.open(path, "rb") as handle: return handle.read()


class S3ObjectStore:
    """R2/S3 adapter. SDK import and credentials stay outside Codex workers."""
    def __init__(self, *, bucket: str, endpoint_url: str, region: str = "auto", access_key_id: str | None = None, secret_access_key: str | None = None, quota_bytes: int | None = None, hold_fraction: float = 0.80):
        try: import boto3  # type: ignore
        except ImportError as exc: raise RuntimeError("install ai-fc[timeseries-v5] for S3/R2 storage") from exc
        self.bucket = bucket; self.quota_bytes = quota_bytes; self.hold_fraction = hold_fraction; self.client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region, aws_access_key_id=access_key_id, aws_secret_access_key=secret_access_key)

    def used_bytes(self) -> int:
        total = 0; token = None
        while True:
            args = {"Bucket": self.bucket, "Prefix": "raw/"}
            if token: args["ContinuationToken"] = token
            response = self.client.list_objects_v2(**args); total += sum(int(row.get("Size", 0)) for row in response.get("Contents", []))
            if not response.get("IsTruncated"): return total
            token = response.get("NextContinuationToken")

    def put_raw(self, source_id: str, body: bytes, *, content_type: str, metadata: dict[str, str]) -> dict[str, Any]:
        if self.quota_bytes is not None and self.used_bytes() + len(body) >= int(self.quota_bytes * self.hold_fraction): raise RuntimeError("V5 private object store reached the registered 80% HOLD threshold")
        digest = hashlib.sha256(body).hexdigest(); key = f"raw/{source_id}/{digest[:2]}/{digest}.gz"; compressed = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0) as handle: handle.write(body)
        self.client.put_object(Bucket=self.bucket, Key=key, Body=compressed.getvalue(), ContentType="application/gzip", Metadata={**metadata, "sha256": digest, "source_content_type": content_type})
        return {"sha256": digest, "uri": f"s3://{self.bucket}/{key}", "size_bytes": len(body), "content_type": content_type, "compression": "gzip", "metadata": metadata}

    def get(self, uri: str) -> bytes:
        prefix = f"s3://{self.bucket}/"
        if not uri.startswith(prefix): raise ValueError("object URI bucket mismatch")
        response = self.client.get_object(Bucket=self.bucket, Key=uri[len(prefix):]); return gzip.decompress(response["Body"].read())
