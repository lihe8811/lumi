"""
Storage abstraction for Tencent COS (S3-compatible) and in-memory testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
import json

import boto3
from botocore.config import Config


class StorageClient(Protocol):
    """Defines the operations the API needs from object storage."""

    def presign_get(self, path: str, expires_in: int = 3600) -> str:
        ...

    def presign_put(self, path: str, expires_in: int = 3600) -> str:
        ...

    def upload_json(self, path: str, payload: dict) -> None:
        ...

    def upload_file(self, src_path: str, dest_path: str) -> None:
        ...

    def get_bytes(self, path: str) -> bytes:
        ...


@dataclass
class InMemoryStorageClient:
    """Test double for storage interactions."""

    base_url: str = "https://example.test/storage"
    stored_objects: dict = None

    def __post_init__(self):
        if self.stored_objects is None:
            self.stored_objects = {}

    def presign_get(self, path: str, expires_in: int = 3600) -> str:
        return f"{self.base_url}/{path}?op=get&expires={expires_in}"

    def presign_put(self, path: str, expires_in: int = 3600) -> str:
        return f"{self.base_url}/{path}?op=put&expires={expires_in}"

    def upload_json(self, path: str, payload: dict) -> None:
        # Use JSON string to mimic real upload behavior
        self.stored_objects[path] = json.loads(json.dumps(payload, default=str))

    def upload_file(self, src_path: str, dest_path: str) -> None:
        with open(src_path, "rb") as f:
            self.stored_objects[dest_path] = f.read()

    def get_bytes(self, path: str) -> bytes:
        stored = self.stored_objects.get(path)
        if stored is None:
            raise FileNotFoundError(path)
        if isinstance(stored, bytes):
            return stored
        return json.dumps(stored, default=str).encode("utf-8")


@dataclass
class CosStorageClient:
    """
    S3-compatible storage client for Tencent COS.
    """

    bucket: str
    region: str
    endpoint: str
    access_key_id: str
    secret_access_key: str

    def __post_init__(self):
        # Use virtual-hosted style addressing to satisfy COS requirements.
        config = Config(
            s3={"addressing_style": "virtual"},
            signature_version="s3v4",
        )
        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            region_name=self.region,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            config=config,
        )

    def presign_get(self, path: str, expires_in: int = 3600) -> str:
        return self._client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self.bucket, "Key": path},
            ExpiresIn=expires_in,
        )

    def presign_put(self, path: str, expires_in: int = 3600) -> str:
        # We include a dummy content type so uploads work in browsers by default.
        return self._client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": self.bucket,
                "Key": path,
                "ContentType": "application/octet-stream",
            },
            ExpiresIn=expires_in,
        )

    def upload_json(self, path: str, payload: dict) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self._client.put_object(
            Bucket=self.bucket,
            Key=path,
            Body=body,
            ContentType="application/json",
        )

    def upload_file(self, src_path: str, dest_path: str) -> None:
        self._client.upload_file(src_path, self.bucket, dest_path)

    def get_bytes(self, path: str) -> bytes:
        response = self._client.get_object(Bucket=self.bucket, Key=path)
        return response["Body"].read()
