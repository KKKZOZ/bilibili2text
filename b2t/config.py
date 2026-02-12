"""TOML 配置加载模块"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SUMMARY_PRESETS_FILE = "summary_presets.toml"
DEFAULT_SUMMARIZE_PROFILE = "dashscope"


@dataclass(frozen=True)
class DownloadConfig:
    audio_quality: str = "30216"
    output_dir: str = "./transcriptions"


@dataclass(frozen=True)
class OSSConfig:
    region: str = ""
    bucket: str = ""
    access_key_id: str = ""
    access_key_secret: str = ""


@dataclass(frozen=True)
class STTConfig:
    provider: str = "qwen"
    language: str = "zh"

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
    oss: OSSConfig
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


def _normalize_stt_config(raw_stt: dict) -> dict:
    """兼容旧配置字段（api_key/model/base_url）。"""
    stt = dict(raw_stt)

    if "api_key" in stt and "qwen_api_key" not in stt:
        stt["qwen_api_key"] = stt["api_key"]
    if "model" in stt and "qwen_model" not in stt:
        stt["qwen_model"] = stt["model"]
    if "base_url" in stt and "qwen_base_url" not in stt:
        stt["qwen_base_url"] = stt["base_url"]

    stt.pop("api_key", None)
    stt.pop("model", None)
    stt.pop("base_url", None)

    return stt


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

    stt_raw = _normalize_stt_config(raw.get("stt", {}))
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

    return AppConfig(
        download=DownloadConfig(**raw.get("download", {})),
        oss=OSSConfig(**raw.get("oss", {})),
        stt=STTConfig(**stt_raw),
        summarize=summarize_config,
        summary_presets=summary_presets,
        converter=ConverterConfig(**raw.get("converter", {})),
    )
