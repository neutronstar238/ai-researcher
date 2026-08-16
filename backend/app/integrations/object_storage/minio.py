"""MinIO object-storage client (spec §9.7/§19.4).

Objects are never public; download uses short-lived presigned URLs. Object keys
are server-generated. The server re-computes SHA-256 on upload completion.
"""

from __future__ import annotations

import contextlib
import hashlib

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings


class MinioStorage:
    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.minio_bucket_assets
        self.client = boto3.client(
            "s3",
            endpoint_url=f"{'https' if settings.minio_secure else 'http'}://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            region_name="us-east-1",
            config=Config(signature_version="s3v4"),
        )

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def presign_put(self, key: str, content_type: str | None = None, expires: int = 600) -> str:
        # 不强制签名 content-type，避免客户端实际 Content-Type 与签名不一致导致 403。
        params = {"Bucket": self.bucket, "Key": key}
        return self.client.generate_presigned_url("put_object", Params=params, ExpiresIn=expires)

    # -- multipart（spec §9.7 分片上传） ---------------------------------

    def create_multipart_upload(self, key: str) -> str:
        response = self.client.create_multipart_upload(Bucket=self.bucket, Key=key)
        return response["UploadId"]

    def presign_upload_part(self, key: str, upload_id: str, part_number: int, expires: int = 600) -> str:
        return self.client.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=expires,
        )

    def complete_multipart_upload(self, key: str, upload_id: str, parts: list[dict]) -> None:
        self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={
                "Parts": [
                    {"PartNumber": int(p["part_number"]), "ETag": p["etag"]} for p in parts
                ]
            },
        )

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        with contextlib.suppress(ClientError):
            self.client.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id)

    def presign_get(self, key: str, expires: int = 300) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires
        )

    def object_exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def sha256_and_size(self, key: str) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        for chunk in iter(lambda: body.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
        return digest.hexdigest(), size

    def read_head(self, key: str, n: int = 16) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key, Range=f"bytes=0-{n - 1}")
        return response["Body"].read(n)

    def download_to_file(self, key: str, dest_path: str) -> None:
        self.client.download_file(Bucket=self.bucket, Key=key, Filename=dest_path)

    def put_text(self, key: str, content: str, content_type: str = "text/plain") -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=content.encode("utf-8"), ContentType=content_type
        )

    def put_bytes(self, key: str, content: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=content, ContentType=content_type
        )
