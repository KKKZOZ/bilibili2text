"""STT Provider 工厂"""

from b2t.config import AppConfig
from b2t.stt.base import STTProvider
from b2t.stt.groq_asr import GroqSTTProvider
from b2t.stt.qwen_asr import QwenSTTProvider


def create_stt_provider(config: AppConfig) -> STTProvider:
    provider = config.stt.provider.strip().lower()

    if provider == "qwen":
        return QwenSTTProvider(config.stt, config.oss)
    if provider == "groq":
        return GroqSTTProvider(config.stt)

    raise ValueError(f"不支持的 stt.provider: {config.stt.provider}，可选值: qwen, groq")


__all__ = ["STTProvider", "create_stt_provider"]
