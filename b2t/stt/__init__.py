"""STT Provider factory"""

from b2t.config import AppConfig
from b2t.storage.base import StorageBackend
from b2t.stt.base import STTProvider
from b2t.stt.groq_asr import GroqSTTProvider
from b2t.stt.qwen_asr import QwenSTTProvider
from b2t.stt.volc_asr import VolcSTTProvider


def create_stt_provider(
    config: AppConfig,
    storage_backend: StorageBackend,
) -> STTProvider:
    stt_profile = config.stt.selected_profile
    provider = stt_profile.provider.strip().lower()

    if provider == "qwen":
        if not storage_backend.supports_public_url():
            raise ValueError(
                "Qwen transcription requires a storage backend that supports public URLs for audio upload. "
                "Please set the storage_profile for the current stt.profile (or storage.backend) to minio or alicloud."
            )
        return QwenSTTProvider(stt_profile, storage_backend)
    if provider == "groq":
        return GroqSTTProvider(stt_profile)
    if provider == "volc":
        if not storage_backend.supports_public_url():
            raise ValueError(
                "Volc transcription requires a storage backend that supports public URLs for audio upload. "
                "Please set the storage_profile for the current stt.profile (or storage.backend) to minio or alicloud."
            )
        return VolcSTTProvider(stt_profile, storage_backend)

    raise ValueError(
        f"Unsupported stt.provider: {config.stt.provider}, supported values: qwen, groq, volc"
    )


__all__ = ["STTProvider", "create_stt_provider"]
