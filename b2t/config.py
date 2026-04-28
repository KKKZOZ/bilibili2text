"""TOML 配置加载模块"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SUMMARY_PRESETS_FILE = "summary_presets.toml"
DEFAULT_STT_PROFILE = "qwen"
DEFAULT_BILIBILI_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_SUPPORTED_SUMMARIZE_PROVIDERS = ("bailian", "openrouter", "groq")
_SUMMARIZE_PROVIDER_DEFAULT_API_BASE: dict[str, str] = {
    "bailian": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
}


@dataclass(frozen=True)
class DownloadConfig:
    audio_quality: str = "30216"
    output_dir: str = "./transcriptions"
    db_dir: str = "./db_data"


@dataclass(frozen=True)
class MinIOStorageConfig:
    endpoint: str = "127.0.0.1:9000"
    bucket: str = ""
    access_key: str = ""
    secret_key: str = ""
    secure: bool = False
    region: str = ""
    base_prefix: str = "b2t"
    auto_create_bucket: bool = True
    temporary_url_expire_seconds: int = 7200


@dataclass(frozen=True)
class AlicloudStorageConfig:
    region: str = ""
    bucket: str = ""
    access_key_id: str = ""
    access_key_secret: str = ""
    base_prefix: str = "b2t"
    temporary_prefix: str = "temp-audio"
    public_base_url: str = ""
    auto_create_bucket: bool = False


@dataclass(frozen=True)
class StorageConfig:
    backend: str = "local"
    minio: MinIOStorageConfig = field(default_factory=MinIOStorageConfig)
    alicloud: AlicloudStorageConfig = field(default_factory=AlicloudStorageConfig)


@dataclass(frozen=True)
class STTProfile:
    provider: str = "qwen"
    language: str = "zh"
    storage_profile: str = ""

    qwen_api_key: str = ""
    qwen_model: str = "qwen3-asr-flash-filetrans"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/api/v1"

    groq_api_key: str = ""
    groq_model: str = "whisper-large-v3-turbo"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_chunk_length: int = 1800
    groq_overlap: int = 10
    groq_bitrate: str = "64k"


def _default_stt_profiles() -> dict[str, "STTProfile"]:
    return {
        "qwen": STTProfile(
            provider="qwen",
            language="zh",
            storage_profile="",
            qwen_api_key="",
            qwen_model="qwen3-asr-flash-filetrans",
            qwen_base_url="https://dashscope.aliyuncs.com/api/v1",
        ),
        "groq": STTProfile(
            provider="groq",
            language="zh",
            storage_profile="",
            groq_api_key="",
            groq_model="whisper-large-v3-turbo",
            groq_base_url="https://api.groq.com/openai/v1",
            groq_chunk_length=1800,
            groq_overlap=10,
            groq_bitrate="64k",
        ),
    }


@dataclass(frozen=True)
class STTConfig:
    profile: str = DEFAULT_STT_PROFILE
    profiles: dict[str, STTProfile] = field(default_factory=_default_stt_profiles)
    provider: str = "qwen"
    language: str = "zh"
    storage_profile: str = ""

    qwen_api_key: str = ""
    qwen_model: str = "qwen3-asr-flash-filetrans"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/api/v1"

    groq_api_key: str = ""
    groq_model: str = "whisper-large-v3-turbo"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_chunk_length: int = 1800
    groq_overlap: int = 10
    groq_bitrate: str = "64k"


@dataclass(frozen=True)
class SummarizeModelProfile:
    provider: str
    model: str
    api_key: str
    api_base: str = ""
    providers: tuple[str, ...] = ()

@dataclass(frozen=True)
class SummarizeConfig:
    profile: str = ""
    profiles: dict[str, SummarizeModelProfile] = field(default_factory=dict)
    enable_thinking: bool = True
    preset: str | None = None
    presets_file: str = DEFAULT_SUMMARY_PRESETS_FILE


@dataclass(frozen=True)
class FancyHtmlConfig:
    profile: str = ""


@dataclass(frozen=True)
class SummaryPreset:
    prompt_template: str
    label: str


@dataclass(frozen=True)
class SummaryPresetsConfig:
    default: str
    presets: dict[str, SummaryPreset]
    source_path: Path


@dataclass(frozen=True)
class ConverterConfig:
    min_length: int = 60


@dataclass(frozen=True)
class RagEmbeddingConfig:
    provider: str = "bailian"
    model: str = "text-embedding-v3"
    api_key: str = ""
    api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass(frozen=True)
class RagConfig:
    enabled: bool = False
    collection_name: str = "b2t_rag"
    chroma_dir: str = "./chroma_data"
    chunk_size: int = 800
    chunk_overlap: int = 100
    top_k: int = 10
    embedding: RagEmbeddingConfig = field(default_factory=RagEmbeddingConfig)
    llm_profile: str = ""


@dataclass(frozen=True)
class FeishuConfig:
    mode: str = "disabled"
    webhook_url: str = ""
    app_id: str = ""
    app_secret: str = ""
    receive_id: str = ""
    receive_id_type: str = "open_id"
    title_prefix: str = "b2t"
    timeout_seconds: int = 20
    summary_max_chars: int = 8000


@dataclass(frozen=True)
class MonitorCreatorConfig:
    uid: int
    name: str = ""
    check_interval: int = 300


@dataclass(frozen=True)
class MonitorConfig:
    enabled: bool = False
    state_file: str = "./db_data/bilibili_monitor_state.json"
    user_agent: str = DEFAULT_BILIBILI_USER_AGENT
    lookback_hours: int = 48
    first_run_max_push: int = 3
    default_check_interval: int = 300
    startup_notification: bool = True
    summary_preset: str | None = None
    summary_profile: str | None = None
    output_dir: str = ""
    creators: tuple[MonitorCreatorConfig, ...] = ()


@dataclass(frozen=True)
class BilibiliConfig:
    SESSDATA: str = ""
    bili_jct: str = ""
    buvid3: str = ""
    DedeUserID: str = ""
    DedeUserID__ckMd5: str = ""
    refresh_token: str = ""


@dataclass(frozen=True)
class AppConfig:
    download: DownloadConfig
    storage: StorageConfig
    stt: STTConfig
    summarize: SummarizeConfig
    fancy_html: FancyHtmlConfig
    summary_presets: SummaryPresetsConfig
    converter: ConverterConfig
    rag: RagConfig = field(default_factory=RagConfig)
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    bilibili: BilibiliConfig = field(default_factory=BilibiliConfig)


def _load_summarize_config(raw_summarize: dict) -> SummarizeConfig:
    if not isinstance(raw_summarize, dict):
        raise ValueError("summarize 配置必须是 TOML 表")

    summarize = dict(raw_summarize)
    allowed_top_level_fields = {
        "profile",
        "profiles",
        "enable_thinking",
        "preset",
        "presets_file",
    }
    unknown_top_level_fields = sorted(
        set(summarize.keys()) - allowed_top_level_fields
    )
    if unknown_top_level_fields:
        raise ValueError(
            "summarize 包含未知字段: "
            f"{', '.join(unknown_top_level_fields)}"
        )

    profile = summarize.get("profile")
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("summarize.profile 必须在配置文件中显式声明为非空字符串")
    profile = profile.strip()

    raw_profiles = summarize.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ValueError(
            "summarize.profiles 必须在配置文件中显式声明为非空 TOML 表"
        )

    profiles: dict[str, SummarizeModelProfile] = {}
    for name, value in raw_profiles.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("summarize.profiles 的配置名必须是非空字符串")
        if not isinstance(value, dict):
            raise ValueError(f"summarize.profiles.{name} 必须是 TOML 表")

        key = name.strip()
        entry = dict(value)
        allowed_entry_fields = {
            "provider",
            "model",
            "api_key",
            "api_base",
            "providers",
        }
        unknown_entry_fields = sorted(set(entry.keys()) - allowed_entry_fields)
        if unknown_entry_fields:
            raise ValueError(
                f"summarize.profiles.{key} 包含未知字段: "
                f"{', '.join(unknown_entry_fields)}"
            )

        raw_provider = entry.get("provider")
        if not isinstance(raw_provider, str) or not raw_provider.strip():
            raise ValueError(f"summarize.profiles.{key} 缺少 provider")
        provider = raw_provider.strip().lower()
        if provider not in _SUPPORTED_SUMMARIZE_PROVIDERS:
            available = ", ".join(_SUPPORTED_SUMMARIZE_PROVIDERS)
            raise ValueError(
                f"summarize.profiles.{key}.provider 仅支持 {available}"
            )

        raw_model = entry.get("model")
        if not isinstance(raw_model, str):
            raise ValueError(f"summarize.profiles.{key} 缺少 model")
        model = raw_model.strip()
        if not model:
            raise ValueError(f"summarize.profiles.{key}.model 必须是非空字符串")

        raw_api_base = entry.get("api_base")
        if isinstance(raw_api_base, str):
            api_base = raw_api_base.strip()
        else:
            api_base = ""
        if not api_base:
            api_base = _SUMMARIZE_PROVIDER_DEFAULT_API_BASE[provider]

        raw_api_key = entry.get("api_key")
        if not isinstance(raw_api_key, str):
            raise ValueError(f"summarize.profiles.{key} 缺少 api_key")
        api_key = raw_api_key.strip()

        raw_providers = entry.get("providers")
        if isinstance(raw_providers, str):
            provider_order = raw_providers.strip()
            if not provider_order:
                raise ValueError(
                    f"summarize.profiles.{key}.providers 必须是非空字符串或字符串数组"
                )
            providers = (provider_order,)
        elif isinstance(raw_providers, list):
            parsed: list[str] = []
            for index, item in enumerate(raw_providers):
                if not isinstance(item, str) or not item.strip():
                    raise ValueError(
                        f"summarize.profiles.{key}.providers[{index}] 必须是非空字符串"
                    )
                parsed.append(item.strip())
            providers = tuple(parsed)
        elif raw_providers is None:
            providers = ()
        else:
            raise ValueError(
                f"summarize.profiles.{key}.providers 必须是字符串或字符串数组"
            )

        if provider != "openrouter" and providers:
            raise ValueError(
                f"summarize.profiles.{key}.providers 仅可用于 provider=openrouter"
            )

        profiles[key] = SummarizeModelProfile(
            provider=provider,
            model=model,
            api_key=api_key,
            api_base=api_base,
            providers=providers,
        )

    if profile not in profiles:
        available = ", ".join(profiles.keys())
        raise ValueError(
            f"summarize.profile `{profile}` 不存在，可选值: {available}"
        )

    enable_thinking = summarize.get("enable_thinking", True)
    if not isinstance(enable_thinking, bool):
        raise ValueError("summarize.enable_thinking 必须是布尔值")

    preset = summarize.get("preset")
    if preset is not None and not isinstance(preset, str):
        raise ValueError("summarize.preset 必须是字符串")
    preset = preset.strip() if isinstance(preset, str) else None

    presets_file = summarize.get("presets_file", DEFAULT_SUMMARY_PRESETS_FILE)
    if not isinstance(presets_file, str) or not presets_file.strip():
        raise ValueError("summarize.presets_file 必须是非空字符串")

    return SummarizeConfig(
        profile=profile,
        profiles=profiles,
        enable_thinking=enable_thinking,
        preset=preset,
        presets_file=presets_file.strip(),
    )


def resolve_summarize_model_profile(
    summarize: SummarizeConfig,
    override: str | None = None,
) -> SummarizeModelProfile:
    selected_profile = override or summarize.profile
    selected_profile = selected_profile.strip()
    profile = summarize.profiles.get(selected_profile)
    if profile is None:
        available = ", ".join(summarize.profiles.keys())
        raise ValueError(
            f"summarize.profile `{selected_profile}` 不存在，可选值: {available}"
        )
    return profile


def resolve_summarize_api_base(profile: SummarizeModelProfile) -> str:
    api_base = profile.api_base.strip()
    if api_base:
        return api_base
    return _SUMMARIZE_PROVIDER_DEFAULT_API_BASE[profile.provider]


def resolve_rag_llm_profile(
    config: "AppConfig",
    override: str | None = None,
) -> SummarizeModelProfile:
    selected_profile = (override or config.rag.llm_profile or config.summarize.profile).strip()
    profile = config.summarize.profiles.get(selected_profile)
    if profile is None:
        available = ", ".join(config.summarize.profiles.keys())
        raise ValueError(
            f"RAG LLM profile `{selected_profile}` 不存在，可选值: {available}"
        )
    return profile


def _load_fancy_html_config(
    raw_fancy_html: dict,
    *,
    summarize: SummarizeConfig,
) -> FancyHtmlConfig:
    if not isinstance(raw_fancy_html, dict):
        raise ValueError("fancy_html 配置必须是 TOML 表")

    fancy_html = dict(raw_fancy_html)
    allowed_fields = {"profile"}
    unknown_fields = sorted(set(fancy_html.keys()) - allowed_fields)
    if unknown_fields:
        raise ValueError(
            "fancy_html 包含未知字段: " f"{', '.join(unknown_fields)}"
        )

    raw_profile = fancy_html.get("profile")
    if not isinstance(raw_profile, str) or not raw_profile.strip():
        raise ValueError("fancy_html.profile 必须在配置文件中显式声明为非空字符串")
    profile = raw_profile.strip()

    if profile not in summarize.profiles:
        available = ", ".join(summarize.profiles.keys())
        raise ValueError(
            f"fancy_html.profile `{profile}` 不存在，可选值: {available}"
        )

    return FancyHtmlConfig(profile=profile)


def _load_stt_profile(
    raw_profile: dict,
    *,
    key: str,
    base: STTProfile | None = None,
    field_prefix: str = "stt.profiles",
) -> STTProfile:
    section_name = f"{field_prefix}.{key}" if field_prefix else key
    if not isinstance(raw_profile, dict):
        raise ValueError(f"{section_name} 必须是 TOML 表")

    normalized = dict(raw_profile)
    allowed_fields = set(STTProfile.__dataclass_fields__.keys())
    unknown_fields = sorted(set(normalized.keys()) - allowed_fields)
    if unknown_fields:
        raise ValueError(
            f"{section_name} 包含未知字段: {', '.join(unknown_fields)}"
        )

    default_profile = STTProfile()
    merged: dict[str, object] = {}
    for field_name in allowed_fields:
        if base is not None:
            merged[field_name] = getattr(base, field_name)
        else:
            merged[field_name] = getattr(default_profile, field_name)
    merged.update(normalized)

    string_fields = {
        "provider",
        "language",
        "storage_profile",
        "qwen_api_key",
        "qwen_model",
        "qwen_base_url",
        "groq_api_key",
        "groq_model",
        "groq_base_url",
        "groq_bitrate",
    }
    for field_name in string_fields:
        value = merged[field_name]
        if not isinstance(value, str):
            raise ValueError(f"{section_name}.{field_name} 必须是字符串")
        merged[field_name] = value.strip()

    if not isinstance(merged["groq_chunk_length"], int):
        raise ValueError(f"{section_name}.groq_chunk_length 必须是整数")
    if not isinstance(merged["groq_overlap"], int):
        raise ValueError(f"{section_name}.groq_overlap 必须是整数")

    provider = str(merged["provider"]).strip().lower()
    if provider not in {"qwen", "groq"}:
        raise ValueError(
            f"{section_name}.provider 仅支持 qwen 或 groq"
        )
    merged["provider"] = provider

    if not str(merged["language"]).strip():
        raise ValueError(f"{section_name}.language 必须是非空字符串")

    storage_profile = str(merged["storage_profile"]).strip()
    if storage_profile:
        merged["storage_profile"] = _validate_storage_backend_choice(
            storage_profile,
            field_name=f"{section_name}.storage_profile",
        )
    else:
        merged["storage_profile"] = ""

    return STTProfile(**merged)


def _load_stt_config(raw_stt: dict) -> STTConfig:
    if not isinstance(raw_stt, dict):
        raise ValueError("stt 配置必须是 TOML 表")

    stt = dict(raw_stt)
    allowed_top_level_fields = {"profile", "profiles"}
    unknown_top_level_fields = sorted(set(stt.keys()) - allowed_top_level_fields)
    if unknown_top_level_fields:
        raise ValueError(
            "stt 不支持平铺字段，请改用 stt.profiles.<name>。"
            f"检测到非法字段: {', '.join(unknown_top_level_fields)}"
        )

    raw_profile = stt.get("profile", DEFAULT_STT_PROFILE)
    if not isinstance(raw_profile, str) or not raw_profile.strip():
        raise ValueError("stt.profile 必须是非空字符串")
    profile = raw_profile.strip()

    raw_profiles = stt.get("profiles")
    if not isinstance(raw_profiles, dict):
        raise ValueError("stt.profiles 必须是 TOML 表，且不能省略")

    profiles: dict[str, STTProfile] = _default_stt_profiles()
    for name, value in raw_profiles.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("stt.profiles 的配置名必须是非空字符串")
        key = name.strip()
        base_profile = profiles.get(key)
        profiles[key] = _load_stt_profile(value, key=key, base=base_profile)

    selected_profile = profiles.get(profile)
    if selected_profile is None:
        available = ", ".join(profiles.keys())
        raise ValueError(f"stt.profile `{profile}` 不存在，可选值: {available}")

    return STTConfig(
        profile=profile,
        profiles=profiles,
        provider=selected_profile.provider,
        language=selected_profile.language,
        storage_profile=selected_profile.storage_profile,
        qwen_api_key=selected_profile.qwen_api_key,
        qwen_model=selected_profile.qwen_model,
        qwen_base_url=selected_profile.qwen_base_url,
        groq_api_key=selected_profile.groq_api_key,
        groq_model=selected_profile.groq_model,
        groq_base_url=selected_profile.groq_base_url,
        groq_chunk_length=selected_profile.groq_chunk_length,
        groq_overlap=selected_profile.groq_overlap,
        groq_bitrate=selected_profile.groq_bitrate,
    )


def _validate_storage_backend_choice(value: str, *, field_name: str) -> str:
    backend = value.strip().lower()
    if backend not in {"local", "minio", "alicloud"}:
        raise ValueError(f"{field_name} 仅支持 local、minio 或 alicloud")
    return backend


def _assert_storage_backend_required_fields(
    storage: StorageConfig,
    *,
    backend: str,
    field_name: str,
) -> None:
    if backend == "local":
        return

    if backend == "minio":
        required_fields = {
            "storage.minio.endpoint": storage.minio.endpoint,
            "storage.minio.bucket": storage.minio.bucket,
            "storage.minio.access_key": storage.minio.access_key,
            "storage.minio.secret_key": storage.minio.secret_key,
        }
    else:
        required_fields = {
            "storage.alicloud.region": storage.alicloud.region,
            "storage.alicloud.bucket": storage.alicloud.bucket,
            "storage.alicloud.access_key_id": storage.alicloud.access_key_id,
            "storage.alicloud.access_key_secret": storage.alicloud.access_key_secret,
        }

    for required_field_name, required_value in required_fields.items():
        if not isinstance(required_value, str) or not required_value.strip():
            raise ValueError(
                f"{field_name}={backend} 时，{required_field_name} 必须是非空字符串"
            )


def _load_storage_config(raw_storage: dict) -> StorageConfig:
    if not isinstance(raw_storage, dict):
        raise ValueError("storage 配置必须是 TOML 表")
    backend_raw = raw_storage.get("backend", "local")
    if not isinstance(backend_raw, str) or not backend_raw.strip():
        raise ValueError("storage.backend 必须是非空字符串")
    backend = _validate_storage_backend_choice(
        backend_raw,
        field_name="storage.backend",
    )

    raw_minio = raw_storage.get("minio", {})
    if not isinstance(raw_minio, dict):
        raise ValueError("storage.minio 配置必须是 TOML 表")

    minio = MinIOStorageConfig(**raw_minio)
    if not isinstance(minio.secure, bool):
        raise ValueError("storage.minio.secure 必须是布尔值")
    if not isinstance(minio.auto_create_bucket, bool):
        raise ValueError("storage.minio.auto_create_bucket 必须是布尔值")
    if not isinstance(minio.temporary_url_expire_seconds, int):
        raise ValueError(
            "storage.minio.temporary_url_expire_seconds 必须是整数秒"
        )
    if minio.temporary_url_expire_seconds <= 0:
        raise ValueError(
            "storage.minio.temporary_url_expire_seconds 必须大于 0"
        )

    string_fields = {
        "storage.minio.endpoint": minio.endpoint,
        "storage.minio.bucket": minio.bucket,
        "storage.minio.access_key": minio.access_key,
        "storage.minio.secret_key": minio.secret_key,
        "storage.minio.region": minio.region,
        "storage.minio.base_prefix": minio.base_prefix,
    }
    for field_name, value in string_fields.items():
        if not isinstance(value, str):
            raise ValueError(f"{field_name} 必须是字符串")

    raw_alicloud = raw_storage.get("alicloud", {})
    if not isinstance(raw_alicloud, dict):
        raise ValueError("storage.alicloud 配置必须是 TOML 表")
    alicloud_source = dict(raw_alicloud)

    alicloud = AlicloudStorageConfig(**alicloud_source)
    if not isinstance(alicloud.auto_create_bucket, bool):
        raise ValueError("storage.alicloud.auto_create_bucket 必须是布尔值")

    alicloud_string_fields = {
        "storage.alicloud.region": alicloud.region,
        "storage.alicloud.bucket": alicloud.bucket,
        "storage.alicloud.access_key_id": alicloud.access_key_id,
        "storage.alicloud.access_key_secret": alicloud.access_key_secret,
        "storage.alicloud.base_prefix": alicloud.base_prefix,
        "storage.alicloud.temporary_prefix": alicloud.temporary_prefix,
        "storage.alicloud.public_base_url": alicloud.public_base_url,
    }
    for field_name, value in alicloud_string_fields.items():
        if not isinstance(value, str):
            raise ValueError(f"{field_name} 必须是字符串")

    storage_config = StorageConfig(backend=backend, minio=minio, alicloud=alicloud)
    _assert_storage_backend_required_fields(
        storage_config,
        backend=backend,
        field_name="storage.backend",
    )
    return storage_config


def _resolve_relative_path(path_value: str, *, base_dir: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _load_summary_presets(path: Path) -> SummaryPresetsConfig:
    if not path.exists():
        raise FileNotFoundError(f"总结 preset 配置文件不存在: {path}")

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    raw_presets = raw.get("presets")
    if not isinstance(raw_presets, dict) or not raw_presets:
        raise ValueError("总结 preset 配置缺少 [presets]，或 [presets] 为空")

    presets: dict[str, SummaryPreset] = {}
    for name, value in raw_presets.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("总结 preset 名称必须是非空字符串")
        if not isinstance(value, dict):
            raise ValueError(f"总结 preset `{name}` 必须是 TOML 表")

        prompt_template = value.get("prompt_template")
        if not isinstance(prompt_template, str) or not prompt_template.strip():
            raise ValueError(f"总结 preset `{name}` 缺少 prompt_template")
        if "{content}" not in prompt_template:
            raise ValueError(
                f"总结 preset `{name}` 的 prompt_template 缺少 {{content}} 占位符"
            )

        raw_label = value.get("label", name)
        if not isinstance(raw_label, str) or not raw_label.strip():
            raise ValueError(f"总结 preset `{name}` 的 label 必须是非空字符串")

        presets[name] = SummaryPreset(
            prompt_template=prompt_template,
            label=raw_label.strip(),
        )

    raw_default = raw.get("default")
    if raw_default is None:
        default = next(iter(presets))
    elif isinstance(raw_default, str) and raw_default.strip():
        default = raw_default.strip()
    else:
        raise ValueError("总结 preset 配置中的 default 必须是非空字符串")

    if default not in presets:
        raise ValueError(
            f"总结 preset 默认值 `{default}` 不存在，可选值: {', '.join(presets.keys())}"
        )

    return SummaryPresetsConfig(default=default, presets=presets, source_path=path)


def resolve_summary_preset_name(
    *,
    summarize: SummarizeConfig,
    summary_presets: SummaryPresetsConfig,
    override: str | None = None,
) -> str:
    candidate = override or summarize.preset or summary_presets.default
    candidate = candidate.strip()

    if candidate not in summary_presets.presets:
        available = ", ".join(summary_presets.presets.keys())
        raise ValueError(f"总结 preset `{candidate}` 不存在，可选值: {available}")

    return candidate


def _load_rag_config(raw_rag: dict, *, base_dir: Path) -> RagConfig:
    if not isinstance(raw_rag, dict):
        raise ValueError("rag 配置必须是 TOML 表")

    allowed_fields = {
        "enabled",
        "collection_name",
        "chroma_dir",
        "chunk_size",
        "chunk_overlap",
        "top_k",
        "embedding",
        "llm_profile",
    }
    unknown_fields = sorted(set(raw_rag.keys()) - allowed_fields)
    if unknown_fields:
        raise ValueError("rag 包含未知字段: " f"{', '.join(unknown_fields)}")

    enabled = raw_rag.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("rag.enabled 必须是布尔值")

    collection_name = raw_rag.get("collection_name", RagConfig.collection_name)
    if not isinstance(collection_name, str) or not collection_name.strip():
        raise ValueError("rag.collection_name 必须是非空字符串")

    chroma_dir_raw = raw_rag.get("chroma_dir", RagConfig.chroma_dir)
    if not isinstance(chroma_dir_raw, str) or not chroma_dir_raw.strip():
        raise ValueError("rag.chroma_dir 必须是非空字符串")
    chroma_dir = str(_resolve_relative_path(chroma_dir_raw, base_dir=base_dir))

    chunk_size = raw_rag.get("chunk_size", RagConfig.chunk_size)
    if not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("rag.chunk_size 必须是正整数")

    chunk_overlap = raw_rag.get("chunk_overlap", RagConfig.chunk_overlap)
    if not isinstance(chunk_overlap, int) or chunk_overlap < 0:
        raise ValueError("rag.chunk_overlap 必须是非负整数")

    top_k = raw_rag.get("top_k", RagConfig.top_k)
    if not isinstance(top_k, int) or top_k <= 0:
        raise ValueError("rag.top_k 必须是正整数")

    raw_llm_profile = raw_rag.get("llm_profile", RagConfig.llm_profile)
    if not isinstance(raw_llm_profile, str):
        raise ValueError("rag.llm_profile 必须是字符串")
    llm_profile = raw_llm_profile.strip()

    raw_embedding = raw_rag.get("embedding", {})
    if not isinstance(raw_embedding, dict):
        raise ValueError("rag.embedding 必须是 TOML 表")
    embedding = RagEmbeddingConfig(
        provider=raw_embedding.get("provider", RagEmbeddingConfig.provider),
        model=raw_embedding.get("model", RagEmbeddingConfig.model),
        api_key=raw_embedding.get("api_key", RagEmbeddingConfig.api_key),
        api_base=raw_embedding.get("api_base", RagEmbeddingConfig.api_base),
    )

    return RagConfig(
        enabled=enabled,
        collection_name=collection_name.strip(),
        chroma_dir=chroma_dir,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        top_k=top_k,
        embedding=embedding,
        llm_profile=llm_profile,
    )


def _load_feishu_config(raw_feishu: dict) -> FeishuConfig:
    if raw_feishu is None:
        raw_feishu = {}
    if not isinstance(raw_feishu, dict):
        raise ValueError("feishu 配置必须是 TOML 表")

    allowed_fields = {
        "mode",
        "webhook_url",
        "app_id",
        "app_secret",
        "receive_id",
        "receive_id_type",
        "title_prefix",
        "timeout_seconds",
        "summary_max_chars",
    }
    unknown_fields = sorted(set(raw_feishu.keys()) - allowed_fields)
    if unknown_fields:
        raise ValueError("feishu 包含未知字段: " f"{', '.join(unknown_fields)}")

    config = FeishuConfig(**raw_feishu)

    string_fields = {
        "feishu.mode": config.mode,
        "feishu.webhook_url": config.webhook_url,
        "feishu.app_id": config.app_id,
        "feishu.app_secret": config.app_secret,
        "feishu.receive_id": config.receive_id,
        "feishu.receive_id_type": config.receive_id_type,
        "feishu.title_prefix": config.title_prefix,
    }
    for field_name, value in string_fields.items():
        if not isinstance(value, str):
            raise ValueError(f"{field_name} 必须是字符串")

    if not isinstance(config.timeout_seconds, int) or config.timeout_seconds <= 0:
        raise ValueError("feishu.timeout_seconds 必须是正整数")
    if not isinstance(config.summary_max_chars, int) or config.summary_max_chars <= 0:
        raise ValueError("feishu.summary_max_chars 必须是正整数")

    mode = config.mode.strip().lower()
    if mode not in {"disabled", "webhook", "app"}:
        raise ValueError("feishu.mode 仅支持 disabled、webhook 或 app")

    receive_id_type = config.receive_id_type.strip().lower()
    if receive_id_type not in {"open_id", "user_id", "union_id", "chat_id", "email"}:
        raise ValueError(
            "feishu.receive_id_type 仅支持 open_id、user_id、union_id、chat_id 或 email"
        )

    if mode == "webhook" and not config.webhook_url.strip():
        raise ValueError("feishu.mode=webhook 时，feishu.webhook_url 必须是非空字符串")
    if mode == "app":
        required_fields = {
            "feishu.app_id": config.app_id,
            "feishu.app_secret": config.app_secret,
            "feishu.receive_id": config.receive_id,
        }
        for field_name, value in required_fields.items():
            if not value.strip():
                raise ValueError(f"feishu.mode=app 时，{field_name} 必须是非空字符串")

    return FeishuConfig(
        mode=mode,
        webhook_url=config.webhook_url.strip(),
        app_id=config.app_id.strip(),
        app_secret=config.app_secret.strip(),
        receive_id=config.receive_id.strip(),
        receive_id_type=receive_id_type,
        title_prefix=config.title_prefix.strip() or "b2t",
        timeout_seconds=config.timeout_seconds,
        summary_max_chars=config.summary_max_chars,
    )


def _load_monitor_config(raw_monitor: dict, *, base_dir: Path) -> MonitorConfig:
    if raw_monitor is None:
        raw_monitor = {}
    if not isinstance(raw_monitor, dict):
        raise ValueError("monitor 配置必须是 TOML 表")

    allowed_fields = {
        "enabled",
        "state_file",
        "user_agent",
        "lookback_hours",
        "first_run_max_push",
        "default_check_interval",
        "startup_notification",
        "summary_preset",
        "summary_profile",
        "output_dir",
        "creators",
    }
    unknown_fields = sorted(set(raw_monitor.keys()) - allowed_fields)
    if unknown_fields:
        raise ValueError("monitor 包含未知字段: " f"{', '.join(unknown_fields)}")

    enabled = raw_monitor.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("monitor.enabled 必须是布尔值")

    raw_state_file = raw_monitor.get("state_file", MonitorConfig.state_file)
    if not isinstance(raw_state_file, str) or not raw_state_file.strip():
        raise ValueError("monitor.state_file 必须是非空字符串")
    state_file = str(
        _resolve_relative_path(raw_state_file.strip(), base_dir=base_dir)
    )

    raw_user_agent = raw_monitor.get("user_agent", DEFAULT_BILIBILI_USER_AGENT)
    if not isinstance(raw_user_agent, str) or not raw_user_agent.strip():
        raise ValueError("monitor.user_agent 必须是非空字符串")

    lookback_hours = raw_monitor.get("lookback_hours", MonitorConfig.lookback_hours)
    if not isinstance(lookback_hours, int) or lookback_hours <= 0:
        raise ValueError("monitor.lookback_hours 必须是正整数")

    first_run_max_push = raw_monitor.get(
        "first_run_max_push",
        MonitorConfig.first_run_max_push,
    )
    if not isinstance(first_run_max_push, int) or first_run_max_push < 0:
        raise ValueError("monitor.first_run_max_push 必须是非负整数")

    default_check_interval = raw_monitor.get(
        "default_check_interval",
        MonitorConfig.default_check_interval,
    )
    if not isinstance(default_check_interval, int) or default_check_interval <= 0:
        raise ValueError("monitor.default_check_interval 必须是正整数")

    startup_notification = raw_monitor.get(
        "startup_notification",
        MonitorConfig.startup_notification,
    )
    if not isinstance(startup_notification, bool):
        raise ValueError("monitor.startup_notification 必须是布尔值")

    raw_summary_preset = raw_monitor.get("summary_preset")
    if raw_summary_preset is not None and not isinstance(raw_summary_preset, str):
        raise ValueError("monitor.summary_preset 必须是字符串")
    summary_preset = raw_summary_preset.strip() if isinstance(raw_summary_preset, str) else None
    if summary_preset == "":
        summary_preset = None

    raw_summary_profile = raw_monitor.get("summary_profile")
    if raw_summary_profile is not None and not isinstance(raw_summary_profile, str):
        raise ValueError("monitor.summary_profile 必须是字符串")
    summary_profile = (
        raw_summary_profile.strip() if isinstance(raw_summary_profile, str) else None
    )
    if summary_profile == "":
        summary_profile = None

    raw_output_dir = raw_monitor.get("output_dir", "")
    if not isinstance(raw_output_dir, str):
        raise ValueError("monitor.output_dir 必须是字符串")
    output_dir = ""
    if raw_output_dir.strip():
        output_dir = str(
            _resolve_relative_path(raw_output_dir.strip(), base_dir=base_dir)
        )

    raw_creators = raw_monitor.get("creators", [])
    if not isinstance(raw_creators, list):
        raise ValueError("monitor.creators 必须是 TOML 数组")

    creators: list[MonitorCreatorConfig] = []
    for index, raw_creator in enumerate(raw_creators):
        if not isinstance(raw_creator, dict):
            raise ValueError(f"monitor.creators[{index}] 必须是 TOML 表")

        uid = raw_creator.get("uid")
        if not isinstance(uid, int) or uid <= 0:
            raise ValueError(f"monitor.creators[{index}].uid 必须是正整数")

        raw_name = raw_creator.get("name", "")
        if not isinstance(raw_name, str):
            raise ValueError(f"monitor.creators[{index}].name 必须是字符串")

        interval = raw_creator.get("check_interval", default_check_interval)
        if not isinstance(interval, int) or interval <= 0:
            raise ValueError(
                f"monitor.creators[{index}].check_interval 必须是正整数"
            )

        creators.append(
            MonitorCreatorConfig(
                uid=uid,
                name=raw_name.strip(),
                check_interval=interval,
            )
        )

    return MonitorConfig(
        enabled=enabled,
        state_file=state_file,
        user_agent=raw_user_agent.strip(),
        lookback_hours=lookback_hours,
        first_run_max_push=first_run_max_push,
        default_check_interval=default_check_interval,
        startup_notification=startup_notification,
        summary_preset=summary_preset,
        summary_profile=summary_profile,
        output_dir=output_dir,
        creators=tuple(creators),
    )


def _load_bilibili_config(raw_bilibili: dict) -> BilibiliConfig:
    if raw_bilibili is None:
        raw_bilibili = {}
    if not isinstance(raw_bilibili, dict):
        raise ValueError("bilibili 配置必须是 TOML 表")

    allowed_fields = {
        "SESSDATA",
        "bili_jct",
        "buvid3",
        "DedeUserID",
        "DedeUserID__ckMd5",
        "refresh_token",
    }
    unknown_fields = sorted(set(raw_bilibili.keys()) - allowed_fields)
    if unknown_fields:
        raise ValueError("bilibili 包含未知字段: " f"{', '.join(unknown_fields)}")

    normalized: dict[str, str] = {}
    for field_name in allowed_fields:
        value = raw_bilibili.get(field_name, "")
        if not isinstance(value, str):
            raise ValueError(f"bilibili.{field_name} 必须是字符串")
        normalized[field_name] = value.strip()

    return BilibiliConfig(**normalized)


def build_bilibili_cookie(config: AppConfig) -> str:
    parts: list[str] = []
    bilibili = config.bilibili
    for key in (
        "SESSDATA",
        "bili_jct",
        "buvid3",
        "DedeUserID",
        "DedeUserID__ckMd5",
    ):
        value = getattr(bilibili, key).strip()
        if value:
            parts.append(f"{key}={value}")
    return "; ".join(parts)


def load_config(path: str | Path | None = None) -> AppConfig:
    """加载 TOML 配置文件

    查找顺序：显式路径 → B2T_CONFIG 环境变量 → <project-root>/config.toml

    Args:
        path: 配置文件路径，为 None 时按查找顺序自动定位

    Returns:
        AppConfig 实例

    Raises:
        FileNotFoundError: 配置文件不存在
    """
    if path is None:
        env_config = os.environ.get("B2T_CONFIG")
        if env_config:
            path = env_config
        else:
            project_root = Path(__file__).resolve().parents[1]
            path = project_root / "config.toml"

    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path.resolve()}")

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    storage_config = _load_storage_config(raw.get("storage", {}))
    stt_config = _load_stt_config(raw.get("stt", {}))
    stt_storage_profile = stt_config.storage_profile.strip()
    if stt_storage_profile:
        stt_storage_field_name = f"stt.profiles.{stt_config.profile}.storage_profile"
        selected_backend = _validate_storage_backend_choice(
            stt_storage_profile,
            field_name=stt_storage_field_name,
        )
        _assert_storage_backend_required_fields(
            storage_config,
            backend=selected_backend,
            field_name=stt_storage_field_name,
        )
    summarize_config = _load_summarize_config(raw.get("summarize", {}))
    presets_path = _resolve_relative_path(
        summarize_config.presets_file,
        base_dir=config_path.parent.resolve(),
    )

    summary_presets = _load_summary_presets(presets_path)
    selected_preset = resolve_summary_preset_name(
        summarize=summarize_config,
        summary_presets=summary_presets,
        override=summarize_config.preset,
    )
    summarize_config = SummarizeConfig(
        profile=summarize_config.profile,
        profiles=summarize_config.profiles,
        enable_thinking=summarize_config.enable_thinking,
        preset=selected_preset,
        presets_file=summarize_config.presets_file,
    )
    fancy_html_config = _load_fancy_html_config(
        raw.get("fancy_html"),
        summarize=summarize_config,
    )

    # Load download config and resolve relative paths
    raw_download = raw.get("download", {})
    download_dict = dict(raw_download)

    # Resolve output_dir relative to config file (always resolve, even if using default)
    output_dir_value = download_dict.get("output_dir", DownloadConfig.output_dir)
    output_dir = _resolve_relative_path(
        output_dir_value,
        base_dir=config_path.parent.resolve(),
    )
    download_dict["output_dir"] = str(output_dir)

    # Resolve db_dir relative to config file (always resolve, even if using default)
    db_dir_value = download_dict.get("db_dir", DownloadConfig.db_dir)
    db_dir = _resolve_relative_path(
        db_dir_value,
        base_dir=config_path.parent.resolve(),
    )
    download_dict["db_dir"] = str(db_dir)

    rag_config = _load_rag_config(
        raw.get("rag", {}),
        base_dir=config_path.parent.resolve(),
    )
    feishu_config = _load_feishu_config(raw.get("feishu", {}))
    monitor_config = _load_monitor_config(
        raw.get("monitor", {}),
        base_dir=config_path.parent.resolve(),
    )
    bilibili_config = _load_bilibili_config(raw.get("bilibili", {}))

    return AppConfig(
        download=DownloadConfig(**download_dict),
        storage=storage_config,
        stt=stt_config,
        summarize=summarize_config,
        fancy_html=fancy_html_config,
        summary_presets=summary_presets,
        converter=ConverterConfig(**raw.get("converter", {})),
        rag=rag_config,
        feishu=feishu_config,
        monitor=monitor_config,
        bilibili=bilibili_config,
    )
