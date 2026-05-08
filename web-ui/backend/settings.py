"""Runtime settings, path-independent config loading, and feature flags."""

from dataclasses import replace
from datetime import datetime, timezone
import os
from threading import Lock

from backend import PROJECT_ROOT
from b2t.config import (
    AppConfig,
    STTConfig,
    STTProfile,
    SummarizeConfig,
    SummarizeModelProfile,
    load_config,
)

ROOT_CONFIG_PATH = PROJECT_ROOT / "config.toml"

WEB_UI_MODE_DEFAULT = "default"
WEB_UI_MODE_OPEN_PUBLIC = "open-public"
WEB_UI_MODE_ENV = "B2T_WEB_UI_MODE"
OPEN_PUBLIC_API_KEY_ENV = "B2T_OPEN_PUBLIC_API_KEY"
OPEN_PUBLIC_DEEPSEEK_API_KEY_ENV = "B2T_OPEN_PUBLIC_DEEPSEEK_API_KEY"
TRANSCRIPTION_BVID_LOCK_TIMEOUT_ENV = "B2T_TRANSCRIPTION_BVID_LOCK_TIMEOUT_SECONDS"

STAGE_KEYS = (
    "queued",
    "downloading",
    "transcribing",
    "converting",
    "summarizing",
    "postprocessing",
    "completed",
)
JOB_LOG_LIMIT = 400
TRANSCRIPTION_BVID_LOCK_TIMEOUT_SECONDS = max(
    1,
    int(os.environ.get(TRANSCRIPTION_BVID_LOCK_TIMEOUT_ENV, "600").strip() or "600"),
)

try:
    _app_config: AppConfig | None = load_config(ROOT_CONFIG_PATH)
except FileNotFoundError:
    _app_config = None

_web_ui_mode = os.environ.get(WEB_UI_MODE_ENV, WEB_UI_MODE_DEFAULT).strip().lower()
if _web_ui_mode not in {WEB_UI_MODE_DEFAULT, WEB_UI_MODE_OPEN_PUBLIC}:
    _web_ui_mode = WEB_UI_MODE_DEFAULT

_public_api_key_lock = Lock()
_public_api_key = (
    os.environ.get(OPEN_PUBLIC_API_KEY_ENV, "").strip()
    if _web_ui_mode == WEB_UI_MODE_OPEN_PUBLIC
    else ""
)

_public_deepseek_api_key_lock = Lock()
_public_deepseek_api_key = (
    os.environ.get(OPEN_PUBLIC_DEEPSEEK_API_KEY_ENV, "").strip()
    if _web_ui_mode == WEB_UI_MODE_OPEN_PUBLIC
    else ""
)


def utc_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def get_app_config() -> AppConfig:
    global _app_config
    if _app_config is None:
        _app_config = load_config(ROOT_CONFIG_PATH)
    return _app_config


def get_web_ui_mode() -> str:
    return _web_ui_mode


def is_open_public_mode() -> bool:
    return _web_ui_mode == WEB_UI_MODE_OPEN_PUBLIC


def is_upload_enabled() -> bool:
    return not is_open_public_mode()


def is_delete_enabled() -> bool:
    return not is_open_public_mode()


def requires_user_api_key() -> bool:
    return is_open_public_mode()


def get_public_api_key() -> str:
    with _public_api_key_lock:
        return _public_api_key


def set_public_api_key(api_key: str) -> None:
    global _public_api_key
    with _public_api_key_lock:
        _public_api_key = api_key.strip()


def clear_public_api_key() -> None:
    global _public_api_key
    with _public_api_key_lock:
        _public_api_key = ""


def is_public_api_key_configured() -> bool:
    return bool(get_public_api_key())


def get_public_deepseek_api_key() -> str:
    with _public_deepseek_api_key_lock:
        return _public_deepseek_api_key


def set_public_deepseek_api_key(api_key: str) -> None:
    global _public_deepseek_api_key
    with _public_deepseek_api_key_lock:
        _public_deepseek_api_key = api_key.strip()


def clear_public_deepseek_api_key() -> None:
    global _public_deepseek_api_key
    with _public_deepseek_api_key_lock:
        _public_deepseek_api_key = ""


def is_public_deepseek_api_key_configured() -> bool:
    return bool(get_public_deepseek_api_key())


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}{'*' * (len(api_key) - 8)}{api_key[-4:]}"


def _pick_qwen_stt_profile(stt: STTConfig) -> STTProfile:
    selected = stt.profiles.get(stt.profile)
    if selected is not None and selected.provider.strip().lower() == "qwen":
        return selected
    for profile in stt.profiles.values():
        if profile.provider.strip().lower() == "qwen":
            return profile
    return STTProfile(
        provider="qwen",
        language=stt.language,
        storage_profile=stt.storage_profile,
        qwen_api_key=stt.qwen_api_key,
        qwen_model=stt.qwen_model,
        qwen_base_url=stt.qwen_base_url,
        groq_api_key=stt.groq_api_key,
        groq_model=stt.groq_model,
        groq_base_url=stt.groq_base_url,
        groq_chunk_length=stt.groq_chunk_length,
        groq_overlap=stt.groq_overlap,
        groq_bitrate=stt.groq_bitrate,
    )


def _pick_bailian_summary_profile(
    summarize: SummarizeConfig,
) -> SummarizeModelProfile:
    selected = summarize.profiles.get(summarize.profile)
    if selected is not None and selected.provider.strip().lower() == "bailian":
        return selected
    for profile in summarize.profiles.values():
        if profile.provider.strip().lower() == "bailian":
            return profile
    return SummarizeModelProfile(
        provider="bailian",
        model="qwen3-max",
        api_key="",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        providers=(),
    )


def _pick_deepseek_summary_profile(
    summarize: SummarizeConfig,
) -> SummarizeModelProfile:
    selected = summarize.profiles.get(summarize.profile)
    if selected is not None and selected.provider.strip().lower() == "deepseek":
        return selected
    for profile in summarize.profiles.values():
        if profile.provider.strip().lower() == "deepseek":
            return profile
    return SummarizeModelProfile(
        provider="deepseek",
        model="deepseek-chat",
        api_key="",
        api_base="https://api.deepseek.com",
        providers=(),
    )


def build_open_public_config(
    config: AppConfig,
    api_key: str,
    deepseek_api_key: str = "",
) -> AppConfig:
    base_stt_profile = _pick_qwen_stt_profile(config.stt)
    public_stt_profile = replace(
        base_stt_profile,
        provider="qwen",
        qwen_api_key=api_key,
        groq_api_key="",
    )
    public_stt_config = STTConfig(
        profile="open_public_qwen",
        profiles={"open_public_qwen": public_stt_profile},
        provider="qwen",
        language=public_stt_profile.language,
        storage_profile=public_stt_profile.storage_profile,
        qwen_api_key=api_key,
        qwen_model=public_stt_profile.qwen_model,
        qwen_base_url=public_stt_profile.qwen_base_url,
        groq_api_key="",
        groq_model=public_stt_profile.groq_model,
        groq_base_url=public_stt_profile.groq_base_url,
        groq_chunk_length=public_stt_profile.groq_chunk_length,
        groq_overlap=public_stt_profile.groq_overlap,
        groq_bitrate=public_stt_profile.groq_bitrate,
    )

    # Build summarize profiles by injecting user API keys into the
    # admin-configured profiles.  All of the admin's profiles are
    # preserved so they appear in the frontend model dropdown.
    use_deepseek = bool(deepseek_api_key)
    public_summarize_profiles: dict[str, SummarizeModelProfile] = {}
    selected_profile = ""
    bailian_fallback_profile = ""
    deepseek_profile_name = ""

    for name, profile in config.summarize.profiles.items():
        provider = profile.provider.strip().lower()
        if provider == "deepseek":
            deepseek_profile_name = name
            public_summarize_profiles[name] = replace(
                profile, api_key=deepseek_api_key if use_deepseek else ""
            )
        elif provider == "bailian":
            public_summarize_profiles[name] = replace(profile, api_key=api_key)
            if not bailian_fallback_profile:
                bailian_fallback_profile = name
        else:
            public_summarize_profiles[name] = profile

    if use_deepseek and deepseek_profile_name:
        selected_profile = deepseek_profile_name
    elif bailian_fallback_profile:
        selected_profile = bailian_fallback_profile
    elif config.summarize.profiles:
        selected_profile = next(iter(config.summarize.profiles))
    fancy_html_profile = selected_profile

    public_summarize_config = SummarizeConfig(
        profile=selected_profile,
        profiles=public_summarize_profiles,
        enable_thinking=config.summarize.enable_thinking,
        preset=config.summarize.preset,
        presets_file=config.summarize.presets_file,
        context_file=config.summarize.context_file,
    )

    # RAG: embedding always uses Aliyun (bailian).  LLM queries follow
    # the DeepSeek profile when available.
    rag_llm_profile = deepseek_profile_name if use_deepseek else ""
    public_rag = config.rag
    if api_key:
        public_rag_embedding = config.rag.embedding
        if config.rag.embedding.provider.strip().lower() == "bailian":
            public_rag_embedding = replace(config.rag.embedding, api_key=api_key)
        public_rag = replace(
            config.rag,
            embedding=public_rag_embedding,
            llm_profile=rag_llm_profile,
        )

    return replace(
        config,
        stt=public_stt_config,
        summarize=public_summarize_config,
        fancy_html=replace(config.fancy_html, profile=fancy_html_profile),
        rag=public_rag,
    )


def get_runtime_app_config(
    *,
    require_public_api_key: bool = False,
    api_key: str | None = None,
    deepseek_api_key: str | None = None,
) -> AppConfig:
    config = get_app_config()
    if not is_open_public_mode():
        return config

    resolved_key = (api_key or "").strip() or get_public_api_key()
    if require_public_api_key and not resolved_key:
        raise ValueError(
            "open-public 模式下请先在「API Key」页面配置阿里云 DashScope API Key"
        )
    resolved_ds_key = (deepseek_api_key or "").strip() or get_public_deepseek_api_key()
    return build_open_public_config(config, resolved_key, resolved_ds_key)


def get_runtime_features() -> dict[str, str | bool]:
    config = get_app_config()
    return {
        "mode": get_web_ui_mode(),
        "allow_upload_audio": is_upload_enabled(),
        "allow_delete": is_delete_enabled(),
        "requires_user_api_key": requires_user_api_key(),
        "api_key_configured": is_public_api_key_configured(),
        "deepseek_api_key_configured": is_public_deepseek_api_key_configured(),
        "counterscale_site_id": config.analytics.counterscale.site_id,
        "counterscale_tracker_url": config.analytics.counterscale.tracker_url,
    }
