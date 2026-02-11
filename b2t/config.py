"""TOML 配置加载模块"""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


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
class PolishConfig:
    api_key: str = ""
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = "moonshotai/kimi-k2.5"
    preset: str | None = None
    presets_file: str = "summary_presets.toml"


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
    polish: PolishConfig
    summary_presets: SummaryPresetsConfig
    converter: ConverterConfig


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
    polish: PolishConfig,
    summary_presets: SummaryPresetsConfig,
    override: str | None = None,
) -> str:
    candidate = override or polish.preset or summary_presets.default
    candidate = candidate.strip()

    if candidate not in summary_presets.presets:
        available = ", ".join(summary_presets.presets.keys())
        raise ValueError(f"总结 preset `{candidate}` 不存在，可选值: {available}")

    return candidate


def load_config(path: str | Path | None = None) -> AppConfig:
    """加载 TOML 配置文件

    查找顺序：显式路径 → B2T_CONFIG 环境变量 → ./config.toml

    Args:
        path: 配置文件路径，为 None 时按查找顺序自动定位

    Returns:
        AppConfig 实例

    Raises:
        FileNotFoundError: 配置文件不存在
    """
    if path is None:
        path = os.environ.get("B2T_CONFIG", "config.toml")

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    stt_raw = _normalize_stt_config(raw.get("stt", {}))
    polish_config = PolishConfig(**raw.get("polish", {}))
    presets_path = _resolve_relative_path(
        polish_config.presets_file,
        base_dir=config_path.parent.resolve(),
    )
    summary_presets = _load_summary_presets(presets_path)
    selected_preset = resolve_summary_preset_name(
        polish=polish_config,
        summary_presets=summary_presets,
        override=polish_config.preset,
    )
    polish_config = PolishConfig(
        api_key=polish_config.api_key,
        base_url=polish_config.base_url,
        model=polish_config.model,
        preset=selected_preset,
        presets_file=polish_config.presets_file,
    )

    return AppConfig(
        download=DownloadConfig(**raw.get("download", {})),
        oss=OSSConfig(**raw.get("oss", {})),
        stt=STTConfig(**stt_raw),
        polish=polish_config,
        summary_presets=summary_presets,
        converter=ConverterConfig(**raw.get("converter", {})),
    )
