"""STT Provider 工厂"""

from b2t.config import AppConfig
from b2t.storage.base import StorageBackend
from b2t.stt.base import STTProvider
from b2t.stt.groq_asr import GroqSTTProvider
from b2t.stt.qwen_asr import QwenSTTProvider


def create_stt_provider(
    config: AppConfig,
    storage_backend: StorageBackend,
) -> STTProvider:
    provider = config.stt.provider.strip().lower()

    if provider == "qwen":
        if not storage_backend.supports_public_url():
            raise ValueError(
                "qwen 转录要求用于上传音频的存储支持公网 URL。"
                "请将当前 stt.profile 对应的 storage_profile（或 storage.backend）设置为 minio 或 alicloud。"
            )
        return QwenSTTProvider(config.stt, storage_backend)
    if provider == "groq":
        return GroqSTTProvider(config.stt)

    raise ValueError(f"不支持的 stt.provider: {config.stt.provider}，可选值: qwen, groq")


__all__ = ["STTProvider", "create_stt_provider"]
