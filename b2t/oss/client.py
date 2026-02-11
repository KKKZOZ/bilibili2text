"""阿里云 OSS 上传/删除"""

import logging
import uuid
from contextlib import contextmanager
from pathlib import Path

import alibabacloud_oss_v2 as oss

from b2t.config import OSSConfig

logger = logging.getLogger(__name__)


class OSSManager:
    """管理 OSS 上传和清理"""

    def __init__(self, config: OSSConfig) -> None:
        cfg = oss.config.Config(
            credentials_provider=oss.credentials.StaticCredentialsProvider(
                access_key_id=config.access_key_id,
                access_key_secret=config.access_key_secret,
            ),
            region=config.region,
        )
        self._client = oss.Client(cfg)
        self._bucket = config.bucket
        self._region = config.region
        self._uploaded_keys: list[str] = []

    def upload(self, file_path: Path | str) -> str:
        """上传文件到 OSS

        Args:
            file_path: 本地文件路径

        Returns:
            上传后的公共可访问 URL
        """
        file_path = Path(file_path)
        object_key = f"temp-audio/{uuid.uuid4()}-{file_path.name}"

        logger.info("上传文件到 OSS: %s", object_key)
        result = self._client.put_object_from_file(
            oss.PutObjectRequest(
                bucket=self._bucket,
                key=object_key,
                acl="public-read",
            ),
            str(file_path),
        )
        logger.info("上传成功 - status: %s, etag: %s", result.status_code, result.etag)

        self._uploaded_keys.append(object_key)
        return f"https://{self._bucket}.oss-{self._region}.aliyuncs.com/{object_key}"

    def delete(self, object_key: str) -> None:
        """从 OSS 删除文件"""
        logger.info("删除 OSS 文件: %s", object_key)
        result = self._client.delete_object(
            oss.DeleteObjectRequest(bucket=self._bucket, key=object_key)
        )
        logger.info("删除成功 - status: %s", result.status_code)

    def cleanup(self) -> None:
        """清理所有已上传的文件"""
        for key in self._uploaded_keys:
            try:
                self.delete(key)
            except Exception as e:
                logger.warning("删除 OSS 文件失败 (%s): %s", key, e)
        self._uploaded_keys.clear()

    @contextmanager
    def temporary_upload(self, file_path: Path | str):
        """上下文管理器：上传文件，退出时自动清理

        Yields:
            上传后的公共可访问 URL
        """
        url = self.upload(file_path)
        try:
            yield url
        finally:
            self.cleanup()
