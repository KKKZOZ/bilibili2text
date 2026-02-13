"""TOML 配置加载模块"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SUMMARY_PRESETS_FILE = "summary_presets.toml"
DEFAULT_SUMMARIZE_PROFILE = "dashscope"
DEFAULT_STT_PROFILE = "qwen"


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
    model: str
    endpoint: str
    api_key: str
    providers: tuple[str, ...] = ()


def _default_summarize_profiles() -> dict[str, "SummarizeModelProfile"]:
    return {
        "openrouter": SummarizeModelProfile(
            model="moonshotai/kimi-k2.5",
            endpoint="https://openrouter.ai/api/v1",
            api_key="",
            providers=(),
        ),
        "dashscope": SummarizeModelProfile(
            model="qwen3-max",
            endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="",
            providers=(),
        ),
    }


@dataclass(frozen=True)
class SummarizeConfig:
    profile: str = DEFAULT_SUMMARIZE_PROFILE
    profiles: dict[str, SummarizeModelProfile] = field(
        default_factory=_default_summarize_profiles
    )
    enable_thinking: bool = True
    preset: str | None = None
    presets_file: str = DEFAULT_SUMMARY_PRESETS_FILE


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
class AppConfig:
    download: DownloadConfig
    storage: StorageConfig
    stt: STTConfig
    summarize: SummarizeConfig
    summary_presets: SummaryPresetsConfig
    converter: ConverterConfig


def _load_summarize_config(raw_summarize: dict) -> SummarizeConfig:
    summarize = dict(raw_summarize)
    profile = summarize.get("profile", DEFAULT_SUMMARIZE_PROFILE)
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("summarize.profile 必须是非空字符串")
    profile = profile.strip()

    raw_profiles = summarize.get("profiles", {})
    if not isinstance(raw_profiles, dict):
        raise ValueError("summarize.profiles 必须是 TOML 表")

    profiles = _default_summarize_profiles()
    for name, value in raw_profiles.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("summarize.profiles 的配置名必须是非空字符串")
        if not isinstance(value, dict):
            raise ValueError(f"summarize.profiles.{name} 必须是 TOML 表")

        key = name.strip()
        base = profiles.get(key)

        raw_model = value.get("model")
        model: str
        if isinstance(raw_model, str):
            model = raw_model.strip()
        elif base is not None:
            model = base.model
        else:
            raise ValueError(f"summarize.profiles.{key} 缺少 model")
        if not model:
            raise ValueError(f"summarize.profiles.{key}.model 必须是非空字符串")

        raw_endpoint = value.get("endpoint")
        endpoint: str
        if isinstance(raw_endpoint, str):
            endpoint = raw_endpoint.strip()
        elif base is not None:
            endpoint = base.endpoint
        else:
            raise ValueError(f"summarize.profiles.{key} 缺少 endpoint")
        if not endpoint:
            raise ValueError(
                f"summarize.profiles.{key}.endpoint 必须是非空字符串"
            )

        raw_api_key = value.get("api_key")
        api_key: str
        if isinstance(raw_api_key, str):
            api_key = raw_api_key.strip()
        elif base is not None:
            api_key = base.api_key
        else:
            raise ValueError(f"summarize.profiles.{key} 缺少 api_key")

        raw_providers = value.get("providers")
        providers: tuple[str, ...]
        if raw_providers is None and base is not None:
            providers = base.providers
        elif isinstance(raw_providers, str):
            provider = raw_providers.strip()
            if not provider:
                raise ValueError(
                    f"summarize.profiles.{key}.providers 必须是非空字符串或字符串数组"
                )
            providers = (provider,)
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

        profiles[key] = SummarizeModelProfile(
            model=model,
            endpoint=endpoint,
            api_key=api_key,
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

    return AppConfig(
        download=DownloadConfig(**download_dict),
        storage=storage_config,
        stt=stt_config,
        summarize=summarize_config,
        summary_presets=summary_presets,
        converter=ConverterConfig(**raw.get("converter", {})),
    )
