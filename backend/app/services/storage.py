import io
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from app.core.config import get_settings

settings = get_settings()


class MinIOService:
    def __init__(self):
        # 惰性导入 minio：未安装该依赖时也能 import app（便于测试/仅用其它功能）
        from minio import Minio

        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.bucket = settings.MINIO_BUCKET

    def ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def upload_file(
        self,
        file_data: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        self.ensure_bucket()
        safe_filename = Path(filename).name.strip() or "file"
        object_name = f"{uuid.uuid4()}/{safe_filename}"
        self.client.put_object(
            self.bucket,
            object_name,
            io.BytesIO(file_data),
            length=len(file_data),
            content_type=content_type,
        )
        return f"http://{settings.MINIO_ENDPOINT}/{self.bucket}/{object_name}"

    def get_presigned_url(self, object_path: str, expires_hours: int = 1) -> str:
        object_name = object_path.split(f"/{self.bucket}/")[-1]
        return self.client.presigned_get_object(
            self.bucket, object_name, expires=timedelta(hours=expires_hours)
        )

    def get_browser_url(self, object_path: str, expires_hours: int = 1) -> str:
        """Return a same-origin, signed URL without exposing the internal MinIO host."""
        parsed = urlsplit(object_path)
        bucket_prefix = f"/{self.bucket}/"
        if not parsed.path.startswith(bucket_prefix):
            return object_path

        signed = urlsplit(
            self.get_presigned_url(object_path, expires_hours=expires_hours)
        )
        return urlunsplit(("", "", f"/storage{signed.path}", signed.query, ""))
