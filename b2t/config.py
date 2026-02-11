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
    api_key: str = ""
    model: str = "qwen3-asr-flash-filetrans"
    language: str = "zh"
    base_url: str = "https://dashscope.aliyuncs.com/api/v1"


@dataclass(frozen=True)
class PolishConfig:
    api_key: str = ""
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = "moonshotai/kimi-k2.5"
    prompt_template: str = (
        "按照文本时间分段总结以下内容, 但是注意，如果相邻的几个时间段的话题主题相同，"
        '应该合并总结, 输出必须是纯 Markdown 正文，不要输出解释、不要输出列表式的'
        '\u201c我做了什么\u201d、不要输出多余前后缀：\n\n{content}'
    )


@dataclass(frozen=True)
class ConverterConfig:
    min_length: int = 60


@dataclass(frozen=True)
class AppConfig:
    download: DownloadConfig
    oss: OSSConfig
    stt: STTConfig
    polish: PolishConfig
    converter: ConverterConfig


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

    return AppConfig(
        download=DownloadConfig(**raw.get("download", {})),
        oss=OSSConfig(**raw.get("oss", {})),
        stt=STTConfig(**raw.get("stt", {})),
        polish=PolishConfig(**raw.get("polish", {})),
        converter=ConverterConfig(**raw.get("converter", {})),
    )
